"""POST /api/v1/import-url, backend half: validate -> fetch -> parse -> STAGE -> human confirm -> ingest.

Nothing here can create an ``official_confirmed`` row without ``confirm_import``. Only registered source hosts are accepted, so
the importer is not an open fetcher; it also refuses hosts that resolve to non-global addresses. Known limit: DNS is resolved
before the request and again by the HTTP client (TOCTOU); redirects are re-validated host-by-host by ``Reader`` but a hostile DNS
answer between the two lookups is not defended against. The importer is a fallback for sources whose terms allow the page to be
read by the user; it must not be used to get around an access restriction (401/403/429 stop the source in ``Reader``).
"""
from __future__ import annotations

import ipaddress
import json
import socket
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import db
from .contract import compact_candidate
from .ingest import Confirmation, ingest_source, iso
from .network import FetchError, Reader
from .parsers import ParseError, parse_presenter_detail
from .sources import DEFERRED, SOURCES

DETAIL_ADAPTERS = {"japanarts", "kajimoto", "yomikyo"}


class ImportRejected(ValueError):
    pass


def _host_map() -> dict[str, str]:
    out = {}
    for sid, src in SOURCES.items():
        host = urlsplit(src.url).hostname
        for h in {host, host.removeprefix("www."), "www." + host.removeprefix("www.")}:
            out[h] = sid
    return out


def validate_url(url: str, resolver=socket.getaddrinfo) -> tuple[str, str]:
    p = urlsplit(url)
    if p.scheme != "https" or p.username or p.password or p.port not in (None, 443) or not p.hostname:
        raise ImportRejected("only plain https URLs on the default port are accepted")
    sid = _host_map().get(p.hostname)
    if sid is None:
        raise ImportRejected("host is not a registered source")
    if sid in DEFERRED:
        raise ImportRejected(f"{sid} is deferred by the user (ADR-0001)")
    if sid not in DETAIL_ADAPTERS:
        raise ImportRejected(f"no detail adapter for {sid} yet; cannot extract candidate fields")
    try:
        infos = resolver(p.hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ImportRejected(f"host does not resolve: {exc}") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ImportRejected("host resolves to a non-public address")
    return sid, p.hostname


def stage_import(conn: sqlite3.Connection, url: str, reader: Reader, now: datetime, resolver=socket.getaddrinfo) -> dict:
    sid, host = validate_url(url, resolver)
    try:
        body, meta = reader.get(url, host)
    except FetchError as exc:
        raise ImportRejected(f"fetch failed: {exc}") from exc
    if meta["status"] != 200:
        raise ImportRejected(f"HTTP {meta['status']}")
    try:
        parsed = parse_presenter_detail(sid, body, meta["url"], iso(now))
    except ParseError as exc:
        raise ImportRejected(f"no performances could be extracted: {exc}") from exc
    import_id = db.new_id()
    conn.execute("INSERT INTO import_candidate VALUES (?,?,?,?,?,?, 'pending', NULL, NULL)",
                 (import_id, meta["url"], sid, iso(now), meta["sha256"], json.dumps(parsed["performances"], ensure_ascii=False)))
    conn.commit()
    return {"import_id": import_id, "source_id": sid, "url": meta["url"], "content_hash": meta["sha256"], "performances": [compact_candidate(x) for x in parsed["performances"]],
            "ticket_claims_unlinked": len(parsed["ticket_claims"])}


def confirm_import(conn: sqlite3.Connection, import_id: str, now: datetime, *, category: str, prefecture_overrides: dict[str, str] | None = None,
                   note: str | None = None) -> dict:
    row = conn.execute("SELECT * FROM import_candidate WHERE id=?", (import_id,)).fetchone()
    if row is None or row["status"] != "pending":
        raise ImportRejected("no pending import with this id")
    cands = json.loads(row["candidates_json"])
    result = ingest_source(conn, row["source_id"], cands, now, complete=True, content_hash=row["content_hash"],
                           confirm=Confirmation(at=now, category=category, prefecture_overrides=prefecture_overrides or {}, note=note))
    if result["status"] == "succeeded":
        conn.execute("UPDATE import_candidate SET status='confirmed', decided_at=?, decision_note=? WHERE id=?", (iso(now), note, import_id))
        conn.commit()
    return result


def reject_import(conn: sqlite3.Connection, import_id: str, now: datetime, note: str | None = None) -> None:
    cur = conn.execute("UPDATE import_candidate SET status='rejected', decided_at=?, decision_note=? WHERE id=? AND status='pending'", (iso(now), note, import_id))
    conn.commit()
    if cur.rowcount != 1:
        raise ImportRejected("no pending import with this id")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
