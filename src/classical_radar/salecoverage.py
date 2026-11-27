"""How much sale-start information do the detail pages carry, regardless of what the parsers read today? (P0.3, ADR-0004)

A MEASUREMENT helper, not wired into ingest. It reads the visible text lines of a page, finds lines about ticket sales
("発売", "先行", "販売", "受付"), and extracts the dates/times they state. A reminder needs an EXACT sale start in the FUTURE, so each
page is put in one class:

* ``exact_future``    a sale start with a date AND a time of day, year known (written, or fixed by the weekday), not before today
* ``exact_past_only`` the same, but every such start has already happened (nothing left to remind)
* ``year_assumed``    date+time but no year and no weekday to check it: the year is a guess, so it is not counted as exact
* ``date_only``       a date without a time of day
* ``no_date``         sale wording with no date ("発売中")
* ``none``            no sale line at all

Years: a line may omit the year (Japan Arts: "② 3月7日(土) 10：00a.m.～発売 一般"). The weekday in the brackets decides it: of
{reference year - 1, reference year} only one has that date on that weekday. The reference date is the page's first performance (a sale
cannot start after it). Without a weekday the year is a guess and the class is ``year_assumed``.
"""
from __future__ import annotations

import re
from datetime import date

WEEKDAYS = "月火水木金土日"
SNIPPET_MAX = 200
_SALE = re.compile(r"発売|先行|販売|受付")
_NOT_SALE = re.compile(r"CD|DVD|アルバム|リリース|著書|出版|書籍|ブルーレイ|配信開始")
_DT = re.compile(r"(?:(?P<y>20\d{2})\s*[年/.]\s*)?(?P<m>\d{1,2})\s*[月/／]\s*(?P<d>\d{1,2})\s*日?\s*(?:[（(](?P<w>[月火水木金土日祝])[^）)]*[）)])?"
                 r"\s*(?:(?P<hh>\d{1,2})\s*[:：]\s*(?P<mm>\d{2})\s*(?P<ap>[ap]\.?m\.?)?)?", re.I)


def _sale_context(lines: list[str], i: int, max_len: int) -> bool:
    """A line counts as a sale line when it says so itself, or when it is a short date line right under a short sale label
    ("カジモト・イープラス会員限定先行受付" / "2026年7月23日(木)12:00〜..."), which is how several sites lay the block out."""
    def says(text: str) -> bool:
        return len(text) <= max_len and bool(_SALE.search(text)) and not _NOT_SALE.search(text)
    if says(lines[i]):
        return True
    return i > 0 and len(lines[i]) <= 60 and bool(_DT.search(lines[i])) and len(lines[i - 1]) <= 60 and says(lines[i - 1]) and not _DT.fullmatch(lines[i - 1].strip())


def sale_starts(lines: list[str], reference: date, *, max_len: int = 120) -> list[dict]:
    """Sale-start statements found in ``lines`` (see module docstring). Long lines (biographies) and CD/DVD releases are not sale lines."""
    out = []
    for i, line in enumerate(lines):
        if len(line) > max_len or not _sale_context(lines, i, max_len):
            continue
        found = []
        for m in _DT.finditer(line):
            if line[:m.start()].rstrip()[-1:] in ("〜", "～", "-", "–"):  # the END of a window ("7/23 12:00〜7/26 23:59", with or without spaces), not a start
                continue
            found.append(_resolve(m, reference))
        label_for_next_line = i + 1 < len(lines) and len(lines[i + 1]) <= 60 and bool(_DT.search(lines[i + 1]))  # a label whose date is on the next line is not a "no date" line
        if not found and not label_for_next_line:
            out.append({"line": line[:SNIPPET_MAX], "date": None, "time": None, "year_basis": None})
        for f in found:
            out.append({"line": line[:SNIPPET_MAX], **f})
    return out


def _resolve(m: re.Match, reference: date) -> dict:
    month, day = int(m["m"]), int(m["d"])
    weekday = m["w"] if m["w"] and m["w"] in WEEKDAYS else None
    candidates, basis = [], None
    for year in ([int(m["y"])] if m["y"] else [reference.year - 1, reference.year]):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if weekday and WEEKDAYS[d.weekday()] != weekday:
            continue
        if m["y"] or d <= reference:
            candidates.append(d)
    if m["y"]:
        basis = "explicit"
    elif weekday:
        basis = "weekday"
    elif candidates:
        basis = "assumed"
    when = max(candidates) if candidates else None
    time = None
    if m["hh"] is not None:
        hh = int(m["hh"]) + (12 if m["ap"] and m["ap"].lower().startswith("p") and int(m["hh"]) < 12 else 0)
        time = f"{hh:02d}:{m['mm']}" if hh < 24 else None
    return {"date": when.isoformat() if when else None, "time": time, "year_basis": basis if when else None}


def japanarts_ticket_block(lines: list[str]) -> list[str]:
    """The page's OWN ticket block: from "チケット発売情報" to the next heading (the rest of a Japan Arts page is navigation cards of other concerts)."""
    start = next((i for i, line in enumerate(lines) if line == "チケット発売情報"), None)
    if start is None:
        return []
    out = []
    for line in lines[start + 1:start + 40]:
        if line in ("チケット残席状況", "Ticket Information", "各種お問い合わせ・申込み"):
            break
        out.append(line)
    return out


def classify(starts: list[dict], today: date) -> str:
    sure = [s for s in starts if s["date"] and s["time"] and s["year_basis"] in ("explicit", "weekday")]
    if sure:
        return "exact_future" if any(s["date"] >= today.isoformat() for s in sure) else "exact_past_only"
    if any(s["date"] and s["time"] for s in starts):
        return "year_assumed"
    if any(s["date"] for s in starts):
        return "date_only"
    return "no_date" if starts else "none"
