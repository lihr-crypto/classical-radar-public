"""Build the self-contained read-only demo page from a local database.

Usage: python scripts/build_demo.py DB OUT.html [--as-of ISO] [--data-only OUT.json]
The page embeds a snapshot of the *official-confirmed* rows (titles, dates, venues, performers, programmes, sale times) and the same UI code
as the local app, with demo.js standing in for the API. Nothing is fetched at runtime. Personal state stays in the viewer's browser.
The output contains scraped facts from official sites: keep it private (see docs/RELEASE_v0.1.md, policy status unknown).
"""
import argparse, json, re, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classical_radar import db, duplicates  # noqa: E402
from classical_radar.parsers import JST  # noqa: E402
import base64  # noqa: E402
from classical_radar.discover import _summaries, concert_detail, coverage, orchestra_map  # noqa: E402
from classical_radar.orchestras import ORCHESTRAS  # noqa: E402
from classical_radar.works import _ALIAS  # noqa: E402

WEB = ROOT / "src/classical_radar/web"


def _inline(img, media_dir: Path):
    if not img:
        return None
    path = media_dir / img["file"]
    if not path.is_file():
        return None
    return {**img, "src": "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()}


def export(conn: sqlite3.Connection, as_of: str, media_dir: Path = Path("data/media")) -> dict:
    concerts = []
    omap = orchestra_map(conn)
    for c in conn.execute("SELECT * FROM concert WHERE verification_status='official_confirmed' ORDER BY id"):
        sid, url = c["identity_key"].split("|", 1)
        perfs = []
        for p in conn.execute("SELECT * FROM performance WHERE concert_id=? AND confirmation_status='official_confirmed' AND status!='cancelled' ORDER BY local_date, starts_at", (c["id"],)):
            phases = [{k: t[k] for k in ("id", "phase_type", "eligibility", "starts_at", "start_precision", "end_precision", "current_status")}
                      for t in conn.execute("SELECT * FROM ticket_phase WHERE performance_id=? ORDER BY starts_at", (p["id"],))]
            perfs.append({"id": p["id"], "concert_id": c["id"], "starts_at": p["starts_at"], "local_date": p["local_date"], "date_precision": p["date_precision"], "country_code": p["country_code"],
                          "prefecture_code": p["prefecture_code"], "venue_name": p["venue_name"], "confirmation_status": "official_confirmed", "status": p["status"],
                          "last_seen_at": p["last_seen_at"], "ticket_phases": phases})
        if not perfs:
            continue
        concerts.append({"id": c["id"], "source_id": sid, "source_url": url, "category": c["category"], "title_ja": c["title_ja"], "official_announcement_date": c["official_announcement_date"],
                         "first_verified_at": c["first_verified_at"], "last_material_change_at": c["last_material_change_at"], "performances": perfs,
                         "program": [dict(r) for r in conn.execute("SELECT position, raw_text, composer_display, composer_key, work_display, work_key FROM program_item WHERE concert_id=? ORDER BY position", (c["id"],))],
                         "artists": [dict(r) for r in conn.execute("SELECT name_display, role FROM concert_artist WHERE concert_id=? ORDER BY rowid", (c["id"],))],
                         "orchestras": omap.get(c["id"], []),
                         "image": _inline(_summaries(conn, [c["id"]])[c["id"]]["image"], media_dir)})
        concerts[-1]["artists"] = [{**a, "image": _inline(a["image"], media_dir)} for a in concert_detail(conn, c["id"])["concert_artists"]]
    # ADR-0006: cards a reviewer merged under another confirmed card (the page applies them performance by performance)
    duplicates.mark_export(concerts, duplicates.merged_map(conn, datetime.fromisoformat(as_of).astimezone(JST).date().isoformat()))
    return {"as_of": as_of, "snapshot_label": as_of[:10] + " 取得", "concerts": concerts, "alias": _ALIAS, "orchestras": ORCHESTRAS, "coverage": coverage(conn)}


def _inline_fonts(css: str) -> str:
    """The demo is one file, so a relative url(fonts/x.woff2) would 404: embed the font as a data: URI.
    (The demo carries no CSP; if it is ever hosted under one, the policy needs font-src data:.)"""
    def swap(m):
        data = base64.b64encode((WEB / "fonts" / m.group(1)).read_bytes()).decode("ascii")
        return f"url(data:font/woff2;base64,{data})"
    return re.sub(r"url\(fonts/([\w.-]+\.woff2)\)", swap, css)


def assemble(data: dict) -> str:
    index = (WEB / "index.html").read_text(encoding="utf8")
    body = index[index.index('<div class="shell"'):index.index("<script src=")]
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""<title>Classical Radar</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
{_inline_fonts((WEB / "app.css").read_text(encoding="utf8"))}
</style>
{body}
<script>window.CR_DEMO_DATA={payload};</script>
<script>
{(WEB / "demo.js").read_text(encoding="utf8")}
</script>
<script>
{(WEB / "app.js").read_text(encoding="utf8")}
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--as-of", default=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    ap.add_argument("--data-only", type=Path)
    ap.add_argument("--media-dir", type=Path, default=Path("data/media"))
    a = ap.parse_args()
    conn = db.connect(str(a.db))
    data = export(conn, a.as_of, a.media_dir)
    conn.close()
    if a.data_only:
        a.data_only.write_text(json.dumps(data, ensure_ascii=False))
    html = assemble(data)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(html, encoding="utf8")
    print(f"{len(data['concerts'])} concerts, {len(html)/1024:.0f} KiB -> {a.out}")


if __name__ == "__main__":
    main()
