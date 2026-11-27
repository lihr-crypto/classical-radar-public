"""T13 (reminder scheduling with a local FAKE sender): see ADR-0002. No test here touches the network."""
import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unittest import mock

from classical_radar import db, personal, reminders, sync
from classical_radar.cli import main
from classical_radar.discover import concert_detail
from classical_radar.ingest import Confirmation, ingest_source, ingest_ticket_phases
from classical_radar.parsers import candidate
from classical_radar.reminders import FakeSender

UTC = timezone.utc
NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)
SALE = datetime(2026, 12, 1, 1, 0, tzinfo=UTC)  # 10:00 JST
USER = "u1"


def seed(conn):
    """One official-confirmed concert with one performance; returns (concert_id, performance poc id)."""
    c = candidate("japanarts", "https://www.japanarts.co.jp/concert/p1/", "公演1", "2027年1月10日 19:00", "サントリーホール")
    ingest_source(conn, "japanarts", [c], NOW, complete=True, confirm=Confirmation(at=NOW))
    row = conn.execute("SELECT c.id, p.poc_performance_id FROM concert c JOIN performance p ON p.concert_id=c.id").fetchone()
    return row[0], row[1]


def phase(poc_id, when=SALE, *, precision="exact_time", channel="official", phase_type="general_sale"):
    return {"performance_id": poc_id, "phase_type": phase_type, "channel": channel, "eligibility": None,
            "starts_at": when.isoformat() if precision == "exact_time" else None, "start_precision": precision,
            "current_status": "announced", "label_raw": "一般発売"}


def phases_of(conn):
    return {r["phase_type"]: r["id"] for r in conn.execute("SELECT id, phase_type FROM ticket_phase")}


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        db.init(self.conn)
        self.cid, self.poc = seed(self.conn)
        ingest_ticket_phases(self.conn, "japanarts", [phase(self.poc)], "https://www.japanarts.co.jp/news/1", NOW)
        self.tid = phases_of(self.conn)["general_sale"]

    def on(self, offset=60, now=NOW, tid=None, enabled=True):
        return personal.put_reminder(self.conn, USER, tid or self.tid, "sale_start", offset, enabled, now)

    def rows(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM notification_delivery ORDER BY scheduled_for, dedupe_key")]

    def by_status(self, status):
        return [r for r in self.rows() if r["status"] == status]

    # --- scheduling ---------------------------------------------------------------------------------
    def test_enabling_schedules_exactly_one_delivery_and_repeats_never_add_another(self):
        self.on(60)
        (row,) = self.rows()
        self.assertEqual((row["status"], row["scheduled_for"]), ("pending", "2026-12-01T00:00:00+00:00"))  # 60 min before 10:00 JST
        self.assertTrue(row["dedupe_key"].startswith("rem:"))
        self.on(60)
        reminders.reconcile_all(self.conn, NOW)
        reminders.reconcile_all(self.conn, NOW)
        self.assertEqual([r["id"] for r in self.rows()], [row["id"]])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM reminder_subscription").fetchone()[0], 1)

    def test_changing_the_offset_invalidates_the_old_delivery_and_going_back_reuses_it(self):
        self.on(60)
        old = self.rows()[0]
        self.on(15)
        self.assertEqual({r["scheduled_for"]: r["status"] for r in self.rows()}, {"2026-12-01T00:00:00+00:00": "cancelled", "2026-12-01T00:45:00+00:00": "pending"})
        self.on(60)  # A -> B -> A: the old key comes back to life instead of violating UNIQUE(dedupe_key)
        self.assertEqual({r["status"] for r in self.by_status("pending")}, {"pending"})
        self.assertEqual([r["id"] for r in self.by_status("pending")], [old["id"]])
        self.assertEqual(len(self.rows()), 2)

    def test_a_time_change_from_ingest_reschedules(self):
        self.on(60)
        moved = SALE + timedelta(days=1)
        ingest_ticket_phases(self.conn, "japanarts", [phase(self.poc, moved)], "https://www.japanarts.co.jp/news/1", NOW + timedelta(hours=1))
        self.assertEqual({r["scheduled_for"]: r["status"] for r in self.rows()}, {"2026-12-01T00:00:00+00:00": "cancelled", "2026-12-02T00:00:00+00:00": "pending"})

    def test_losing_the_exact_time_cancels(self):
        self.on(60)
        ingest_ticket_phases(self.conn, "japanarts", [phase(self.poc, precision="date_only")], "https://www.japanarts.co.jp/news/1", NOW)
        (row,) = self.rows()
        self.assertEqual(row["status"], "cancelled")
        self.assertIn("exact time", row["last_error"])

    def test_unsubscribing_cancels_and_subscribing_again_reuses_the_same_rows(self):
        first = self.on(60)
        self.on(60, enabled=False)
        self.assertEqual([r["status"] for r in self.rows()], ["cancelled"])
        again = self.on(60)
        self.assertEqual(again["id"], first["id"])
        self.assertEqual([r["status"] for r in self.rows()], ["pending"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM reminder_subscription").fetchone()[0], 1)

    def test_a_cancelled_or_postponed_performance_drops_its_delivery(self):
        for status in ("cancelled", "postponed", "needs_review"):
            self.conn.execute("UPDATE performance SET status='scheduled'")
            self.on(60)
            self.assertEqual(len(self.by_status("pending")), 1, status)
            self.conn.execute("UPDATE performance SET status=?", (status,))
            reminders.reconcile_all(self.conn, NOW)
            self.assertEqual(self.by_status("pending"), [], status)
            self.assertIn(status, self.by_status("cancelled")[0]["last_error"])

    # --- gates --------------------------------------------------------------------------------------
    def test_only_official_sales_channels_with_a_future_exact_time_can_be_switched_on(self):
        ingest_ticket_phases(self.conn, "japanarts", [phase(self.poc, channel="other", phase_type="other")], "https://www.japanarts.co.jp/news/2", NOW)
        other = phases_of(self.conn)["other"]
        with self.assertRaisesRegex(ValueError, "not an official sales source"):
            self.on(60, tid=other)
        self.on(60, tid=other, enabled=False)  # switching off is always fine
        with self.assertRaisesRegex(ValueError, "already passed"):
            self.on(60, now=SALE + timedelta(hours=1))
        self.on(60, now=SALE + timedelta(minutes=5))  # still inside the grace window
        self.assertEqual(self.by_status("pending")[0]["status"], "pending")

    # --- running the fake sender --------------------------------------------------------------------
    def test_run_due_sends_once_and_never_again(self):
        self.on(60)
        with tempfile.TemporaryDirectory() as d:
            outbox = Path(d) / "out.jsonl"
            sender = FakeSender(outbox)
            early = reminders.run_due(self.conn, NOW, sender)
            self.assertEqual((early["sent"], early["not_due"]), (0, 1))
            due = reminders.run_due(self.conn, SALE - timedelta(minutes=60), sender)
            self.assertEqual((due["sent"], due["failed"]), (1, 0))
            (row,) = self.rows()
            self.assertEqual((row["status"], row["sent_at"]), ("sent", "2026-12-01T00:00:00+00:00"))
            self.assertTrue(row["provider_id"].startswith("fake:"))
            for _ in range(2):  # replays, a repeated subscribe call and a reconcile must not resend or re-create
                self.assertEqual(reminders.run_due(self.conn, SALE, sender)["sent"], 0)
                self.on(60, now=SALE - timedelta(minutes=30))
                reminders.reconcile_all(self.conn, SALE)
            self.assertEqual(len(self.rows()), 1)
            lines = [json.loads(x) for x in outbox.read_text().splitlines()]
            self.assertEqual(len(lines), 1)
            self.assertEqual((lines[0]["milestone"], lines[0]["offset_minutes"], lines[0]["target_time"]), ("sale_start", 60, "2026-12-01T01:00:00+00:00"))
            self.assertIn("公演1", lines[0]["text"])

    def test_a_failed_send_is_recorded_and_retried_without_a_second_delivery(self):
        self.on(60)
        at = SALE - timedelta(minutes=30)
        did = self.rows()[0]["id"]
        self.assertEqual(reminders.run_due(self.conn, at, FakeSender(fail_ids={did}))["failed"], 1)
        (row,) = self.rows()
        self.assertEqual(row["status"], "failed")
        self.assertIn("simulated failure", row["last_error"])
        skipped = reminders.run_due(self.conn, at, FakeSender(), retry_failed=False)
        self.assertEqual((skipped["sent"], self.rows()[0]["status"]), (0, "failed"))
        retry = FakeSender()
        self.assertEqual(reminders.run_due(self.conn, at, retry)["sent"], 1)
        self.assertEqual((len(self.rows()), self.rows()[0]["status"], len(retry.sent)), (1, "sent", 1))

    def test_a_failed_row_is_not_retried_after_the_user_changed_or_dropped_the_reminder(self):
        self.on(60)
        at = SALE - timedelta(minutes=30)
        reminders.run_due(self.conn, at, FakeSender(fail_ids={self.rows()[0]["id"]}))
        self.on(15, now=at)  # new offset: the failed 60-minute row is stale
        sender = FakeSender()
        reminders.run_due(self.conn, SALE - timedelta(minutes=10), sender)
        self.assertEqual([d["offset_minutes"] for d in sender.sent], [15])
        self.assertEqual(sorted(r["status"] for r in self.rows()), ["cancelled", "sent"])

        self.on(30, now=at)
        reminders.run_due(self.conn, at, FakeSender(fail_ids={r["id"] for r in self.by_status("pending")}))
        self.assertEqual(len(self.by_status("failed")), 1)
        self.on(30, now=at, enabled=False)  # opt out after a failure
        sender = FakeSender()
        reminders.run_due(self.conn, SALE, sender)
        self.assertEqual((sender.sent, self.by_status("failed")), ([], []))

    def test_offset_zero_is_sent_at_the_milestone(self):
        self.on(0)
        sender = FakeSender()
        self.assertEqual(reminders.run_due(self.conn, SALE, sender)["sent"], 1)
        self.assertIn("现在", sender.sent[0]["text"])

    def test_a_missed_milestone_is_cancelled_not_sent_and_does_not_flap_back(self):
        self.on(60)
        late = SALE + reminders.GRACE + timedelta(minutes=1)
        sender = FakeSender()
        out = reminders.run_due(self.conn, late, sender)
        self.assertEqual((out["sent"], out["missed"]), (0, 1))
        for _ in range(3):
            reminders.reconcile_all(self.conn, late)
            reminders.run_due(self.conn, late, sender)
        (row,) = self.rows()
        self.assertEqual(row["status"], "cancelled")
        self.assertTrue(row["last_error"].startswith("missed"))
        self.assertEqual(sender.sent, [])

    def test_the_text_says_what_is_true_when_it_is_sent(self):
        self.on(60)
        sender = FakeSender()
        reminders.run_due(self.conn, SALE - timedelta(minutes=40), sender)
        self.assertIn("还有 40 分钟", sender.sent[0]["text"])
        self.on(60, enabled=False)
        self.on(30, now=SALE + timedelta(minutes=5))  # enabled late, inside the grace window: goes out at once, honestly worded
        late = FakeSender()
        reminders.run_due(self.conn, SALE + timedelta(minutes=5), late)
        self.assertIn("已经", late.sent[0]["text"])

    # --- sync -------------------------------------------------------------------------------------
    def test_sync_reconciles_when_a_source_finishes(self):
        self.on(60)
        self.conn.execute("UPDATE performance SET status='cancelled'")
        with mock.patch.object(sync, "_paged", return_value={"status": "succeeded"}):
            sync.sync_source(self.conn, None, "tso", NOW)
        self.assertEqual([r["status"] for r in self.rows()], ["cancelled"])

    def test_an_uncaught_sync_error_still_leaves_half_written_rows_uncommitted(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "s.db")
            conn = db.connect(path)
            db.init(conn)

            def boom(c, *a, **k):
                c.execute("INSERT INTO unverified_lead (id,source_url,text_summary,observed_at,review_status) VALUES ('x','https://x.example/','half','2026-11-04','new')")
                raise RuntimeError("boom")
            with mock.patch.object(sync, "_paged", side_effect=boom), self.assertRaises(RuntimeError):
                sync.sync_source(conn, None, "tso", NOW)
            other = db.connect(path)
            self.assertEqual(other.execute("SELECT COUNT(*) FROM unverified_lead").fetchone()[0], 0)
            other.close()
            conn.close()

    # --- read side, schema, CLI ---------------------------------------------------------------------
    def test_concert_detail_shows_each_user_only_their_own_reminder(self):
        def reminder(user):
            return concert_detail(self.conn, self.cid, user)["performances"][0]["ticket_phases"][0]["reminder"]
        self.assertIsNone(reminder(USER))
        self.on(60)
        self.assertEqual(reminder(USER), {"milestone": "sale_start", "offset_minutes": 60, "enabled": True})
        self.assertIsNone(reminder("someone-else"))
        self.assertIsNone(reminder(None))
        self.on(60, enabled=False)
        self.assertFalse(reminder(USER)["enabled"])

    def test_delivery_status_is_checked_and_init_repairs_an_old_database_with_duplicates(self):
        self.on(60)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE notification_delivery SET status='bogus'")
        sub = dict(self.conn.execute("SELECT * FROM reminder_subscription").fetchone())
        self.conn.execute("DROP INDEX ux_reminder_subscription")  # what a database created before ADR-0002 looks like
        self.conn.execute("INSERT INTO reminder_subscription VALUES ('dup',?,?,?,?,0)", (sub["user_id"], sub["ticket_phase_id"], sub["milestone"], 5))
        self.conn.execute("INSERT INTO notification_delivery (id,reminder_subscription_id,scheduled_for,dedupe_key,status) VALUES ('d2','dup','2026-12-01T00:55:00+00:00','rem:old','pending')")
        db.init(self.conn)
        self.assertEqual([r["id"] for r in self.conn.execute("SELECT id FROM reminder_subscription")], [sub["id"]])  # the enabled one is kept
        self.assertEqual(self.conn.execute("SELECT reminder_subscription_id FROM notification_delivery WHERE id='d2'").fetchone()[0], sub["id"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO reminder_subscription VALUES ('x',?,?,?,1,1)", (sub["user_id"], sub["ticket_phase_id"], sub["milestone"]))

    def test_remind_run_cli_uses_the_fake_sender_and_writes_the_outbox(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "r.db")
            conn = db.connect(path)
            db.init(conn)
            _, poc = seed(conn)
            ingest_ticket_phases(conn, "japanarts", [phase(poc)], "https://www.japanarts.co.jp/news/1", NOW)
            personal.put_reminder(conn, USER, phases_of(conn)["general_sale"], "sale_start", 60, True, NOW)
            conn.close()
            outbox = Path(d) / "out.jsonl"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main(["remind-run", path, "--now", "2026-12-01T00:00:00+00:00", "--outbox", str(outbox)])
            self.assertEqual(json.loads(out.getvalue())["sent"], 1)
            self.assertEqual(len(outbox.read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
