"""Offline: cross-source same-date/compatible-venue review hints over the P0.2 evidence (paginate + presenter details)."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classical_radar.parsers import possible_duplicates  # noqa: E402


def rows():
    pg = json.loads((ROOT / "evidence/p02/paginate-2026-11-04.json").read_text())
    pd = json.loads((ROOT / "evidence/p02/presenter-details-2026-11-04.json").read_text())
    for s in pg["sources"]:
        for c in s["candidates"]:
            yield dict(source_id=s["source_id"], performance_id=f"{s['source_id']}|{c['url']}|{c['local_date']}", local_date=c["local_date"], venue=c["venue"], title=c["title"], url=c["url"])
    for s in pd["sources"]:
        for i in s["items"]:
            for p in i["performances"]:
                yield dict(source_id=p["source_id"], performance_id=p["performance_id"], local_date=p["local_date"], venue=p["venue"], title=p["title"], url=p["source_url"])


def main():
    allc = list(rows())
    by = {c["performance_id"]: c for c in allc}
    groups = possible_duplicates(allc)
    out = {"note": "review hints only; nothing is merged", "groups": [[{k: by[i][k] for k in ("source_id", "local_date", "venue", "title", "url")} for i in g] for g in groups]}
    (ROOT / "evidence/p02/possible-duplicates-2026-11-04.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(len(groups), "groups")


if __name__ == "__main__":
    main()
