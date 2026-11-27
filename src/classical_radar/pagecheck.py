"""Automated consistency check of a Japan Arts detail page against its parse and against the site's own list card (P0.3, ADR-0004).

This is NOT human verification and not ground truth. It checks three things that a parser regression would break:

1. the parse succeeds and every parsed date, time and venue really occurs in the page's visible text;
2. the site's LIST card for the same URL (a different part of the site, different markup: title, first date/time, venue) agrees with the detail
   parse: same title, and the card's performance is among the parsed ones. This catches a parse that LOST or CHANGED the page's own performance;
   it does not catch an EXTRA performance;
3. ``cross_page_notes`` looks for the ERRATA E1 failure (a related-performance card counted as this page's performance) across pages: a parsed
   performance that is also the LIST card of another page is reported. Series pages legitimately overlap with their parts, so these are notes for a
   person, not failures, and a related card that is not another page's first card is not seen at all;
4. mentions of ticket sales are listed, because the Japan Arts parser reads no sale times (a core field in 05_ACCEPTANCE A) and the
   category label is shown next to the list card's, for a human or agent to judge.

Detail pages also embed the whole upcoming list as navigation cards with the same markup as the page's own performances, so a text-only
split of "this page's blocks" is unreliable; this module does not attempt it. Output holds short snippets only (<= 200 chars).
"""
from __future__ import annotations

import re
import unicodedata

from bs4 import BeautifulSoup

from .parsers import ParseError, parse_presenter_detail

SNIPPET_MAX = 200
_SALE = re.compile(r"発売|チケット|販売|先行|Ticket", re.I)


def _s(text: str | None) -> str:
    return re.sub(r"[\s　]+", " ", text or "").strip()


def _squash(text: str) -> str:
    """Whitespace-free NFKC form: the parser normalises width (full-width colon -> ':'), so compare in that form."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def visible_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return [_s(x) for x in soup.get_text("\n").splitlines() if _s(x)]


def check_japanarts_detail(html: str, url: str, list_card: dict | None = None) -> dict:
    flags: list[str] = []
    try:
        parsed = parse_presenter_detail("japanarts", html, url)["performances"]
    except ParseError as exc:  # a page the parser rejects is a finding, not a crash
        parsed = []
        flags.append(f"parser raised: {str(exc)[:SNIPPET_MAX]}")
    lines = visible_lines(html)
    text = "\n".join(lines)
    squashed = _squash(text)
    mine = [(p["local_date"], p["local_time"], _s(p["venue"])) for p in parsed]
    for d, t, v in mine:
        y, m, day = (int(x) for x in d.split("-"))
        if not re.search(rf"{y}年\s*{m}月\s*{day}日", text):
            flags.append(f"parsed date {d} is not in the page text")
        if t and t not in text:
            flags.append(f"parsed time {t} is not in the page text")
        if v and _squash(v) not in squashed:
            flags.append(f"parsed venue is not in the page text: {v[:60]}")
    if len(set(mine)) != len(mine):
        flags.append("duplicate parsed performance")
    title = parsed[0]["title"] if parsed else ""
    card = None
    if list_card is not None:
        card = {"title": _s(list_card["title"])[:120], "date": list_card["local_date"], "time": list_card["local_time"], "venue": _s(list_card["venue"])[:80], "category": list_card["category"]}
        if parsed and _s(list_card["title"]) != _s(title):
            flags.append(f"list card title differs from the detail title: {card['title'][:60]!r} vs {_s(title)[:60]!r}")
        if parsed and (list_card["local_date"], list_card["local_time"], _s(list_card["venue"])) not in mine:
            flags.append(f"the list card's performance ({list_card['local_date']} {list_card['local_time']}) is not among the parsed performances")
    sale = [ln[:SNIPPET_MAX] for ln in lines if _SALE.search(ln)]
    return {"url": url, "title": _s(title)[:120], "parsed_performances": len(parsed), "performances": [{"date": d, "time": t, "venue": v[:80]} for d, t, v in mine],
            "category_detail": sorted({p["category"] for p in parsed}), "list_card": card, "sale_mentions": len(sale), "sale_snippets": sale[:3],
            "ticket_claims_parsed": 0, "flags": flags, "consistent": not flags and bool(parsed)}


def _key(date, time, venue) -> tuple:
    return (date, time, _squash(venue or ""))


def cross_page_notes(results: list[dict]) -> list[str]:
    """Parsed performances that are also the list card of ANOTHER page (see module docstring, point 3)."""
    cards: dict[tuple, set[str]] = {}
    for r in results:
        c = r.get("list_card")
        if c:
            cards.setdefault(_key(c["date"], c["time"], c["venue"]), set()).add(r["url"])
    notes = []
    for r in results:
        for p in r["performances"]:
            others = sorted(cards.get(_key(p["date"], p["time"], p["venue"]), set()) - {r["url"]})
            if others:
                notes.append(f"{r['url'].rstrip('/').rsplit('/', 1)[-1]}: {p['date']} {p['time']} is also the list card of " + ", ".join(u.rstrip("/").rsplit("/", 1)[-1] for u in others))
    return [n[:SNIPPET_MAX] for n in notes]
