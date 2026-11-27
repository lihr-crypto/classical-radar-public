"""Idempotent ingestion of parser candidates into the contract tables (ADR-0001).

Guarantees (all covered by tests/test_ingest.py):
* re-ingesting identical input creates no rows and no change_event;
* a concert is matched by (source, canonical URL); a performance by (date, time, venue);
* a changed date/venue is treated as the SAME performance only when exactly one stored and one incoming performance
  of that concert are unmatched (evidence-based reschedule, change_event written); anything else is never merged;
* a source failure rolls back that source's writes only and is recorded in ingestion_run (T11);
* nothing becomes official_confirmed without an explicit Confirmation (the human step).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from . import db, duplicates, reminders
from .contract import Performance, TicketPhase
from .discover import _summaries
from .parsers import JST, canonical, clean
from .orchestras import suggest_category
from .venues import prefecture_code

_PRECISION = {"minute": "exact_time", "day": "date_only", "unknown": "unknown"}


@dataclass
class Confirmation:
    """The human decision that promotes candidates to official_confirmed."""
    at: datetime
    category: str | None = None  # reviewer may set overseas_orchestra_visit etc.
    prefecture_overrides: dict[str, str] = field(default_factory=dict)  # poc performance_id -> JIS code
    note: str | None = None


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _vkey(v: str | None) -> str:
    return clean(v or "")


def _upsert_document(conn, source_id, url, kind, observed, policy, content_hash=None) -> str:
    row = conn.execute("SELECT id FROM source_document WHERE source_id=? AND url=?", (source_id, url)).fetchone()
    if row:
        conn.execute("UPDATE source_document SET last_verified_at=?, content_hash=COALESCE(?, content_hash) WHERE id=?", (iso(observed), content_hash, row["id"]))
        return row["id"]
    doc_id = db.new_id()
    conn.execute("INSERT INTO source_document (id,source_id,url,kind,first_seen_at,last_verified_at,content_hash,policy_status) VALUES (?,?,?,?,?,?,?,?)",
                 (doc_id, source_id, url, kind, iso(observed), iso(observed), content_hash, policy))
    return doc_id


def _claim(conn, doc_id, entity_type, entity_id, field_path, raw, normalized, observed, status="needs_review") -> str:
    cid = db.new_id()
    conn.execute("INSERT INTO source_claim VALUES (?,?,?,?,?,?,?,?,?)", (cid, doc_id, entity_type, entity_id, field_path, raw, normalized, iso(observed), status))
    return cid


def _event(conn, entity_type, entity_id, field_path, before, after, claim_id, observed, note=None):
    conn.execute("INSERT INTO change_event VALUES (?,?,?,?,?,?,?,?,?)",
                 (db.new_id(), entity_type, entity_id, field_path, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), claim_id, iso(observed), note))


def _validated(p: dict, concert_id: str, perf_id: str, confirmed: bool, prefecture: str | None) -> dict:
    precision = _PRECISION[p["date_precision"]]
    starts = datetime.fromisoformat(p["starts_at"]) if precision == "exact_time" else None
    Performance(id=perf_id, concert_id=concert_id, confirmation_status="official_confirmed" if confirmed else "needs_review",
                status="scheduled" if confirmed else "needs_review", country_code="JP", prefecture_code=prefecture,
                venue_name=p.get("venue") or "", starts_at=starts, local_date=date.fromisoformat(p["local_date"]), date_precision=precision)
    return {"starts_at": iso(starts), "local_date": p["local_date"], "date_precision": precision, "venue_name": p.get("venue") or ""}


def _ingest_concert(conn, source_id, source_url, items, observed, complete, doc_id, confirm: Confirmation | None, counts):
    identity = f"{source_id}|{canonical(source_url)}"
    head = items[0]
    confirmed = confirm is not None
    row = conn.execute("SELECT * FROM concert WHERE identity_key=?", (identity,)).fetchone()
    today = observed.astimezone(JST).date().isoformat()
    if row is None:
        names = [a["name_display"] for a in head.get("artists_items") or []]
        category = confirm.category if confirm and confirm.category else suggest_category(source_id, head["title"], names, head["category"])
        concert_id = db.new_id()
        conn.execute("INSERT INTO concert (id,identity_key,organization_id,category,title_ja,first_verified_at,verification_status) VALUES (?,?,?,?,?,?,?)",
                     (concert_id, identity, source_id, category, head["title"], iso(confirm.at if confirm else observed), "official_confirmed" if confirmed else "needs_review"))
        counts["concerts_new"] += 1
    else:
        concert_id = row["id"]
        if row["title_ja"] != head["title"]:
            cid = _claim(conn, doc_id, "concert", concert_id, "title_ja", head["title"], head["title"], observed)
            _event(conn, "concert", concert_id, "title_ja", row["title_ja"], head["title"], cid, observed)
            conn.execute("UPDATE concert SET title_ja=?, last_material_change_at=? WHERE id=?", (head["title"], iso(observed), concert_id))
            counts["concerts_retitled"] += 1
        if confirmed and row["verification_status"] != "official_confirmed":
            dup = duplicates.effective_duplicate_of(conn, concert_id, today)
            if dup:
                raise ValueError(f"marked as a duplicate of {dup['concert_id']}: undo that decision first")
            conn.execute("UPDATE concert SET verification_status='official_confirmed', first_verified_at=?, category=COALESCE(?, category) WHERE id=?",
                         (iso(confirm.at), confirm.category, concert_id))  # reset is deliberate, not a material change (ADR-0001)
    stored = [dict(r) for r in conn.execute("SELECT * FROM performance WHERE concert_id=? AND status!='cancelled'", (concert_id,))]
    by_key = {(r["local_date"], (datetime.fromisoformat(r["starts_at"]).astimezone(JST).strftime("%H:%M") if r["starts_at"] else None), _vkey(r["venue_name"])): r for r in stored}
    matched, unmatched_in = set(), []
    for p in items:
        key = (p["local_date"], p["local_time"] if p["date_precision"] == "minute" else None, _vkey(p["venue"]))
        r = by_key.get(key)
        if r is not None and r["id"] not in matched:
            matched.add(r["id"])
            _touch(conn, r, p, observed, confirm, counts)
        else:
            unmatched_in.append(p)
    unmatched_stored = [r for r in stored if r["id"] not in matched]
    if len(unmatched_stored) == 1 and len(unmatched_in) == 1:
        _reschedule(conn, unmatched_stored[0], unmatched_in[0], doc_id, observed, confirm, counts)
        unmatched_stored, unmatched_in = [], []
    for p in unmatched_in:
        pid = db.new_id()
        pref = confirm.prefecture_overrides.get(p["performance_id"]) if confirm else None
        pref = pref or prefecture_code(p["venue"])
        fields = _validated(p, concert_id, pid, confirmed, pref)
        conn.execute("INSERT INTO performance (id,concert_id,starts_at,local_date,date_precision,country_code,prefecture_code,venue_name,confirmation_status,status,poc_performance_id,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (pid, concert_id, fields["starts_at"], fields["local_date"], fields["date_precision"], "JP", pref, fields["venue_name"],
                      "official_confirmed" if confirmed else "needs_review", "scheduled" if confirmed else "needs_review", p["performance_id"], iso(observed)))
        _claim(conn, doc_id, "performance", pid, "local_date", p["evidence"]["date_raw"], p["local_date"], observed, "official_confirmed" if confirmed else "needs_review")
        counts["performances_new"] += 1
        if stored and (unmatched_stored or complete):
            counts["new_performance_on_existing_concert"] += 1
    _sync_lists(conn, concert_id, head, observed, counts)
    if row is not None and row["verification_status"] == "needs_review" and not confirmed:
        # still a candidate: keep its category hint current with what is now known (no change_event; a human confirms later)
        names = [r[0] for r in conn.execute("SELECT name_display FROM concert_artist WHERE concert_id=?", (concert_id,))]
        hint = suggest_category(source_id, head["title"], names, head["category"])
        if hint != row["category"]:
            conn.execute("UPDATE concert SET category=? WHERE id=?", (hint, concert_id))
    for r in unmatched_stored:
        if r["local_date"] < today:
            if r["status"] != "completed":
                _event(conn, "performance", r["id"], "status", r["status"], "completed", None, observed, "date passed")
                conn.execute("UPDATE performance SET status='completed' WHERE id=?", (r["id"],))
                counts["completed"] += 1
        elif complete:
            # unmatched is not deleted; flag once per absence (an event newer than last_seen_at already records it)
            already = conn.execute("SELECT 1 FROM change_event WHERE entity_type='performance' AND entity_id=? AND note LIKE 'missing_in_source%' AND detected_at>=?",
                                   (r["id"], r["last_seen_at"] or "")).fetchone()
            if not already:
                _event(conn, "performance", r["id"], "status", r["status"], "needs_review", None, observed, "missing_in_source (not matched; not deleted)")
                conn.execute("UPDATE performance SET status='needs_review' WHERE id=?", (r["id"],))
                counts["flagged_missing"] += 1


def _sync_lists(conn, concert_id, head, observed, counts):
    """Replace stored programme / performers when a page states a non-empty, different list.

    An empty or missing list means "this page did not say" and never erases stored data. Replacing a non-empty list is a material change
    (a conductor swap or programme change, T10) and is logged with before/after; the first load is not a change.
    """
    for key, table, fields, label in (
            ("programme_items", "program_item", ("position", "raw_text", "composer_display", "composer_key", "work_display", "work_key"), "program_items"),
            ("artists_items", "concert_artist", ("name_display", "role"), "concert_artists")):
        new = head.get(key)
        if not new:
            continue
        rows = [{f: it.get(f) for f in fields} for it in new]
        old = [dict(r) for r in conn.execute(f"SELECT {', '.join(fields)} FROM {table} WHERE concert_id=? ORDER BY rowid", (concert_id,))]
        if old == rows:
            continue
        conn.execute(f"DELETE FROM {table} WHERE concert_id=?", (concert_id,))
        for r in rows:
            conn.execute(f"INSERT INTO {table} (id, concert_id, {', '.join(fields)}) VALUES (?, ?, {', '.join('?' * len(fields))})", (db.new_id(), concert_id, *[r[f] for f in fields]))
        counts[f"{label}_stored"] = counts.get(f"{label}_stored", 0) + 1
        if old:
            _event(conn, "concert", concert_id, label, old, rows, None, observed, "page now states a different list")
            conn.execute("UPDATE concert SET last_material_change_at=? WHERE id=?", (iso(observed), concert_id))
            counts[f"{label}_changed"] = counts.get(f"{label}_changed", 0) + 1


def _touch(conn, r, p, observed, confirm, counts):
    conn.execute("UPDATE performance SET last_seen_at=?, poc_performance_id=? WHERE id=?", (iso(observed), p["performance_id"], r["id"]))
    if confirm and r["confirmation_status"] != "official_confirmed":
        pref = confirm.prefecture_overrides.get(p["performance_id"]) or r["prefecture_code"] or prefecture_code(p["venue"])
        _validated(p, r["concert_id"], r["id"], True, pref)
        conn.execute("UPDATE performance SET confirmation_status='official_confirmed', status='scheduled', prefecture_code=? WHERE id=?", (pref, r["id"]))
        counts["performances_confirmed"] += 1
    else:
        counts["performances_unchanged"] += 1


def _reschedule(conn, r, p, doc_id, observed, confirm, counts):
    confirmed = r["confirmation_status"] == "official_confirmed" or confirm is not None
    pref = (confirm.prefecture_overrides.get(p["performance_id"]) if confirm else None) or prefecture_code(p["venue"]) or r["prefecture_code"]
    fields = _validated(p, r["concert_id"], r["id"], confirmed, pref)
    note = "matched as the only unmatched pair of this concert (not proof of an official reschedule)"
    for fp, old, new in (("local_date", r["local_date"], fields["local_date"]), ("starts_at", r["starts_at"], fields["starts_at"]), ("venue_name", r["venue_name"], fields["venue_name"])):
        if old != new:
            cid = _claim(conn, doc_id, "performance", r["id"], fp, str(new), str(new), observed)
            _event(conn, "performance", r["id"], fp, old, new, cid, observed, note)
    conn.execute("UPDATE performance SET starts_at=?, local_date=?, date_precision=?, venue_name=?, prefecture_code=?, poc_performance_id=?, last_seen_at=?, "
                 "confirmation_status=?, status=? WHERE id=?",
                 (fields["starts_at"], fields["local_date"], fields["date_precision"], fields["venue_name"], pref, p["performance_id"], iso(observed),
                  "official_confirmed" if confirmed else "needs_review", "scheduled" if confirmed else "needs_review", r["id"]))
    conn.execute("UPDATE concert SET last_material_change_at=? WHERE id=?", (iso(observed), r["concert_id"]))
    counts["reschedules"] += 1


def ingest_source(conn: sqlite3.Connection, source_id: str, candidates: list[dict], observed_at: datetime, *, complete: bool,
                  doc_kind: str = "list", policy_status: str = "unknown", confirm: Confirmation | None = None, content_hash: str | None = None) -> dict:
    """One source, one transaction. Returns counts; on failure writes a failed ingestion_run and re-raises nothing."""
    run_id = db.new_id()
    counts = {k: 0 for k in ("concerts_new", "concerts_retitled", "performances_new", "performances_unchanged", "performances_confirmed", "reschedules",
                             "flagged_missing", "completed", "new_performance_on_existing_concert", "skipped_no_date", "skipped_excluded")}
    if confirm is not None:
        counts["human_confirmed_import"] = 1  # marks a person's URL-import confirmation: one page, not a pass over the source (monitor.py ignores it as an observation)
    conn.execute("INSERT INTO ingestion_run (id,source_id,started_at,status) VALUES (?,?,?,'running')", (run_id, source_id, iso(observed_at)))
    conn.commit()
    try:
        conn.execute("SAVEPOINT ingest")
        grouped: dict[str, list[dict]] = {}
        for c in candidates:
            if c["source_id"] != source_id:
                raise ValueError(f"candidate from {c['source_id']} in {source_id} run")
            if c["category"] == "excluded_domestic_orchestra":
                counts["skipped_excluded"] += 1
            elif not c.get("local_date"):
                counts["skipped_no_date"] += 1
            else:
                grouped.setdefault(canonical(c["source_url"]), []).append(c)
        for url, items in grouped.items():
            doc_id = _upsert_document(conn, source_id, items[0]["source_url"], "import" if confirm else doc_kind, observed_at, policy_status, content_hash)
            _ingest_concert(conn, source_id, items[0]["source_url"], items, observed_at, complete, doc_id, confirm, counts)
        conn.execute("RELEASE ingest")
        conn.execute("UPDATE ingestion_run SET status='succeeded', ended_at=?, counts_json=? WHERE id=?", (iso(datetime.now(timezone.utc)), json.dumps(counts), run_id))
        conn.commit()
        return {"run_id": run_id, "status": "succeeded", "counts": counts}
    except Exception as exc:  # noqa: BLE001 - isolate one source's failure from the others (T11)
        conn.execute("ROLLBACK TO ingest")
        conn.execute("RELEASE ingest")
        conn.execute("UPDATE ingestion_run SET status='failed', ended_at=?, error_summary=? WHERE id=?",
                     (iso(datetime.now(timezone.utc)), f"{type(exc).__name__}: {exc}"[:300], run_id))
        conn.commit()
        return {"run_id": run_id, "status": "failed", "counts": counts, "error": f"{type(exc).__name__}: {exc}"}


def ingest_ticket_phases(conn: sqlite3.Connection, source_id: str, phases: list[dict], announcement_url: str, observed_at: datetime, policy_status: str = "unknown") -> dict:
    """Store evidence-linked phases (``linking.py`` output). performance_id there is the POC id -> resolved through poc_performance_id."""
    counts = {"new": 0, "unchanged": 0, "changed": 0, "skipped_unknown_performance": 0}
    doc_id = _upsert_document(conn, source_id, announcement_url, "announcement", observed_at, policy_status)
    for ph in phases:
        perf = conn.execute("SELECT id FROM performance WHERE poc_performance_id=?", (ph["performance_id"],)).fetchone()
        if perf is None:
            counts["skipped_unknown_performance"] += 1
            continue
        precision = ph["start_precision"]
        starts = ph["starts_at"] if precision == "exact_time" else None
        TicketPhase(id="x", performance_id=perf["id"], phase_type=ph["phase_type"], channel=ph["channel"], eligibility=ph["eligibility"],
                    starts_at=datetime.fromisoformat(starts) if starts else None, start_precision=precision, end_precision="unknown",
                    current_status=ph["current_status"], source_document_id=doc_id)
        row = conn.execute("SELECT * FROM ticket_phase WHERE performance_id=? AND phase_type=? AND COALESCE(eligibility,'')=COALESCE(?,'')", (perf["id"], ph["phase_type"], ph["eligibility"])).fetchone()
        if row is None:
            tid = db.new_id()
            conn.execute("INSERT INTO ticket_phase (id,performance_id,phase_type,channel,eligibility,starts_at,start_precision,end_precision,current_status,source_document_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (tid, perf["id"], ph["phase_type"], ph["channel"], ph["eligibility"], starts, precision, "unknown", ph["current_status"], doc_id))
            _claim(conn, doc_id, "ticket_phase", tid, "starts_at", ph.get("label_raw"), starts, observed_at)
            counts["new"] += 1
        elif row["starts_at"] != starts:
            cid = _claim(conn, doc_id, "ticket_phase", row["id"], "starts_at", ph.get("label_raw"), starts, observed_at)
            _event(conn, "ticket_phase", row["id"], "starts_at", row["starts_at"], starts, cid, observed_at)
            conn.execute("UPDATE ticket_phase SET starts_at=?, start_precision=?, current_status=?, source_document_id=? WHERE id=?", (starts, precision, ph["current_status"], doc_id, row["id"]))
            reminders.reconcile_phase(conn, row["id"], observed_at)  # 3.6: a changed time invalidates the old scheduled delivery and schedules the new one
            counts["changed"] += 1
        else:
            conn.execute("UPDATE ticket_phase SET current_status=? WHERE id=?", (ph["current_status"], row["id"]))
            counts["unchanged"] += 1
    conn.commit()
    return counts


def confirm_stored(conn: sqlite3.Connection, concert_ids: list[str], at: datetime, *, category_overrides: dict[str, str] | None = None,
                   prefecture_overrides: dict[str, str] | None = None) -> dict:
    """Human decision on already-stored needs_review concerts (review queue). Atomic per concert.

    Only upcoming performances are confirmed (past ones stay as they are). A concert whose upcoming performance lacks a day-level
    date, a venue or a prefecture (stored, mapped or supplied) is refused with the reason; nothing is guessed.
    """
    category_overrides, prefecture_overrides = category_overrides or {}, prefecture_overrides or {}
    today = at.astimezone(JST).date().isoformat()
    out = {"confirmed": [], "failed": {}}
    for cid in concert_ids:
        c = conn.execute("SELECT * FROM concert WHERE id=?", (cid,)).fetchone()
        if c is None:
            out["failed"][cid] = "unknown concert"
            continue
        if c["verification_status"] == "official_confirmed":
            out["failed"][cid] = "already official_confirmed"
            continue
        perfs = [dict(r) for r in conn.execute("SELECT * FROM performance WHERE concert_id=? AND status NOT IN ('cancelled','completed') AND local_date>=?", (cid, today))]
        if not perfs:
            out["failed"][cid] = "no upcoming performance"
            continue
        dup = duplicates.effective_duplicate_of(conn, cid, today)
        if dup:
            out["failed"][cid] = f"marked as a duplicate of {dup['concert_id']}: undo that decision first"
            continue
        try:
            updates = []
            for p in perfs:
                pref = prefecture_overrides.get(p["id"]) or p["prefecture_code"] or prefecture_code(p["venue_name"])
                starts = datetime.fromisoformat(p["starts_at"]) if p["starts_at"] else None
                Performance(id=p["id"], concert_id=cid, confirmation_status="official_confirmed", status="scheduled", country_code="JP", prefecture_code=pref,
                            venue_name=p["venue_name"], starts_at=starts, local_date=date.fromisoformat(p["local_date"]), date_precision=p["date_precision"])
                updates.append((pref, p["id"]))
        except Exception as exc:  # noqa: BLE001 - pydantic ValidationError / ValueError: report, change nothing for this concert
            out["failed"][cid] = str(exc).splitlines()[-1][:160] if str(exc) else type(exc).__name__
            continue
        category = category_overrides.get(cid) or c["category"]
        conn.execute("SAVEPOINT confirm_one")
        conn.execute("UPDATE concert SET verification_status='official_confirmed', category=?, first_verified_at=? WHERE id=?", (category, iso(at), cid))
        for pref, pid in updates:
            conn.execute("UPDATE performance SET confirmation_status='official_confirmed', status='scheduled', prefecture_code=? WHERE id=?", (pref, pid))
        _event(conn, "concert", cid, "verification_status", "needs_review", "official_confirmed", None, at, "human confirmation (review queue)")
        conn.execute("RELEASE confirm_one")
        out["confirmed"].append(cid)
    conn.commit()
    return out


def review_candidates(conn: sqlite3.Connection, now: datetime, *, source_id: str | None = None, page: int = 1, limit: int = 50) -> dict:
    """Concerts waiting for a human decision, with the evidence needed to decide and the blockers that make confirmation impossible."""
    today = now.astimezone(JST).date().isoformat()
    rows = conn.execute("SELECT * FROM concert WHERE verification_status='needs_review' AND (:s IS NULL OR identity_key LIKE :s || '|%') ORDER BY identity_key", {"s": source_id}).fetchall()
    items = []
    hidden = {m["concert_id"] for m in duplicates.marked_duplicates(conn, today)}  # reviewer said "same show as another card": out of the queue, undoable
    hints = duplicates.hints_for(conn, [c["id"] for c in rows if c["id"] not in hidden], today)
    for c in rows:
        if c["id"] in hidden:
            continue
        perfs = []
        for p in conn.execute("SELECT * FROM performance WHERE concert_id=? AND status NOT IN ('cancelled','completed') AND local_date>=? ORDER BY local_date, starts_at", (c["id"], today)):
            pref = p["prefecture_code"] or prefecture_code(p["venue_name"])
            issues = ([] if p["venue_name"] else ["venue_missing"]) + ([] if pref else ["prefecture_unknown"]) + ([] if p["date_precision"] in ("exact_time", "date_only") else ["date_not_day_level"])
            raw = conn.execute("SELECT raw_value FROM source_claim WHERE entity_type='performance' AND entity_id=? AND field_path='local_date' ORDER BY verified_at LIMIT 1", (p["id"],)).fetchone()
            perfs.append({"performance_id": p["id"], "local_date": p["local_date"], "starts_at": p["starts_at"], "date_precision": p["date_precision"], "venue_name": p["venue_name"],
                          "prefecture_code": pref, "date_raw": raw[0] if raw else None, "issues": issues})
        if not perfs:
            continue
        sid, url = c["identity_key"].split("|", 1)
        summ = _summaries(conn, [c["id"]])[c["id"]]
        items.append({**summ, "concert_id": c["id"], "source_id": sid, "source_url": url, "title_ja": c["title_ja"], "suggested_category": c["category"], "performances": perfs,
                      "confirmable": all(not p["issues"] for p in perfs), "blockers": sorted({i for p in perfs for i in p["issues"]}),
                      "possible_duplicates": hints.get(c["id"], [])})
    by_source: dict[str, int] = {}
    for i in items:
        by_source[i["source_id"]] = by_source.get(i["source_id"], 0) + 1
    return {"total": len(items), "by_source": by_source, "page": page, "limit": limit, "items": items[(page - 1) * limit: page * limit],
            "marked_duplicates": duplicates.marked_duplicates(conn, today, source_id),
            "confirmed_duplicates": duplicates.confirmed_pairs(conn, today, source_id),
            "notice": "候选来自官方页面的自动解析，尚未人工核对。确认前请对照来源链接；缺场馆/都道府县的条目不能确认。"}
