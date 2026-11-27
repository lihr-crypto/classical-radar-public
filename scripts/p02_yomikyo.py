"""P0.2: Yomikyo season calendar (cal.php) -> every concert of the fiscal year, then venue from each future detail page.
Usage: python scripts/p02_yomikyo.py [--out evidence/p02/yomikyo-YYYY-MM-DD.json] [--from-date YYYY-MM-DD]
One request per 2 s; stops on 401/403/429."""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classical_radar.network import FetchError, Reader  # noqa: E402
from classical_radar.parsers import ParseError, parse_presenter_detail, parse_yomikyo_calendar  # noqa: E402

HOST = "yomikyo.or.jp"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / f"evidence/p02/yomikyo-{datetime.now().date()}.json")
    ap.add_argument("--from-date", default=str(datetime.now().date()))
    args = ap.parse_args()
    reader = Reader(ROOT / "evidence/raw")
    try:
        body, meta = reader.get("https://yomikyo.or.jp/cal.php", HOST)
        cal, cov = parse_yomikyo_calendar(body, "https://yomikyo.or.jp/cal.php")
        future = [c for c in cal if c["local_date"] >= args.from_date]
        details = []
        for c in future:
            row = {"url": c["source_url"], "calendar_date": c["local_date"], "calendar_time": c["local_time"], "calendar_title": c["title"],
                   "status": None, "venue": None, "detail_date": None, "detail_time": None, "error": None}
            try:
                html, m = reader.get(c["source_url"], HOST)
                row.update(status=m["status"], sha256=m["sha256"], fetched_at=m["fetched_at"])
                if m["status"] == 200:
                    p = parse_presenter_detail("yomikyo", html, c["source_url"])["performances"][0]
                    row.update(venue=p["venue"], detail_date=p["local_date"], detail_time=p["local_time"])
            except (FetchError, ParseError) as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, FetchError) and "paused" in str(exc):
                    details.append(row); break
            details.append(row)
    finally:
        reader.close()
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "source_id": "yomikyo", "calendar_url": "https://yomikyo.or.jp/cal.php",
           "calendar_sha256": meta["sha256"], "calendar_fetched_at": meta["fetched_at"], "calendar_coverage": cov,
           "baseline_scope": "official season calendar 2026年度 (Apr 2026 - Mar 2027); N = concert anchors in the 12 monthly tables",
           "calendar_N": cov["anchors"], "calendar_n_parsed": cov["unique_candidates"], "from_date": args.from_date,
           "future_items": len(future), "detail_venue_n": sum(1 for d in details if d["venue"]),
           "date_time_mismatches": [d for d in details if d["venue"] and (d["detail_date"], d["detail_time"]) != (d["calendar_date"], d["calendar_time"])],
           "details": details}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"calendar {out['calendar_n_parsed']}/{out['calendar_N']}; future {out['future_items']}; venue {out['detail_venue_n']}/{out['future_items']}; "
          f"date/time mismatches {len(out['date_time_mismatches'])}")
    for d in details:
        if not d["venue"] or d in out["date_time_mismatches"]:
            print("  CHECK", d["url"], d["status"], d["error"], d["calendar_date"], d["calendar_time"], d["detail_date"], d["detail_time"])


if __name__ == "__main__":
    main()
