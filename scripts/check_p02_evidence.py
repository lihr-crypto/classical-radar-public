"""Offline consistency checks for the 2026-11-04 P0.2 evidence. Fails if the committed numbers drift from what the report states."""
import glob, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classical_radar.contract import find_legacy_keys  # noqa: E402


def load(name):
    return json.loads((ROOT / "evidence/p02" / name).read_text())


def main():
    for f in sorted(glob.glob(str(ROOT / "evidence/p02/*.json"))):
        assert find_legacy_keys(json.loads(Path(f).read_text())) == [], f"legacy field names in {f}"
    pd = {s["source_id"]: s for s in load("presenter-details-2026-11-04.json")["sources"]}
    assert (pd["japanarts"]["items_parsed_n"], pd["japanarts"]["baseline_N_items"], pd["japanarts"]["performances_n"]) == (42, 42, 58)
    assert (pd["kajimoto"]["items_parsed_n"], pd["kajimoto"]["baseline_N_items"], pd["kajimoto"]["performances_n"]) == (15, 15, 17)
    for s in pd.values():
        for i in s["items"]:
            for p in i["performances"]:
                assert p["local_date"] and p["venue"] and p["date_precision"] == "exact_time", (i["url"], p)
    y = load("yomikyo-2026-11-04.json")
    assert (y["calendar_n_parsed"], y["calendar_N"], y["future_items"], y["detail_venue_n"], len(y["date_time_mismatches"])) == (83, 83, 33, 27, 0)
    pg = {s["source_id"]: s for s in load("paginate-2026-11-04.json")["sources"]}
    assert {k: v["unique_candidates"] for k, v in pg.items()} == {"tso": 69, "njp": 47, "jpo": 80, "kanagawa_geikyo": 71}
    assert {k: len(v["pages"]) for k, v in pg.items()} == {"tso": 4, "njp": 6, "jpo": 4, "kanagawa_geikyo": 8}
    assert sum(1 for c in pg["kanagawa_geikyo"]["candidates"] if c["category_hint"] == "piano_recital") == 21
    assert sum(1 for c in pg["kanagawa_geikyo"]["candidates"] if c["category_hint"] == "excluded_domestic_orchestra") == 6
    hints = {sid: [i["performances"][0]["category_hint"] for i in pd[sid]["items"]] for sid in pd}
    assert (hints["japanarts"].count("piano_recital"), hints["japanarts"].count("excluded_domestic_orchestra"), hints["kajimoto"].count("piano_recital")) == (14, 2, 2)
    dup = load("possible-duplicates-2026-11-04.json")["groups"]
    assert len(dup) == 10 and all(len({x["source_id"] for x in g}) > 1 for g in dup)
    t = load("ticket-linking-2026-11-04.json")
    assert (t["nhk"]["future_subscription_linked"], t["nhk"]["future_subscription_performances"], len(t["nhk"]["linked"])) == (32, 32, 80)
    assert all(x["reminder_eligible"] is False and x["linkage_status"] == "linked_by_rule" for x in t["nhk"]["linked"])
    assert (t["kajimoto"]["single_performance_items_linked"], t["kajimoto"]["multi_performance_items_unlinked"]) == (13, 2)
    c = load("nhk-sale-crosscheck-2026-11-04.json")
    assert (c["match"], c["mismatch"], c["page_unparsed"], c["pages"]) == (16, 0, 0, 16)
    print("OK: P0.2 evidence consistent (no legacy names; 4 presenter/season baselines; 16/16 NHK cross-check)")


if __name__ == "__main__":
    main()
