"""P0.2: cross-check announcement-based NHK links against each future subscription concert's own page (independent evidence).
Reads evidence/p02/ticket-linking-*.json, fetches each distinct details_url once (2 s apart). Writes evidence/p02/nhk-sale-crosscheck-DATE.json."""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classical_radar.linking import parse_nhk_detail_single_ticket  # noqa: E402
from classical_radar.network import FetchError, Reader  # noqa: E402
from classical_radar.parsers import parse_nhk  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--linking", type=Path, default=ROOT / "evidence/p02/ticket-linking-2026-11-04.json")
    ap.add_argument("--out", type=Path, default=ROOT / f"evidence/p02/nhk-sale-crosscheck-{datetime.now().date()}.json")
    args = ap.parse_args()
    link = json.loads(args.linking.read_text())["nhk"]
    reader = Reader(ROOT / "evidence/raw")
    jtxt, _ = reader.get("https://www.nhkso.or.jp/concert/json/archive_concert_2026.json", "www.nhkso.or.jp")
    perfs = {p["performance_id"]: p for p in parse_nhk(json.loads(jtxt), json.loads((ROOT / "tests/fixtures/nhkso-halls.json").read_text()), "https://www.nhkso.or.jp/concert/json/archive_concert_2026.json")}
    expected = {}
    for x in link["linked"]:
        if x["local_date"] >= str(datetime.now().date()):
            expected.setdefault(perfs[x["performance_id"]]["source_url"], {})[x["phase_type"]] = x["starts_at"]
    rows = []
    try:
        for url, want in sorted(expected.items()):
            row = {"url": url, "linked": want, "page": None, "match": None, "error": None}
            try:
                html, m = reader.get(url, "www.nhkso.or.jp")
                row["sha256"] = m["sha256"]
                got = parse_nhk_detail_single_ticket(html) if m["status"] == 200 else None
                row["page"], row["match"] = got, (got == want) if got else None
            except FetchError as exc:
                row["error"] = str(exc)
                if "paused" in str(exc):
                    rows.append(row); break
            rows.append(row)
    finally:
        reader.close()
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "pages": len(rows), "match": sum(r["match"] is True for r in rows),
           "mismatch": sum(r["match"] is False for r in rows), "page_unparsed": sum(r["match"] is None for r in rows), "rows": rows}
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print({k: v for k, v in out.items() if k != "rows"})
    for r in rows:
        if r["match"] is not True:
            print("  CHECK", r["url"], r["match"], r["error"], r["linked"], r["page"])


if __name__ == "__main__":
    main()
