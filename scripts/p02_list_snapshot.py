"""P0.2: re-read each registered list landing page once, parse it, and diff against the committed 2026-10-31 snapshot.
Records the observation window (days between snapshots) and pagination links seen on each page.
Usage: python scripts/p02_list_snapshot.py [--out evidence/p02/list-snapshot-YYYY-MM-DD.json]"""
import argparse, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classical_radar.network import FetchError, Reader  # noqa: E402
from classical_radar.parsers import ParseError, parse_list  # noqa: E402
from classical_radar.sources import SOURCES  # noqa: E402

STATIC = ["tmso", "tso", "jpo", "njp", "japanarts", "kajimoto", "kanagawa_geikyo"]  # tpo deferred (ADR-0001)


def pagination(html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = set()
    for a in soup.select("a[href]"):
        label = a.get_text(" ", strip=True)
        href = a["href"]
        if re.search(r"[?&/](page|paged|p|month|y|ym|date)[=/]\d|/page/\d+|[?&]yyyy=|[?&]mm=", href) or re.fullmatch(r"(次へ|NEXT|Next|>|›|»|\d{1,2}月|\d{4}年\d{1,2}月)", label):
            out.add((label[:20], urljoin(url, href)))
    return sorted(out)[:25]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / f"evidence/p02/list-snapshot-{datetime.now().date()}.json")
    args = ap.parse_args()
    old = json.loads((ROOT / "evidence/list-candidates.json").read_text())
    old_by = {}
    for r in old:
        old_by.setdefault(r["source_id"], {})[r["performance_id"]] = r
    reader = Reader(ROOT / "evidence/raw")
    rows = []
    try:
        for sid in STATIC:
            src = SOURCES[sid]
            host = re.sub(r"^https://([^/]+)/.*", r"\1", src.url)
            row = {"source_id": sid, "url": src.url, "error": None}
            try:
                try:
                    body, meta = reader.get(src.url, host)
                except FetchError as exc:
                    if "transport error" not in str(exc):
                        raise
                    time.sleep(5)  # one retry for a transient reset; never for 401/403/429
                    body, meta = reader.get(src.url, host)
                recs, cov = parse_list(sid, body, src.url)
                new = {r["performance_id"]: r for r in recs}
                prev = old_by.get(sid, {})
                row.update(sha256=meta["sha256"], fetched_at=meta["fetched_at"], coverage=cov,
                           snapshot_2026_10_31_n=len(prev), snapshot_now_n=len(new),
                           added=[{"title": r["title"], "local_date": r["local_date"], "url": r["source_url"]} for k, r in new.items() if k not in prev],
                           removed=[{"title": r["title"], "local_date": r["local_date"], "url": r["source_url"]} for k, r in prev.items() if k not in new],
                           pagination_links=pagination(body, src.url))
            except (FetchError, ParseError) as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
    finally:
        reader.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "baseline_snapshot": "evidence/list-candidates.json (2026-10-31)", "sources": rows}, ensure_ascii=False, indent=1))
    for r in rows:
        if r["error"]:
            print(r["source_id"], "ERROR", r["error"]); continue
        print(r["source_id"], f"{r['snapshot_2026_10_31_n']} -> {r['snapshot_now_n']}  +{len(r['added'])} -{len(r['removed'])}  paging:{len(r['pagination_links'])}")


if __name__ == "__main__":
    main()
