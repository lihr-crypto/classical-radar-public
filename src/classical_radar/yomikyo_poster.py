"""読響's 2027/28 programme, from the orchestra's preliminary-edition PDF, as a committed transcription (ADR-0021).

The PDF (``season_posters/yomikyo-2027-28.json`` records its address and sha256) has no text layer: every glyph is an outline, so the coordinate parser
of ADR-0009 (``season_pdf``) has nothing to read. The six pages were read from their images instead and written down once, card by card.
Because a person's reading can slip where a parser cannot, ``load`` refuses a file that disagrees with itself: the weekday of every date
must be the weekday printed on its card, the series and number must be unique, every hall must resolve to a prefecture, every role must
be a known one. The sync (``sync._yomikyo_poster``) also compares the live PDF's sha256 with the one recorded here and says so when the
orchestra has replaced it.

One stored concert per performance, with the title the official site uses ("第296回土曜マチネーシリーズ" and "第296回日曜マチネーシリーズ"
are two concerts there too), so the season page's series rules (app.js, ``SERIES.yomikyo``) place them and an official concert can take
a poster concert over one for one (``match_official``).
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from .parsers import ParseError, candidate, canonical, clean
from .venues import prefecture_code
from .works import _clean_name, build_artists, parse_programme  # _clean_name: the one name cleaner of every other source (keeps the ＝ inside フランソワ＝グザヴィエ)

DATA = Path(__file__).parent / "season_posters" / "yomikyo-2027-28.json"  # not "data/": .gitignore ignores every directory of that name
WEEKDAYS = "月火水木金土日"
SEASON_START, SEASON_END = date(2027, 4, 1), date(2028, 3, 31)

# The series word in a concert title, tried in this order (the order of SERIES.yomikyo in web/app.js: 大阪定期 before 定期).
SERIES_WORDS = (("osaka", "大阪定期演奏会"), ("teiki", "定期演奏会"), ("meikyoku", "名曲シリーズ"),
                ("sat", "土曜マチネー"), ("sun", "日曜マチネー"), ("yoko", "横浜マチネー"))
TITLE_WORD = {"osaka": "大阪定期演奏会", "teiki": "定期演奏会", "meikyoku": "名曲シリーズ",
              "sat": "土曜マチネーシリーズ", "sun": "日曜マチネーシリーズ", "yoko": "横浜マチネーシリーズ"}
CARD_SERIES = {"teiki", "meikyoku", "matinee", "yoko", "osaka"}  # "matinee" is one programme on a Saturday and the Sunday after
CHORUS_ROLES = {"合唱", "児童合唱"}
SOLO_ROLES = ("ピアノ", "ヴァイオリン", "チェロ", "フルート", "ハープ", "ホルン", "トランペット", "箏", "尺八", "ソプラノ", "テノール", "バス", "バリトン")
_ARRANGER = re.compile(r"^([^：（）]+?)（([^（）]*編)）：(.+)$")


def series_and_number(title: str) -> tuple[str, int] | None:
    """("teiki", 666) from "第666回定期演奏会"; None for a title that names no numbered series (特別演奏会, 公演, ...)."""
    m = re.match(r"\s*第\s*(\d+)\s*回\s*(.+)", unicodedata.normalize("NFKC", title or ""))
    if not m:
        return None
    for series, word in SERIES_WORDS:
        if word in m.group(2):
            return series, int(m.group(1))
    return None


def _fail(card: dict | None, why: str):
    where = f"{card.get('series')} No.{card.get('no')}: " if card else ""
    raise ParseError(f"yomikyo poster: {where}{why}")


def _check_card(card: dict) -> None:
    if card.get("series") not in CARD_SERIES or not isinstance(card.get("no"), int):
        _fail(card, "unknown series or a number that is not an integer")
    dates = card.get("dates")
    if not isinstance(dates, list) or not dates:
        _fail(card, "no dates")
    if card["series"] != "matinee" and len(dates) != 1:
        _fail(card, "only a matinee programme has two dates")
    for pair in dates:
        try:
            iso, weekday = pair
            day = date.fromisoformat(iso)
        except (TypeError, ValueError):
            _fail(card, f"bad date entry {pair!r}")
        if WEEKDAYS[day.weekday()] != weekday:
            _fail(card, f"{iso} is a {WEEKDAYS[day.weekday()]}, the card prints {weekday}")
        if not SEASON_START <= day <= SEASON_END:
            _fail(card, f"{iso} is outside the 2027-28 season")
        if card["series"] == "matinee" and weekday not in ("土", "日"):
            _fail(card, "a matinee date must be a Saturday or a Sunday")
    if not re.fullmatch(r"\d{2}:\d{2}", card.get("time") or ""):
        _fail(card, "bad time")
    if not prefecture_code(card.get("hall")):
        _fail(card, f"hall {card.get('hall')!r} has no prefecture (venues.py)")
    performers = card.get("performers")
    if not isinstance(performers, list) or not performers:
        _fail(card, "no performers")
    for p in performers:
        if not isinstance(p, list) or not (2 <= len(p) <= 3) or not all(isinstance(x, str) for x in p) or not clean(p[1]):
            _fail(card, f"bad performer entry {p!r}")
    if sum(1 for p in performers if p[0] == "指揮") != 1:
        _fail(card, "exactly one 指揮 is needed")
    for p in performers:
        if p[0] != "指揮" and p[0] not in CHORUS_ROLES and not p[0].startswith(SOLO_ROLES):
            _fail(card, f"unknown role {p[0]!r}")
    pieces = card.get("pieces")
    if not isinstance(pieces, list) or not pieces or any("：" not in x for x in pieces):
        _fail(card, "every piece must read 'composer：work'")


def load(path: Path = DATA) -> dict:
    """{"source": {...}, "concerts": [one dict per performance]}; ParseError for a file that disagrees with itself."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ParseError(f"yomikyo poster: cannot read {path}: {exc}") from exc
    source, cards = raw.get("source") or {}, raw.get("cards")
    if not source.get("pdf") or not re.fullmatch(r"[0-9a-f]{64}", source.get("sha256") or "") or not isinstance(cards, list) or not cards:
        raise ParseError("yomikyo poster: the source block (pdf, sha256) or the cards are missing")
    concerts, seen = [], set()
    for card in cards:
        _check_card(card)
        for iso, weekday in card["dates"]:
            series = ({"土": "sat", "日": "sun"}[weekday]) if card["series"] == "matinee" else card["series"]
            tag = f"{series}-{card['no']}"
            if tag in seen:
                _fail(card, f"{tag} appears twice")
            seen.add(tag)
            concerts.append({"tag": tag, "series": series, "no": card["no"], "title": f"第{card['no']}回{TITLE_WORD[series]}", "date": iso,
                             "time": card["time"], "hall": card["hall"], "performers": card["performers"], "pieces": card["pieces"], "notes": card.get("notes") or []})
    return {"source": source, "concerts": concerts}


def _performer_line(p: list) -> str:
    role, name, note = p[0], p[1], (p[2] if len(p) > 2 else None)
    if note == "他":
        return f"{role}＝{name} 他"
    if note == "＊":
        return f"{role}＝{name}＊"
    return f"{role}＝{name}" + (f"（{note}）" if note else "")


def _kind(role: str) -> str:
    return "conductor" if role == "指揮" else "other" if role in CHORUS_ROLES else "soloist"


def _arranger_after_work(piece: str) -> str:
    """"ムソルグスキー（ラヴェル編）：組曲「展覧会の絵」" -> "ムソルグスキー：組曲「展覧会の絵」（ラヴェル編）", so the composer on the left is just a name."""
    m = _ARRANGER.match(piece)
    return f"{m.group(1)}：{m.group(3)}（{m.group(2)}）" if m else piece


def candidates(concerts: list[dict], source_url: str, observed_at: str | None = None) -> list[dict]:
    """One candidate per performance, identity ``<pdf>?program=<tag>`` (the PDF is the page that states it)."""
    out = []
    for c in concerts:
        y, m, d = (int(x) for x in c["date"].split("-"))
        artists = [_performer_line(p) for p in c["performers"]] + [f"（{n}）" for n in c["notes"]]
        item = candidate("yomikyo", f"{source_url}?program={c['tag']}", c["title"], f"{y}年{m}月{d}日 {c['time']}", c["hall"],
                         artists="; ".join(artists), programme="; ".join(c["pieces"]), selector="2027-28web.pdf, transcribed from the page images", observed_at=observed_at)
        item["evidence"]["pdf_url"] = source_url
        item["programme_items"] = parse_programme([_arranger_after_work(x) for x in c["pieces"]])
        item["artists_items"] = build_artists([{"name_display": _clean_name(p[1]), "role_label": p[0], "kind": _kind(p[0])} for p in c["performers"]])
        item["poster"] = {"tag": c["tag"], "series": c["series"], "no": c["no"]}
        out.append(item)
    return out


def match_official(poster: list[dict], official: list[dict]) -> tuple[dict, dict]:
    """Which official concert already is each poster programme: ({tag: official candidate}, {tag: why it is ambiguous}).

    By the series and number the official title carries ("第666回定期演奏会"), whatever its date (a programme can move). Only when no official
    title carries them, by the same date, time AND hall, and only when exactly one official concert qualifies and its title names no other
    numbered programme. Two or more candidates is a doubt, never a guess: the poster concert stays where it is and the caller says so."""
    def distinct(hits: list[dict]) -> list[dict]:  # one page listed twice (a Saturday and a Sunday on one address, a repeated calendar cell) is one concert
        first: dict[str, dict] = {}
        for o in hits:
            first.setdefault(canonical(o["source_url"]), o)
        return list(first.values())

    # Only an official concert dated inside the 2027-28 season can be one of these programmes: an older season's concert that carries the
    # same number (it cannot happen while numbers only go up, but a wrong merge here would replace a real programme) is never taken for it.
    official = [o for o in official if o.get("local_date") and SEASON_START.isoformat() <= o["local_date"] <= SEASON_END.isoformat()]
    by_number: dict[tuple[str, int], list[dict]] = {}
    for o in official:
        sn = series_and_number(o["title"])
        if sn:
            by_number.setdefault(sn, []).append(o)
    matched, ambiguous = {}, {}
    for p in poster:
        tag, sn = p["poster"]["tag"], (p["poster"]["series"], p["poster"]["no"])
        hits = distinct(by_number.get(sn, []))
        if not hits and p["venue"] and p["local_time"]:
            hits = distinct([o for o in official if series_and_number(o["title"]) is None and o["venue"] and o["local_time"]
                             and (o["local_date"], o["local_time"], clean(o["venue"])) == (p["local_date"], p["local_time"], clean(p["venue"]))])
        if len(hits) == 1:
            matched[tag] = hits[0]
        elif hits:
            ambiguous[tag] = f"{len(hits)} official concerts fit"
    return matched, ambiguous
