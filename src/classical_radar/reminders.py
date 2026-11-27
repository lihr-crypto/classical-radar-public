"""Reminder scheduling for 03_CONTRACTS 3.6 / T13, with a LOCAL FAKE sender only (ADR-0002).

The model is "reconcile": for one subscription we compute from the *current* database state whether a delivery should exist and,
if so, its deterministic ``dedupe_key``; then we make ``notification_delivery`` match. That one function serves every trigger
(user toggles, a ticket time moves, a performance is cancelled, a milestone passes), so retries and replays cannot create a second
delivery for the same (subscription, milestone, target time, offset), and a changed time/offset invalidates the old one.

Nothing here touches the network. ``FakeSender`` appends JSON lines to a local file. Real sending needs the user's explicit permission.
Delivery is AT-LEAST-ONCE: a crash between ``send`` and the commit that records it can resend; exactly-once cannot be promised (3.6).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from .db import new_id

TRUSTED_CHANNELS = ("official", "official_presenter")  # ticket_phase.channel values that count as an official sales source
GRACE = timedelta(minutes=10)  # a reminder may still go out this long after the milestone itself (offset 0 means "at the milestone")
_SQL_ACTIVE = "('pending','failed')"  # rows a runner would still act on

_CONTEXT_SQL = """SELECT r.id, r.user_id, r.ticket_phase_id, r.milestone, r.offset_minutes, r.enabled,
                         t.channel, t.starts_at, t.start_precision, t.ends_at, t.end_precision,
                         p.status AS pstatus, p.confirmation_status AS pconf, p.venue_name, p.local_date,
                         c.verification_status AS cconf, c.title_ja
                  FROM reminder_subscription r JOIN ticket_phase t ON t.id=r.ticket_phase_id
                  JOIN performance p ON p.id=t.performance_id JOIN concert c ON c.id=p.concert_id"""


class Sender(Protocol):
    def send(self, delivery: dict) -> str:
        """Hand one delivery to the channel and return a provider id. Raise to signal a (retryable) failure."""


class FakeSender:
    """Local stand-in for a mail/push provider: records what *would* be sent. ``fail_ids`` makes chosen deliveries raise (tests)."""

    def __init__(self, outbox: Path | None = None, fail_ids: set[str] | None = None) -> None:
        self.outbox = outbox
        self.fail_ids = set(fail_ids or ())
        self.sent: list[dict] = []

    def send(self, delivery: dict) -> str:
        if delivery["id"] in self.fail_ids:
            raise RuntimeError("fake sender: simulated failure")
        self.sent.append(delivery)
        if self.outbox is not None:
            self.outbox.parent.mkdir(parents=True, exist_ok=True)
            with self.outbox.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(delivery, ensure_ascii=False, sort_keys=True) + "\n")
        return "fake:" + delivery["dedupe_key"][4:16]


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)  # a naive instant is read as UTC, never as local time


def dedupe_key(subscription_id: str, milestone: str, target: datetime, offset_minutes: int) -> str:
    raw = f"{subscription_id}|{milestone}|{_iso(target)}|{offset_minutes}"
    return "rem:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def evaluate(row: sqlite3.Row, now: datetime) -> tuple[datetime | None, str | None]:
    """Return (milestone time, None) when a reminder should exist now, else (None, why not). The reason is stored on cancelled rows."""
    if not row["enabled"]:
        return None, "unsubscribed"
    when, precision = (row["starts_at"], row["start_precision"]) if row["milestone"] == "sale_start" else (row["ends_at"], row["end_precision"])
    if precision != "exact_time" or when is None:
        return None, f"{row['milestone']} is no longer an exact time"
    if row["pconf"] != "official_confirmed" or row["cconf"] != "official_confirmed":
        return None, "not official_confirmed"
    if row["channel"] not in TRUSTED_CHANNELS:
        return None, f"channel {row['channel']} is not an official sales source"
    if row["pstatus"] != "scheduled":
        return None, f"performance is {row['pstatus']}"
    target = _utc(when)
    if now > target + GRACE:
        return None, "missed: milestone already passed"
    return target, None


def reconcile(conn: sqlite3.Connection, subscription_id: str, now: datetime | None = None) -> dict:
    """Make ``notification_delivery`` match the subscription's current state. Does not commit. Never deletes; ``sent`` rows are history."""
    now = _now(now)
    row = conn.execute(_CONTEXT_SQL + " WHERE r.id=?", (subscription_id,)).fetchone()
    if row is None:
        return {"scheduled": False, "cancelled": 0, "reason": "no such subscription"}
    target, why = evaluate(row, now)
    keep = None
    if target is not None:
        keep = dedupe_key(subscription_id, row["milestone"], target, row["offset_minutes"])
        fire = target - timedelta(minutes=row["offset_minutes"])
        created = conn.execute("INSERT OR IGNORE INTO notification_delivery (id,reminder_subscription_id,scheduled_for,dedupe_key,status) VALUES (?,?,?,?, 'pending')",
                               (new_id(), subscription_id, _iso(fire), keep)).rowcount
        if not created:  # same key seen before: only a cancelled row (user toggled off then on) comes back; sent/failed/pending stay as they are
            conn.execute("UPDATE notification_delivery SET status='pending', last_error=NULL WHERE dedupe_key=? AND status='cancelled'", (keep,))
    # every other not-yet-sent row (pending OR failed-and-awaiting-retry) is stale: old time, old offset, unsubscribed, cancelled, expired
    cancelled = conn.execute(f"UPDATE notification_delivery SET status='cancelled', last_error=? WHERE reminder_subscription_id=? AND status IN {_SQL_ACTIVE} AND dedupe_key IS NOT ?",
                             (why or "superseded by a new time or offset", subscription_id, keep)).rowcount
    return {"scheduled": target is not None, "cancelled": cancelled, "reason": why}


def reconcile_phase(conn: sqlite3.Connection, ticket_phase_id: str, now: datetime | None = None) -> None:
    for r in conn.execute("SELECT id FROM reminder_subscription WHERE ticket_phase_id=?", (ticket_phase_id,)).fetchall():
        reconcile(conn, r["id"], now)


def reconcile_all(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    out = {"cancelled": 0, "missed": 0}
    for r in conn.execute("SELECT id FROM reminder_subscription").fetchall():
        res = reconcile(conn, r["id"], now)
        out["cancelled"] += res["cancelled"]
        if res["cancelled"] and (res["reason"] or "").startswith("missed"):
            out["missed"] += res["cancelled"]
    conn.commit()
    return out


def _payload(r: sqlite3.Row, now: datetime) -> dict:
    target = _utc(r["starts_at"] if r["milestone"] == "sale_start" else r["ends_at"])
    what = "开票" if r["milestone"] == "sale_start" else "截止"
    left = int((target - now).total_seconds() // 60)  # what is true when it is sent, which can be late (grace window) or early
    lead = f"还有 {left} 分钟" if left > 0 else "现在" if left == 0 else "已经"
    return {"id": r["id"], "subscription_id": r["subscription_id"], "user_id": r["user_id"], "ticket_phase_id": r["ticket_phase_id"], "milestone": r["milestone"],
            "offset_minutes": r["offset_minutes"], "scheduled_for": r["scheduled_for"], "target_time": _iso(target), "dedupe_key": r["dedupe_key"],
            "text": f"{what}提醒：{r['title_ja']}（{r['venue_name']}，{r['local_date']}）{lead}{what}。"}


def run_due(conn: sqlite3.Connection, now: datetime | None, sender: Sender, *, retry_failed: bool = True) -> dict:
    """Send every delivery whose time has come. Reconciles first, so anything stale is cancelled before it can be sent.

    ``failed`` rows are retried on later runs (no attempt cap; they stop once the milestone has passed, because reconcile then cancels
    them). Each row is committed on its own so one bad send does not hide the others.
    """
    now = _now(now)
    swept = reconcile_all(conn, now)
    statuses = "('pending','failed')" if retry_failed else "('pending')"
    rows = conn.execute(f"""SELECT d.id, d.reminder_subscription_id AS subscription_id, d.scheduled_for, d.dedupe_key, c.title_ja, p.venue_name, p.local_date,
                                   r.user_id, r.ticket_phase_id, r.milestone, r.offset_minutes, t.starts_at, t.ends_at
                            FROM notification_delivery d JOIN reminder_subscription r ON r.id=d.reminder_subscription_id
                            JOIN ticket_phase t ON t.id=r.ticket_phase_id JOIN performance p ON p.id=t.performance_id JOIN concert c ON c.id=p.concert_id
                            WHERE d.status IN {statuses} ORDER BY d.scheduled_for, d.id""").fetchall()
    out = {"sent": 0, "failed": 0, "not_due": 0, "cancelled": swept["cancelled"], "missed": swept["missed"]}
    for r in rows:
        if _utc(r["scheduled_for"]) > now:
            out["not_due"] += 1
            continue
        try:
            provider_id = sender.send(_payload(r, now))
        except Exception as exc:  # any sender failure is recorded and retried later; it must not stop the other deliveries
            conn.execute("UPDATE notification_delivery SET status='failed', last_error=? WHERE id=?", (f"{type(exc).__name__}: {exc}"[:300], r["id"]))
            out["failed"] += 1
        else:
            conn.execute("UPDATE notification_delivery SET status='sent', sent_at=?, provider_id=?, last_error=NULL WHERE id=?", (_iso(now), provider_id, r["id"]))
            out["sent"] += 1
        conn.commit()
    return out
