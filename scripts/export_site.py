"""Export the official-confirmed concerts of a local database to the site data file (reviewed in a PR, deployed on merge).

Usage: python scripts/export_site.py DB [site-data/concerts.json]
The file holds facts only (titles, dates, venues, performers, programmes, sale times, source URLs) - no page text, posters or photos
other than freely licensed Commons thumbnails with credits. The repository must stay private (source policies are unknown).
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from build_demo import export  # noqa: E402
from classical_radar import db  # noqa: E402


def main():
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "site-data/concerts.json"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn = db.connect(str(src))
    data = export(conn, now)
    conn.close()
    for c in data["concerts"]:  # merges are not stored here: build_site.py applies site-data/same_concert.json at every build (ADR-0006)
        c.pop("duplicate_of", None)
        for p in c["performances"]:
            p.pop("same_as", None)
    data["fixed_as_of"] = False  # the site computes "the next 12 months" from the viewer's current time
    data["snapshot_label"] = now[:10] + " 更新"
    data["coverage"]["sources"] = sorted(data["coverage"]["sources"], key=lambda s: s["source_id"])
    out.parent.mkdir(parents=True, exist_ok=True)
    # one concert per line: small, reviewable diffs in data PRs
    lines = ",\n".join(json.dumps(c, ensure_ascii=False, sort_keys=True) for c in sorted(data.pop("concerts"), key=lambda c: c["id"]))
    head = json.dumps(data, ensure_ascii=False, sort_keys=True)
    out.write_text(head[:-1] + ',"concerts":[\n' + lines + "\n]}\n", encoding="utf8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
