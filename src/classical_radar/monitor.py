"""Monitoring rounds and the change-latency report (ADR-0004). A round is run BY HAND; this project installs no scheduler.

``run_round`` is one polite pass over the registered sources (the existing ``sync_source``), with a per-source minimum interval
so a careless loop cannot hammer a site, and with 都响 (``tmso``) hard-excluded: its usage terms restrict reuse (ADR-0001).

``report`` answers "how fast do we notice a change?" and says honestly what it cannot know. 03_CONTRACTS asks for
``detected_at - official_change_known_at``, but the official site's change time is only partly knowable:

* ``official_change_known_at`` = the detail page's own last-modified stamp (JSON-LD ``dateModified``, ``article:modified_time``,
  ``og:updated_time``; 5 of 8 sources, P0.3) recorded by ``pageobs`` at each fetch, used only when it MOVED since the previous observation.
  It is the CMS save time, not proof of a material change, and it is null for the other sources and for list-level changes.
* for every change there is also an UPPER BOUND that needs no page stamp::

      page_change_to_detection_upper_bound_hours = run.ended_at - previous_run.started_at

  The old value was last fetched no earlier than the previous run's start and the new value no later than this run's end, so the site
  changed in between and our delay is at most that. It is not time since the official announcement and not an SLA.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone
from typing import Callable

from .sync import SUPPORTED, sync_source

MONITOR_EXCLUDED = ("tmso",)  # hard rule in code, not only in docs
DEFAULT_MIN_INTERVAL_HOURS = 6.0
HUMAN_FIELDS = ("verification_status", "identity_key")  # not changes on the official site: a person confirming a concert, and our own moving of a poster card onto its official page (ADR-0021)


def monitor_sources() -> list[str]:
    return [s for s in SUPPORTED if s not in MONITOR_EXCLUDED]


def _t(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _hours(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 3600, 2)


def _is_import_run(run: sqlite3.Row) -> bool:
    """A human URL-import confirmation also writes an ingestion_run, but it observed one page, not the source: not a monitoring observation."""
    return bool(run["counts_json"] and json.loads(run["counts_json"]).get("human_confirmed_import"))


def _observation_runs(conn: sqlite3.Connection, source_id: str | None = None) -> list[sqlite3.Row]:
    rows = conn.execute("SELECT * FROM ingestion_run WHERE status IN ('succeeded','failed') AND (:s IS NULL OR source_id=:s) ORDER BY started_at, id", {"s": source_id}).fetchall()
    return [r for r in rows if not _is_import_run(r)]


def run_round(conn: sqlite3.Connection, reader, sources: list[str] | None, now: datetime, *,
              min_interval_hours: float = DEFAULT_MIN_INTERVAL_HOURS, force: bool = False, log: Callable[[str], None] = lambda s: None) -> dict:
    """One manual pass. Excluded sources are refused even when asked for by name; a source seen successfully less than
    ``min_interval_hours`` ago is skipped unless ``force``."""
    out = []
    for sid in sources or monitor_sources():
        if sid in MONITOR_EXCLUDED:
            out.append({"source_id": sid, "status": "skipped", "reason": "excluded from monitoring: usage terms restrict reuse (ADR-0001)"})
            continue
        last = [r for r in _observation_runs(conn, sid) if r["status"] == "succeeded"]
        if last and not force and now - _t(last[-1]["started_at"]) < timedelta(hours=min_interval_hours):
            wait = round(min_interval_hours - (now - _t(last[-1]["started_at"])).total_seconds() / 3600, 2)
            out.append({"source_id": sid, "status": "skipped", "reason": f"too soon: last succeeded run was {_hours(_t(last[-1]['started_at']), now)} h ago, minimum {min_interval_hours} h (wait {wait} h or pass --force)"})
            continue
        res = sync_source(conn, reader, sid, now, log)
        out.append({"source_id": sid, "status": res.get("status"), **{k: res[k] for k in ("counts", "items_listed", "items_failed", "error", "reason") if k in res}})
    return {"started_at": now.isoformat(), "sources": out}


def _identity_of(conn: sqlite3.Connection, entity_type: str, entity_id: str) -> tuple[str | None, str | None]:
    """(source_id, the concert's detail-page URL) of the concert an event is about."""
    sql = {"concert": "SELECT identity_key FROM concert WHERE id=?",
           "performance": "SELECT c.identity_key FROM performance p JOIN concert c ON c.id=p.concert_id WHERE p.id=?",
           "ticket_phase": "SELECT c.identity_key FROM ticket_phase t JOIN performance p ON p.id=t.performance_id JOIN concert c ON c.id=p.concert_id WHERE t.id=?"}.get(entity_type)
    row = conn.execute(sql, (entity_id,)).fetchone() if sql else None
    return tuple(row[0].split("|", 1)) if row else (None, None)


JST = timezone(timedelta(hours=9))


def _stamp_window(value: str) -> tuple[datetime, datetime]:
    """(earliest, latest) instant a page stamp can mean: a timestamp is itself; a date-only stamp is a whole JST day (a Japanese site's day)."""
    if len(value) == 10:
        day = datetime.fromisoformat(value + "T00:00:00").replace(tzinfo=JST)
        return day.astimezone(timezone.utc), (day + timedelta(days=1)).astimezone(timezone.utc)
    t = _t(value)
    return t, t


def _official_change(conn: sqlite3.Connection, source_id: str, url: str, run: sqlite3.Row, previous_run_start: datetime | None) -> tuple[str | None, str | None]:
    """(the page's modified stamp, None) when it MOVED into this run's window, else (None, why not).

    Three guards: there must be an earlier observation of the page's modified time to compare with (a first observation, or the first run after
    an upgrade, would otherwise hand back an old CMS save time); the stamp must have moved since then; and it must not be older than the
    previous run (a stale cache or an edit we already saw is not this change)."""
    canon = url.rstrip("/")
    obs = conn.execute("SELECT * FROM page_observation WHERE source_id=? AND (url=? OR url=?) ORDER BY observed_at", (source_id, canon, canon + "/")).fetchall()
    now_obs = next((o for o in obs if _t(o["observed_at"]) == _t(run["started_at"])), None)
    if now_obs is None:
        return None, "no page observation at this run (a source without page stamps, or a change seen only on a list page)"
    if not now_obs["page_modified_at"]:
        return None, "the page carries no modified time"
    before = [o for o in obs if _t(o["observed_at"]) < _t(run["started_at"]) and o["page_modified_at"]]
    if not before:
        return None, "no earlier observation of this page's modified time to compare with"
    (n_lo, n_hi), (o_lo, o_hi) = _stamp_window(now_obs["page_modified_at"]), _stamp_window(before[-1]["page_modified_at"])
    moved = n_hi > o_hi if (n_lo == n_hi and o_lo == o_hi) else n_lo >= o_hi  # a day-precision stamp that overlaps the other one proves no move
    if not moved:
        return None, "the page's modified time did not move since the previous observation"
    if previous_run_start is not None and _stamp_window(now_obs["page_modified_at"])[1] < previous_run_start:
        return None, "the page's modified time is older than the previous run (a stale copy, not this change)"
    return now_obs["page_modified_at"], None


def _interval_stats(runs: list[sqlite3.Row]) -> dict | None:
    ok = [_t(r["started_at"]) for r in runs if r["status"] == "succeeded"]
    gaps = [_hours(a, b) for a, b in zip(ok, ok[1:])]
    return {"min": min(gaps), "median": round(statistics.median(gaps), 2), "max": max(gaps)} if gaps else None


def report(conn: sqlite3.Connection) -> dict:
    runs = _observation_runs(conn)
    by_source: dict[str, list[sqlite3.Row]] = {}
    for r in runs:
        by_source.setdefault(r["source_id"], []).append(r)
    rounds = {}
    for sid, rs in sorted(by_source.items()):
        ok = [r for r in rs if r["status"] == "succeeded"]
        counts = [json.loads(r["counts_json"]) for r in ok if r["counts_json"]]
        rounds[sid] = {"succeeded": len(ok), "failed": len(rs) - len(ok), "first_started_at": rs[0]["started_at"], "last_started_at": rs[-1]["started_at"],
                       "interval_hours": _interval_stats(rs),
                       "totals": {k: sum(c.get(k, 0) for c in counts) for k in ("concerts_new", "performances_new", "reschedules", "concerts_retitled", "flagged_missing")}}
    changes = []
    for e in conn.execute("SELECT * FROM change_event WHERE field_path NOT IN ({}) ORDER BY detected_at, id".format(",".join("?" * len(HUMAN_FIELDS))), HUMAN_FIELDS):
        sid, url = _identity_of(conn, e["entity_type"], e["entity_id"])
        detected = _t(e["detected_at"])
        run = next((r for r in by_source.get(sid, []) if r["status"] == "succeeded" and _t(r["started_at"]) == detected), None) if sid else None
        prev = [r for r in by_source.get(sid, []) if r["status"] == "succeeded" and run is not None and _t(r["started_at"]) < _t(run["started_at"])]
        bound = None
        why = None
        if sid is None:
            why = "entity has no known source"
        elif run is None:
            why = "no ingestion run starts at detected_at"
        elif not prev:
            why = "no earlier succeeded run: this was the first observation of the source"
        else:
            end = _t(run["ended_at"]) if run["ended_at"] and _t(run["ended_at"]) >= _t(run["started_at"]) else _t(run["started_at"])
            bound = _hours(_t(prev[-1]["started_at"]), end)
        known, why_official = _official_change(conn, sid, url, run, _t(prev[-1]["started_at"]) if prev else None) if run is not None and sid else (None, "no matching run")
        official_hours = official_range = None
        if known is not None:
            lo, hi = _stamp_window(known)
            if lo == hi:
                official_hours = max(0.0, _hours(lo, detected))  # a stamp saved after the run began (edit during the run) counts as 0
            else:  # date-only stamp: the true time is somewhere in a JST day, so give the range instead of a made-up point
                official_range = [max(0.0, _hours(hi, detected)), max(0.0, _hours(lo, detected))]
        changes.append({"source_id": sid, "entity_type": e["entity_type"], "entity_id": e["entity_id"], "field_path": e["field_path"],
                        "before": json.loads(e["before_json"]) if e["before_json"] else None, "after": json.loads(e["after_json"]) if e["after_json"] else None,
                        "detected_at": e["detected_at"], "previous_run_started_at": prev[-1]["started_at"] if prev else None,
                        "page_change_to_detection_upper_bound_hours": bound, "no_bound_reason": why,
                        "official_change_known_at": known, "official_change_signal": "page modified time" if known else None,
                        "official_change_precision": (None if known is None else "date" if len(known) == 10 else "timestamp"),
                        "detected_minus_official_change_hours": official_hours, "detected_minus_official_change_range_hours": official_range,
                        "official_change_unknown_reason": why_official})
    bounds = [c["page_change_to_detection_upper_bound_hours"] for c in changes if c["page_change_to_detection_upper_bound_hours"] is not None]
    known_hours = [c["detected_minus_official_change_hours"] for c in changes if c["detected_minus_official_change_hours"] is not None]
    known_total = sum(1 for c in changes if c["official_change_known_at"] is not None)
    stat = lambda xs: {"median": round(statistics.median(xs), 2), "max": max(xs)} if xs else None  # noqa: E731
    return {"rounds": rounds, "changes": changes,
            "summary": {"changes": len(changes), "with_upper_bound": len(bounds), "with_known_official_change_time": known_total,
                        "upper_bound_hours": stat(bounds), "detected_minus_official_change_hours": stat(known_hours)},
            "notice": "official_change_known_at is the detail page's own modified stamp and exists only for sources that publish one (5 of 8, ADR-0004), only "
                      "when it moved since an earlier observation and falls after the previous run; it is the CMS save time, not proof of a material change. "
                      "A date-only stamp gives a range (a whole JST day), not a point, and is left out of the median. "
                      "For every change the upper bound is the time between the start of the previous successful run and the end of the run that saw it; "
                      "neither number is time since the official announcement and neither is an SLA. A change event can also come from a parser change between "
                      "two runs (runs do not record a code version). Imports confirmed by a person are not counted as runs (only runs made by this version carry that marker; older import runs count as observations)."}
