"""P0.2: link ticket-sale announcements to concrete performances, evidence-only.
NHK: season JSON + announcement page (2 requests). KAJIMOTO: re-uses the committed presenter-details evidence + local raw store.
Writes evidence/p02/ticket-linking-YYYY-MM-DD.json. No notifications are created (reminder_eligible is always false)."""
import argparse, collections, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classical_radar.linking import link_nhk_subscription, link_presenter_claims, parse_nhk_single_ticket_batches  # noqa: E402
from classical_radar.network import Reader  # noqa: E402
from classical_radar.parsers import parse_nhk, parse_presenter_detail  # noqa: E402

H = "www.nhkso.or.jp"
JSON_URL = "https://www.nhkso.or.jp/concert/json/archive_concert_2026.json"
NEWS_URL = "https://www.nhkso.or.jp/news/20260701.html"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / f"evidence/p02/ticket-linking-{datetime.now().date()}.json")
    ap.add_argument("--details", type=Path, default=ROOT / "evidence/p02/presenter-details-2026-11-04.json")
    args = ap.parse_args()
    as_of = datetime.now(timezone.utc)
    reader = Reader(ROOT / "evidence/raw")
    try:
        jtxt, jmeta = reader.get(JSON_URL, H)
        ntxt, nmeta = reader.get(NEWS_URL, H)
        halls_txt, _ = reader.get("https://www.nhkso.or.jp/concert/json/list_archive_concert.json", H)  # season index (not hall data)
    finally:
        reader.close()
    halls = json.loads((ROOT / "tests/fixtures/nhkso-halls.json").read_text())
    perfs = parse_nhk(json.loads(jtxt), halls, JSON_URL)
    batches = parse_nhk_single_ticket_batches(ntxt, NEWS_URL)
    nhk = link_nhk_subscription(perfs, batches, as_of)
    future = [p for p in perfs if p["local_date"] >= str(as_of.date())]
    linked_ids = {x["performance_id"] for x in nhk["linked"]}
    sub_future = [p for p in future if p["nhk"]["category"] == "subscription"]
    kaj = {"items": 0, "items_with_claims": 0, "single_performance_items_linked": 0, "multi_performance_items_unlinked": 0, "linked_phases": 0, "unlinked": []}
    details = json.loads(args.details.read_text())
    for src in details["sources"]:
        if src["source_id"] != "kajimoto":
            continue
        for item in src["items"]:
            kaj["items"] += 1
            html = (ROOT / f"evidence/raw/{item['sha256']}.html").read_text(encoding="utf8")
            d = parse_presenter_detail("kajimoto", html, item["url"])
            r = link_presenter_claims(d, as_of)
            kaj["items_with_claims"] += bool(d["ticket_claims"])
            if r["linked"]:
                kaj["single_performance_items_linked"] += 1
                kaj["linked_phases"] += len(r["linked"])
            elif d["ticket_claims"]:
                kaj["multi_performance_items_unlinked"] += 1
                kaj["unlinked"].append({"url": item["url"], "reason": r["unlinked"][0]["reason"]})
    out = {"generated_at": as_of.isoformat(), "as_of": as_of.isoformat(),
           "nhk": {"json_sha256": jmeta["sha256"], "news_sha256": nmeta["sha256"], "news_url": NEWS_URL,
                   "batches": [{"months": b["months"], "general_sale_starts_at": b["general"]["starts_at"], "member_presale_starts_at": b["member"]["starts_at"],
                                "start_precision": "exact_time", "source_url": b["source_url"], "label_raw": b["label_raw"]} for b in batches],
                   "performances_in_json": len(perfs), "future_performances": len(future), "future_subscription_performances": len(sub_future),
                   "future_subscription_linked": sum(1 for p in sub_future if p["performance_id"] in linked_ids),
                   "unlinked_reasons": dict(collections.Counter(u["reason"][:60] for u in nhk["unlinked"])),
                   "linked": [{**x, "local_date": next(p["local_date"] for p in perfs if p["performance_id"] == x["performance_id"])} for x in nhk["linked"]],
                   "unlinked": nhk["unlinked"]},
           "kajimoto": kaj}
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    n = out["nhk"]
    print(f"NHK: future subscription performances linked {n['future_subscription_linked']}/{n['future_subscription_performances']}; "
          f"phases {len(n['linked'])}; unlinked reasons {n['unlinked_reasons']}")
    print("KAJIMOTO:", {k: v for k, v in kaj.items() if k != "unlinked"})


if __name__ == "__main__":
    main()
