"""Personal state with the three separate granularities of 03_CONTRACTS 3.6. Pickup never creates a reminder."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .contract import UserPerformanceStatus, Priority
from . import reminders
from .db import new_id
from typing import get_args


def _now(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def put_pickup(conn: sqlite3.Connection, user_id: str, concert_id: str, priority: str = "normal", notes: str | None = None, now: datetime | None = None) -> None:
    if priority not in get_args(Priority):
        raise ValueError("priority")
    if conn.execute("SELECT 1 FROM concert WHERE id=? AND verification_status='official_confirmed'", (concert_id,)).fetchone() is None:
        raise LookupError("concert not found or not official_confirmed")
    conn.execute("INSERT INTO user_pickup (user_id,concert_id,priority,notes,created_at) VALUES (?,?,?,?,?) "
                 "ON CONFLICT(user_id,concert_id) DO UPDATE SET priority=excluded.priority, notes=excluded.notes", (user_id, concert_id, priority, notes, _now(now)))
    conn.commit()


def delete_pickup(conn: sqlite3.Connection, user_id: str, concert_id: str) -> bool:
    cur = conn.execute("DELETE FROM user_pickup WHERE user_id=? AND concert_id=?", (user_id, concert_id))
    conn.commit()
    return cur.rowcount == 1


def put_performance_state(conn: sqlite3.Connection, user_id: str, performance_id: str, status: str, notes: str | None = None, now: datetime | None = None) -> None:
    if status not in get_args(UserPerformanceStatus):
        raise ValueError("status")
    if conn.execute("SELECT 1 FROM performance WHERE id=?", (performance_id,)).fetchone() is None:
        raise LookupError("performance not found")
    conn.execute("INSERT INTO user_performance_state (user_id,performance_id,status,notes,updated_at) VALUES (?,?,?,?,?) "
                 "ON CONFLICT(user_id,performance_id) DO UPDATE SET status=excluded.status, notes=excluded.notes, updated_at=excluded.updated_at",
                 (user_id, performance_id, status, notes, _now(now)))
    conn.commit()


MILESTONES = ("sale_start", "sale_end")


def put_reminder(conn: sqlite3.Connection, user_id: str, ticket_phase_id: str, milestone: str, offset_minutes: int, enabled: bool, now: datetime | None = None) -> dict:
    """Create/update the subscription and make its scheduled delivery match (``reminders.reconcile``; the fake sender delivers it later).

    3.6: a minute-level reminder needs an ``exact_time`` milestone from an official-confirmed performance and an official sales channel,
    and only makes sense while the milestone is still ahead. A date-only or unknown milestone can never become a clock-time reminder,
    so it is rejected instead of defaulting to 10:00 or midnight. Switching a reminder off is always allowed.
    """
    if milestone not in MILESTONES or not 0 <= offset_minutes <= 60 * 24 * 30:
        raise ValueError("milestone must be sale_start|sale_end and offset_minutes within 0..43200")
    t = conn.execute("""SELECT t.*, p.confirmation_status AS pconf, c.verification_status AS cconf FROM ticket_phase t
                        JOIN performance p ON p.id=t.performance_id JOIN concert c ON c.id=p.concert_id WHERE t.id=?""", (ticket_phase_id,)).fetchone()
    if t is None or t["pconf"] != "official_confirmed" or t["cconf"] != "official_confirmed":
        raise LookupError("ticket phase not found or not official_confirmed")
    when, precision = (t["starts_at"], t["start_precision"]) if milestone == "sale_start" else (t["ends_at"], t["end_precision"])
    if enabled:
        if precision != "exact_time" or when is None:
            raise ValueError(f"{milestone} has precision {precision}: a clock-time reminder needs an exact official time")
        if t["channel"] not in reminders.TRUSTED_CHANNELS:
            raise ValueError(f"channel {t['channel']} is not an official sales source: no reminder")
        if reminders._now(now) > reminders._utc(when) + reminders.GRACE:
            raise ValueError(f"{milestone} has already passed: nothing left to remind")
    conn.execute("INSERT INTO reminder_subscription (id,user_id,ticket_phase_id,milestone,offset_minutes,enabled) VALUES (?,?,?,?,?,?) "
                 "ON CONFLICT(user_id,ticket_phase_id,milestone) DO UPDATE SET offset_minutes=excluded.offset_minutes, enabled=excluded.enabled",
                 (new_id(), user_id, ticket_phase_id, milestone, offset_minutes, int(enabled)))
    rid = conn.execute("SELECT id FROM reminder_subscription WHERE user_id=? AND ticket_phase_id=? AND milestone=?", (user_id, ticket_phase_id, milestone)).fetchone()["id"]
    reminders.reconcile(conn, rid, now)
    conn.commit()
    return {"id": rid, "user_id": user_id, "ticket_phase_id": ticket_phase_id, "milestone": milestone, "offset_minutes": offset_minutes, "enabled": enabled}


def _performances(conn: sqlite3.Connection, user_id: str, concert_id: str) -> list[dict]:
    return [dict(p) for p in conn.execute(
        """SELECT p.id AS performance_id, p.local_date, p.starts_at, p.date_precision, p.venue_name, p.prefecture_code, p.status, s.status AS user_status
           FROM performance p LEFT JOIN user_performance_state s ON s.performance_id=p.id AND s.user_id=?
           WHERE p.concert_id=? AND p.confirmation_status='official_confirmed' ORDER BY p.local_date, p.starts_at""", (user_id, concert_id))]


def list_pickups(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    out = []
    for r in conn.execute("""SELECT u.concert_id, u.priority, u.notes, u.created_at, c.title_ja, c.category, c.organization_id FROM user_pickup u JOIN concert c ON c.id=u.concert_id
                             WHERE u.user_id=? ORDER BY u.priority DESC, u.created_at DESC""", (user_id,)):
        out.append({**dict(r), "performances": _performances(conn, user_id, r["concert_id"])})
    return out


# "plan to attend" (ADR-0012): the same shape as a pickup, one row per concert. A plan is the concert-level "I intend to go"; it never creates a reminder and
# does not touch the per-performance statuses (which record tickets and attendance per date)
def put_plan(conn: sqlite3.Connection, user_id: str, concert_id: str, now: datetime | None = None) -> None:
    if conn.execute("SELECT 1 FROM concert WHERE id=? AND verification_status='official_confirmed'", (concert_id,)).fetchone() is None:
        raise LookupError("concert not found or not official_confirmed")
    conn.execute("INSERT INTO user_plan (user_id,concert_id,created_at) VALUES (?,?,?) ON CONFLICT(user_id,concert_id) DO NOTHING", (user_id, concert_id, _now(now)))
    conn.commit()


def delete_plan(conn: sqlite3.Connection, user_id: str, concert_id: str) -> bool:
    cur = conn.execute("DELETE FROM user_plan WHERE user_id=? AND concert_id=?", (user_id, concert_id))
    conn.commit()
    return cur.rowcount == 1


def list_plans(conn: sqlite3.Connection, user_id: str) -> list[dict]:
    out = []
    for r in conn.execute("""SELECT u.concert_id, u.created_at, c.title_ja, c.category, c.organization_id FROM user_plan u JOIN concert c ON c.id=u.concert_id
                             WHERE u.user_id=? ORDER BY u.created_at DESC""", (user_id,)):
        out.append({**dict(r), "performances": _performances(conn, user_id, r["concert_id"])})
    return out
