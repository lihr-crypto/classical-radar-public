"""GET /api/v1/discover semantics (03_CONTRACTS 3.5) over the SQLite store, plus the coverage read model.

Only official_confirmed concerts/performances in Japan, not cancelled, inside the window. Unconfirmed candidates, announced-but-undated
tours and unverified leads never appear here. Window end is exclusive: as_of(JST date) + N *calendar* months.
"""
from __future__ import annotations

import calendar
import sqlite3
from datetime import date, datetime, timezone

from . import duplicates
from .parsers import JST
from .venues import KANTO
from .images import image_for
from .orchestras import ORCHESTRAS, concert_orchestras
from .works import composer_key as _composer_key, n as _norm

TICKET_RANK = {"open": 4, "announced": 3, "closed": 2, "unknown": 1}
CATEGORIES = {"all", "domestic_orchestra", "overseas_orchestra_visit", "piano_recital", "other"}


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


DIMENSIONS = ("orchestra", "composer", "work", "conductor", "performer", "venue")
MAX_FILTER_VALUES, MAX_FILTER_LEN = 10, 100


def _clean_filters(filters: dict | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for dim, vals in (filters or {}).items():
        if dim not in DIMENSIONS:
            raise ValueError(f"unsupported filter: {dim}")
        vals = [v.strip() for v in (vals or []) if v and v.strip()]
        if len(vals) > MAX_FILTER_VALUES or any(len(v) > MAX_FILTER_LEN for v in vals):
            raise ValueError(f"too many or too long values for {dim}")
        if vals:
            out[dim] = vals
    return out


def orchestra_map(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """concert_id -> orchestra keys (source orchestra for the seven sites, plus known names in title/performers)."""
    artists: dict[str, list[str]] = {}
    for r in conn.execute("SELECT concert_id, name_display FROM concert_artist"):
        artists.setdefault(r[0], []).append(r[1])
    return {r["id"]: concert_orchestras(r["identity_key"].split("|", 1)[0], r["title_ja"], artists.get(r["id"], []))
            for r in conn.execute("SELECT id, identity_key, title_ja FROM concert")}


def _orchestra_match(keys: list[str], value: str) -> bool:
    """value: an orchestra key, 'overseas' / 'seven' for a whole group, or text matched against the displayed names."""
    if value in ("overseas", "seven"):
        return any(ORCHESTRAS[k]["origin"] == value for k in keys)
    if value in ORCHESTRAS:
        return value in keys
    v = _norm(value)
    return bool(v) and any(v in _norm(ORCHESTRAS[k]["display"]) for k in keys)


def _concert_ids(conn: sqlite3.Connection, filters: dict[str, list[str]]) -> set[str] | None:
    """Concert ids matching every non-venue dimension (values within one dimension are OR). None = no such filter.

    composer: key equality (when the value is a known alias) or substring of the displayed composer; work: ``composer:kind`` key equality
    or substring of the work/raw text (full-text fallback, no world catalogue); conductor/performer: substring of the displayed name,
    role-restricted for conductor. Matching only ever sees stored, official-confirmed-or-not rows - visibility is decided by the caller.
    """
    ids: set[str] | None = None

    def narrow(found: set[str]):
        nonlocal ids
        ids = found if ids is None else ids & found

    if "orchestra" in filters:
        narrow({cid for cid, keys in orchestra_map(conn).items() if any(_orchestra_match(keys, v) for v in filters["orchestra"])})
    if "composer" in filters:
        found = set()
        wanted = [(_composer_key(v), _norm(v)) for v in filters["composer"]]
        for r in conn.execute("SELECT concert_id, composer_key, composer_display FROM program_item"):
            disp = _norm(r["composer_display"] or "")
            if any((k and r["composer_key"] == k) or (nv and nv in disp) for k, nv in wanted):
                found.add(r["concert_id"])
        narrow(found)
    if "work" in filters:
        found = set()
        for r in conn.execute("SELECT concert_id, work_key, work_display, raw_text FROM program_item"):
            text = _norm((r["work_display"] or "") + " " + (r["raw_text"] or ""))
            if any((":" in v and (r["work_key"] or "") == v.lower()) or (":" not in v and _norm(v) and _norm(v) in text) for v in filters["work"]):
                found.add(r["concert_id"])
        narrow(found)
    for dim, roles in (("conductor", ("conductor",)), ("performer", None)):
        if dim in filters:
            found = set()
            for r in conn.execute("SELECT concert_id, name_display, role FROM concert_artist"):
                if (roles is None or r["role"] in roles) and any(_norm(v) in _norm(r["name_display"]) for v in filters[dim]):
                    found.add(r["concert_id"])
            narrow(found)
    return ids


def _summaries(conn: sqlite3.Connection, concert_ids: list[str]) -> dict[str, dict]:
    omap = orchestra_map(conn) if concert_ids else {}
    out = {c: {"orchestras": [{"key": k, "display": ORCHESTRAS[k]["display"], "origin": ORCHESTRAS[k]["origin"], "names": ORCHESTRAS[k]["names"]} for k in omap.get(c, [])],
               "composers": [], "conductors": [], "soloists": [], "pieces": []} for c in concert_ids}
    for cid in concert_ids:
        for r in conn.execute("SELECT composer_display, composer_key, work_display, work_key, raw_text FROM program_item WHERE concert_id=? ORDER BY position", (cid,)):
            if r["composer_display"] and r["composer_display"] not in out[cid]["composers"]:
                out[cid]["composers"].append(r["composer_display"])
            # every programme row, uncapped: the browse pages (ADR-0010) group concerts by composer and by piece in the browser
            out[cid]["pieces"].append({"composer": r["composer_display"] or "", "composer_key": r["composer_key"], "work": r["work_display"] or r["raw_text"] or "", "work_key": r["work_key"]})
        for r in conn.execute("SELECT name_display, role FROM concert_artist WHERE concert_id=?", (cid,)):
            if r["role"] == "conductor":
                out[cid]["conductors"].append(r["name_display"])
            elif r["role"] in ("recital_headliner", "concerto_soloist"):
                out[cid]["soloists"].append(r["name_display"])
        out[cid]["composers"] = out[cid]["composers"][:6]
        out[cid]["image"] = _card_image(conn, cid, out[cid])
    return out


def _with_src(img: dict | None, name: str) -> dict | None:
    return {**img, "src": f"/media/{img['file']}", "subject": name} if img else None


def _card_image(conn, cid: str, summ: dict) -> dict | None:
    """First freely licensed photo among: recital headliner, overseas orchestra, conductor, soloists, other orchestras."""
    heads = [r[0] for r in conn.execute("SELECT name_display FROM concert_artist WHERE concert_id=? AND role='recital_headliner'", (cid,))]
    orch = [o["display"] for o in summ["orchestras"]]
    overseas = [o["display"] for o in summ["orchestras"] if o["origin"] == "overseas"]
    for name in heads + overseas + summ["conductors"] + summ["soloists"] + orch:
        img = image_for(conn, name)
        if img:
            return _with_src(img, name)
    return None


def _filter_rows(conn, rows, flt):
    ids = _concert_ids(conn, flt)
    if ids is not None:
        rows = [r for r in rows if r["cid"] in ids]
    if "venue" in flt:  # performance-level: only the matching performances are listed (3.5: expand the matching actual performances)
        wanted = [_norm(v) for v in flt["venue"]]
        rows = [r for r in rows if any(w in _norm(r["venue_name"]) for w in wanted)]
    return rows


def _absorb(rows: list, merged: dict[str, str], cid: str = "cid") -> tuple[list, dict[str, list[str]]]:
    """ADR-0006, performance by performance: a row of a hidden card is dropped only when its keeper has, IN THE SAME ROW SET, a row on
    that day at a compatible venue. Anything else stays listed, so a filter or a date range can never make a date disappear.
    Returns (rows kept, {keeper concert id: [hidden concert ids it absorbed]})."""
    if not merged:
        return rows, {}
    by: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        by.setdefault(r[cid], []).append((r["local_date"], r["venue_name"]))
    kept, absorbed = [], {}
    for r in rows:
        keeper = merged.get(r[cid])
        if keeper and any(d == r["local_date"] and duplicates.venue_compatible(v, r["venue_name"]) for d, v in by.get(keeper, [])):
            if r[cid] not in absorbed.setdefault(keeper, []):
                absorbed[keeper].append(r[cid])
            continue
        kept.append(r)
    return kept, absorbed


def _window_rows(conn: sqlite3.Connection, as_of: datetime, category: str, months: int) -> list:
    as_of = as_of.astimezone(timezone.utc)
    today = as_of.astimezone(JST).date()
    end = add_months(today, months)
    return conn.execute(
        """SELECT c.id AS cid, c.category, c.title_ja, c.official_announcement_date, c.first_verified_at, c.identity_key, c.organization_id,
                  p.id AS pid, p.starts_at, p.local_date, p.date_precision, p.prefecture_code, p.venue_name, p.last_seen_at
           FROM concert c JOIN performance p ON p.concert_id = c.id
           WHERE c.verification_status='official_confirmed' AND p.confirmation_status='official_confirmed' AND p.country_code='JP'
             AND p.status NOT IN ('cancelled','completed') AND (:cat='all' OR c.category=:cat)
             AND p.local_date < :end
             AND ((p.date_precision='exact_time' AND p.starts_at >= :as_of) OR (p.date_precision='date_only' AND p.local_date >= :today))""",
        {"cat": category, "end": end.isoformat(), "as_of": as_of.isoformat(), "today": today.isoformat()}).fetchall()


def facets(conn: sqlite3.Connection, *, as_of: datetime, category: str = "all", months: int = 12, filters: dict | None = None) -> dict:
    """GET /discover/facets: counts of matching concerts per category / prefecture / venue (same window rules as discover)."""
    if category not in CATEGORIES or months not in (12, 24):
        raise ValueError("unsupported discover parameters")
    flt = _clean_filters(filters)
    rows = _filter_rows(conn, _window_rows(conn, as_of, category, months), flt)
    cids = sorted({r["cid"] for r in rows})
    def count(key):
        seen: dict[str, set] = {}
        for r in rows:
            seen.setdefault(r[key] or "unknown", set()).add(r["cid"])
        return sorted(({"value": k, "concerts": len(v)} for k, v in seen.items()), key=lambda x: (-x["concerts"], x["value"]))
    comp: dict[str, set] = {}
    cond: dict[str, set] = {}
    perf: dict[str, set] = {}
    for cid in cids:
        for r in conn.execute("SELECT composer_display, composer_key FROM program_item WHERE concert_id=?", (cid,)):
            if r["composer_display"]:
                comp.setdefault(r["composer_display"], set()).add(cid)
        for r in conn.execute("SELECT name_display, role FROM concert_artist WHERE concert_id=?", (cid,)):
            perf.setdefault(r["name_display"], set()).add(cid)
            if r["role"] == "conductor":
                cond.setdefault(r["name_display"], set()).add(cid)
    omap = orchestra_map(conn) if cids else {}
    orch: dict[str, set] = {}
    for cid in cids:
        for k in omap.get(cid, []):
            orch.setdefault(k, set()).add(cid)
    orchestra_facet = sorted(({"value": k, "label": ORCHESTRAS[k]["display"], "origin": ORCHESTRAS[k]["origin"], "concerts": len(v)} for k, v in orch.items()),
                             key=lambda x: (-x["concerts"], x["value"]))
    top = lambda d: sorted(({"value": k, "concerts": len(v)} for k, v in d.items()), key=lambda x: (-x["concerts"], x["value"]))[:100]  # noqa: E731
    return {"category": count("category"), "prefecture_code": count("prefecture_code"), "venue_name": count("venue_name"),
            "orchestra": orchestra_facet,
            "orchestra_groups": {g: sum(1 for cid in cids if any(ORCHESTRAS[k]["origin"] == g for k in omap.get(cid, []))) for g in ("seven", "overseas")},
            "composer": top(comp), "conductor": top(cond), "performer": top(perf),
            "total_concerts": len(cids), "filters": {"category": category, "months": months, **flt}}


def _reminder_of(conn: sqlite3.Connection, user_id: str | None, ticket_phase_id: str) -> dict | None:
    """The user's sale_start reminder on this phase (the only milestone that can be switched on today), or None."""
    r = conn.execute("SELECT milestone, offset_minutes, enabled FROM reminder_subscription WHERE user_id=? AND ticket_phase_id=? AND milestone='sale_start'",
                     (user_id, ticket_phase_id)).fetchone() if user_id else None
    return {"milestone": r["milestone"], "offset_minutes": r["offset_minutes"], "enabled": bool(r["enabled"])} if r else None


def concert_detail(conn: sqlite3.Connection, concert_id: str, user_id: str | None = None, now: datetime | None = None) -> dict | None:
    c = conn.execute("SELECT * FROM concert WHERE id=? AND verification_status='official_confirmed'", (concert_id,)).fetchone()
    if c is None:
        return None
    merged = duplicates.merged_map(conn, (now or datetime.now(timezone.utc)).astimezone(JST).date().isoformat())
    perfs = []
    for p in conn.execute("SELECT * FROM performance WHERE concert_id=? AND confirmation_status='official_confirmed' ORDER BY local_date, starts_at", (concert_id,)):
        phases = [{**dict(t), "reminder": _reminder_of(conn, user_id, t["id"])} for t in conn.execute("SELECT * FROM ticket_phase WHERE performance_id=? ORDER BY starts_at", (p["id"],))]
        state = conn.execute("SELECT status, notes FROM user_performance_state WHERE user_id=? AND performance_id=?", (user_id, p["id"])).fetchone() if user_id else None
        perfs.append({**{k: p[k] for k in ("id", "concert_id", "starts_at", "local_date", "date_precision", "country_code", "prefecture_code", "venue_name", "confirmation_status", "status")},
                      "ticket_phases": phases, "user_state": dict(state) if state else None})
    docs = [dict(d) for d in conn.execute("SELECT url, kind, first_seen_at, last_verified_at, policy_status FROM source_document WHERE source_id=? AND url IN (?, ?)",
                                          (c["identity_key"].split("|", 1)[0], c["identity_key"].split("|", 1)[1], c["identity_key"].split("|", 1)[1] + "/"))]
    return {"concert": {k: c[k] for k in ("id", "category", "title_ja", "organization_id", "verification_status", "official_announcement_date", "first_verified_at", "last_material_change_at")},
            "performances": perfs, "program_items": [dict(x) for x in conn.execute("SELECT position, raw_text, composer_display, composer_key, work_display, work_key FROM program_item WHERE concert_id=? ORDER BY position", (concert_id,))],
            "concert_artists": [{**dict(x), "image": _with_src(image_for(conn, x["name_display"]), x["name_display"])}
                                for x in conn.execute("SELECT name_display, role FROM concert_artist WHERE concert_id=? ORDER BY rowid", (concert_id,))],
            "image": _summaries(conn, [concert_id])[concert_id]["image"],
            "source_documents": docs, "source_url": c["identity_key"].split("|", 1)[1],
            # ADR-0006: the cards a reviewer merged under this one / the card this one is listed under. Each keeps its own page and ticket phases.
            "other_sources": sorted((duplicates.source_card(conn, h) for h, k in merged.items() if k == concert_id), key=lambda s: (s["source_id"], s["source_url"])),
            "merged_into": duplicates.source_card(conn, merged[concert_id]) if concert_id in merged else None,
            "user_pickup": bool(user_id and conn.execute("SELECT 1 FROM user_pickup WHERE user_id=? AND concert_id=?", (user_id, concert_id)).fetchone()),
            "user_plan": bool(user_id and conn.execute("SELECT 1 FROM user_plan WHERE user_id=? AND concert_id=?", (user_id, concert_id)).fetchone())}


def discover(conn: sqlite3.Connection, *, as_of: datetime, category: str = "all", months: int = 12, region_mode: str = "kanto_first",
             sort: str = "announcement_desc", page: int = 1, limit: int = 20, user_id: str | None = None, filters: dict | None = None) -> dict:
    if category not in CATEGORIES or months not in (12, 24) or region_mode not in ("kanto_first", "nationwide") or sort != "announcement_desc" or page < 1 or not 1 <= limit <= 100:
        raise ValueError("unsupported discover parameters")
    as_of = as_of.astimezone(timezone.utc)
    today = as_of.astimezone(JST).date()
    end = add_months(today, months)
    flt = _clean_filters(filters)
    rows, absorbed = _absorb(_filter_rows(conn, _window_rows(conn, as_of, category, months), flt), duplicates.merged_map(conn, today.isoformat()))
    concerts: dict[str, dict] = {}
    for r in rows:
        c = concerts.setdefault(r["cid"], {"concert_id": r["cid"], "category": r["category"], "title_ja": r["title_ja"], "organization_id": r["organization_id"], "performances": [],
                                           "_official": r["official_announcement_date"], "_fv": r["first_verified_at"],
                                           "source_url": r["identity_key"].split("|", 1)[1]})
        c["performances"].append({"performance_id": r["pid"], "local_date": r["local_date"], "starts_at": r["starts_at"], "date_precision": r["date_precision"],
                                  "prefecture_code": r["prefecture_code"], "venue_name": r["venue_name"], "last_seen_at": r["last_seen_at"]})
    pickups = set()
    if user_id:
        pickups = {x[0] for x in conn.execute("SELECT concert_id FROM user_pickup WHERE user_id=?", (user_id,))}
    items = []
    for c in concerts.values():
        c["performances"].sort(key=lambda p: (p["local_date"], p["starts_at"] or ""))
        fv_date = datetime.fromisoformat(c["_fv"]).astimezone(JST).date().isoformat()
        official = c["_official"] is not None
        sort_date = c["_official"] if official else fv_date
        phases = conn.execute("SELECT current_status FROM ticket_phase WHERE performance_id IN (%s)" % ",".join("?" * len(c["performances"])),
                              [p["performance_id"] for p in c["performances"]]).fetchall()
        ticket = max((x[0] for x in phases), key=lambda s: TICKET_RANK.get(s, 0), default="not_announced")
        kanto = any(p["prefecture_code"] in KANTO for p in c["performances"])
        items.append({
            "concert_id": c["concert_id"], "category": c["category"], "title_ja": c["title_ja"], "organization_id": c["organization_id"], "announcement_sort_date": sort_date,
            "announcement_basis": "official" if official else "first_verified_fallback", "announcement_label": "官方公布" if official else "首次收录",
            "region_group": ("kanto" if kanto else "rest_of_japan") if region_mode == "kanto_first" else None,
            "performance_ids": [p["performance_id"] for p in c["performances"]], "performances": c["performances"], "ticket_status": ticket,
            "source_url": c["source_url"], "last_verified_at": max(p["last_seen_at"] or "" for p in c["performances"]) or c["_fv"], "user_pickup": c["concert_id"] in pickups,
            "_fv": c["_fv"],
        })
    # 3.5 rule 5: bucket (kanto first) -> announcement date DESC -> first_verified_at DESC -> nearest performance ASC -> concert_id ASC.
    # Stable multi-pass sort so each DESC key can be applied independently.
    items.sort(key=lambda i: i["concert_id"])
    items.sort(key=lambda i: i["performances"][0]["starts_at"] or i["performances"][0]["local_date"])
    items.sort(key=lambda i: i["_fv"], reverse=True)
    items.sort(key=lambda i: i["announcement_sort_date"], reverse=True)
    if region_mode == "kanto_first":
        items.sort(key=lambda i: i["region_group"] != "kanto")
    total = len(items)
    window = items[(page - 1) * limit: page * limit]
    summ = _summaries(conn, [i["concert_id"] for i in window])
    for i in window:
        i.pop("_fv")
        i.update(summ[i["concert_id"]])
        i["other_sources"] = sorted(filter(None, (duplicates.source_card(conn, h) for h in absorbed.get(i["concert_id"], []))), key=lambda s: (s["source_id"], s["source_url"]))
    groups = [{"key": "kanto", "title": "首都圈"}, {"key": "rest_of_japan", "title": "日本其他地区"}] if region_mode == "kanto_first" else []
    return {"filters": {"category": category, "months": months, "region_mode": region_mode, "sort": sort, "view": "concerts", "page": page, "limit": limit, **flt},
            "as_of": as_of.isoformat(), "window": {"from": today.isoformat(), "to_exclusive": end.isoformat()}, "total": total, "groups": groups, "items": window,
            "coverage_notice": "仅显示已收录且官方确认的公演；未收录不代表没有公演，详见 /discover/coverage。"}


def coverage(conn: sqlite3.Connection) -> dict:
    """Read model for GET /discover/coverage: what is stored per source, never a national coverage percentage."""
    out = []
    for s in conn.execute("SELECT DISTINCT substr(identity_key,1,instr(identity_key,'|')-1) AS source_id FROM concert ORDER BY 1"):
        sid = s["source_id"]
        r = conn.execute(
            """SELECT COUNT(DISTINCT c.id) AS concerts, SUM(c.verification_status='official_confirmed') AS confirmed_rows
               FROM concert c WHERE c.identity_key LIKE ?""", (sid + "|%",)).fetchone()
        perfs = conn.execute("SELECT COUNT(*) FROM performance p JOIN concert c ON c.id=p.concert_id WHERE c.identity_key LIKE ?", (sid + "|%",)).fetchone()[0]
        last = conn.execute("SELECT MAX(ended_at) FROM ingestion_run WHERE source_id=? AND status='succeeded'", (sid,)).fetchone()[0]
        fail = conn.execute("SELECT status, error_summary FROM ingestion_run WHERE source_id=? ORDER BY started_at DESC LIMIT 1", (sid,)).fetchone()
        out.append({"source_id": sid, "concerts_stored": r["concerts"], "concerts_official_confirmed": r["confirmed_rows"] or 0, "performances_stored": perfs,
                    "last_success_at": last, "latest_run_status": fail["status"] if fail else None, "latest_error": fail["error_summary"] if fail else None})
    return {"sources": out, "notice": "仅为已入库记录的数量；没有独立分母，因此不给出全国/全期间的覆盖率百分比。"}


def calendar_range(conn: sqlite3.Connection, start: date, end: date, now: datetime | None = None) -> dict:
    """Confirmed performances and sale-start milestones with local dates in [start, end]. Date-only sale starts stay all-day (no clock time)."""
    if end < start or (end - start).days > 62:
        raise ValueError("range must be 0..62 days")
    perfs = conn.execute(
        """SELECT p.id, p.concert_id, c.title_ja, c.category, c.organization_id, p.local_date, p.starts_at, p.date_precision, p.venue_name, p.prefecture_code, p.status
           FROM performance p JOIN concert c ON c.id=p.concert_id
           WHERE c.verification_status='official_confirmed' AND p.confirmation_status='official_confirmed' AND p.status!='cancelled'
             AND p.local_date BETWEEN ? AND ? ORDER BY p.local_date, p.starts_at, p.id""", (start.isoformat(), end.isoformat())).fetchall()
    perfs, _ = _absorb(perfs, duplicates.merged_map(conn, (now or datetime.now(timezone.utc)).astimezone(JST).date().isoformat()), "concert_id")
    omap = orchestra_map(conn)  # each row says which orchestras play, so the page can filter by orchestra without another request

    def orch(cid: str) -> list[dict]:
        return [{"key": k, "display": ORCHESTRAS[k]["display"], "origin": ORCHESTRAS[k]["origin"], "names": ORCHESTRAS[k]["names"]} for k in omap.get(cid, [])]
    sales = []
    for t in conn.execute(
            """SELECT t.id, t.performance_id, t.phase_type, t.eligibility, t.starts_at, t.start_precision, t.current_status, c.id AS concert_id, c.title_ja, c.category, c.organization_id
               FROM ticket_phase t JOIN performance p ON p.id=t.performance_id JOIN concert c ON c.id=p.concert_id
               WHERE c.verification_status='official_confirmed' AND p.confirmation_status='official_confirmed' AND t.starts_at IS NOT NULL"""):
        local = datetime.fromisoformat(t["starts_at"]).astimezone(JST)
        if start <= local.date() <= end:
            sales.append({**dict(t), "local_date": local.date().isoformat(), "local_time": local.strftime("%H:%M") if t["start_precision"] == "exact_time" else None, "orchestras": orch(t["concert_id"])})
    sales.sort(key=lambda s: (s["local_date"], s["local_time"] or "", s["id"]))
    return {"from": start.isoformat(), "to": end.isoformat(), "performances": [{**dict(r), "orchestras": orch(r["concert_id"])} for r in perfs], "sales": sales}
