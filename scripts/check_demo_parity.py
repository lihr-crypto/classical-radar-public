"""Parity check: the browser demo backend (demo.js) must return the same ids, order, totals, facets and calendar as the Python implementation.
Usage: python scripts/check_demo_parity.py DB DATA.json   (DATA.json from build_demo.py --data-only, built from the same DB and --as-of)"""
import json, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classical_radar import db  # noqa: E402
from classical_radar.discover import calendar_range, discover, facets  # noqa: E402

QUERIES = [
    "category=all&months=12&region_mode=kanto_first&page=1&limit=100", "category=all&months=24&region_mode=nationwide&page=1&limit=100",
    "category=piano_recital&months=12&region_mode=kanto_first&page=1&limit=50", "category=all&months=12&region_mode=kanto_first&page=2&limit=10",
    "composer=ベートーヴェン&limit=100", "composer=Beethoven&composer=ブラームス&limit=100", "composer=ベートーヴェン&conductor=沼尻&limit=100",
    "work=交響曲第9番&limit=100", "work=beethoven:symphony-9&limit=100", "performer=石井&limit=100", "venue=サントリー&limit=100",
    "composer=ショパン&venue=みなとみらい&performer=牛田&limit=100", "orchestra=overseas&limit=100", "orchestra=nhkso&limit=100",
    "orchestra=tpo&orchestra=tso&limit=100", "orchestra=ov-br-so&limit=100", "orchestra=東京フィル&limit=100", "orchestra=seven&composer=ブラームス&limit=100",
    "category=overseas_orchestra_visit&limit=100", "composer=存在しない&limit=20", "conductor=小林研一郎&composer=ブラームス&limit=100",
]


def main():
    dbpath, datapath = sys.argv[1], sys.argv[2]
    data = json.loads(Path(datapath).read_text())
    as_of = datetime.fromisoformat(data["as_of"])
    conn = db.connect(dbpath)
    expected = []
    for q in QUERIES:
        qs = parse_qs(q)
        flt = {k: qs[k] for k in ("orchestra", "composer", "work", "conductor", "performer", "venue") if k in qs}
        r = discover(conn, as_of=as_of, category=qs.get("category", ["all"])[0], months=int(qs.get("months", ["12"])[0]), region_mode=qs.get("region_mode", ["kanto_first"])[0],
                     page=int(qs.get("page", ["1"])[0]), limit=int(qs.get("limit", ["20"])[0]), filters=flt)
        expected.append({"q": q, "total": r["total"], "ids": [i["concert_id"] for i in r["items"]], "perf_ids": [i["performance_ids"] for i in r["items"]],
                         "tickets": [i["ticket_status"] for i in r["items"]], "groups": [i["region_group"] for i in r["items"]], "orgs": [i["organization_id"] for i in r["items"]],
                         "pieces": [i["pieces"] for i in r["items"]], "soloists": [i["soloists"] for i in r["items"]], "conductors": [i["conductors"] for i in r["items"]]})
    fac = facets(conn, as_of=as_of)
    fac2 = facets(conn, as_of=as_of, filters={"composer": ["ベートーヴェン"]})
    from datetime import date
    cal = calendar_range(conn, date(2026, 11, 1), date(2026, 12, 31))
    out = {"queries": expected, "facets": [{k: v for k, v in f.items() if k != "filters"} for f in (fac, fac2)],
           "calendar": {"perf": [p["id"] for p in cal["performances"]], "sales": [s["id"] for s in cal["sales"]],
                                                                                          "orch": [[o["key"] for o in p["orchestras"]] for p in cal["performances"]]}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(out, f, ensure_ascii=False)
    res = subprocess.run(["node", str(ROOT / "scripts/check_demo_parity.js"), datapath, f.name], capture_output=True, text=True)
    print(res.stdout.strip())
    if res.returncode:
        print(res.stderr.strip())
        sys.exit(1)


if __name__ == "__main__":
    main()
