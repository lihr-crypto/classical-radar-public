"""Rebuild the cloud database from the published site data (ADR-0008, step 2).

The live site keeps favourites, performance states and reminders under the concert, performance and ticket-phase ids that
``site-data/concerts.json`` carries. Those ids are random (``db.new_id``), so a cloud database that starts empty would mint new ones
and orphan everything. This writes the published rows back under their original ids:

* the match keys the next sync uses are rebuilt from the file: ``source_id|source_url`` is the concert's identity key, and a performance
  matches on day, time and venue, so the following sync finds these rows instead of creating twins;
* what the file does not carry gets a neutral value: a ticket phase's ``channel`` is ``other`` and its evidence document is a stand-in
  row for the concert's page; ``poc_performance_id`` stays empty until the next sync touches the performance;
* candidates (``needs_review``), cancelled performances and change history are not in the file, so they are not restored. The next sync
  finds the candidates again;
* only an empty database is accepted, so a restore can never overwrite real work.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from . import db


def _insert_concert(conn: sqlite3.Connection, c: dict) -> dict:
    concert_id = c["id"]
    conn.execute("INSERT INTO concert (id,identity_key,organization_id,category,title_ja,official_announcement_date,first_verified_at,last_material_change_at,verification_status) "
                 "VALUES (?,?,?,?,?,?,?,?, 'official_confirmed')",
                 (concert_id, f"{c['source_id']}|{c['source_url']}", c["source_id"], c["category"], c["title_ja"], c.get("official_announcement_date"),
                  c["first_verified_at"], c.get("last_material_change_at")))
    doc_id = db.new_id()
    conn.execute("INSERT INTO source_document (id,source_id,url,kind,first_seen_at,last_verified_at,policy_status) VALUES (?,?,?,'detail',?,?,'unknown')",
                 (doc_id, c["source_id"], c["source_url"], c["first_verified_at"], c["first_verified_at"]))
    phases = 0
    for p in c["performances"]:
        conn.execute("INSERT INTO performance (id,concert_id,starts_at,local_date,date_precision,country_code,prefecture_code,venue_name,confirmation_status,status,poc_performance_id,last_seen_at) "
                     "VALUES (?,?,?,?,?,?,?,?, 'official_confirmed',?,NULL,?)",
                     (p["id"], concert_id, p.get("starts_at"), p.get("local_date"), p["date_precision"], p.get("country_code") or "JP", p.get("prefecture_code"),
                      p["venue_name"], p["status"], p.get("last_seen_at")))
        for t in p.get("ticket_phases", []):
            conn.execute("INSERT INTO ticket_phase (id,performance_id,phase_type,channel,eligibility,starts_at,start_precision,end_precision,current_status,source_document_id) "
                         "VALUES (?,?,?, 'other',?,?,?,?,?,?)",
                         (t["id"], p["id"], t["phase_type"], t.get("eligibility"), t.get("starts_at"), t["start_precision"], t["end_precision"], t["current_status"], doc_id))
            phases += 1
    for it in c.get("program", []):
        conn.execute("INSERT INTO program_item (id,concert_id,position,raw_text,composer_display,composer_key,work_display,work_key) VALUES (?,?,?,?,?,?,?,?)",
                     (db.new_id(), concert_id, it["position"], it["raw_text"], it.get("composer_display"), it.get("composer_key"), it.get("work_display"), it.get("work_key")))
    for a in c.get("artists", []):
        conn.execute("INSERT INTO concert_artist (id,concert_id,name_display,role) VALUES (?,?,?,?)", (db.new_id(), concert_id, a["name_display"], a["role"]))
    return {"performances": len(c["performances"]), "phases": phases}


def restore_site(conn: sqlite3.Connection, concerts_file: Path, same_file: Path | None, now: datetime) -> dict:
    """Load ``concerts.json`` into an empty database under its original ids, then replay the reviewed same-concert decisions."""
    if conn.execute("SELECT COUNT(*) FROM concert").fetchone()[0]:
        raise ValueError("the database is not empty: restore only starts from an empty one")
    data = json.loads(Path(concerts_file).read_text(encoding="utf8"))
    concerts = data.get("concerts") if isinstance(data, dict) else None
    if not isinstance(concerts, list) or not concerts:
        raise ValueError(f"{concerts_file} has no concerts list")
    counts = {"concerts": 0, "performances": 0, "ticket_phases": 0}
    try:
        for c in concerts:
            n = _insert_concert(conn, c)
            counts["concerts"] += 1
            counts["performances"] += n["performances"]
            counts["ticket_phases"] += n["phases"]
    except (KeyError, sqlite3.Error) as exc:  # a malformed row must not leave half a database behind
        conn.rollback()
        raise ValueError(f"cannot restore {concerts_file}: {type(exc).__name__}: {exc}") from exc
    conn.commit()
    out = {**counts, "as_of": data.get("as_of")}
    if same_file is not None and Path(same_file).is_file():
        from .duplicates import apply_file
        r = apply_file(conn, Path(same_file), now)
        out["same_concert"] = {"applied": r["applied"], "skipped": len(r["skipped"])}
    return out
