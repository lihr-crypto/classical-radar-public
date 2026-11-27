"""Sale-start claims from Japan Arts, TSO and Kanagawa detail pages (ADR-0005; amends ADR-0001's "year stated explicitly").

A claim is the existing ``ticket_claims`` dict (see ``detail._claim``): phase_type, audience_eligibility, local_date/local_time/starts_at,
``label_raw`` (shown as the phase's eligibility), plus ``year_basis``: ``"explicit"`` (the page wrote the year) or ``"weekday"`` (it did not,
and the weekday in brackets fixed it). Rules, all fail-safe (no claim rather than a guess):

* a claim needs a day AND a clock time; a date-only line yields nothing (as for every other source);
* no year and no weekday -> no claim; a weekday that fits none or both of {reference year - 1, reference year}, or a date after the
  reference (the first performance), -> no claim. The same month/day falls on a different weekday in two consecutive years, so a
  fitting weekday is unique;
* ``a.m.`` / ``p.m.`` are converted to 24 h before the time is stored;
* only ``general_sale`` ("一般") is named; everything else the page does not label as such is ``other`` with its own label as eligibility.
  Nothing is called a member presale or a lottery unless the page says 会員 (TSO) - lines are not interpreted beyond what they state;
* a claim never has an empty label, and linking to a performance stays with ``linking.link_presenter_claims`` (sole performance, no two
  claims with the same phase and label).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

from bs4 import BeautifulSoup

from .parsers import clean, parse_date

WEEKDAYS = "月火水木金土日"


def resolve_start(year: int | None, month: int, day: int, weekday: str | None, reference: date | None) -> tuple[date | None, str | None]:
    """(date, basis) with basis "explicit" | "weekday", or (None, None) when the year cannot be fixed without guessing."""
    if year is not None:
        try:
            return date(year, month, day), "explicit"
        except ValueError:
            return None, None
    if reference is None or not weekday or weekday not in WEEKDAYS:
        return None, None
    fits = []
    for y in (reference.year - 1, reference.year):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if WEEKDAYS[d.weekday()] == weekday and d <= reference:
            fits.append(d)
    return (fits[0], "weekday") if len(fits) == 1 else (None, None)


def clock(hour: str | None, minute: str | None, ampm: str | None = None) -> str | None:
    if hour is None or minute is None:
        return None
    h = int(hour)
    if ampm:
        pm = ampm.lower().startswith("p")
        if not 1 <= h <= 12:
            return None
        h = (h % 12) + (12 if pm else 0)
    return f"{h:02d}:{minute}" if h < 24 and int(minute) < 60 else None


def make_claim(phase_type: str, label: str, when: date, hhmm: str, url: str, year_basis: str, *, label_raw: str | None = None) -> dict | None:
    """The shared claim shape. ``label`` is both the audience text and (unless ``label_raw`` is given) the eligibility shown for the phase."""
    d = parse_date(f"{when.year}年{when.month}月{when.day}日 {hhmm}")
    if d["starts_at"] is None or not label.strip():
        return None
    return {"phase_type": phase_type, "audience_eligibility": label, "local_date": d["local_date"], "local_time": d["local_time"], "starts_at": d["starts_at"],
            "date_precision": d["date_precision"], "ends_at": None, "source_url": url, "label_raw": label_raw or label, "year_basis": year_basis,
            "linkage_status": "needs_review", "performance_ids": []}


# ---- Japan Arts: <h3 class="heading-2">チケット発売情報</h3><ol class="list-type-7"><li>① 3月7日(土) 10：00a.m.～発売 一般 <span class="label">WEB</span></li>…
_JA = re.compile(r"^(?:(?P<pre>受付期間)\s*:\s*)?(?:\d+\s+)?(?:(?P<y>\d{4})年\s*)?(?P<m>\d{1,2})月(?P<d>\d{1,2})日\s*(?:\((?P<w>[月火水木金土日])[^)]*\))?\s*"
                 r"(?P<h>\d{1,2}):(?P<mi>\d{2})\s*(?P<ap>[ap]\.?m\.?)?\s*(?P<rest>.*)$", re.I)
_JA_END = re.compile(r"^\d{1,2}月\d{1,2}日\s*(?:\([^)]*\))?\s*(?:\d{1,2}:\d{2}\s*)?")
_PLACE = re.compile(r"ホール|劇場|会館|アクロス|センター|シンフォニー|Hall", re.I)


def japanarts_ticket_items(soup: BeautifulSoup) -> list[str]:
    """The page's OWN ticket list (the rest of a Japan Arts page is navigation cards of other concerts): the ``ol`` right under the
    "チケット発売情報" heading. Labels such as WEB / TEL are removed."""
    for h in soup.find_all("h3"):
        if clean(h.get_text()) == "チケット発売情報":
            ol = h.find_next_sibling("ol")
            if ol is None:
                return []
            out = []
            for li in ol.find_all("li", recursive=False):
                li = BeautifulSoup(str(li), "html.parser")
                for t in li.select("span.label"):
                    t.decompose()
                out.append(unicodedata.normalize("NFKC", li.get_text(" ", strip=True)))
            return out
    return []


def japanarts_sale_claims(soup: BeautifulSoup, url: str, reference: date | None, venues: str = "") -> list[dict]:
    claims = []
    squashed_venue = re.sub(r"\s+", "", unicodedata.normalize("NFKC", venues))
    for line in japanarts_ticket_items(soup):
        m = _JA.match(re.sub(r"\s+", " ", line).strip())
        if not m:
            continue
        rest = (m["rest"] or "").strip()
        if m["pre"] is None and not rest.startswith("~"):
            continue  # a date that is not introduced as a sale start/window
        if rest.startswith("~"):
            rest = _JA_END.sub("", rest[1:].strip(), count=1)  # the END of a window is not a start
            rest = re.sub(r"^発売\s*", "", rest.strip())
        label = re.split(r"※|https?://", rest)[0].strip(" :・") or (m["pre"] or "")  # trailing notes and URLs are not part of the label
        if not label:
            continue
        if _PLACE.search(label):  # a venue named in the label ("アクロス福岡 先行") sells for that tour stop: keep it only if it is THIS performance's venue
            core = re.sub(r"\s+", "", re.sub(r"先行|発売|先着|プリセール", "", label))
            if not core or core not in squashed_venue:
                continue
        when, basis = resolve_start(int(m["y"]) if m["y"] else None, int(m["m"]), int(m["d"]), m["w"], reference)
        hhmm = clock(m["h"], m["mi"], m["ap"])
        if when is None or hhmm is None:
            continue
        c = make_claim("general_sale" if "一般" in label else "other", label[:60], when, hhmm, url, basis)
        if c:
            claims.append(c)
    return claims


# ---- TSO: "東響会員先行発売…2025年11/27（木）10:00", "オンライン先行発売：12/1（月）10:00", "一般発売…2026/2/6(金)10:00"
# Pages list one set of three lines per ticket group, each group under its own heading ("■定期会員券", "■選べるプラン・1回券", or inline
# "年間セット券 □東響会員先行発売…"): the heading is part of the label, so two groups on one page do not look like the same sale.
_TSO = re.compile(r"(?P<label>東響会員先行発売|オンライン先行発売|一般発売)\s*[…:.・]+\s*(?:(?P<y>\d{4})(?:年|/)\s*)?(?P<m>\d{1,2})/(?P<d>\d{1,2})\s*\((?P<w>[月火水木金土日])[^)]*\)[^\S\n]*(?:(?P<h>\d{1,2}):(?P<mi>\d{2}))?")
_TSO_LABELS = {"東響会員先行発売": ("member_presale", "東響会員先行"), "オンライン先行発売": ("other", "オンライン先行"), "一般発売": ("general_sale", "一般")}
_MARKS = "■□◇◆●○▲△▼▽・ \u3000"
_TICKET_WORD = re.compile(r"券|プラン|セット")  # every heading seen on real pages: 定期会員券, 選べるプラン・1回券, 年間セット券, 後期セット券・後期1回券


def _tso_heading(gap: str, current: str | None) -> str | None:
    """The ticket-group heading from the text between two sale lines: the last short line, but only if it names a ticket type (else keep the current one)."""
    for line in reversed([x.strip(_MARKS) for x in gap.splitlines() if x.strip(_MARKS)]):
        if len(line) <= 40 and _TICKET_WORD.search(line) and not re.search(r"発売|先行|受付|販売|開始|主催|助成|日時|会場", line) and not re.search(r"\d+\s*[/月年日:]", line):
            return line
        break  # the last line is not a ticket-type heading (a price, a venue, a note ...): keep the current heading, never guess one
    return current


def tso_sale_claims(text: str, url: str, reference: date | None) -> list[dict]:
    claims = []
    normalized = unicodedata.normalize("NFKC", text)
    heading, last_end = None, 0
    for m in _TSO.finditer(normalized):
        heading = _tso_heading(normalized[last_end:m.start()], heading)
        last_end = m.end()
        when, basis = resolve_start(int(m["y"]) if m["y"] else None, int(m["m"]), int(m["d"]), m["w"], reference)
        hhmm = clock(m["h"], m["mi"])
        if when is None or hhmm is None:
            continue
        phase_type, label = _TSO_LABELS[m["label"]]
        c = make_claim(phase_type, f"{label}（{heading}）" if heading else label, when, hhmm, url, basis)
        if c:
            claims.append(c)
    return claims


# ---- Kanagawa: "一回券：2026年2月27日（金）10:00～", "セット券一般発売：…", "１回券一般発売：…", "一般発売日：7月29日（水）10:00～"
_KG = re.compile(r"(?P<label>セット券一般発売日?|(?:1|一)回券一般発売日?|セット券|(?:1|一)回券|一般発売日?)\s*:\s*(?:(?P<y>\d{4})年\s*)?(?P<m>\d{1,2})月(?P<d>\d{1,2})日[^\S\n]*(?:\((?P<w>[月火水木金土日])[^)]*\))?[^\S\n]*(?P<h>\d{1,2}):(?P<mi>\d{2})")
_KG_BRACKET = re.compile(r"(?:【(?P<b>[^】\n]{1,20})】|<(?P<a>[^>\n]{1,20})>)[^\S\n]*(?:(?P<y>\d{4})年[^\S\n]*)?(?P<m>\d{1,2})月(?P<d>\d{1,2})日[^\S\n]*(?:\((?P<w>[月火水木金土日])[^)]*\))?[^\S\n]*(?P<h>\d{1,2}):(?P<mi>\d{2})")
_KG_LEGACY = re.compile(r"一回券[:：]\s*(\d{4}年\d{1,2}月\d{1,2}日)[^\d]{0,6}(\d{1,2}:\d{2})")


def kanagawa_sale_claims(text: str, url: str, reference: date | None) -> list[dict]:
    claims = []
    normalized = unicodedata.normalize("NFKC", text)
    # the text the first version stored as eligibility for 一回券: kept so a re-sync adds no duplicate phase (keyed by the numbers, so full-width or zero-padded digits still match)
    legacy = {tuple(int(x) for x in re.findall(r"\d+", m.group(1))): m.group(0) for m in _KG_LEGACY.finditer(text)}
    for m in _KG.finditer(normalized):  # one claim per line, the most specific label first (alternation order)
        when, basis = resolve_start(int(m["y"]) if m["y"] else None, int(m["m"]), int(m["d"]), m["w"], reference)
        hhmm = clock(m["h"], m["mi"])
        if when is None or hhmm is None:
            continue
        label = m["label"]
        eligibility = "一般（セット券）" if label.startswith("セット券") else "一般（1回券）" if re.match(r"(?:1|一)回券", label) else "一般"
        raw = legacy.get((when.year, when.month, when.day)) if label == "一回券" else None
        c = make_claim("general_sale", eligibility, when, hhmm, url, basis, label_raw=raw)
        if c:
            claims.append(c)
    for m in _KG_BRACKET.finditer(normalized):  # "【４公演セット】2026年10月23日（金）10:00～ 一般発売", "＜２公演セット券＞2026年4月28日（火）10:00～"
        label = m["b"] or m["a"]
        line_end = normalized.find("\n", m.end())
        rest = normalized[m.end(): line_end if line_end != -1 else len(normalized)]
        if not re.fullmatch(r"[\s~〜]*(?:一般(?:発売日?)?)?[\s~〜]*", rest):  # "…10:00～ 会員先行発売", "…抽選受付" etc. are not a general sale: say nothing
            continue
        eligibility = "一般（セット券）" if "セット" in label else "一般（1回券）" if re.search(r"(?:1|一)回券", label) else None
        when, basis = resolve_start(int(m["y"]) if m["y"] else None, int(m["m"]), int(m["d"]), m["w"], reference)
        hhmm = clock(m["h"], m["mi"])
        if eligibility is None or when is None or hhmm is None:
            continue
        c = make_claim("general_sale", eligibility, when, hhmm, url, basis)
        if c:
            claims.append(c)
    return claims
