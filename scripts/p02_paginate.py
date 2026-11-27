"""P0.2: walk the numbered pages of the static list sources (tso, njp, jpo, kanagawa_geikyo) and report per-source
page count, unique candidates, date range and month distribution. tmso (use-restriction pending) and tpo (unreachable
from this network on 2026-11-04) are intentionally not walked. One request per 2 s; pages are discovered from page 1.
Usage: python scripts/p02_paginate.py [--out evidence/p02/paginate-YYYY-MM-DD.json]"""
import argparse, collections, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classical_radar.network import FetchError, Reader  # noqa: E402
from classical_radar.parsers import ParseError, parse_list  # noqa: E402

CFG = {  # source -> (host, first page url, page url template, regex over hrefs that yields the page number)
    "tso": ("tokyosymphony.jp", "https://tokyosymphony.jp/concert/", "https://tokyosymphony.jp/concert/page/{n}/", r"/concert/page/(\d+)/"),
    "njp": ("www.njp.or.jp", "https://www.njp.or.jp/concerts/", "https://www.njp.or.jp/concerts/page/{n}/", r"/concerts/page/(\d+)/"),
    "jpo": ("japanphil.or.jp", "https://japanphil.or.jp/concert/?p_type=performance&p_status=", "https://japanphil.or.jp/concert/?p_type=performance&p_status&p_page={n}", r"p_page=(\d+)"),
    "kanagawa_geikyo": ("kanagawa-geikyo.com", "https://kanagawa-geikyo.com/concert/", "https://kanagawa-geikyo.com/concert/page/{n}/", r"/concert/page/(\d+)/"),
}


def fetch(reader, url, host):
    try:
        return reader.get(url, host)
    except FetchError as exc:
        if "transport error" not in str(exc):
            raise
        time.sleep(5)
        return reader.get(url, host)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / f"evidence/p02/paginate-{datetime.now().date()}.json")
    args = ap.parse_args()
    reader = Reader(ROOT / "evidence/raw")
    rows = []
    try:
        for sid, (host, first, tpl, rx) in CFG.items():
            row = {"source_id": sid, "pages": [], "error": None}
            try:
                body, meta = fetch(reader, first, host)
                last = max([int(m.group(1)) for a in BeautifulSoup(body, "html.parser").select("a[href]") if (m := re.search(rx, a["href"]))] or [1])
                cands, pages = {}, []
                for n in range(1, last + 1):
                    url = first if n == 1 else tpl.format(n=n)
                    html, m = (body, meta) if n == 1 else fetch(reader, url, host)
                    recs, cov = parse_list(sid, html, url)
                    pages.append({"page": n, "url": url, "sha256": m["sha256"], "dom_cards": cov["dom_cards"], "candidates": len(recs), "skipped": cov["skipped_cards"]})
                    for r in recs:
                        cands[r["performance_id"]] = r
                dates = sorted(r["local_date"] for r in cands.values() if r["local_date"])
                row.update(pages=pages, last_page_declared=last, unique_candidates=len(cands), dom_cards=sum(p["dom_cards"] for p in pages),
                           date_min=dates[0] if dates else None, date_max=dates[-1] if dates else None,
                           by_month=dict(sorted(collections.Counter(d[:7] for d in dates).items())),
                           no_date=sum(1 for r in cands.values() if not r["local_date"]),
                           candidates=[{"title": r["title"], "local_date": r["local_date"], "local_time": r["local_time"], "venue": r["venue"], "url": r["source_url"], "category_hint": r["category"]} for r in cands.values()])
            except (FetchError, ParseError) as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
    finally:
        reader.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "sources": rows}, ensure_ascii=False, indent=1))
    for r in rows:
        print(r["source_id"], r["error"] or f"pages {len(r['pages'])}/{r['last_page_declared']} unique {r['unique_candidates']} (cards {r['dom_cards']}) {r['date_min']}..{r['date_max']} no_date {r['no_date']}")
        if not r["error"]:
            print("   ", r["by_month"])


if __name__ == "__main__":
    main()
