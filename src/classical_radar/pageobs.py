"""What a detail page says about WHEN it was published / last modified, recorded at every fetch (ADR-0004).

P0.3 found machine-readable stamps on 5 of 8 sources (JSON-LD ``dateModified``, ``article:modified_time``, ``og:updated_time``). The page's
modified time is the only handle on ``official_change_known_at`` there is: it says when the CMS last saved the page. It is NOT proof of a
material change (any edit moves it) and it is absent on 3 sources. ``monitor.report`` uses it only to put a real number next to a
change when it exists. Nothing here writes ``official_announcement_date``.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .announcement import signals
from .db import new_id
from .parsers import canonical

_PUBLISHED = ("json_ld_published", "meta_published", "itemprop_published", "labelled_published")
_MODIFIED = ("json_ld_modified", "meta_modified", "labelled_updated")


def _pick(page_signals: list[dict], kinds: tuple[str, ...]) -> str | None:
    for kind in kinds:  # machine-readable first, a visible label last
        for s in page_signals:
            if s["kind"] == kind:
                return _stamp(s["value"], s["date"])
    return None


def _stamp(value: str, date: str) -> str:
    """ISO UTC timestamp when the page gave a time of day, otherwise the bare date (precision is visible in the string length)."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return date
    if "T" not in value and " " not in value.strip():
        return date
    jst = timezone(timedelta(hours=9))  # a stamp without a zone on a Japanese site is read as JST
    return (dt.replace(tzinfo=jst) if dt.tzinfo is None else dt).astimezone(timezone.utc).isoformat(timespec="seconds")


def page_times(html: str) -> tuple[str | None, str | None]:
    sig = signals(html)
    return _pick(sig, _PUBLISHED), _pick(sig, _MODIFIED)


def record_page(conn: sqlite3.Connection, source_id: str, url: str, html: str, observed_at: datetime) -> None:
    """Store this fetch's stamps (idempotent per source/url/run). Does not commit."""
    published, modified = page_times(html)
    conn.execute("INSERT OR IGNORE INTO page_observation (id,source_id,url,observed_at,page_published_at,page_modified_at) VALUES (?,?,?,?,?,?)",
                 (new_id(), source_id, canonical(url), observed_at.astimezone(timezone.utc).isoformat(), published, modified))
