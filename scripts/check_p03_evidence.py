"""Offline consistency checks for the P0.3 evidence (announcement-date availability + Japan Arts consistency check).

Fails when the committed JSON breaks its own rules (size/snippet caps, sample rule, request cap, never-probed sources, counts that do not add up)
or when docs/reports/P0_3_ANNOUNCEMENT_AND_JAPANARTS.md states numbers that differ from the JSON. Runs without network.
"""
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 600_000  # snippets only: a full page would blow this immediately
SNIPPET_MAX = 200
VERDICTS = ("published", "update_only", "ambiguous", "none", "fetch_failed")


def fail(msg):
    sys.exit(f"check_p03_evidence: {msg}")


files = sorted(glob.glob(str(ROOT / "evidence/p03/announcement-availability-*.json")))
if not files:
    fail("no evidence/p03/announcement-availability-*.json")
path = Path(files[-1])
if path.stat().st_size > MAX_BYTES:
    fail(f"{path.name} is {path.stat().st_size} bytes: it must hold snippets only")
doc = json.loads(path.read_text())

if doc.get("aborted"):
    fail(f"the committed run was aborted: {doc['aborted']}")
if not {"tmso", "tpo"} <= set(doc["never_probed"]) or {"tmso", "tpo"} & set(doc["sources"]):
    fail("tmso/tpo must be listed as never probed and absent from the sources")
if any(r["requests_made"] > doc["request_cap"] for r in doc["runs"]):
    fail("a run made more requests than the per-run cap")
if doc["requests_made"] != sum(r["requests_made"] for r in doc["runs"]) or any(r["mode"] == "replay-raw" and r["requests_made"] for r in doc["runs"]):
    fail("requests_made must equal the sum over runs, and a replay run makes no requests")


def walk(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("snippet", "line") and isinstance(v, str) and len(v) > SNIPPET_MAX:
                fail(f"a {k} is longer than {SNIPPET_MAX} characters")
            walk(v)
    elif isinstance(node, list):
        for v in node:
            walk(v)


walk(doc)
for sid, src in doc["sources"].items():
    urls = [p["url"] for p in src["pages"]]
    if len(urls) != len(set(urls)):
        fail(f"{sid}: a URL was sampled twice")
    if src["n_sampled"] != len(urls) or sum(src["counts"].values()) != src["n_sampled"] or set(src["counts"]) != set(VERDICTS):
        fail(f"{sid}: counts do not add up")
    if src["n_sampled"] > src["N_offered"]:
        fail(f"{sid}: sampled more pages than offered")
    if sid != "japanarts" and src["n_sampled"] > doc["k_per_source"]:
        fail(f"{sid}: more than k pages sampled")
    for p in src["pages"]:
        if p["verdict"] not in VERDICTS:
            fail(f"{sid}: unknown verdict {p['verdict']}")
        if p["verdict"] == "published" and not any(s["class"] == "published" for s in p["signals"]):
            fail(f"{sid}: a page is 'published' without a published-class signal")
        if p["verdict"] == "published" and p["performance_dates"] and not any(s["class"] == "published" and s["date"] < min(p["performance_dates"]) for s in p["signals"]):
            fail(f"{sid}: a 'published' date is not before the performance date")
if "cross_page_notes" not in doc or any(len(n) > SNIPPET_MAX for n in doc["cross_page_notes"]):
    fail("cross_page_notes must be present and short")
ja = doc["sources"].get("japanarts")
if ja and len(doc["japanarts_crosscheck"]) != sum(1 for p in ja["pages"] if p["status"] == 200):
    fail("japanarts_crosscheck must cover every fetched Japan Arts page")

report = (ROOT / "docs/reports/P0_3_ANNOUNCEMENT_AND_JAPANARTS.md").read_text()
m = re.search(r"requests_made=(\d+)", report)
if not m or int(m.group(1)) != doc["requests_made"]:
    fail("the report must state requests_made=<n> equal to the evidence")
for sid, src in doc["sources"].items():
    row = re.search(rf"^\|\s*`{sid}`\s*\|([^\n]*)", report, re.M)
    expect = f"{src['n_sampled']}/{src['N_offered']}"
    if not row or expect not in row.group(1):
        fail(f"the report table row for {sid} must contain n/N = {expect}")
    pub = src["counts"]["published"]
    if f"published={pub}" not in row.group(1):
        fail(f"the report table row for {sid} must contain published={pub}")
cc = doc["japanarts_crosscheck"]
m = re.search(r"cross_check_consistent=(\d+)/(\d+)", report)
if cc and (not m or (int(m.group(1)), int(m.group(2))) != (sum(1 for c in cc if c["consistent"]), len(cc))):
    fail("the report must state cross_check_consistent=<ok>/<n> equal to the evidence")
# --- sale-time coverage (offline measurement over the cached pages) ---
sale_files = sorted(glob.glob(str(ROOT / "evidence/p03/sale-time-coverage-*.json")))
if not sale_files:
    fail("no evidence/p03/sale-time-coverage-*.json")
sale = json.loads(Path(sale_files[-1]).read_text())
if sale["network_requests"] != 0:
    fail("the sale-time coverage measurement must not make network requests")
CLASSES = ("exact_future", "exact_past_only", "year_assumed", "date_only", "no_date", "none", "not_measured")
for sid, src in sale["sources"].items():
    if set(src["counts"]) != set(CLASSES) or sum(src["counts"].values()) != len(src["pages"]):
        fail(f"sale coverage {sid}: counts do not add up")
    if src["n_measured"] != len(src["pages"]) - src["counts"]["not_measured"]:
        fail(f"sale coverage {sid}: n_measured is wrong")
    if src["text_exact_pages"] != src["counts"]["exact_future"] + src["counts"]["exact_past_only"] or src["text_exact_future_pages"] != src["counts"]["exact_future"]:
        fail(f"sale coverage {sid}: exact counts do not match the classes")
    lo = src["link_outcome"]
    if lo["pages_linked"] + lo["pages_refused_multi_performance"] + lo["pages_refused_same_label"] + lo["pages_without_claims"] != src["n_measured"]:
        fail(f"sale coverage {sid}: the linking outcome does not add up to n_measured")
    for pg in src["pages"]:
        for st in pg.get("sale_starts", []):
            if len(st["line"]) > SNIPPET_MAX:
                fail(f"sale coverage {sid}: a snippet is longer than {SNIPPET_MAX} characters")
sale_report = (ROOT / "docs/reports/P0_3_SALE_TIME_COVERAGE.md").read_text()
if sale["today"] not in sale_report:
    fail("the sale-time report must state the 'today' date the numbers were computed for: " + sale["today"])
for sid, src in sale["sources"].items():
    for pg in src["pages"]:
        if pg["class"] == "exact_future" and not any(st["date"] and st["time"] and st["year_basis"] in ("explicit", "weekday") and st["date"] >= sale["today"] for st in pg["sale_starts"]):
            fail(f"sale coverage {sid}: {pg['url']} is exact_future but shows no sale start on or after today within the kept snippets")
for sid, src in sale["sources"].items():
    row = re.search(rf"^\|\s*`{sid}`\s*\|([^\n]*)", sale_report, re.M)
    lo = src["link_outcome"]
    want = (f"n/N={src['n_measured']}/{src['N_offered']}", f"text_exact={src['text_exact_pages']}", f"future={src['text_exact_future_pages']}", f"parser={src['parser_pages_with_claims']}",
            f"linked_pages={lo['pages_linked']}", f"phases={lo['phases']}", f"future_phases={lo['future_phases']}")
    if not row or any(w not in row.group(1) for w in want):
        fail(f"the sale-time report row for {sid} must contain {', '.join(want)}")
# --- the real sync summary (counts only) and the report rows quoting it ---
sync_files = sorted(glob.glob(str(ROOT / "evidence/p03/sale-sync-*.json")))
if not sync_files:
    fail("no evidence/p03/sale-sync-*.json")
sync = json.loads(Path(sync_files[-1]).read_text())
for label, run in sync["runs"].items():
    for sid, s in run["sources"].items():
        if sum(s["by_type"].values()) != s["phases"] or any(v != 0 for v in s["sanity"].values()):
            fail(f"sale sync {label}/{sid}: phase counts do not add up or a sanity count is not zero")
for sid in ("japanarts", "kanagawa_geikyo", "tso"):
    for label, tag in (("first_real_sync", "before"), ("after_fixes_replay", "after")):
        s = sync["runs"][label]["sources"][sid]
        want = f"sync_{sid}_{tag}={s['performances_with_phases']} / {s['phases']} / {s['future_phases']}"
        if want not in sale_report:
            fail(f"the sale-time report must contain '{want}'")
        if s["performances_with_phases"] > s["performances"] or s["future_phases"] > s["phases"]:
            fail(f"sale sync {label}/{sid}: impossible counts")
        if any(len(k) > 60 for k in s["eligibility_labels"]) or sum(s["eligibility_labels"].values()) != s["phases"]:
            fail(f"sale sync {label}/{sid}: eligibility labels must be short and add up to the phase count")
    after = sync["runs"]["after_fixes_replay"]["sources"][sid]
    for marker in (f"sync_{sid}_total_performances={after['performances']}", f"sync_{sid}_distinct_future_moments={after['distinct_future_start_label_pairs']}"):
        if marker not in sale_report:
            fail(f"the sale-time report must contain '{marker}'")
if sync["runs"]["first_real_sync"]["requests"] != 186 or "186 个请求" not in sale_report:
    fail("the report must state the real sync's request count (186) from the evidence")
if sync["runs"]["after_fixes_replay"]["requests"] != 36 or "36 个请求" not in sale_report:
    fail("the report must state the replays' extra list-page requests (36) from the evidence")
pop = sale["population_from_p02_evidence"]
for phrase in (f"{pop['kajimoto']['pages_with_a_future_claim']}/{pop['kajimoto']['pages']} 页", f"NHK 响 {pop['nhkso']['future_performances_with_a_future_phase']} 场"):
    if phrase not in sale_report:
        fail(f"the sale-time report must state '{phrase}'")
print(f"OK: P0.3 evidence consistent ({doc['requests_made']} requests; " + "; ".join(f"{s} {v.get('n_sampled', len(v.get('pages', [])))}" for s, v in doc["sources"].items()) + f"; Japan Arts cross-check {len(cc)} pages)")
