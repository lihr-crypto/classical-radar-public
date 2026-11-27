"""P0.2: fetch every UPCOMING item on the Japan Arts / KAJIMOTO landing page and parse its detail page.

Low volume (one request per 2 s per host, stops on 401/403/429). Writes a dated evidence file with
n/N per source and every failure. Raw HTML stays in the git-ignored evidence/raw directory.
Usage: python scripts/p02_presenter_details.py [--out evidence/p02/presenter-details-YYYY-MM-DD.json]
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classical_radar.contract import compact_candidate, compact_claim  # noqa: E402
from classical_radar.network import FetchError, Reader  # noqa: E402
from classical_radar.parsers import ParseError, parse_list, parse_presenter_detail  # noqa: E402

TARGETS = {"japanarts": "www.japanarts.co.jp", "kajimoto": "www.kajimotomusic.com"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / f"evidence/p02/presenter-details-{datetime.now().date()}.json")
    args = ap.parse_args()
    from classical_radar.sources import SOURCES
    reader = Reader(ROOT / "evidence/raw")
    result = []
    try:
        for sid, host in TARGETS.items():
            list_url = SOURCES[sid].url
            body, meta = reader.get(list_url, host)
            cards, cov = parse_list(sid, body, list_url)
            urls = sorted({c["source_url"] for c in cards})
            row = {"source_id": sid, "list_url": list_url, "list_sha256": meta["sha256"], "list_fetched_at": meta["fetched_at"],
                   "baseline_N_items": len(urls), "baseline_scope": "all items in the UPCOMING block of the landing page (no pagination observed)",
                   "items": []}
            for u in urls:
                item = {"url": u, "status": None, "performances": [], "ticket_claims": [], "error": None}
                try:
                    html, m = reader.get(u, host)
                    item.update(status=m["status"], sha256=m["sha256"], fetched_at=m["fetched_at"])
                    if m["status"] == 200:
                        d = parse_presenter_detail(sid, html, u)
                        item["performances"] = [compact_candidate(x) for x in d["performances"]]
                        item["ticket_claims"] = [compact_claim(x) for x in d["ticket_claims"]]
                except (FetchError, ParseError) as exc:
                    item["error"] = f"{type(exc).__name__}: {exc}"
                    if isinstance(exc, FetchError) and "paused" in str(exc):
                        row["items"].append(item); break
                row["items"].append(item)
            row["items_parsed_n"] = sum(1 for i in row["items"] if i["performances"])
            row["performances_n"] = sum(len(i["performances"]) for i in row["items"])
            result.append(row)
    finally:
        reader.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "sources": result}, ensure_ascii=False, indent=1))
    for r in result:
        print(r["source_id"], f"items parsed {r['items_parsed_n']}/{r['baseline_N_items']}", "performances", r["performances_n"])
        for i in r["items"]:
            if not i["performances"]:
                print("  FAIL", i["url"], i["status"], i["error"])


if __name__ == "__main__":
    main()
