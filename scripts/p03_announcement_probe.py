#!/usr/bin/env python3
"""P0.3 probe: how often does a detail page show WHEN the concert was first announced, and does the Japan Arts parse match its pages?

A bounded, polite, one-shot LIVE read (HANDOFF boundary: no scheduled/full-site crawling, no full pages committed):
  * sources: japanarts kajimoto yomikyo nhkso tso njp jpo kanagawa_geikyo.  NOT tmso (usage terms restrict reuse, ADR-0001) and NOT tpo (deferred);
  * robots.txt is read once per host; if it cannot be read (any error other than 404) the host is treated as disallowed and not fetched;
  * every URL is fetched at most once; <= 2 s between requests per host (network.Reader); a 401/403/429 stops that host;
  * a hard cap on requests (default 120) aborts the run;
  * sample rule per source (recorded in the output): the detail URLs offered by the first list page, sorted, then K=8 evenly spread
    (index round(i*(N-1)/(K-1))); Japan Arts: every URL offered (its 35 unverified pages are part of the point);
  * raw pages go to the git-ignored evidence/raw; the committed JSON holds only extracted snippets (<= 200 chars), never page bodies;
  * --replay-raw re-analyses pages already in evidence/raw (matched by their canonical/og:url) with NO network request; --merge-into FILE
    replaces only the probed sources in an existing evidence file and records every run in "runs" (live requests are summed).

Usage: python scripts/p03_announcement_probe.py [--out evidence/p03/announcement-availability-YYYY-MM-DD.json] [--max-requests 120] [--k 8]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from classical_radar.announcement import SNIPPET_MAX, signals, source_level  # noqa: E402
from classical_radar.network import FetchError, Reader, robots_allowed  # noqa: E402
from classical_radar.pagecheck import check_japanarts_detail, cross_page_notes, visible_lines  # noqa: E402
from classical_radar.parsers import JST, ParseError, parse_list, parse_presenter_detail, parse_yomikyo_calendar  # noqa: E402
from classical_radar.sources import DEFERRED, SOURCES  # noqa: E402
from classical_radar.sync import NHK_JSON_INDEX, NHK_TICKET_NEWS, PAGED  # noqa: E402

PROBED = ("japanarts", "kajimoto", "yomikyo", "nhkso", "tso", "njp", "jpo", "kanagawa_geikyo")
NEVER = ("tmso",) + tuple(DEFERRED)
assert not set(PROBED) & set(NEVER)
PRESENTERS = ("japanarts", "kajimoto", "yomikyo")  # detail parsers exist: performance dates are read from the detail page
NEWS_WORDS = re.compile(r"NEWS|ニュース|お知らせ|トピックス|新着|INFORMATION", re.I)
DATE_RX = re.compile(r"\d{4}\s*[./年\-]\s*\d{1,2}\s*[./月\-]\s*\d{1,2}")


class CapReached(RuntimeError):
    pass


def raw_index(raw_dir: Path) -> dict[str, Path]:
    """{canonical url: cached file} from <link rel=canonical> / og:url of the pages already in the raw cache."""
    from bs4 import BeautifulSoup
    idx: dict[str, Path] = {}
    for f in sorted(raw_dir.glob("*.html")):
        soup = BeautifulSoup(f.read_bytes().decode("utf-8", "ignore"), "html.parser")
        for sel, attr in (('link[rel="canonical"]', "href"), ('meta[property="og:url"]', "content")):
            node = soup.select_one(sel)
            if node and node.get(attr):
                idx.setdefault(node[attr].rstrip("/"), f)
    return idx


class Fetcher:
    """Reader + request cap + fetch-once + robots gate. Counts every request, including robots.txt. With ``replay`` it never touches the network."""

    def __init__(self, reader: Reader | None, cap: int, replay: dict[str, Path] | None = None):
        self.reader, self.cap, self.count, self.replay = reader, cap, 0, replay
        if reader is not None:  # count what really goes on the wire: a redirect hop inside one Reader.get is a request too
            reader.client.event_hooks["request"].append(self._on_request)
        self.seen: dict[str, tuple[str, dict]] = {}
        self.robots: dict[str, tuple[str, int] | None] = {}
        self.log: list[str] = []

    def _on_request(self, request) -> None:
        if self.count >= self.cap:  # refuse BEFORE counting: the request that would exceed the cap is never sent
            raise CapReached(f"request cap {self.cap} reached")
        self.count += 1

    def _get(self, url: str):
        if self.count >= self.cap:
            raise CapReached(f"request cap {self.cap} reached")
        return self.reader.get(url, urlsplit(url).hostname)

    def allowed(self, url: str) -> tuple[bool, str]:
        host = urlsplit(url).hostname
        if host not in self.robots:
            try:
                body, meta = self._get(f"https://{host}/robots.txt")
                self.robots[host] = (body, meta["status"])
            except FetchError as exc:
                self.robots[host] = None
                self.log.append(f"{host}: robots.txt unreadable ({exc}); host treated as disallowed")
        r = self.robots[host]
        if r is None:
            return False, "robots.txt unreadable: host treated as disallowed"
        ok = robots_allowed(r[0], r[1], url)
        return ok, "allowed" if ok else "disallowed by robots.txt"

    def get(self, url: str) -> tuple[str | None, dict]:
        if url in self.seen:
            return self.seen[url]
        if self.replay is not None:
            f = self.replay.get(url.rstrip("/"))
            res = (f.read_bytes().decode("utf-8", "ignore"), {"status": 200, "bytes": f.stat().st_size, "sha256": f.stem,
                                                                 "fetched_at": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(), "replayed": True}) if f else (None, {"status": None, "error": "not in the raw cache"})
            self.seen[url] = res
            return res
        ok, why = self.allowed(url)
        if not ok:
            res = (None, {"status": None, "error": why})
        else:
            try:
                body, meta = self._get(url)
                res = (body, {"status": meta["status"], "bytes": meta["bytes"], "sha256": meta["sha256"], "fetched_at": meta["fetched_at"]})
            except FetchError as exc:
                res = (None, {"status": None, "error": str(exc)[:SNIPPET_MAX]})
        self.seen[url] = res
        return res


def spread(urls: list[str], k: int) -> list[str]:
    urls = sorted(urls)
    if len(urls) <= k:
        return urls
    return [urls[i] for i in sorted({round(j * (len(urls) - 1) / (k - 1)) for j in range(k)})]


def dated_news(html: str) -> dict:
    lines = visible_lines(html)
    for i, line in enumerate(lines):
        if DATE_RX.search(line) and any(NEWS_WORDS.search(x) for x in lines[max(0, i - 4): i + 1]):
            return {"present": True, "snippet": " / ".join(lines[max(0, i - 1): i + 2])[:SNIPPET_MAX]}
    return {"present": False, "snippet": None}


def listing(source_id: str, f: Fetcher, today: str) -> tuple[str, str | None, dict[str, list[str]], str, dict[str, dict]]:
    """(list url, list html, {detail url: [performance dates]}, scope, {detail url: first list card}) for one source."""
    if source_id == "yomikyo":
        url = "https://yomikyo.or.jp/cal.php"
        body, _ = f.get(url)
        recs, _ = parse_yomikyo_calendar(body, url) if body else ([], {})
        scope = "calendar page, upcoming entries"
    else:
        url = PAGED[source_id][0] if source_id in PAGED else SOURCES[source_id].url
        body, _ = f.get(url)
        recs, _ = parse_list(source_id, body, url) if body else ([], {})
        scope = "first list page, upcoming entries" if source_id in PAGED else "landing list page"
    host = urlsplit(url).hostname
    ok_hosts = {host, host.removeprefix("www."), "www." + host.removeprefix("www.")}
    urls: dict[str, list[str]] = {}
    cards: dict[str, dict] = {}
    presenter = source_id in PRESENTERS  # their list cards carry no day-level date: take every offered page, read the date from the page itself
    for c in recs:
        if c["category"] != "excluded_domestic_orchestra" and urlsplit(c["source_url"]).hostname in ok_hosts and (presenter or (c["local_date"] and c["local_date"] >= today)):
            urls.setdefault(c["source_url"], [])
            cards.setdefault(c["source_url"], c)
            if c["local_date"]:
                urls[c["source_url"]].append(c["local_date"])
    return url, body, urls, scope, cards


def probe_nhk(f: Fetcher, k: int) -> dict:
    """NHK響's concert list is a JSON API: inspect its record keys, sample the per-concert HTML pages it links (``details_url``), and read the
    season ticket announcement news page separately (an article, not a concert page)."""
    out = {"scope": "JSON concert list (details_url pages sampled) + ticket announcement news page", "list_url": NHK_JSON_INDEX, "pages": [], "news_pages": [],
           "json_record_keys": None, "date_like_keys": None, "N_offered": 0}
    details: list[str] = []
    idx, _ = f.get(NHK_JSON_INDEX)
    if idx:
        newest = "https://www.nhkso.or.jp" + sorted(json.loads(idx)["year_list"])[-1]
        data, _ = f.get(newest)
        if data:
            parsed = json.loads(data)
            records = parsed.get("concert_list") or parsed.get("list") or next((v for v in parsed.values() if isinstance(v, list)), [])
            keys = sorted({k_ for r in records if isinstance(r, dict) for k_ in r})
            out["json_record_keys"] = keys
            out["date_like_keys"] = [k_ for k_ in keys if re.search(r"date|day|time|update|release|open|publish|news", k_, re.I)]
            details = sorted({urljoin("https://www.nhkso.or.jp/", r["details_url"]) for r in records if isinstance(r, dict) and r.get("details_url")})
            details = [u for u in details if urlsplit(u).hostname == "www.nhkso.or.jp"]
            out["N_offered"] = len(details)
    for u in spread(details, k):
        html, meta = f.get(u)
        page = {"url": u, "status": meta.get("status"), "error": meta.get("error"), "sha256": meta.get("sha256"), "fetched_at": meta.get("fetched_at"), "performance_dates": [], "signals": []}
        if html and meta.get("status") == 200:
            page["signals"] = signals(html)
        out["pages"].append(page)
    for url in NHK_TICKET_NEWS:
        html, meta = f.get(url)
        out["news_pages"].append({"url": url, "status": meta.get("status"), "error": meta.get("error"), "sha256": meta.get("sha256"), "fetched_at": meta.get("fetched_at"),
                                  "signals": signals(html) if html and meta.get("status") == 200 else []})
    return out


def probe(f: Fetcher, k: int, only: list[str] | None, today: str | None = None) -> dict:
    today = today or datetime.now(JST).date().isoformat()
    out: dict[str, dict] = {}
    cross: list[dict] = []
    for sid in (only or PROBED):
        if sid in NEVER:
            raise SystemExit(f"{sid} is never probed")
        if sid == "nhkso":
            nh = probe_nhk(f, k)
            ok_pages = [p for p in nh["pages"] if p["status"] == 200]
            verdicts = iter(source_level([{"signals": p["signals"], "performance_dates": []} for p in ok_pages]))
            for p in nh["pages"]:
                p["verdict"] = next(verdicts) if p["status"] == 200 else "fetch_failed"
            counts = {c: sum(1 for p in nh["pages"] if p["verdict"] == c) for c in ("published", "update_only", "ambiguous", "none", "fetch_failed")}
            out[sid] = {**nh, "sample_rule": f"sorted details_url pages, {k} evenly spread; the season ticket news page is listed apart (an article, not a concert page)",
                        "n_sampled": len(nh["pages"]), "counts": counts, "landing_news": None}
            continue
        list_url, list_html, urls, scope, cards = listing(sid, f, today)
        sample = sorted(urls) if sid == "japanarts" else spread(list(urls), k)
        pages = []
        for u in sample:
            html, meta = f.get(u)
            page = {"url": u, "status": meta.get("status"), "error": meta.get("error"), "sha256": meta.get("sha256"), "fetched_at": meta.get("fetched_at"),
                    "performance_dates": sorted(set(urls[u])), "signals": []}
            if html and meta.get("status") == 200:
                page["signals"] = signals(html)
                if sid in PRESENTERS:
                    try:
                        page["performance_dates"] = sorted({c["local_date"] for c in parse_presenter_detail(sid, html, u)["performances"] if c["local_date"]} | set(page["performance_dates"]))
                    except ParseError:
                        pass
                if sid == "japanarts":
                    cross.append(check_japanarts_detail(html, u, cards.get(u)))
            pages.append(page)
        ok_pages = [p for p in pages if p["status"] == 200]
        verdicts = iter(source_level([{"signals": p["signals"], "performance_dates": p["performance_dates"]} for p in ok_pages]))
        for p in pages:
            p["verdict"] = next(verdicts) if p["status"] == 200 else "fetch_failed"
        counts = {c: sum(1 for p in pages if p["verdict"] == c) for c in ("published", "update_only", "ambiguous", "none", "fetch_failed")}
        out[sid] = {"scope": scope, "list_url": list_url, "N_offered": len(urls), "sample_rule": "all offered URLs" if sid == "japanarts" else f"sorted URLs, {k} evenly spread (index round(i*(N-1)/(k-1)))",
                    "n_sampled": len(pages), "counts": counts, "landing_news": dated_news(list_html) if list_html else None, "pages": pages}
    return {"sources": out, "japanarts_crosscheck": cross, "cross_page_notes": cross_page_notes(cross)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / f"evidence/p03/announcement-availability-{datetime.now(JST).date().isoformat()}.json")
    ap.add_argument("--max-requests", type=int, default=120)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--source", action="append", choices=PROBED)
    ap.add_argument("--replay-raw", action="store_true", help="re-analyse pages already in evidence/raw (no network at all)")
    ap.add_argument("--merge-into", type=Path, help="update only the probed sources of this existing evidence file and append to its runs")
    a = ap.parse_args()
    raw_dir = ROOT / "evidence/raw"
    reader = None if a.replay_raw else Reader(raw_dir, interval=2.0)
    f = Fetcher(reader, a.max_requests, replay=raw_index(raw_dir) if a.replay_raw else None)
    aborted = None
    result: dict = {"sources": {}, "japanarts_crosscheck": [], "cross_page_notes": []}
    try:
        result = probe(f, a.k, a.source)
    except CapReached as exc:
        aborted = str(exc)
    finally:
        if reader:
            reader.close()
    run = {"at": datetime.now(timezone.utc).isoformat(), "mode": "replay-raw" if a.replay_raw else "live", "sources": a.source or list(PROBED), "requests_made": f.count, "aborted": aborted}
    base = json.loads(a.merge_into.read_text()) if a.merge_into else {}
    prior = base.get("runs") or ([{"at": base["generated_at"], "mode": "live", "sources": list(base.get("sources", {})), "requests_made": base["requests_made"], "aborted": base.get("aborted")}] if base else [])
    runs = prior + [run]
    sources = {**base.get("sources", {}), **result["sources"]}
    refreshed = "japanarts" in result["sources"] or not base
    cross = result["japanarts_crosscheck"] if refreshed else base.get("japanarts_crosscheck", [])
    notes_cross = result["cross_page_notes"] if refreshed else base.get("cross_page_notes", [])
    doc = {"generated_at": run["at"], "tool": "scripts/p03_announcement_probe.py", "never_probed": list(NEVER), "request_cap": a.max_requests, "k_per_source": a.k,
           "requests_made": sum(r["requests_made"] for r in runs), "aborted": next((r["aborted"] for r in runs if r["aborted"]), None), "runs": runs,
           "robots": {**base.get("robots", {}), **{h: (None if r is None else {"status": r[1]}) for h, r in f.robots.items()}}, "notes": base.get("notes", []) + f.log,
           "sources": {k: sources[k] for k in PROBED if k in sources}, "japanarts_crosscheck": cross, "cross_page_notes": notes_cross}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.out} ({f.count} {'replayed lookups' if a.replay_raw else 'requests'}{', ABORTED: ' + aborted if aborted else ''})", file=sys.stderr)
    return 1 if aborted else 0


if __name__ == "__main__":
    raise SystemExit(main())
