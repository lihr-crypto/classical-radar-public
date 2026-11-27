"""Overseas-orchestra tour *leads* from オケミン！ (okemin.com), a personal compilation site (ADR-0007).

These are second-hand facts. They are kept apart from official data on purpose: a lead is never an ``official_confirmed`` concert,
never passes ``confirm_stored``, never reaches discover, the calendar, reminders, monitoring or duplicate review. The site is shown
as a separate shelf labelled "第三方整理，未核实", with a link back and the credit "オケミン！".

Only facts are kept (orchestra, dates, cities, conductor, soloists, venue, programme lines): no page text, no images, no ratings
(the author's opinions). One reading is manual, polite and capped: robots.txt first, 2 s per request, at most ``MAX_REQUESTS``
requests, the okemin host only, no cookies, and a 401/403/429 stops everything.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from . import orchestras
from .network import FetchError, Reader, robots_allowed
from .parsers import JST

SOURCE_ID = "okemin"
SOURCE_NAME = "オケミン！"
HOST = "okemin.com"
LIST_URL = "https://okemin.com/abroad{year}/"
MAX_REQUESTS = 80
ARTICLE_REFRESH_DAYS = 7  # an article read within this many days is not read again unless its list block changed (3 until ADR-0018: the daily cloud run reads gently, about 10 requests a day)

_FIELD = re.compile(r"^(期間|会場|指揮|独奏)[：:]\s*(.*)$")
_DAY = re.compile(r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_MONTH = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月")
_PERF_HEAD = re.compile(r"^(.+?)公演\s*[：:]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_TIME_VENUE = re.compile(r"(\d{1,2})[:：](\d{2})\s*開演\s*[@＠]\s*(.+)")
_AD = re.compile(r"ホテル|探す\s*[＞>]|詳細はこちら|スポンサー|コチラ|＞＞")


def _text(el) -> str:
    return unicodedata.normalize("NFKC", re.sub(r"\s+", " ", el.get_text(" ", strip=True))).strip()


def _lead_id(article_url: str | None, name: str, date_from: str | None, month_hint: str | None) -> str:
    key = article_url or f"{name}|{date_from or month_hint or ''}"
    return "lead-" + hashlib.sha256(f"{SOURCE_ID}|{key}".encode()).hexdigest()[:20]


def parse_period(raw: str, default_year: int | None = None) -> dict:
    """{date_from, date_to, month_hint}: day-level when the page gives days, else only the month. Never invents a day."""
    t = unicodedata.normalize("NFKC", raw or "")
    days, year, prev = [], default_year, None
    for y, m, d in _DAY.findall(t):
        year = int(y) if y else year
        if year is None:
            return {"date_from": None, "date_to": None, "month_hint": None}
        if prev and int(m) < prev and not y:
            year += 1  # a tour crossing New Year
        prev = int(m)
        try:
            days.append(date(year, int(m), int(d)))
        except ValueError:
            return {"date_from": None, "date_to": None, "month_hint": None}
    if days:
        return {"date_from": days[0].isoformat(), "date_to": days[-1].isoformat(), "month_hint": None}
    mo = _MONTH.search(t)
    return {"date_from": None, "date_to": None, "month_hint": f"{int(mo.group(1)):04d}-{int(mo.group(2)):02d}" if mo else None}


def parse_list(html: str, year: int) -> list[dict]:
    """One lead per orchestra block under the page's "オーケストラ" heading (the recital section is skipped: soloists are not orchestras)."""
    soup = BeautifulSoup(html, "html.parser")
    entry = soup.select_one("div.entry-content") or soup
    out = []
    for h2 in entry.find_all("h2"):
        if "オーケストラ" not in _text(h2):
            continue
        for sib in h2.find_next_siblings():
            if sib.name == "h2":
                break
            if sib.name != "h3":
                continue
            name = _text(sib)
            fields, link = {}, None
            for el in sib.find_next_siblings():
                if el.name in ("h2", "h3"):
                    break
                for li in el.select("li"):
                    m = _FIELD.match(_text(li))
                    if m:
                        fields[m.group(1)] = m.group(2).strip()
                a = el.select_one("a.blogcard-wrap")
                if a and not link and a.get("href"):
                    href = urljoin(f"https://{HOST}/", a["href"])
                    if urlsplit(href).hostname == HOST:
                        link = href
            if not name or "期間" not in fields:
                continue
            period = parse_period(fields["期間"], year)
            out.append({"orchestra_name": name, "period_raw": fields["期間"], **period, "cities_raw": fields.get("会場", ""),
                        "conductor": fields.get("指揮", ""), "soloists": fields.get("独奏", ""), "article_url": link, "year": year})
    return out


def parse_article(html: str) -> list[dict]:
    """Performances from a per-orchestra article: "<city>公演：YYYY年M月D日", then "HH:MM開演 @venue", then programme lines.
    A block that does not fit is skipped (never guessed); an article with none yields []."""
    soup = BeautifulSoup(html, "html.parser")
    entry = soup.select_one("div.entry-content") or soup
    out = []
    for head in entry.find_all(["h3", "h4"]):
        m = _PERF_HEAD.match(unicodedata.normalize("NFKC", _text(head)))
        if not m:
            continue
        try:
            day = date(int(m.group(2)), int(m.group(3)), int(m.group(4)))
        except ValueError:
            continue
        lines = []
        for el in head.find_next_siblings():
            if el.name in ("h2", "h3", "h4"):
                break
            for raw in el.get_text("\n").splitlines():
                t = unicodedata.normalize("NFKC", raw).strip()
                if t and not _AD.search(t):
                    lines.append(t)
        tv = next((_TIME_VENUE.search(x) for x in lines if _TIME_VENUE.search(x)), None)
        if tv is None:
            continue
        program = [x for x in lines if ":" in x and not _TIME_VENUE.search(x)][:14]  # "composer: work" lines only; commentary is never copied
        out.append({"local_date": day.isoformat(), "local_time": f"{int(tv.group(1)):02d}:{tv.group(2)}", "venue": tv.group(3).strip(), "city": m.group(1).strip(), "program": program})
    return out


def orchestra_key(name: str) -> str | None:
    found = orchestras.detect([name])
    return found[0] if found else None


# ---- store -------------------------------------------------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upsert(conn: sqlite3.Connection, lead: dict, performances: list[dict] | None, now: str) -> str:
    """Insert or refresh one lead. ``last_changed_at`` moves only when a fact changed. Returns "new", "changed" or "same"."""
    lid = _lead_id(lead.get("article_url"), lead["orchestra_name"], lead.get("date_from"), lead.get("month_hint"))
    facts = {k: lead.get(k) for k in ("orchestra_name", "period_raw", "date_from", "date_to", "month_hint", "cities_raw", "conductor", "soloists", "article_url")}
    perf_json = json.dumps(performances, ensure_ascii=False, sort_keys=True) if performances is not None else None
    row = conn.execute("SELECT * FROM tour_lead WHERE id=?", (lid,)).fetchone()
    key = orchestra_key(lead["orchestra_name"])
    if row is None:
        conn.execute("INSERT INTO tour_lead (id, source_id, year, orchestra_key, orchestra_name, period_raw, date_from, date_to, month_hint, cities_raw, conductor, soloists, "
                     "article_url, performances, first_seen_at, last_seen_at, last_changed_at, article_read_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (lid, SOURCE_ID, lead.get("year"), key, facts["orchestra_name"], facts["period_raw"], facts["date_from"], facts["date_to"], facts["month_hint"], facts["cities_raw"],
                      facts["conductor"], facts["soloists"], facts["article_url"], perf_json or "[]", now, now, now, now if performances is not None else None))
        return "new"
    changed = any(row[k] != facts[k] for k in facts) or (perf_json is not None and perf_json != row["performances"])
    conn.execute("UPDATE tour_lead SET year=?, orchestra_key=?, orchestra_name=?, period_raw=?, date_from=?, date_to=?, month_hint=?, cities_raw=?, conductor=?, soloists=?, article_url=?, "
                 "performances=COALESCE(?, performances), last_seen_at=?, last_changed_at=?, article_read_at=COALESCE(?, article_read_at) WHERE id=?",
                 (lead.get("year"), key, facts["orchestra_name"], facts["period_raw"], facts["date_from"], facts["date_to"], facts["month_hint"], facts["cities_raw"], facts["conductor"], facts["soloists"],
                  facts["article_url"], perf_json, now, now if changed else row["last_changed_at"], now if performances is not None else None, lid))
    return "changed" if changed else "same"


def sync_leads(conn: sqlite3.Connection, reader: Reader, years: list[int], *, now: str | None = None, log=lambda m: None) -> dict:
    """One polite reading (by hand, or by the daily cloud job since ADR-0018). Stops cleanly (reporting what it did) on any access restriction.

    Phase 1 per year: read the list page and record every block (so "seen" never depends on the articles), then mark that year page as read.
    Phase 2: read the articles that need it. A reading that stops early (a refusal, the request cap) marks nothing as dropped off."""
    now = now or _now()
    stats = {"requests": 0, "new": 0, "changed": 0, "same": 0, "articles_read": 0, "articles_skipped_recent": 0, "articles_skipped_robots": 0, "list_only": 0, "stopped": None,
             "not_published": []}
    robots: dict = {}

    def get(url: str):
        if stats["requests"] >= MAX_REQUESTS:
            raise FetchError("request cap reached")
        stats["requests"] += 1
        return reader.get(url, HOST)

    def allowed(url: str) -> bool:  # robots.txt is checked for EVERY url, not only the first
        return robots_allowed(robots["text"], robots["status"], url)

    try:
        text, meta = get(f"https://{HOST}/robots.txt")
        robots.update(text=text, status=meta["status"])
        pending: list[tuple[dict, str, str]] = []
        for year in years:
            list_url = LIST_URL.format(year=year)
            if not allowed(list_url):
                stats["stopped"] = f"robots.txt does not allow reading {urlsplit(list_url).path}"
                return stats
            html, meta = get(list_url)
            if meta["status"] == 404 and year != years[0]:
                # a later year's page that okemin.com has not written YET (every January, when "next year" moves on): skip it, read the rest. A page that WAS read
                # before and now answers 404 has been pulled or moved: that is a stop, or its old leads would stay on show with no end (ADR-0018)
                if conn.execute("SELECT 1 FROM lead_page_read WHERE source_id=? AND year=?", (SOURCE_ID, year)).fetchone():
                    stats["stopped"] = f"the {year} page was read before and now answers 404: not recorded as read"
                    conn.commit()
                    return stats
                stats["not_published"].append(year)
                log(f"{year}: page not published yet")
                continue
            blocks = parse_list(html, year)
            if not blocks:  # a layout change must not look like "every lead has dropped off"
                stats["stopped"] = f"the {year} page parsed to no orchestra blocks: not recorded as read"
                conn.commit()
                return stats
            for lead in blocks:
                row = conn.execute("SELECT * FROM tour_lead WHERE id=?", (_lead_id(lead["article_url"], lead["orchestra_name"], lead["date_from"], lead["month_hint"]),)).fetchone()
                fresh = row is not None and row["article_read_at"] and row["article_read_at"] >= (datetime.fromisoformat(now) - timedelta(days=ARTICLE_REFRESH_DAYS)).isoformat()
                list_same = row is not None and all(row[k] == lead.get(k) for k in ("period_raw", "cities_raw", "conductor", "soloists", "article_url"))
                outcome = upsert(conn, lead, None, now)
                stats[outcome] += 1
                if not lead["article_url"]:
                    stats["list_only"] += 1
                elif fresh and list_same:
                    stats["articles_skipped_recent"] += 1
                else:
                    pending.append((lead, lead["article_url"], outcome))
            conn.execute("INSERT INTO lead_page_read (source_id, year, read_at) VALUES (?,?,?) ON CONFLICT(source_id, year) DO UPDATE SET read_at=excluded.read_at", (SOURCE_ID, year, now))
            conn.commit()
            log(f"{year}: {len(blocks)} orchestra blocks")
        for lead, url, first in pending:
            if not allowed(url):
                stats["articles_skipped_robots"] += 1
                continue
            art, _ = get(url)
            performances = parse_article(art)
            stats["articles_read"] += 1
            if not performances:
                stats["list_only"] += 1
            if upsert(conn, lead, performances, now) == "changed" and first == "same":  # only the article differed: count the lead as changed, not as same
                stats["same"] -= 1
                stats["changed"] += 1
            conn.commit()
    except FetchError as exc:
        conn.commit()
        stats["stopped"] = str(exc)
    return stats


# ---- reading ----------------------------------------------------------------------------------------------------------------

def _row_to_lead(r: sqlite3.Row) -> dict:
    key = r["orchestra_key"]
    o = orchestras.ORCHESTRAS.get(key) if key else None
    return {"lead_id": r["id"], "orchestra": {"key": key, "display": o["display"], "origin": o["origin"], "names": o.get("names", "")} if o else None,
            "orchestra_name": r["orchestra_name"], "period_raw": r["period_raw"], "date_from": r["date_from"], "date_to": r["date_to"], "month_hint": r["month_hint"],
            "cities": [c for c in re.split(r"[、,，\s]+", r["cities_raw"] or "") if c and c != "他"], "more_cities": "他" in (r["cities_raw"] or ""),
            "conductor": r["conductor"] or None, "soloists": r["soloists"] or None, "article_url": r["article_url"], "performances": json.loads(r["performances"] or "[]"),
            "last_seen_at": r["last_seen_at"], "last_changed_at": r["last_changed_at"]}


def all_leads(conn: sqlite3.Connection) -> list[dict]:
    """Leads still on their year page: one that the latest COMPLETE reading of its year page did not see has dropped off (and is hidden).
    A year page never read to the end (or a lead without a year) is not judged."""
    q = ("SELECT l.* FROM tour_lead l LEFT JOIN lead_page_read p ON p.source_id=l.source_id AND p.year=l.year WHERE p.read_at IS NULL OR l.last_seen_at >= p.read_at "
         "ORDER BY COALESCE(l.date_from, l.month_hint || '-99'), l.orchestra_name")
    return [_row_to_lead(r) for r in conn.execute(q)]


def is_covered(lead: dict, concerts: list[dict]) -> str | None:
    """The id of an official concert that already covers this lead: same orchestra key and a performance within the lead's dates +-1 day
    (for a month-only lead: anywhere in that month). ``concerts`` = [{id, orchestras: [keys], dates: [iso]}]."""
    key = (lead.get("orchestra") or {}).get("key")
    if not key:
        return None
    if lead.get("date_from"):
        lo, hi = date.fromisoformat(lead["date_from"]) - timedelta(days=1), date.fromisoformat(lead["date_to"] or lead["date_from"]) + timedelta(days=1)
        inside = lambda d: lo <= date.fromisoformat(d) <= hi  # noqa: E731
    elif lead.get("month_hint"):
        inside = lambda d: d.startswith(lead["month_hint"])  # noqa: E731
    else:
        return None
    return next((c["id"] for c in concerts if key in c["orchestras"] and any(inside(d) for d in c["dates"])), None)


def visible(leads: list[dict], concerts: list[dict], today: str) -> dict:
    """Leads still ahead of ``today``, each with ``covered_by`` (an official concert id or None), as the pages show them."""
    out = []
    for lead in leads:
        end = lead["date_to"] or lead["date_from"]
        if end and end < today:
            continue
        if not end and (not lead["month_hint"] or lead["month_hint"] < today[:7]):  # no day and no month: nothing to show, nothing to ever expire
            continue
        out.append({**lead, "covered_by": is_covered(lead, concerts)})
    return {"items": out, "source": {"name": SOURCE_NAME, "url": f"https://{HOST}/"}, "as_of": today,
            "notice": "オケミン！という第三方サイトの整理による来日情報です。官方には未核实：日程、曲目、チケットは主催者の公式サイトで確認してください。"}


def concerts_from_db(conn: sqlite3.Connection) -> list[dict]:
    """Official concerts as [{id, orchestras: [keys], dates: [iso]}], for ``is_covered``."""
    from .discover import orchestra_map  # local import: discover imports a lot
    omap = orchestra_map(conn)
    out = []
    for c in conn.execute("SELECT id FROM concert WHERE verification_status='official_confirmed'"):
        dates = [r[0] for r in conn.execute("SELECT local_date FROM performance WHERE concert_id=? AND confirmation_status='official_confirmed' AND local_date IS NOT NULL", (c["id"],))]
        out.append({"id": c["id"], "orchestras": omap.get(c["id"], []), "dates": dates})
    return out


def page_for_db(conn: sqlite3.Connection, today: str) -> dict:
    return visible(all_leads(conn), concerts_from_db(conn), today)


def export_file(conn: sqlite3.Connection, today: str) -> dict:
    """The file the static site publishes (site-data/leads.json): facts, a credit and the reading time; no coverage flags (the build computes them
    against the concerts it publishes)."""
    leads = all_leads(conn)
    for lead in leads:
        lead.pop("last_seen_at", None)
    read_at = conn.execute("SELECT MAX(read_at) FROM lead_page_read").fetchone()[0]
    return {"source": {"name": SOURCE_NAME, "url": f"https://{HOST}/"}, "as_of": today, "read_at": read_at, "leads": leads}


def validate_file(data: dict) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("leads"), list):
        raise ValueError("leads file: expected {leads: [...]}")
    for lead in data["leads"]:
        if not isinstance(lead, dict) or not lead.get("lead_id", "").startswith("lead-") or not lead.get("orchestra_name"):
            raise ValueError("leads file: every lead needs lead_id (lead-…) and orchestra_name")
