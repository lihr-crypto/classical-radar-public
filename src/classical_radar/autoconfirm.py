"""Automatic confirmation of new concerts from the official sites (the user's decisions: 2026-11-13 "全自动" for the six orchestras, and
2026-11-17 "都改成自动确认" for the presenters too, ADR-0017).

Everything the sync stores starts as ``needs_review``; a person normally confirms it in the review queue. For an official site the person's
check is mostly "are the fields complete?", so this does exactly the machine-checkable part and nothing more:

* only sources in ``AUTO_SOURCES``: the six orchestras' own sites and, since ADR-0017, the presenters (Japan Arts, KAJIMOTO, 神奈川芸術協会).
  The deferred 東京フィル and the okemin leads are never auto-confirmed. ``presenters=False`` (the cloud job's switch AUTO_CONFIRM_PRESENTERS)
  takes the presenters out again;
* only concerts the review queue itself calls ``confirmable`` (every upcoming performance has a day-level date, a venue and a prefecture),
  whatever their category (all four categories are site categories; ADR-0017 dropped the old ``domestic_orchestra`` gate);
* the confirmation is ``confirm_stored``: every existing guard (duplicate decisions, past performances, validation) still runs;
* a concert that has possible duplicates (another source on the same day at a compatible venue) is held for a person, and so is one with
  a performance that an earlier run flagged ``missing_in_source`` (``confirm_stored`` would quietly set it back to scheduled);
* a flood guard: if more than ``max_confirm`` concerts qualify in one run, NOTHING is confirmed and the run says so (a parser regression
  or a changed page layout must not publish dozens of wrong concerts at once). A dry run reports the guard separately
  (``flood_guard``) and still lists every concert that would be confirmed or held, with the reason.

The default is a dry run: it reports what it would confirm and what it holds back, with the reasons.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .ingest import confirm_stored, review_candidates

ORCHESTRA_SOURCES = ("nhkso", "tmso", "tso", "jpo", "njp", "yomikyo")
PRESENTER_SOURCES = ("japanarts", "kajimoto", "kanagawa_geikyo")
AUTO_SOURCES = ORCHESTRA_SOURCES + PRESENTER_SOURCES
DEFAULT_MAX = 120


def _missing_in_source(conn: sqlite3.Connection, concert_id: str) -> bool:
    return conn.execute("SELECT 1 FROM change_event e JOIN performance p ON p.id=e.entity_id WHERE e.entity_type='performance' AND p.concert_id=? AND e.note LIKE 'missing_in_source%' LIMIT 1",
                        (concert_id,)).fetchone() is not None


def _utc(text: str) -> datetime:
    d = datetime.fromisoformat(text)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _first_seen(conn: sqlite3.Connection, concert_id: str) -> datetime:
    """A candidate's ``first_verified_at`` is the instant its first sync saw it (a person's confirmation is what overwrites it)."""
    return _utc(conn.execute("SELECT first_verified_at FROM concert WHERE id=?", (concert_id,)).fetchone()[0])


def plan(conn: sqlite3.Connection, now: datetime, first_seen_after: str | None = None, presenters: bool = True) -> dict:
    """``first_seen_after``: only candidates a sync first saw at or after this instant are considered; older ones stay for a person
    (the cloud run must not confirm what an earlier run already looked at and left in the queue)."""
    items = review_candidates(conn, now, limit=1_000_000)["items"]
    cutoff = _utc(first_seen_after) if first_seen_after else None
    qualify, held, other, older = [], [], 0, 0
    scope = AUTO_SOURCES if presenters else ORCHESTRA_SOURCES
    for it in items:
        if it["source_id"] not in scope:
            other += 1
            continue
        if cutoff is not None and _first_seen(conn, it["concert_id"]) < cutoff:
            older += 1
            continue
        if it.get("possible_duplicates"):
            held.append({"concert_id": it["concert_id"], "title_ja": it["title_ja"], "source_id": it["source_id"], "reason": "possible duplicate of another source: a person decides"})
        elif _missing_in_source(conn, it["concert_id"]):
            held.append({"concert_id": it["concert_id"], "title_ja": it["title_ja"], "source_id": it["source_id"], "reason": "a performance went missing from the source earlier: a person decides"})
        elif not it["confirmable"]:
            held.append({"concert_id": it["concert_id"], "title_ja": it["title_ja"], "source_id": it["source_id"], "reason": "incomplete: " + ", ".join(it["blockers"])})
        else:
            qualify.append({"concert_id": it["concert_id"], "title_ja": it["title_ja"], "source_id": it["source_id"]})
    return {"qualify": qualify, "held": held, "outside_scope": other, "older_candidates": older}


def run(conn: sqlite3.Connection, now: datetime, *, apply: bool = False, max_confirm: int = DEFAULT_MAX, first_seen_after: str | None = None, presenters: bool = True) -> dict:
    p = plan(conn, now, first_seen_after, presenters)
    out = {"mode": "apply" if apply else "dry-run", "qualifying": len(p["qualify"]), "would_confirm": p["qualify"], "held": p["held"], "outside_scope": p["outside_scope"],
           "older_candidates": p["older_candidates"], "first_seen_after": first_seen_after, "presenters": presenters, "confirmed": [], "refused": {}, "flood_guard": False}
    if len(p["qualify"]) > max_confirm:
        out["flood_guard"] = True
        out["note"] = f"flood guard {'tripped' if apply else 'would trip'}: {len(p['qualify'])} concerts qualify, more than the limit {max_confirm}" + ("; nothing confirmed, a person should look" if apply else "")
        return out
    if apply and p["qualify"]:
        done = confirm_stored(conn, [q["concert_id"] for q in p["qualify"]], now)
        out["confirmed"], out["refused"] = done["confirmed"], done["failed"]
        live = set(done["confirmed"])
        out["went_live"] = [q for q in p["qualify"] if q["concert_id"] in live]  # title + source of each, for the job summary (a presenter's concert is published unseen by a person)
    return out
