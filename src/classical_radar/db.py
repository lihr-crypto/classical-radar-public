"""SQLite schema for the 03_CONTRACTS entities (ADR-0001). Names and enums match the contract; times are UTC ISO-8601 text.

Rules that need cross-field context (exact_time <-> starts_at, confirmed needs prefecture ...) are enforced in Python
by ``contract`` before a row is written; CHECK constraints below cover the enums so a typo cannot be stored.
"""
from __future__ import annotations

import sqlite3
import uuid

SCHEMA_VERSION = 1

_ENUMS = {
    "category": "('domestic_orchestra','overseas_orchestra_visit','piano_recital','other')",
    "verification": "('official_confirmed','needs_review')",
    "precision": "('exact_time','date_only','month_only','unknown')",
    "perf_status": "('scheduled','postponed','cancelled','completed','needs_review')",
    "ticket_status": "('not_announced','announced','open','closed','unknown')",
    "role": "('conductor','recital_headliner','concerto_soloist','other')",
    "policy": "('permitted','restricted','unknown','blocked')",
    "phase_type": "('member_presale','general_sale','lottery','additional_sale','other')",
    "channel": "('official','official_presenter','other')",
    "doc_kind": "('list','detail','announcement','calendar','import')",
    "user_status": "('interested','planning','applied','won','purchased','skipped','attended')",
    "delivery_status": "('pending','sent','failed','cancelled')",
}

DDL = f"""
CREATE TABLE IF NOT EXISTS schema_info (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS organization (id TEXT PRIMARY KEY, source_id TEXT NOT NULL UNIQUE, name_ja TEXT NOT NULL, official_url TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artist (id TEXT PRIMARY KEY, name_ja TEXT NOT NULL, verified_aliases TEXT);
CREATE TABLE IF NOT EXISTS source_document (
  id TEXT PRIMARY KEY, source_id TEXT NOT NULL, url TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN {_ENUMS['doc_kind']}),
  published_on TEXT, first_seen_at TEXT NOT NULL, last_verified_at TEXT NOT NULL, content_hash TEXT,
  policy_status TEXT NOT NULL CHECK (policy_status IN {_ENUMS['policy']}), UNIQUE (source_id, url));
CREATE TABLE IF NOT EXISTS concert (
  id TEXT PRIMARY KEY, identity_key TEXT NOT NULL UNIQUE, organization_id TEXT,
  category TEXT NOT NULL CHECK (category IN {_ENUMS['category']}), title_ja TEXT NOT NULL,
  official_announcement_date TEXT, first_verified_at TEXT NOT NULL, last_material_change_at TEXT,
  verification_status TEXT NOT NULL CHECK (verification_status IN {_ENUMS['verification']}));
CREATE TABLE IF NOT EXISTS program_item (id TEXT PRIMARY KEY, concert_id TEXT NOT NULL REFERENCES concert(id), position INTEGER NOT NULL,
  raw_text TEXT NOT NULL, composer_display TEXT, composer_key TEXT, work_display TEXT, work_key TEXT);
CREATE TABLE IF NOT EXISTS concert_artist (id TEXT PRIMARY KEY, concert_id TEXT NOT NULL REFERENCES concert(id), artist_id TEXT,
  name_display TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN {_ENUMS['role']}));
CREATE TABLE IF NOT EXISTS performance (
  id TEXT PRIMARY KEY, concert_id TEXT NOT NULL REFERENCES concert(id), starts_at TEXT, local_date TEXT,
  date_precision TEXT NOT NULL CHECK (date_precision IN {_ENUMS['precision']}), country_code TEXT NOT NULL DEFAULT 'JP',
  prefecture_code TEXT, venue_name TEXT NOT NULL,
  confirmation_status TEXT NOT NULL CHECK (confirmation_status IN {_ENUMS['verification']}),
  status TEXT NOT NULL CHECK (status IN {_ENUMS['perf_status']}),
  poc_performance_id TEXT, last_seen_at TEXT);
CREATE INDEX IF NOT EXISTS performance_concert ON performance(concert_id);
CREATE TABLE IF NOT EXISTS ticket_phase (
  id TEXT PRIMARY KEY, performance_id TEXT NOT NULL REFERENCES performance(id),
  phase_type TEXT NOT NULL CHECK (phase_type IN {_ENUMS['phase_type']}), channel TEXT NOT NULL CHECK (channel IN {_ENUMS['channel']}),
  eligibility TEXT, starts_at TEXT, ends_at TEXT, result_at TEXT, payment_due_at TEXT,
  start_precision TEXT NOT NULL CHECK (start_precision IN {_ENUMS['precision']}),
  end_precision TEXT NOT NULL CHECK (end_precision IN {_ENUMS['precision']}),
  current_status TEXT NOT NULL CHECK (current_status IN {_ENUMS['ticket_status']}),
  source_document_id TEXT NOT NULL REFERENCES source_document(id));
CREATE TABLE IF NOT EXISTS source_claim (
  id TEXT PRIMARY KEY, source_document_id TEXT NOT NULL REFERENCES source_document(id), entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  field_path TEXT NOT NULL, raw_value TEXT, normalized_value TEXT, verified_at TEXT NOT NULL,
  verification_status TEXT NOT NULL CHECK (verification_status IN {_ENUMS['verification']}));
CREATE TABLE IF NOT EXISTS change_event (
  id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, field_path TEXT NOT NULL,
  before_json TEXT, after_json TEXT, source_claim_id TEXT REFERENCES source_claim(id), detected_at TEXT NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS tour_announcement (id TEXT PRIMARY KEY, official_source_document_id TEXT NOT NULL REFERENCES source_document(id),
  organizer_or_artist_name TEXT NOT NULL, declared_range TEXT, linked_concert_id TEXT);
CREATE TABLE IF NOT EXISTS unverified_lead (id TEXT PRIMARY KEY, source_url TEXT NOT NULL, text_summary TEXT NOT NULL, observed_at TEXT NOT NULL, review_status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_pickup (user_id TEXT NOT NULL, concert_id TEXT NOT NULL REFERENCES concert(id), priority TEXT NOT NULL CHECK (priority IN ('normal','high')),
  notes TEXT, created_at TEXT NOT NULL, PRIMARY KEY (user_id, concert_id));
CREATE TABLE IF NOT EXISTS user_plan (user_id TEXT NOT NULL, concert_id TEXT NOT NULL REFERENCES concert(id), created_at TEXT NOT NULL, PRIMARY KEY (user_id, concert_id));
CREATE TABLE IF NOT EXISTS user_performance_state (user_id TEXT NOT NULL, performance_id TEXT NOT NULL REFERENCES performance(id),
  status TEXT NOT NULL CHECK (status IN {_ENUMS['user_status']}), notes TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (user_id, performance_id));
CREATE TABLE IF NOT EXISTS reminder_subscription (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, ticket_phase_id TEXT NOT NULL REFERENCES ticket_phase(id),
  milestone TEXT NOT NULL, offset_minutes INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS notification_delivery (id TEXT PRIMARY KEY, reminder_subscription_id TEXT NOT NULL REFERENCES reminder_subscription(id),
  scheduled_for TEXT NOT NULL, dedupe_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL CHECK (status IN {_ENUMS['delivery_status']}), sent_at TEXT, provider_id TEXT, last_error TEXT);
CREATE INDEX IF NOT EXISTS ix_delivery_status ON notification_delivery (status, scheduled_for);
-- not in 03_CONTRACTS: second-hand overseas-orchestra tour leads (ADR-0007). Never an official concert; facts only.
CREATE TABLE IF NOT EXISTS tour_lead (id TEXT PRIMARY KEY, source_id TEXT NOT NULL, year INTEGER, orchestra_key TEXT, orchestra_name TEXT NOT NULL, period_raw TEXT NOT NULL,
  date_from TEXT, date_to TEXT, month_hint TEXT, cities_raw TEXT, conductor TEXT, soloists TEXT, article_url TEXT, performances TEXT NOT NULL DEFAULT '[]',
  first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, last_changed_at TEXT NOT NULL, article_read_at TEXT);
-- one row per year page that was read to the end: a lead of that year not seen in that reading has dropped off the page. A reading that stops early records nothing.
CREATE TABLE IF NOT EXISTS lead_page_read (source_id TEXT NOT NULL, year INTEGER NOT NULL, read_at TEXT NOT NULL, PRIMARY KEY (source_id, year));
-- not in 03_CONTRACTS: reviewer decisions about cross-source duplicate hints (ADR-0003). duplicate_of: concert_id is the same show as other_concert_id;
-- different: not the same show (stored once, in sorted order)
CREATE TABLE IF NOT EXISTS duplicate_review (concert_id TEXT NOT NULL REFERENCES concert(id) ON DELETE CASCADE, other_concert_id TEXT NOT NULL REFERENCES concert(id) ON DELETE CASCADE,
  decision TEXT NOT NULL CHECK (decision IN ('duplicate_of','different')), decided_at TEXT NOT NULL, PRIMARY KEY (concert_id, other_concert_id));
-- not in 03_CONTRACTS: what a detail page itself said about its publication / last-modified time when we fetched it (P0.3 found machine-readable
-- stamps on 5 of 8 sources). Only the monitoring report reads it; it never fills official_announcement_date.
CREATE TABLE IF NOT EXISTS page_observation (id TEXT PRIMARY KEY, source_id TEXT NOT NULL, url TEXT NOT NULL, observed_at TEXT NOT NULL,
  page_published_at TEXT, page_modified_at TEXT, UNIQUE (source_id, url, observed_at));
CREATE TABLE IF NOT EXISTS ingestion_run (id TEXT PRIMARY KEY, source_id TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')), counts_json TEXT, error_summary TEXT);
-- not in 03_CONTRACTS: staging area for POST /import-url (human confirmation required before anything becomes official_confirmed)
CREATE TABLE IF NOT EXISTS import_candidate (id TEXT PRIMARY KEY, url TEXT NOT NULL, source_id TEXT NOT NULL, fetched_at TEXT NOT NULL, content_hash TEXT NOT NULL,
  candidates_json TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('pending','confirmed','rejected')), decided_at TEXT, decision_note TEXT);
"""


def new_id() -> str:
    return uuid.uuid4().hex


def connect(path: str = ":memory:", *, shared_thread: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=not shared_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _collapse_duplicate_subscriptions(conn: sqlite3.Connection) -> None:
    """Older databases only had an application-level "one subscription per (user, phase, milestone)" rule (select, then insert), so
    a race could have left duplicates. Keep one (an enabled one if any), repoint its deliveries, drop the rest, so the unique index can be built."""
    groups = conn.execute("SELECT user_id, ticket_phase_id, milestone FROM reminder_subscription GROUP BY 1, 2, 3 HAVING COUNT(*) > 1").fetchall()
    for g in groups:
        ids = [r["id"] for r in conn.execute("SELECT id FROM reminder_subscription WHERE user_id=? AND ticket_phase_id=? AND milestone=? ORDER BY enabled DESC, rowid",
                                             (g["user_id"], g["ticket_phase_id"], g["milestone"]))]
        for dup in ids[1:]:
            conn.execute("UPDATE notification_delivery SET reminder_subscription_id=? WHERE reminder_subscription_id=?", (ids[0], dup))
            conn.execute("DELETE FROM reminder_subscription WHERE id=?", (dup,))


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS never adds a column to a table an older database already has."""
    if "year" not in {r["name"] for r in conn.execute("PRAGMA table_info(tour_lead)")}:
        conn.execute("ALTER TABLE tour_lead ADD COLUMN year INTEGER")


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    _add_missing_columns(conn)
    _collapse_duplicate_subscriptions(conn)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_reminder_subscription ON reminder_subscription (user_id, ticket_phase_id, milestone)")
    if conn.execute("SELECT COUNT(*) FROM schema_info").fetchone()[0] == 0:
        conn.execute("INSERT INTO schema_info VALUES (?)", (SCHEMA_VERSION,))
    conn.commit()
