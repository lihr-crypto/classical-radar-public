"""Assemble the Cloudflare Pages output directory from the web UI and the reviewed data file.

Usage: python scripts/build_site.py [site-data/concerts.json] [site] [site-data/same_concert.json] [site-data/leads.json]
Output: index.html (loads classical-links.js and memberships.js, then site.js), app.css, app.js, demo.js, site.js, classical-links.js, memberships.js, fonts/, icons/ (home-screen icon, favicon, manifest), data/concerts.json, _headers. Pages Functions live in ./functions.
"""
import json, shutil, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classical_radar import duplicates, leads as leads_mod  # noqa: E402
from classical_radar.orchestras import ORCHESTRAS, concert_orchestras  # noqa: E402

LEADS = ROOT / "site-data/leads.json"  # second-hand tour leads (ADR-0007), written by `classical-radar leads-export`
DECISIONS = ROOT / "site-data/same_concert.json"  # human same-concert decisions, keyed by source|url (ADR-0006)
WEB = ROOT / "src/classical_radar/web"
HEADERS = """/*
  Content-Security-Policy: default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  X-Robots-Tag: noindex, nofollow
/data/*
  Cache-Control: no-store
/api/*
  Cache-Control: no-store
"""


def main():
    data = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site-data/concerts.json"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "site"
    parsed = json.loads(data.read_text(encoding="utf8"))  # fail the build on a broken data file
    if parsed.get("fixed_as_of") is not False or not isinstance(parsed.get("concerts"), list):
        sys.exit("site data must come from scripts/export_site.py")
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    index = (WEB / "index.html").read_text(encoding="utf8")
    start, end = index.index('<script src="app.js"></script>'), None
    index = index[:start] + '<script src="site.js"></script>' + index[start + len('<script src="app.js"></script>'):]
    (out / "index.html").write_text(index, encoding="utf8")
    for name in ("app.css", "app.js", "demo.js", "site.js", "classical-links.js", "memberships.js"):
        shutil.copy(WEB / name, out / name)
    shutil.copytree(WEB / "fonts", out / "fonts")  # the self-hosted font and its licence; CSP default-src 'self' allows it
    shutil.copytree(WEB / "icons", out / "icons")  # home-screen icon, favicon and manifest (scripts/build_icons.py)
    # ADR-0006: the decisions file is the source of truth for the site. Applied here, with the same guards as the review page;
    # an entry the data can no longer honour is listed and left out, never forced.
    decisions = Path(sys.argv[3]) if len(sys.argv) > 3 else DECISIONS
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    merged, skipped = duplicates.merged_from_file(parsed["concerts"], decisions, today)
    duplicates.mark_export(parsed["concerts"], merged)
    for c in parsed["concerts"]:  # the tags follow the current table too, exactly as a fresh export would compute them (new orchestras apply to old concerts)
        c["orchestras"] = concert_orchestras(c["source_id"], c["title_ja"], [a["name_display"] for a in c["artists"]])
    parsed["orchestras"] = {**parsed.get("orchestras", {}), **ORCHESTRAS}  # the orchestra table is code, not data: the current one wins (it carries the names the filter searches); a key dropped since the export stays resolvable
    for s in skipped:
        print(f"same-concert decision skipped: {s['a']} / {s['b']}: {s['reason']}")
    (out / "data/concerts.json").write_text(json.dumps(parsed, ensure_ascii=False, sort_keys=True), encoding="utf8")
    (out / "_headers").write_text(HEADERS, encoding="utf8")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf8")
    leads_path = Path(sys.argv[4]) if len(sys.argv) > 4 else LEADS
    n_leads = 0
    if leads_path.is_file():  # validated like concerts.json; served from data/ (behind the login), never from the public icons/ folder
        lead_data = json.loads(leads_path.read_text(encoding="utf8"))
        leads_mod.validate_file(lead_data)
        official = [{"id": c["id"], "orchestras": c["orchestras"], "dates": [p["local_date"] for p in c["performances"] if p.get("local_date")]} for c in parsed["concerts"]]
        lead_data["leads"] = [{**lead, "covered_by": leads_mod.is_covered(lead, official)} for lead in lead_data["leads"]]
        (out / "data/leads.json").write_text(json.dumps(lead_data, ensure_ascii=False, sort_keys=True), encoding="utf8")
        n_leads = len(lead_data["leads"])
    print(f"site built in {out} ({len(parsed['concerts'])} concerts, {len(merged)} listed under another source's card, {n_leads} tour leads)")


if __name__ == "__main__":
    main()
