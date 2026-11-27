#!/usr/bin/env python3
"""Build src/classical_radar/web/classical-links.js: Apple Music Classical ids for the browse pages (ADR-0013, ADR-0014).

A one-off, hand-run tool (not CI, not the daily refresh). The ids the browse pages use come from the APP'S OWN rules (scripts/browse_entities.mjs, which
runs the <browse-rules> block of web/app.js over site-data/concerts.json), so the table can never drift from the pages. Apple is asked only what
``classical_radar.classical_links`` allows (the public lookup API and ``/jp/artist/<id>`` pages; never the Classical search page, which robots.txt
disallows). Slow (>= 2 s a page, >= 3.2 s a lookup), cached under evidence/cache/classical (git-ignored, so a re-run is free), capped, and it stops at
the first 403 / 429.

Only exact matches are written on their own. Everything else is a PROPOSAL in the review file and gets a link only after a person has read it and added
it to site-data/classical-reviewed.json:
  {"composers": {"brahms": 264688, "ブルッフ": 4321},      composer_key or folded name -> Apple artist id (surname-only matches)
   "people":    {"藤岡幸夫": 265293859},                     folded name -> artist id (a near miss of spelling whose identity is certain)
   "works":     {"~ravel|ボレロ": "maurice-ravel-1875-pp11"}, local piece id -> Apple work slug (must be on the composer's famous-works shelf)
   "composer_alias": {"fリスト": "liszt"},                      a folded name (a composer written with initials, "F.リスト") -> the composer key it is
   "works_skip": ["schubert:symphony-8"],                    pieces kept out of the table
   "works_pin":  {"dvorak:symphony-7": "antonin-dvorak-1841-pp21"}}   generic key -> slug: settles a tie our texts cannot (still audited)
Every linked piece with a generic key is also checked against OUR programme texts: a different key signature or catalogue number than Apple's title drops it.

review.tsv lists the proposals twice over: "work-proposal" (our core title equals Apple's) and "work-loose" (ADR-0015, fourth batch: the titles are only ALIKE; the note
column says the score and, where the review has to look twice, RULE-a/b/d). Neither is ever a link by itself. A composer whose artist the lookup API files under
サウンドトラック / ポップ / タンゴ ... is never found by the search (it asks about クラシック / オペラ only): pin the id in "composers" after reading its Classical page.

--full-works N reads, for the composers where it pays most, the COMPLETE list of works Apple files under their name (ADR-0015): the work sitemaps that
robots.txt lists give the slugs, one work page per slug gives its title. N caps the work pages fetched NOW (cached ones are free, a re-run resumes; N = 0 sends no request and uses the cached pages only,
which is how a finished crawl is turned into the table).
A composer whose list was not completed keeps the 15-work shelf; a partial list could make a title look unique.

Usage: python scripts/resolve_classical_links.py [--stage composers|works|people|all] [--cap 2500] [--people-limit N] [--min-composer-concerts 2] [--dry]
                                                 [--full-works N] [--full-composers beethoven,chopin]
"""
from __future__ import annotations

import argparse
import collections
import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path

from classical_radar import classical_links as cl
from classical_radar.works import _DISPLAY

ROOT = Path(__file__).resolve().parent.parent
DATA, REVIEWED = ROOT / "site-data/concerts.json", ROOT / "site-data/classical-reviewed.json"
OUT, CACHE = ROOT / "src/classical_radar/web/classical-links.js", ROOT / "evidence/cache/classical"


def entities(data_path: Path) -> dict:
    """{works, composers, people}: the browse pages' local ids with their texts and concert counts, computed by app.js itself."""
    node = shutil.which("node")
    if not node:
        sys.exit("node is needed: the ids come from web/app.js")
    run = subprocess.run([node, str(ROOT / "scripts/browse_entities.mjs"), str(data_path)], capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stage", choices=["composers", "works", "people", "all"], default="all")
    ap.add_argument("--cap", type=int, default=2500, help="most NEW network requests in this run (cached answers are free)")
    ap.add_argument("--people-limit", type=int, default=0, help="only the N most used people (0 = all)")
    ap.add_argument("--min-composer-concerts", type=int, default=2, help="composers without a key are looked up by name only when they play in at least this many concerts")
    ap.add_argument("--dry", action="store_true", help="do not write classical-links.js")
    ap.add_argument("--full-works", type=int, default=None, help="most NEW work pages to fetch for complete work lists (0 = use only the pages already cached, no request; omitted = 15-work shelf only)")
    ap.add_argument("--full-composers", default="", help="comma-separated composer ids to read completely (default: ranked by our unlinked visits per Apple page)")
    args = ap.parse_args()
    if args.stage != "all":
        args.dry = True  # the file is written only from a complete run
    reviewed = json.loads(REVIEWED.read_text("utf8")) if REVIEWED.exists() else {}
    pins = reviewed.get("works_pin") or {}
    ent = entities(DATA)
    f = cl.Fetcher(CACHE, cap=args.cap)
    table = {"as_of": datetime.date.today().isoformat(), "composers": {}, "works": {}, "people": {}}
    rows, stopped, detail, pages = [], None, {}, {}
    # our programme texts per generic work key: the audit compares them with Apple's title
    texts = {e["id"]: set(e["texts"]) for e in ent["works"] if e["keyed"]}
    try:
        if args.stage in ("composers", "works", "all"):
            for key in sorted(_DISPLAY):
                r = cl.resolve_composer(f, key, reviewed.get("composers"))
                rows.append(("composer", key, r["verdict"], r["id"], (r["page"] or {}).get("title", ""), (r["page"] or {}).get("start", ""), "; ".join(f"{k}:{p['title']}/{p['id']}" for k, p in r["seen"])))
                if r["id"] and r["verdict"] in ("accepted", "reviewed"):
                    table["composers"][key] = r["id"]
                    pages[key] = r["page"]
                    detail.update(cl.works_detail(key, r["page"], texts, pins))
            # composers that carry no composer_key: the browse page id is their folded name
            pinned_names = reviewed.get("composers") or {}
            for e in ent["composers"]:
                if e["keyed"] or e["id"] in _DISPLAY or (e["n"] < args.min_composer_concerts and e["id"] not in pinned_names):
                    continue
                r = cl.resolve_composer_by_name(f, e["texts"][0], reviewed.get("composers"))
                rows.append(("composer-name", e["id"], r["verdict"], r["id"], (r["page"] or {}).get("title", ""), (r["page"] or {}).get("start", ""),
                             f"{e['n']} concerts; " + "; ".join(f"{k}:{p['title']}/{p['id']}/{p['start']}" for k, p in r["seen"])))
                if r["id"] and r["verdict"] in ("accepted", "reviewed"):
                    table["composers"][e["id"]] = r["id"]
                    pages[e["id"]] = r["page"]
            for alias, key, why in cl.apply_composer_aliases(table["composers"], pages, reviewed.get("composer_alias") or {}):
                rows.append(("composer-alias-problem", alias, "dropped", key, "", "", why))
        if args.stage in ("people", "all"):
            for e in ent["people"][: args.people_limit or None]:
                pin = (reviewed.get("people") or {}).get(e["id"])
                if pin:
                    page = cl.artist_page(f, pin)
                    r = {"verdict": "reviewed" if page and page["role"] else "none", "id": pin, "page": page}
                else:
                    r = cl.resolve_person(f, e["texts"][0])
                rows.append(("person", e["texts"][0], r["verdict"], r["id"], (r["page"] or {}).get("title", ""), (r["page"] or {}).get("role", ""), f"{e['n']} concerts"))
                if r["id"] and r["verdict"] in ("accepted", "reviewed"):
                    table["people"][e["id"]] = r["id"]
    except cl.Stopped as e:
        stopped = str(e)
    # complete work lists (ADR-0015): only for composers whose list was read to the end
    full_done, full_partial = [], []
    texts_skip = reviewed.get("works_skip") or []
    if args.full_works is not None and not stopped:
        try:
            slugs = cl.load_work_slugs(cl.Fetcher(CACHE, cap=200))
            ff = cl.Fetcher(CACHE, cap=args.full_works)
            shelf_linked, _ = cl.audit_works(detail, texts, texts_skip)
            shelf_linked = set(shelf_linked) | set((reviewed.get("works") or {}))
            value = collections.Counter()
            for e in ent["works"]:
                if e["id"] not in shelf_linked and e["cid"] in pages and not any(cl.excluded_text(t) for t in e["texts"]):
                    value[e["cid"]] += e["n"]
            # a piece accepted from the long list (not on the 15-work shelf) keeps its composer's list wanted, or the next run would drop it
            # as "not on the shelf any more" the moment the composer has no unlinked piece left
            for wid, slug in (reviewed.get("works") or {}).items():
                owner = wid[1:].split("|")[0] if wid.startswith("~") else ""
                if owner in pages and owner not in value and slug not in {w["slug"] for w in pages[owner]["works"]}:
                    value[owner] = 0.001
            def cost(cid):
                prefix = cl.composer_slug(pages[cid])
                return len(slugs.get(prefix, ())) or 10 ** 9
            wanted = [c for c in args.full_composers.split(",") if c] or [c for c, v in sorted(value.items(), key=lambda kv: -kv[1] / cost(kv[0])) if cost(c) < 10 ** 9]
            for cid in wanted:
                if cid not in pages:
                    continue
                try:
                    full = cl.complete_works(ff, pages[cid], slugs)
                except cl.CapReached:  # this composer needs a page not fetched yet; one whose pages are all cached can still follow
                    full_partial.append(cid)
                    continue
                if full is None:
                    full_partial.append(cid)
                    continue
                have = {w["slug"] for w in pages[cid]["works"]}
                pages[cid] = {**pages[cid], "works": pages[cid]["works"] + [{**w, "extra": True} for w in full if w["slug"] not in have]}
                full_done.append((cid, len(full)))
                if cid in _DISPLAY:
                    detail = {k: v for k, v in detail.items() if not k.startswith(cid + ":")}
                    detail.update(cl.works_detail(cid, pages[cid], texts, pins))
            print(f"work pages fetched now: {ff.sent}; complete lists: {len(full_done)} composers, {sum(n for _, n in full_done)} works; not completed: {full_partial}")
        except cl.Stopped as e:
            stopped = str(e)
    # pieces: generic keys (audited against our texts), then titled pieces (hand-reviewed proposals only)
    table["works"], dropped = cl.audit_works(detail, texts, reviewed.get("works_skip") or [])
    for k, why in sorted(dropped.items()):
        rows.append(("work-dropped", k, "dropped", "", "", "", why))
    for k, slug in sorted(pins.items()):  # a pin that matches nothing any more (the page left the list, the key changed, the audit dropped it) must not vanish silently
        if table["works"].get(k) != slug:
            rows.append(("work-pin-missing", k, "dropped", slug, "", "", "the pin matches nothing now, or the audit dropped it"))
    by_composer = collections.defaultdict(list)
    for e in ent["works"]:
        if not e["keyed"]:
            by_composer[e["cid"]].append(e)
    reviewed_works = reviewed.get("works") or {}
    arranged_ids = {e["id"] for e in ent["works"] if e.get("arranged")}
    for cid, page in pages.items():
        shelf = {w["slug"]: w for w in page["works"]}
        for pr in cl.propose_works(by_composer.get(cid, []), page, loose=True):
            ok = reviewed_works.get(pr["id"]) == pr["slug"]
            note = f"{pr['n']} concerts" + (" TWIN-ARRANGEMENT" if pr["twin"] else "") + (" MIXED-ARRANGER-LINES" if pr.get("mixed") else "") + (f" score={pr['score']} " + " ".join(pr["hints"]) if pr.get("loose") else "")
            rows.append(("work-loose" if pr.get("loose") else "work-proposal", pr["id"], "reviewed" if ok else "PROPOSED", pr["slug"], f"{pr['title']} {pr['subtitle']}", note.rstrip(), " | ".join(pr["texts"])))
        for wid, slug in reviewed_works.items():
            if wid.startswith("~" + cid + "|"):
                own = [t for e in by_composer.get(cid, []) if e["id"] == wid for t in e["texts"]]
                if slug in shelf and not any(cl.excluded_text(t) for t in own) and wid not in arranged_ids:
                    table["works"][wid] = slug
                else:
                    rows.append(("work-reviewed-missing", wid, "dropped", slug, "", "", "not on the shelf any more, or its text is an arrangement / excerpt, or a programme line names an arranger"))
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "review.tsv").write_text("\n".join("\t".join(str(x) for x in r) for r in rows) + "\n", "utf8")
    count = collections.Counter((r[0], r[2]) for r in rows)
    print(f"requests sent now: {f.sent}  stopped: {stopped or 'no'}")
    for k, v in sorted(count.items()):
        print(f"  {k[0]:22} {k[1]:10} {v}")
    for k, why in sorted(dropped.items()):
        print(f"  dropped work {k}: {why}")
    print(f"table: {len(table['composers'])} composers, {len(table['works'])} works, {len(table['people'])} people  (review: {CACHE / 'review.tsv'})")
    if OUT.exists():
        text = OUT.read_text("utf8")
        old = json.loads(text[text.index("{"): text.rindex("}") + 1])
        for grp in ("composers", "works", "people"):
            gone = sorted(set(old.get(grp, {})) - set(table[grp]))
            new_ = sorted(set(table[grp]) - set(old.get(grp, {})))
            changed = sorted(k for k in set(old.get(grp, {})) & set(table[grp]) if old[grp][k] != table[grp][k])
            print(f"  vs shipped {grp}: +{len(new_)} -{len(gone)} changed {len(changed)}" + (f"  LOST: {gone[:40]}" if gone else "") + (f"  CHANGED: {changed[:20]}" if changed else ""))
    if stopped:
        print("STOPPED EARLY: nothing written (a partial table must not replace a good one)", file=sys.stderr)
        return 2
    if not args.dry:
        OUT.write_text(cl.render_js(table), "utf8")
        print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
