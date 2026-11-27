"""Pure, conservative POC parsers; output is not the frozen V1.5 API contract."""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import re
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .works import build_artists, parse_artist, parse_programme

JST = ZoneInfo("Asia/Tokyo")


class ParseError(ValueError):
    pass


def clean(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def text(node, selector: str | None = None) -> str:
    node = node.select_one(selector) if node is not None and selector else node
    return clean(node.get_text(" ", strip=True)) if node else ""


def canonical(url: str) -> str:
    p = urlsplit(url)
    # Query is significant (TMSO uses ?id=). Never collapse distinct events.
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), p.query, ""))


def parse_date(raw: str) -> dict:
    raw = clean(raw)
    match = re.search(r"(?<!\d)(\d{4})\s*[年/.-]\s*(\d{1,2})\s*[月/.-]\s*(\d{1,2})(?:日)?(?!\d)", raw)
    result = {"raw": raw, "local_date": None, "local_time": None, "starts_at": None, "date_precision": "unknown"}
    if not match:
        return result
    try:
        d = date(*map(int, match.groups()))
    except ValueError as exc:
        raise ParseError(f"invalid explicit date: {raw}") from exc
    result.update(local_date=d.isoformat(), date_precision="day")
    time_match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})\s*(am|pm)?", raw[match.end():], re.I)
    if time_match:
        tail=raw[match.end():]
        # An opening time alone does not establish the performance start time.
        suffix=tail[time_match.end():].lstrip(" )）")
        if suffix.startswith("開場"):
            return result
        h, minute = map(int, time_match.groups()[:2])
        ampm = time_match.group(3)
        if ampm:
            if not 1 <= h <= 12:
                raise ParseError("invalid 12-hour time")
            h = h % 12 + (12 if ampm.lower() == "pm" else 0)
        try:
            dt = datetime(d.year, d.month, d.day, h, minute, tzinfo=JST)
        except ValueError as exc:
            raise ParseError(f"invalid explicit time: {raw}") from exc
        result.update(local_time=dt.strftime("%H:%M"), starts_at=dt.astimezone(timezone.utc).isoformat(), date_precision="minute")
    return result


# 00_DECISIONS 0.1: the user excluded these domestic orchestras. The exclusion is applied to the *title hint* only
# and only reported as a hint (never silently dropped): a presenter page may merely feature them as a guest.
EXCLUDED_ORCHESTRAS = re.compile(r"神奈川フィル|東京シティ[・･]?フィル|パシフィック[・･]?フィルハーモニア|Pacific Philharmonia|千葉交響楽団")


def sole_pianist(artists: str) -> bool:
    """True when the performer field lists exactly one role and it is piano, with no orchestra/conductor.

    Japan Arts writes performers as ``name (ピアノ, Piano)``. This catches solo programmes whose title lacks
    ``リサイタル`` (e.g. ピアノ・ソナタ全曲演奏会) without promoting concerto programmes, duos or accompanied recitals.
    """
    roles = re.findall(r"[（(]([^()（）]*)[)）]", artists or "")
    return len(roles) == 1 and roles[0].lstrip().startswith("ピアノ") and not re.search(r"管弦楽|交響楽|オーケストラ|Orchestra|指揮|Conductor", artists)


def classify(title: str, source_id: str, artists: str = "") -> str:
    if source_id in {"kanagawa_geikyo", "japanarts", "kajimoto"} and EXCLUDED_ORCHESTRAS.search(f"{title} {artists}"):
        return "excluded_domestic_orchestra"
    if source_id == "japanarts" and sole_pianist(artists) and not re.search(r"協奏|デュオ|DUO|二台|2台", title, re.I):
        return "piano_recital"
    if re.search(r"ピアノ.{0,4}リサイタル|PIANO RECITAL", title, re.I):
        if not re.search(r"デュオ|二台|2台|DUO|協奏", title, re.I):
            return "piano_recital"
    if source_id in {"nhkso", "tmso", "tso", "jpo", "njp", "yomikyo", "tpo"}:
        # A domestic orchestra website may also list chamber music or guest recitals.
        return "domestic_source_candidate"
    return "needs_review"


def candidate(source_id, url, title, raw_date, venue, *, artists="", programme="", selector="", observed_at=None):
    dates = parse_date(raw_date)
    concert_id = sha256(f"{source_id}|{canonical(url)}".encode()).hexdigest()[:24]
    pkey = sha256(f"{concert_id}|{dates['local_date']}|{dates['local_time']}|{clean(venue)}".encode()).hexdigest()[:24]
    return {
        "poc_schema_version": 1, "source_id": source_id, "source_url": url,
        "concert_id": concert_id, "performance_id": pkey,
        "title": clean(title), "category": classify(title, source_id, artists),
        **dates, "venue": clean(venue) or None,
        "artists_raw": clean(artists) or None, "programme_raw": clean(programme) or None,
        "official_announcement_at": None, "first_seen_at": observed_at,
        "verification_status": "candidate", "ticket_phases": [],
        "evidence": {"selector": selector, "date_raw": clean(raw_date), "venue_raw": clean(venue)},
    }


LIST_SELECTORS = {
    "tmso": ".entry-cell.entry-content", "tso": "a.concertslist__box-link",
    "jpo": "article.cardPostDetail", "njp": ".concertsList__item",
    "tpo": "div.concert", "japanarts": ".item-type-4",
    "kajimoto": "a.concert_item", "kanagawa_geikyo": "article.media",
}


def _list_fields(source_id, node):
    if source_id == "tmso":
        return (node.select_one("h3 a"), text(node,".entry-title"), text(node,".entry-date"), text(node,".entry-hall"), text(node,".entry-detail p"), text(node,".notes"))
    if source_id == "tso":
        return (node, text(node,"h3"), text(node,".concertslist__contents-date")+" "+text(node,".concertslist__contents-time"), text(node,".concertslist__contents-location"), text(node,".concertslist__artist"), text(node,".concertslist__program"))
    if source_id == "jpo":
        notes = node.select(".noteIcon")
        return (node.select_one(".cardPostDetail__ttl a"), text(node,".cardPostDetail__ttl"), text(notes[0]) if notes else "", text(notes[1]) if len(notes)>1 else "", text(node,".cardPostDetail__textarea p"), "")
    if source_id == "njp":
        return (node.select_one("a.--detail"), text(node,".--title"), text(node,".--date"), text(node,".--place"), "", text(node,".program__list"))
    if source_id == "tpo":
        return (node.select_one(".more a"), text(node,"h3"), text(node,".year")+" "+text(node,".day"), text(node,".spot"), "", "")
    if source_id == "japanarts":
        fields = {text(dl,"dt"):text(dl,"dd") for dl in node.select("dl")}
        return (node.select_one("a"), text(node,"h3"), fields.get("日時",""), fields.get("会場",""), "", "")
    if source_id == "kajimoto":
        # Only the first .content block is UPCOMING; exclude the archive.
        title = text(node,".item_header p:last-child") or text(node,".item_header")
        return (node, title, text(node,".item_label"), "", "", "")
    if source_id == "kanagawa_geikyo":
        return (node.select_one("h1 a"), text(node,"h1"), text(node,".published"), text(node,".concert-place-btn"), "", "")
    raise ParseError(f"no list parser: {source_id}")


def parse_list(source_id: str, html: str, url: str, observed_at=None) -> tuple[list, dict]:
    soup = BeautifulSoup(html, "html.parser")
    if source_id not in LIST_SELECTORS:
        raise ParseError(f"{source_id}: no static list adapter; do not report zero concerts")
    scope = soup
    if source_id == "kajimoto":
        first_card = soup.select_one("a.concert_item")
        first = first_card.parent if first_card else None
        if first:
            scope = first
    nodes = scope.select(LIST_SELECTORS[source_id])
    if not nodes:
        raise ParseError(f"{source_id}: no expected cards; source may have changed")
    records, skipped = {}, 0
    for node in nodes:
        a, title, raw_date, venue, artists, programme = _list_fields(source_id,node)
        if not a or not a.get("href") or not title:
            skipped += 1
            continue
        # A multi-day range cannot be safely represented as a single performance.
        if source_id == "tpo" and re.search(r"[〜～~]", raw_date):
            skipped += 1
            continue
        item = candidate(source_id,urljoin(url,a["href"]),title,raw_date,venue,artists=artists,programme=programme,selector=LIST_SELECTORS[source_id],observed_at=observed_at)
        records[item["performance_id"]] = item
    return list(records.values()), {"dom_cards":len(nodes), "unique_candidates":len(records), "skipped_cards":skipped, "scope":"one fetched landing page only; not all announced performances"}


def parse_yomikyo_calendar(html: str, url: str, observed_at=None) -> tuple[list, dict]:
    """Season calendar (cal.php): one table.cal per month, one a[data-title] per concert.

    Dates come from the month header (``11 Nov 2026``) plus the day cell, and are cross-checked
    against the ``M/D`` prefix of the popover title; a disagreement skips the cell rather than guessing.
    The calendar shows start time but not venue (venue needs the detail page).
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("table.cal")
    if not tables:
        raise ParseError("yomikyo: no calendar tables; source may have changed")
    records, skipped, anchors, months = {}, [], 0, []
    for table in tables:
        box = table.find_parent("div")
        m = re.search(r"(?<!\d)(\d{1,2})\s+[A-Z][a-z]{2}\s+(\d{4})", text(box))
        if not m:
            raise ParseError("yomikyo: month header not found")
        month, year = int(m.group(1)), int(m.group(2))
        months.append(f"{year}-{month:02d}")
        for td in table.select("td.concert_day"):
            if "other_month" in td.get("class", []):
                continue
            for a in td.select("a[data-title][href]"):
                anchors += 1
                title = clean(a["data-title"])
                dm = re.match(r"(\d{1,2})/(\d{1,2})\s+(.*)", title)
                day = clean(a.get_text())
                if not dm or not day.isdigit() or (int(dm.group(1)), int(dm.group(2))) != (month, int(day)):
                    skipped.append({"href": a["href"], "reason": "date prefix disagrees with calendar cell", "title": title})
                    continue
                tm = re.match(r"\s*(\d{1,2}:\d{2})", BeautifulSoup(a.get("data-content", ""), "html.parser").get_text())
                raw = f"{year}年{month}月{int(day)}日" + (f" {tm.group(1)}" if tm else "")
                item = candidate("yomikyo", urljoin(url, a["href"].split("#")[0]), dm.group(3), raw, "", selector="table.cal td.concert_day a[data-title]", observed_at=observed_at)
                records[item["performance_id"]] = item
    return list(records.values()), {"months": months, "anchors": anchors, "unique_candidates": len(records), "skipped": skipped,
                                    "scope": "season calendar page (one fiscal year); venue not present on this page"}


def parse_nhk(data: dict, halls: dict, url: str, observed_at=None) -> list:
    if "concerts" not in data:
        raise ParseError("NHK: concerts missing")
    out = []
    for event in data["concerts"]:
        title = text(BeautifulSoup(event["title"],"html.parser"))
        venue = halls.get("hall_info",{}).get(event["hall_id"],{}).get("name", "")
        for perf in event["details"]:
            raw = perf["date"]+" "+perf.get("start_time","")
            item = candidate("nhkso",urljoin(url,event["details_url"]),title,raw,venue,artists="; ".join(x["text"] for x in event.get("main_performers",[])),programme="; ".join(x["name"] for x in event.get("songs",[])),selector="concerts[].details[] + hall_info[hall_id]",observed_at=observed_at)
            item["evidence"]["list_data_url"] = url
            item["programme_items"] = parse_programme([x["name"] for x in event.get("songs", [])])
            item["artists_items"] = build_artists([a for a in (parse_artist(x["text"]) for x in event.get("main_performers", [])) if a])
            item["source_ticket_status_raw"] = perf.get("ticket_status")
            item["nhk"] = {"category": event.get("category"), "program": event.get("program"),
                           "change_information": clean(BeautifulSoup(event.get("change_information") or "", "html.parser").get_text(" "))}
            # Numeric status codes are deliberately not guessed.
            out.append(item)
    return out


def ticket_claims(soup, url: str) -> list:
    claims=[]
    for p in soup.select("p.wp-block-paragraph"):
        lines=[clean(x) for x in p.get_text("\n",strip=True).splitlines() if clean(x)]
        for i,label in enumerate(lines[:-1]):
            if label != "一般発売" and not re.search(r"会員.*(先行|受付)",label):
                continue
            raw=lines[i+1]
            d=parse_date(raw)
            if d["local_date"] is None:
                continue
            claims.append({"phase_type":"general_sale" if label=="一般発売" else "member_presale", "audience_eligibility":"general" if label=="一般発売" else label,
                **d,"ends_at":None,"source_url":url,"label_raw":label,"linkage_status":"needs_review","performance_ids":[]})
    return claims


def _presenter_programme_and_artists(source_id: str, soup, perfs: list) -> tuple[list, list]:
    """Concert-level programme and performers from a presenter detail page; empty lists when the page states none."""
    prog: list = []
    parsed: list = []
    if source_id == "japanarts":
        for h in soup.find_all(["h2", "h3"]):
            if "曲目" in clean(h.get_text()):
                lines = []
                for sib in h.find_next_siblings():  # a programme may be split over several blocks (one per day) until the next heading
                    if sib.name in ("h2", "h3"):
                        break
                    lines += [clean(x) for x in sib.get_text("\n", strip=True).splitlines()]
                prog = parse_programme(lines)
                break
        for a in soup.select(".l-overview__info a.anchor"):
            parsed.append(parse_artist(a.get_text(" ", strip=True)))
    elif source_id == "kajimoto":
        pairs, seen = [], set()
        for sec in soup.select("#information section.concert_info"):
            comp = None
            for el in sec.select(".concert_info_program dt, .concert_info_program dd"):
                t = clean(el.get_text(" ", strip=True))
                if el.name == "dt":
                    comp = t or None
                elif comp:
                    pair = (comp, t)
                    if pair not in seen:
                        seen.add(pair)
                        pairs.append(pair)
                    comp = None
                elif t:
                    pairs.append(("", t))
        prog = parse_programme([], pairs=pairs)
        names = []
        for img in soup.select("aside.concert_artists a.item img[alt]"):
            alt = clean(img["alt"])
            names.append(re.split(r"\s[–—-]\s", alt)[-1].strip() or alt)
        names = list(dict.fromkeys(names))
        solo = len(names) == 1 and perfs and perfs[0]["category"] == "piano_recital"
        parsed = [{"name_display": nm, "role_label": "", "kind": "soloist" if solo else "other"} for nm in names]
    elif source_id == "yomikyo":
        box = soup.select_one(".concert_info_detail")
        lines = [clean(x) for x in box.get_text("\n", strip=True).splitlines()] if box else []
        lines = [x for x in lines if x and not x.startswith("【")]
        perf_lines = [x for x in lines if re.match(r"^[^:=/]{1,24}=", x)]
        prog = parse_programme([x for x in lines if x not in perf_lines])
        parsed = [parse_artist(x) for x in perf_lines]
    return prog, build_artists([p for p in parsed if p])


def parse_presenter_detail(source_id: str, html: str, url: str, observed_at=None) -> dict:
    soup=BeautifulSoup(html,"html.parser")
    title=text(soup,"h1")
    out=[]
    if source_id == "japanarts":
        # Only the performance's own overview. Related-performance cards (a.item-type-6)
        # and national-schedule links reuse list-type-3 markup but belong to other pages.
        for node in soup.select("div.l-overview__info div.list-type-3"):
            fields={text(dl,"dt"):text(dl,"dd") for dl in node.select("dl")}
            if "日時" not in fields or "会場" not in fields:
                continue
            out.append(candidate(source_id,url,title,fields["日時"],fields["会場"],artists=fields.get("出演",""),selector="div.list-type-3 dl[日時/会場]",observed_at=observed_at))
    elif source_id == "kajimoto":
        for node in soup.select("#information section.concert_info"):
            out.append(candidate(source_id,url,title,text(node,".concert_info_dates_date"),text(node,".concert_info_venue_name"),programme=text(node,".concert_info_program"),selector="#information section.concert_info",observed_at=observed_at))
    elif source_id == "yomikyo":
        node=soup.select_one(".concert_info_main")
        if node:
            raw=text(node,"p.hall")
            # The dedicated source field spells the date as '2026 11.24'.
            normalized=re.sub(r"^(\d{4})\s+(\d{1,2})\.\s*(\d{1,2})",r"\1年\2月\3日",raw)
            out.append(candidate(source_id,url,text(node,"h2"),normalized,text(node,".place"),selector=".concert_info_main p.hall",observed_at=observed_at))
    else:
        raise ParseError("no detail adapter for this source")
    if not out:
        raise ParseError(f"{source_id}: missing expected performance fields")
    claims = ticket_claims(soup, url) if source_id == "kajimoto" else []
    if source_id == "japanarts":  # the page's own チケット発売情報 list; year-less lines are fixed by their weekday against the first performance (saleparse, ADR-0005)
        from datetime import date as _date
        from .saleparse import japanarts_sale_claims
        days = [c["local_date"] for c in out if c["local_date"]]
        claims = japanarts_sale_claims(soup, url, _date.fromisoformat(min(days)) if days else None, " ".join(c["venue"] or "" for c in out))
    prog, arts = _presenter_programme_and_artists(source_id, soup, out)
    for item in out:
        item["programme_items"], item["artists_items"] = prog, arts
    unique={x["performance_id"]:x for x in out}
    return {"performances":list(unique.values()),"ticket_claims":claims}


def material_hash(item: dict) -> str:
    fields=["title","category","local_date","local_time","venue","artists_raw","programme_raw","ticket_phases"]
    return sha256(json.dumps({k:item.get(k) for k in fields},ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def changes(before: dict, after: dict) -> dict:
    ignored={"first_seen_at","source_url","evidence","verification_status"}
    return {k:{"before":before.get(k),"after":after.get(k)} for k in sorted(set(before)|set(after)) if k not in ignored and before.get(k)!=after.get(k)}


def _venue_key(venue: str | None) -> str:
    """Japanese part of a venue label (before double space / Latin text), without hall suffixes."""
    v = clean(venue or "")
    v = re.split(r"\s[A-Za-z]", v)[0]
    return re.sub(r"[\s\u3000・･()（）\-]|コンサートホール|大ホール|ホール", "", v)


def possible_duplicates(candidates: list[dict]) -> list[list[str]]:
    """Groups of performance_ids from DIFFERENT sources with the same local date and compatible venue labels
    (one normalised label is a prefix of the other, e.g. ミューザ川崎 / ミューザ川崎シンフォニー).

    A review hint only. Presenter pages often co-list the same real concert (e.g. Japan Arts and a hall
    operator); different concerts on one day in one venue are possible, so nothing is merged automatically.
    """
    by_date: dict[str, list[dict]] = {}
    for c in candidates:
        if c.get("local_date") and c.get("venue"):
            by_date.setdefault(c["local_date"], []).append(c)
    groups: list[set[str]] = []
    for items in by_date.values():
        for i, a in enumerate(items):
            ka = _venue_key(a["venue"])
            for b in items[i + 1:]:
                kb = _venue_key(b["venue"])
                if a["source_id"] != b["source_id"] and ka and kb and (ka.startswith(kb) or kb.startswith(ka)):
                    merged = {a["performance_id"], b["performance_id"]}
                    for g in [g for g in groups if g & merged]:
                        merged |= g
                        groups.remove(g)
                    groups.append(merged)
    return sorted(sorted(g) for g in groups)
