"""Builds docs/poc/source-audit.csv from evidence/probe.json (2026-10-31 robots/HTTP) plus the P0.2 observations below.
Engineering facts only, not a legal conclusion. policy_status never says 'permitted' without a positive grant."""
import csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P02 = {
    "nhkso": dict(role="domestic_orchestra", mode="public season JSON (found via site script) + HTML detail/news", announce="P0.3 (2026-11-09): concert JSON has no date-like key; 0/8 sampled concert pages show any date besides the performance; the season ticket news article prints a bare date (2026-07-01, class date: article date, season-level, ambiguous)", ticket="season announcement: single-ticket dates per month group; each concert page repeats its own dates; JSON ticket_status is an uninterpreted code", p02="200; JSON+news+16 concert pages read; 16/16 sale dates agree with announcement-derived links", policy="unknown", risk="JSON is not a documented API; 2 subscription concerts with conductor-change notes held back", fallback="HTML detail pages; URL import"),
    "tmso": dict(role="domestic_orchestra", mode="HTML list ?tab=1&page=N + own detail pages (programme, performers)", announce="not measured", ticket="sale dates printed without year/time ('一般発売：7/8（水）'): not parsed", p02="enabled by the user 2026-11-04; facts only (no biographies, descriptions or images), manual sync, no republication", policy="unknown", risk="terms page https://www.tmso.or.jp/j/guide/ is a general copyright notice (no reproduction/retransmission without permission; linking free); external-presenter concerts link off-site and stay list-level", fallback="URL import"),
    "tso": dict(role="domestic_orchestra", mode="static HTML list, /concert/page/N/", announce="P0.3: JSON-LD datePublished + article:published_time on 8/8 sampled pages, 5 distinct values (4 pages share 2025-10-07: probably one batch publication); page publication time, not verified as first announcement", ticket="not measured", p02="4/4 pages walked: 69 unique candidates, 2026-11-14..2028-03-26", policy="unknown", risk="detail/ticket pages not yet read", fallback="URL import"),
    "jpo": dict(role="domestic_orchestra", mode="static HTML list, ?p_type=performance&p_page=N", announce="P0.3: 0/8 sampled pages: the only date on the page is the performance date", ticket="'発売中' kept as current_status only", p02="4/4 pages walked: 80 unique candidates, 2026-11-05..2028-03-25", policy="unknown", risk="events (p_type=event) deliberately not walked", fallback="URL import"),
    "njp": dict(role="domestic_orchestra", mode="static HTML list, /concerts/page/N/", announce="P0.3: 0/8 sampled pages have a publication date; only og:updated_time (an update time)", ticket="not measured", p02="6/6 pages walked: 47 unique candidates, 2026-11-07..2027-04-21", policy="unknown", risk="mixes vocal recitals; detail pages not read", fallback="URL import"),
    "yomikyo": dict(role="domestic_orchestra", mode="season calendar cal.php (12 monthly tables) + detail pages", announce="P0.3: 0/8 sampled detail pages show any date besides the performance; the URL path embeds /YYYY/MM/ (not counted: unverified meaning)", ticket="not measured (links to ticket channels not followed)", p02="calendar 83/83 anchors parsed; 33 future detail pages read: calendar vs detail date/time 0 mismatches; venue 27/33", policy="unknown", risk="6 regional concerts have no venue field on the page", fallback="URL import"),
    "tpo": dict(role="domestic_orchestra", mode="static HTML list (10-31 only)", announce="not measured", ticket="not measured", p02="DEFERRED BY USER 2026-11-04 (ADR-0001). Before that: TLS connection reset on /concert/, /robots.txt and / (adapter x2 incl. one retry, curl x5); no workaround attempted", policy="unknown", risk="multi-day range cards (11 skipped on 10-31) still unexpanded; cannot be verified from this environment", fallback="none planned; not in current execution scope (still in the 00_DECISIONS whitelist)"),
    "japanarts": dict(role="overseas_and_piano_presenter", mode="static HTML list + detail pages", announce="P0.3: JSON-LD datePublished on 42/42 detail pages, 25 distinct values, each before the performance date = CMS page publication time (an upper bound for the first announcement ONLY IF the stamp is when the page actually went public; not checkable from outside, not verified as the organiser's first announcement)", ticket="no sale paragraphs parsed on detail pages", p02="landing page 42 items, no pagination seen: 42/42 detail pages parsed, 58 performances, all with date+time+venue", policy="unknown", risk="detail page also holds related-performance cards (fixed, see evidence/p02/ERRATA.md); series-pass page duplicates 3 performances", fallback="URL import"),
    "kajimoto": dict(role="overseas_and_piano_presenter", mode="static HTML list (UPCOMING block only) + detail pages", announce="P0.3: 0/8 sampled pages have a publication date; only article:modified_time (an update time, not an announcement)", ticket="explicit member/general sale date+time per project; no per-performance labels", p02="15/15 detail pages parsed, 17 performances; 13 single-performance pages linked to sale phases, 2 multi-performance pages left unlinked", policy="unknown", risk="images must not be reused (site terms); piano-recital recall by title only 2 of 15 projects", fallback="URL import"),
    "kanagawa_geikyo": dict(role="complementary_hall_presenter", mode="static HTML list, /concert/page/N/", announce="P0.3: JSON-LD datePublished on 8/8 sampled pages, 8 distinct values = CMS page publication time; WARNING: span.published in the list/detail markup is the PERFORMANCE date", ticket="not measured", p02="8/8 pages walked: 71 unique of 128 cards; 21 piano-recital hints; 6 excluded-orchestra hints", policy="unknown", risk="presenter of Kanagawa Phil concerts (excluded orchestra) - exclusion is a title hint only", fallback="URL import"),
}


def main():
    probe = {r["source_id"]: r for r in json.loads((ROOT / "evidence/probe.json").read_text())}
    cols = ["source_id", "role", "official_url", "robots_2026_10_31", "robots_allows_list_path", "robots_rules", "usage_terms_url", "policy_status",
            "acquisition_mode", "announcement_date_field", "ticket_field", "access_2026_11_04", "scheduled_collection", "risk", "fallback"]
    out = ROOT / "docs/poc/source-audit.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        for sid, x in P02.items():
            pr = probe[sid]
            rb = pr["robots"]
            w.writerow(dict(source_id=sid, role=x["role"], official_url=pr["list_url"], robots_2026_10_31=rb["status"],
                            robots_allows_list_path=rb.get("allows_list"), robots_rules=(rb.get("rules") or "").replace("\r", "").replace("\n", " | ")[:140],
                            usage_terms_url=";".join(pr["policy_links"]) or "", policy_status=x["policy"], acquisition_mode=x["mode"],
                            announcement_date_field=x["announce"], ticket_field=x["ticket"], access_2026_11_04=x["p02"], scheduled_collection="false",
                            risk=x["risk"], fallback=x["fallback"]))
    print("wrote", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
