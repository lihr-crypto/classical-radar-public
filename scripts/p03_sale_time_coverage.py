#!/usr/bin/env python3
"""P0.3: how many detail pages state a sale START TIME, how many of those are still in the future, and how many does today's parser read?

OFFLINE: re-reads the pages that scripts/p03_announcement_probe.py already cached in the git-ignored evidence/raw (matched by canonical URL),
so it makes no network request. The sample is that probe's sample (Japan Arts: every page; the others: 8 evenly spread pages), so the numbers
are n/N of a sample, not of all upcoming performances. Output holds snippets only (<= 200 chars).

Usage: python scripts/p03_sale_time_coverage.py [--today YYYY-MM-DD] [--out evidence/p03/sale-time-coverage-YYYY-MM-DD.json]
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from classical_radar.detail import parse_detail  # noqa: E402
from classical_radar.linking import link_presenter_claims  # noqa: E402
from classical_radar.pagecheck import visible_lines  # noqa: E402
from classical_radar.parsers import ParseError, parse_presenter_detail  # noqa: E402
from classical_radar.salecoverage import SNIPPET_MAX, classify, japanarts_ticket_block, sale_starts  # noqa: E402

CLASSES = ("exact_future", "exact_past_only", "year_assumed", "date_only", "no_date", "none")
SOURCES = ("japanarts", "kajimoto", "tso", "njp", "jpo", "kanagawa_geikyo")  # yomikyo and nhkso: see the report (not in the raw cache / not per-concert pages)


def _probe_module():
    spec = importlib.util.spec_from_file_location("p03_probe", ROOT / "scripts" / "p03_announcement_probe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parser_claims(sid: str, html: str, url: str, reference: date | None = None) -> tuple[list[dict], int | None]:
    """(claims today's parsers read from this page, performances the page's own parse shows or None). ``reference`` = the page's first
    performance date, as ``sync._paged`` passes it for TSO/Kanagawa."""
    try:
        if sid in ("japanarts", "kajimoto"):
            d = parse_presenter_detail(sid, html, url)
            return d["ticket_claims"], len(d["performances"])
        return parse_detail(sid, html, url, reference)["ticket_claims"], None
    except ParseError:
        return [], None


def measure(today: date, announcement: dict, raw_dir: Path) -> dict:
    index = _probe_module().raw_index(raw_dir)
    out = {}
    for sid in SOURCES:
        src = announcement["sources"][sid]
        pages, counts = [], collections.Counter()
        parser_pages = parser_claims_n = parser_exact = 0
        outcome = collections.Counter()
        as_of = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        for p in src["pages"]:
            f = index.get(p["url"].rstrip("/"))
            if f is None or p["status"] != 200 or not p["performance_dates"]:
                pages.append({"url": p["url"], "class": "not_measured", "reason": "page not in the raw cache or no performance date"})
                counts["not_measured"] += 1
                continue
            html = f.read_text(errors="ignore")
            lines = visible_lines(html)
            ref = date.fromisoformat(min(p["performance_dates"]))
            starts = sale_starts(japanarts_ticket_block(lines) if sid == "japanarts" else lines, ref)
            cls = classify(starts, today)
            claims, perf_n = parser_claims(sid, html, p["url"], ref)
            # would sync attach them? the same rule sync uses (link_presenter_claims); TSO/Kanagawa/NJP performance counts are the list's distinct dates (an approximation)
            n_perf = perf_n if perf_n is not None else len(p["performance_dates"])
            linked = link_presenter_claims({"performances": [{"performance_id": str(i)} for i in range(n_perf)], "ticket_claims": claims}, as_of, channel="official")
            if not claims:
                outcome["pages_without_claims"] += 1
            elif linked["linked"]:
                outcome["pages_linked"] += 1
                outcome["phases"] += len(linked["linked"])
                outcome["future_phases"] += sum(1 for x in linked["linked"] if x["starts_at"] > as_of.isoformat())
            else:
                outcome["pages_refused_same_label" if "same label" in linked["unlinked"][0]["reason"] else "pages_refused_multi_performance"] += 1
            exact_claims = [c for c in claims if c.get("starts_at") and c.get("date_precision") == "minute"]
            counts[cls] += 1
            parser_pages += bool(claims)
            parser_claims_n += len(claims)
            parser_exact += bool(exact_claims)
            pages.append({"url": p["url"], "reference_date": ref.isoformat(), "class": cls, "sale_starts": [{k: v for k, v in s.items()} for s in starts[:6]],
                          "parser_claims": len(claims), "parser_exact_claims": len(exact_claims)})
        measured = [x for x in pages if x["class"] != "not_measured"]
        text_exact = sum(1 for x in measured if x["class"] in ("exact_future", "exact_past_only"))
        out[sid] = {"N_offered": src["N_offered"], "n_measured": len(measured), "counts": {c: counts.get(c, 0) for c in (*CLASSES, "not_measured")},
                    "text_exact_pages": text_exact, "text_exact_future_pages": counts.get("exact_future", 0),
                    "parser_pages_with_claims": parser_pages, "parser_claims": parser_claims_n, "parser_pages_with_exact_claim": parser_exact,
                    "link_outcome": {k: outcome.get(k, 0) for k in ("pages_linked", "pages_refused_multi_performance", "pages_refused_same_label", "pages_without_claims", "phases", "future_phases")}, "pages": pages}
    return out


def population(today: date) -> dict:
    """Complete populations that the P0.2 evidence already holds (as of its own date, not re-fetched): KAJIMOTO's 15 pages and NHK's season announcement."""
    link = json.loads((ROOT / "evidence/p02/ticket-linking-2026-11-04.json").read_text())
    details = json.loads((ROOT / "evidence/p02/presenter-details-2026-11-04.json").read_text())
    kaj = next(s for s in details["sources"] if s["source_id"] == "kajimoto")
    since = today.isoformat()
    future_pages = [i["url"] for i in kaj["items"] if any(c.get("starts_at") and c["starts_at"][:10] >= since for c in (i.get("ticket_claims") or []))]
    nhk_future = [x for x in link["nhk"]["linked"] if (x.get("starts_at") or "")[:10] >= since]
    return {"as_of_evidence": link["as_of"][:10], "kajimoto": {"pages": len(kaj["items"]), "pages_with_a_future_claim": len(future_pages),
                                                              "claims": sum(len(i.get("ticket_claims") or []) for i in kaj["items"]), "single_performance_pages_linked": link["kajimoto"]["single_performance_items_linked"],
                                                              "multi_performance_pages_refused": link["kajimoto"]["multi_performance_items_unlinked"]},
            "nhkso": {"future_performances": link["nhk"]["future_performances"], "linked_phases": len(link["nhk"]["linked"]), "future_phases": len(nhk_future),
                      "future_performances_with_a_future_phase": len({x["performance_id"] for x in nhk_future}),
                      "batches": [{"months": b["months"], "general_sale": b["general_sale_starts_at"][:16], "member_presale": b["member_presale_starts_at"][:16]} for b in link["nhk"]["batches"]]}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--today", default=datetime.now(timezone.utc).astimezone().date().isoformat())
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    today = date.fromisoformat(a.today)
    announcement = json.loads(sorted((ROOT / "evidence/p03").glob("announcement-availability-*.json"))[-1].read_text())
    doc = {"generated_at": datetime.now(timezone.utc).isoformat(), "tool": "scripts/p03_sale_time_coverage.py", "today": today.isoformat(), "network_requests": 0,
           "method": "visible-text sale lines (Japan Arts: its own チケット発売情報 block); year from the written year or fixed by the weekday; classes in src/classical_radar/salecoverage.py",
           "sample": "the P0.3 announcement probe's pages (Japan Arts all, others 8 spread); numbers are n/N of that sample", "sources": measure(today, announcement, ROOT / "evidence/raw"),
           "population_from_p02_evidence": population(today), "not_measured": {"yomikyo": "pages are not in the raw cache; the calendar prints 【発売日】 without year or time (fixture tests/fixtures/yomikyo-697-programme.html)", "nhkso": "concert pages carry no sale lines; sale starts come from the season announcement article (see population_from_p02_evidence)"}}
    out = a.out or ROOT / f"evidence/p03/sale-time-coverage-{today.isoformat()}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)
    for sid, s in doc["sources"].items():
        print(f"{sid:16} n={s['n_measured']}/{s['N_offered']}  text exact={s['text_exact_pages']}  future={s['text_exact_future_pages']}  parser pages with a claim={s['parser_pages_with_claims']}  classes={ {k: v for k, v in s['counts'].items() if v} }", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
