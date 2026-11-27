"""The N響 next-season announcement (the 〈速報〉 news item) is a one-page PDF poster, months long before the yearly data file lists
the concerts (ADR-0009). This module turns that poster into events shaped like the yearly data file, so ``parsers.parse_nhk`` can read them.

The poster is a grid: three columns (PROGRAM A / B / C, each with its hall and the weekday + start time of its two performances) and one
row per month. Text is matched to its cell by page coordinates, never by reading order (the reading order of the text stream is not the
grid order). Everything is checked against what the poster says about itself: the weekday printed next to every date must be the real
weekday of that date, every month row must carry its month label, and every programme needs a work. When anything disagrees the whole
poster is refused with a ParseError, because a wrong date shown as official is worse than a missing one.

Only facts are kept (dates, hall, performers, works); no layout, no prose.
"""
from __future__ import annotations

import io
import re
import unicodedata
from datetime import date, timedelta

from .parsers import ParseError

MAX_PDF_BYTES = 5_000_000
WEEKDAYS = "月火水木金土日"  # date.weekday(): Monday is 0
MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_WIDE = r"、-鿿！-￯"  # CJK, kana, full-width forms (not the ideographic space U+3000)
_MARKS = " *◆＊"  # the poster marks which soloist plays which work with * and ◆; the marks are not part of a name or a title


def extract_items(pdf: bytes) -> list[list[tuple[float, float, str]]]:
    """Per page, every text run with its position: [(x, y, text)]. pypdf is imported here so only the season path needs it."""
    if len(pdf) > MAX_PDF_BYTES or not pdf.startswith(b"%PDF"):
        raise ParseError("season PDF: not a PDF or too large")
    import logging
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # it warns about every font it cannot fully decode; the text layer is all this needs
    try:
        reader = PdfReader(io.BytesIO(pdf))
        pages = []
        for page in reader.pages:
            items: list[tuple[float, float, str]] = []

            def visit(text, cm, tm, font_dict, font_size, items=items):
                text = (text or "").strip(" \t\r\n")  # the full-width indent (U+3000) is kept: it marks a continuation line
                if text.strip():
                    items.append((round(tm[4] * cm[0] + tm[5] * cm[2] + cm[4], 1), round(tm[4] * cm[1] + tm[5] * cm[3] + cm[5], 1), text.replace("･", "・")))
            page.extract_text(visitor_text=visit)
            pages.append(items)
        return pages
    except ParseError:
        raise
    except Exception as exc:  # noqa: BLE001 - a malformed PDF must fail this source's season step, not the run
        raise ParseError(f"season PDF unreadable: {type(exc).__name__}") from exc


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def _strip_marks(s: str) -> str:
    return s.rstrip(_MARKS)


def _tidy_work(line: str) -> str:
    """Some lines are stretched to the column width with a space between every letter ("コ リ リ ャ ーノ"). A normal line has spaces
    only between words, each longer than two letters or carrying a digit or Latin letter, so a line with two or more tiny all-CJK words
    (or one tiny first word) is a stretched one and loses its spaces between CJK characters."""
    line = _strip_marks(line.strip().strip("　"))
    tokens = line.split(" ")
    tiny = sum(1 for t in tokens if 0 < len(t) <= 2 and re.fullmatch(f"[{_WIDE}]+", t))
    if tiny >= 2 or (len(tokens) > 1 and len(tokens[0]) == 1 and re.fullmatch(f"[{_WIDE}]", tokens[0])):
        line = re.sub(f"(?<=[{_WIDE}]) (?=[{_WIDE}])", "", line)
    return line


def _tidy_performer(line: str) -> str:
    return re.sub(" +", "", _strip_marks(line.strip().strip("　")))


def _is_footnote(text: str) -> bool:
    return text.startswith(("※", "［", "■")) or text.endswith("］") or "委嘱" in text


def _blocks_lines(items: list[tuple[float, float, str]]) -> tuple[list[str], list[str]]:
    """The works and the performer entries of one cell, in reading order."""
    works: list[str] = []
    performers: list[str] = []
    last = None  # "work" | "perf": what a continuation line extends
    for _, _, text in sorted(items, key=lambda t: (-t[1], t[0])):
        if _is_footnote(text):
            continue
        indented = text.startswith("　")
        if "／" in text:
            if last == "work" and (indented or works[-1].endswith("／")):
                works[-1] += _tidy_work(text)
            else:
                works.append(_tidy_work(text))
            last = "work"
        elif "：" in text and "。" not in text:  # a sentence (a note such as 「…」で演奏予定です（指揮：…）。) is not a performer line
            for part in re.split(r"　+(?=[^：　]{1,16}：)", text.strip()):
                label, _, name = _tidy_performer(part).partition("：")
                if label and name:
                    performers.append(f"{label} : {name}")
            last = "perf"
        elif last == "work" and indented:
            works[-1] += _tidy_work(text)
        elif last == "perf" and performers and performers[-1].endswith("、"):
            performers[-1] += _tidy_performer(text)
        # anything else is decoration (a heading set in a font the text layer cannot decode)
    return works, performers


def _cluster(values: list[float], tol: float = 2.0) -> list[float]:
    out: list[float] = []
    for v in sorted(values, reverse=True):
        if not out or abs(out[-1] - v) > tol:
            out.append(v)
    return out


def _season_year(month: int, start_year: int) -> int:
    return start_year if month >= 9 else start_year + 1


def parse_season_page(items: list[tuple[float, float, str]], start_year: int) -> tuple[list[dict], dict]:
    """One poster page -> (events shaped like the yearly data file, hall table for ``parse_nhk``); ([], {}) when the page has no grid."""
    heads = sorted(((x, y) for x, y, t in items if t == "PROGRAM"), key=lambda p: p[0])
    if not heads:
        return [], {}
    starts = [x for x, _ in heads]
    head_y = heads[0][1]

    def col(x: float) -> int:
        return max(i for i, s in enumerate(starts) if s <= x + 5) if x + 5 >= starts[0] else -1

    cols = []
    for x, y in heads:
        letter = next((t for lx, ly, t in items if t in ("A", "B", "C") and 20 < lx - x < 50 and abs(ly - y) < 4), None)
        hall = next((_nfkc(t) for hx, hy, t in items if "ホール" in t and 20 < hx - x < 180 and abs(hy - y) < 3), None)
        if not letter or not hall:
            raise ParseError(f"season PDF: column at x={x} has no program letter or hall")
        cols.append({"letter": letter, "hall": hall, "times": []})
    # the weekday + start time of each performance, printed once per column under the heading
    head = [(x, y, t) for x, y, t in items if abs(y - head_y) <= 12 and col(x) >= 0]  # one time line sits just above the "PROGRAM" line, the other just below
    for c_index, c in enumerate(cols):
        mine = [(x, y, t) for x, y, t in head if col(x) == c_index]
        for line_y in _cluster([y for _, y, _ in mine], 1.5):
            parts = sorted((x, t) for x, y, t in mine if abs(y - line_y) <= 1.5)
            wd = next((t for _, t in parts if len(t) == 1 and t in WEEKDAYS), None)
            tm = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)", _nfkc("".join(t for _, t in parts if t not in WEEKDAYS)), re.I)
            if wd and tm:
                c["times"].append((wd, f"{int(tm.group(1))}:{tm.group(2)}{tm.group(3).lower()}"))
    for c in cols:
        if len(c["times"]) != 2:
            raise ParseError(f"season PDF: program {c['letter']} needs two weekday+time lines, found {len(c['times'])}")

    # one row per month: the first date of any column ("9/11") fixes the row's y
    first_dates = [(x, y, t) for x, y, t in items if re.fullmatch(r"\d{1,2}/\d{1,2}", _nfkc(t)) and col(x) >= 0 and y < head_y - 10]
    if not first_dates:
        raise ParseError("season PDF: no dates found")
    rows = _cluster([y for _, y, _ in first_dates])
    margin = [(y, MONTHS[t]) for x, y, t in items if t in MONTHS and x < starts[0] - 5]
    events: list[dict] = []
    halls: dict[str, dict] = {}
    for i, row_y in enumerate(rows):
        upper = row_y - 4
        lower = rows[i + 1] + 3 if i + 1 < len(rows) else float("-inf")
        label = next((m for y, m in margin if abs(y - row_y) <= 3), None)
        if label is None:
            raise ParseError(f"season PDF: month label missing for the row at y={row_y}")
        for c_index, c in enumerate(cols):
            mine = sorted(((x, t) for x, y, t in first_dates if abs(y - row_y) <= 2 and col(x) == c_index))
            if not mine:
                continue  # this program is not held that month (a special concert takes its place)
            first_x, first_text = mine[0]
            m1, d1 = map(int, _nfkc(first_text).split("/"))
            # the other dates of the same row and column: "12", or "7/1" when the run crosses a month
            rest = sorted(((x, _nfkc(t)) for x, y, t in items if abs(y - row_y) <= 2 and col(x) == c_index and x > first_x and re.fullmatch(r"\d{1,2}(/\d{1,2})?", _nfkc(t))))
            weekdays = [t for x, t in sorted(((x, t) for x, y, t in items if abs(y - row_y) <= 2 and col(x) == c_index and t.startswith("（"))) if t]
            dates: list[date] = []
            month, day = m1, d1
            for k, (_, txt) in enumerate([(first_x, f"{m1}/{d1}")] + rest):
                if "/" in txt:
                    month, day = map(int, txt.split("/"))
                else:
                    day = int(txt)
                    if k and day < dates[-1].day:
                        month = month % 12 + 1  # rolled into the next month
                try:
                    dates.append(date(_season_year(month, start_year), month, day))
                except ValueError as exc:
                    raise ParseError(f"season PDF: impossible date {month}/{day}") from exc
            if len(dates) != 2 or len(weekdays) != 2:
                raise ParseError(f"season PDF: program {c['letter']} row {label}: expected two dates, found {len(dates)} dates and {len(weekdays)} weekdays")
            for d, printed, (header_wd, _) in zip(dates, weekdays, c["times"]):
                real = WEEKDAYS[d.weekday()]
                if printed[1:2] != real or header_wd != real:
                    raise ParseError(f"season PDF: {d.isoformat()} is a {real}, the poster says {printed} / {header_wd}")
            cell = [(x, y, t) for x, y, t in items if lower < y < upper and col(x) == c_index and x >= starts[c_index] - 5]
            works, performers = _blocks_lines(cell)
            if not works:
                raise ParseError(f"season PDF: program {c['letter']} {label}月 lists no work")
            year = _season_year(label, start_year)
            hall_id = {"NHKホール": "nhk-hall", "サントリーホール": "suntory-hall"}.get(c["hall"], re.sub(r"\W+", "-", c["hall"]))
            halls[hall_id] = {"name": c["hall"]}
            key = f"{year}{label:02d}{c['letter']}"  # the stem of the address the yearly data file will use (/concert/202709A.html)
            events.append({
                "program_key": key, "details_url": f"/concert/{key}.html",  # sync replaces details_url with the announcement page (the concert page does not exist yet)
                "category": "subscription", "season": "", "program": c["letter"], "status": True,
                "title": f"{year}年{label}月定期公演 {c['letter']}プログラム", "hall_id": hall_id,
                "details": [{"date": d.isoformat(), "start_time": tm, "ticket_status": None} for d, (_, tm) in zip(dates, c["times"])],
                "change_information": "", "main_performers": [{"text": p} for p in performers], "songs": [{"name": w} for w in works],
            })
    return events, {"hall_info": halls}


def parse_season_pdf(pdf: bytes, start_year: int) -> tuple[list[dict], dict]:
    """The whole poster. Pages without the grid (the special-concert page of a 〈速報〉) are skipped; a poster with no grid at all is an error."""
    events: list[dict] = []
    halls: dict = {"hall_info": {}}
    for items in extract_items(pdf):
        page_events, page_halls = parse_season_page(items, start_year)
        events += page_events
        halls["hall_info"].update(page_halls.get("hall_info", {}))
    if not events:
        raise ParseError("season PDF: no programme grid found")
    urls = [e["details_url"] for e in events]
    if len(urls) != len(set(urls)):
        raise ParseError("season PDF: two programmes map to the same address")
    return events, halls
