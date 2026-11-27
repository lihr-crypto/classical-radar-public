import unittest
from datetime import date, datetime, timedelta, timezone

from classical_radar import db, personal
from classical_radar.discover import add_months, concert_detail, coverage, discover
from classical_radar.ingest import Confirmation, ingest_source
from classical_radar.parsers import candidate

JST = timezone(timedelta(hours=9))
AS_OF = datetime(2026, 11, 4, 10, 0, tzinfo=JST)


def store():
    conn = db.connect()
    db.init(conn)
    unittest.addModuleCleanup(conn.close)
    return conn


def add(conn, n, raw, venue="サントリーホール", title=None, confirmed_at=AS_OF, source="japanarts", category=None, official_date=None, extra=()):
    c = [candidate(source, f"https://www.japanarts.co.jp/concert/p{n}/", title or f"公演{n}", r, venue) for r in (raw if isinstance(raw, list) else [raw])]
    ingest_source(conn, source, c, confirmed_at, complete=True, confirm=Confirmation(at=confirmed_at, category=category))
    if official_date:
        conn.execute("UPDATE concert SET official_announcement_date=? WHERE identity_key LIKE ?", (official_date, f"%p{n}"))
        conn.commit()


def ids(res):
    return [i["title_ja"] for i in res["items"]]


class WindowTests(unittest.TestCase):
    def test_add_months_is_calendar_based(self):
        self.assertEqual(add_months(date(2026, 11, 4), 12), date(2027, 11, 4))
        self.assertEqual(add_months(date(2028, 2, 29), 12), date(2029, 2, 28))
        self.assertEqual(add_months(date(2026, 8, 31), 6), date(2027, 2, 28))

    def test_t03_exact_time_before_now_excluded_date_only_today_kept_window_end_exclusive(self):
        c = store()
        add(c, 1, "2026年11月4日 09:00", title="今朝終了")
        add(c, 2, "2026年11月4日 19:00", title="今夜")
        add(c, 3, "2026年11月4日", title="日付のみ今日")
        add(c, 4, "2027年11月3日 19:00", title="12か月内最終日")
        add(c, 5, "2027年11月4日 19:00", title="境界(含まない)")
        r12 = discover(c, as_of=AS_OF)
        self.assertEqual(set(ids(r12)), {"今夜", "日付のみ今日", "12か月内最終日"})
        self.assertEqual(r12["window"], {"from": "2026-11-04", "to_exclusive": "2027-11-04"})
        self.assertIn("境界(含まない)", ids(discover(c, as_of=AS_OF, months=24)))

    def test_only_confirmed_japan_noncancelled_appear(self):
        c = store()
        ingest_source(c, "japanarts", [candidate("japanarts", "https://www.japanarts.co.jp/concert/p9/", "未確認", "2027年1月1日 19:00", "サントリーホール")], AS_OF, complete=True)
        add(c, 10, "2027年1月2日 19:00", title="確認済")
        add(c, 11, "2027年1月3日 19:00", title="中止")
        c.execute("UPDATE performance SET status='cancelled' WHERE concert_id=(SELECT id FROM concert WHERE identity_key LIKE '%p11')")
        c.commit()
        self.assertEqual(ids(discover(c, as_of=AS_OF)), ["確認済"])

    def test_unsupported_parameters_rejected(self):
        c = store()
        for kw in ({"months": 6}, {"category": "rock"}, {"region_mode": "x"}, {"limit": 0}, {"page": 0}):
            with self.assertRaises(ValueError):
                discover(c, as_of=AS_OF, **kw)


class OrderingTests(unittest.TestCase):
    def setUp(self):
        self.c = store()
        add(self.c, 1, "2027年1月10日 19:00", venue="フェスティバルホール(大阪)", title="大阪(本日収録)", confirmed_at=datetime(2026, 11, 4, 9, 0, tzinfo=JST))
        add(self.c, 2, "2027年1月11日 19:00", venue="サントリーホール", title="東京(昨日収録)", confirmed_at=datetime(2026, 11, 3, 9, 0, tzinfo=JST))

    def test_t04_kanto_bucket_precedes_newer_announcement_and_nationwide_sorts_by_announcement(self):
        self.assertEqual(ids(discover(self.c, as_of=AS_OF)), ["東京(昨日収録)", "大阪(本日収録)"])
        self.assertEqual([i["region_group"] for i in discover(self.c, as_of=AS_OF)["items"]], ["kanto", "rest_of_japan"])
        nat = discover(self.c, as_of=AS_OF, region_mode="nationwide")
        self.assertEqual(ids(nat), ["大阪(本日収録)", "東京(昨日収録)"])
        self.assertEqual(nat["groups"], [])

    def test_t05_fallback_is_labelled_first_collected_and_official_date_wins(self):
        add(self.c, 3, "2027年1月12日 19:00", title="官方公布日あり", official_date="2026-10-01")
        by = {i["title_ja"]: i for i in discover(self.c, as_of=AS_OF)["items"]}
        self.assertEqual((by["東京(昨日収録)"]["announcement_basis"], by["東京(昨日収録)"]["announcement_label"]), ("first_verified_fallback", "首次收录"))
        self.assertEqual((by["官方公布日あり"]["announcement_basis"], by["官方公布日あり"]["announcement_sort_date"]), ("official", "2026-10-01"))
        self.assertEqual(by["東京(昨日収録)"]["announcement_sort_date"], "2026-11-03")

    def test_t05_same_day_tie_is_broken_by_nearest_performance_then_id_and_page_is_stable(self):
        c = store()
        for n, raw in ((1, "2027年3月1日 19:00"), (2, "2027年2月1日 19:00"), (3, "2027年2月1日 19:00")):
            add(c, n, raw, title=f"同日{n}", confirmed_at=AS_OF)
        res = discover(c, as_of=AS_OF)
        self.assertEqual(ids(res)[0:2].count("同日1"), 0)  # later performance sorts last
        self.assertEqual(ids(res)[2], "同日1")
        p1 = ids(discover(c, as_of=AS_OF, limit=2, page=1)) + ids(discover(c, as_of=AS_OF, limit=2, page=2))
        self.assertEqual(p1, ids(res))
        self.assertEqual(res["total"], 3)

    def test_every_item_names_its_organiser_and_it_matches_the_detail(self):
        from classical_radar.discover import concert_detail
        c = store()
        add(c, 1, "2027年1月10日 19:00", title="主催あり", source="japanarts")
        item = discover(c, as_of=AS_OF)["items"][0]
        self.assertEqual(item["organization_id"], "japanarts")
        self.assertEqual(concert_detail(c, item["concert_id"])["concert"]["organization_id"], item["organization_id"])
        # the calendar and the pickup list sign their rows the same way
        from classical_radar.discover import calendar_range
        cal = calendar_range(c, date(2027, 1, 10), date(2027, 1, 10))
        self.assertEqual([p["organization_id"] for p in cal["performances"]], ["japanarts"])
        personal.put_pickup(c, "u1", item["concert_id"])
        self.assertEqual([x["organization_id"] for x in personal.list_pickups(c, "u1")], ["japanarts"])
        pid = c.execute("SELECT id FROM performance").fetchone()[0]  # a sale row names its concert's kind inputs too
        c.execute("INSERT OR IGNORE INTO source_document VALUES ('d1','japanarts','https://x.example/a','announcement',NULL,'2026-11-04','2026-11-04',NULL,'unknown')")
        c.execute("INSERT INTO ticket_phase (id,performance_id,phase_type,channel,starts_at,start_precision,end_precision,current_status,source_document_id) VALUES "
                  "('t1',?,'general_sale','official','2026-12-01T01:00:00+00:00','exact_time','unknown','announced','d1')", (pid,))
        c.commit()
        sale = calendar_range(c, date(2026, 12, 1), date(2026, 12, 1))["sales"][0]
        self.assertEqual((sale["organization_id"], sale["category"]), ("japanarts", item["category"]))
        c.execute("UPDATE concert SET organization_id=NULL")
        c.commit()
        self.assertIsNone(discover(c, as_of=AS_OF)["items"][0]["organization_id"])  # unknown stays null, never guessed

    def test_t06_two_performances_one_card_with_independent_venues(self):
        c = store()
        add(c, 1, ["2027年1月10日 19:00", "2027年1月12日 19:00"], title="東京と大阪", venue="サントリーホール")
        # second performance at another venue, same concert page
        ingest_source(c, "japanarts", [candidate("japanarts", "https://www.japanarts.co.jp/concert/p1/", "東京と大阪", "2027年1月14日 19:00", "フェスティバルホール(大阪)")],
                      AS_OF, complete=False, confirm=Confirmation(at=AS_OF))
        res = discover(c, as_of=AS_OF)
        self.assertEqual(res["total"], 1)
        item = res["items"][0]
        self.assertEqual(len(item["performance_ids"]), 3)
        self.assertEqual({p["prefecture_code"] for p in item["performances"]}, {"13", "27"})
        self.assertEqual(item["region_group"], "kanto")  # any Kanto performance puts the card in the Kanto bucket

    def test_category_filter_and_coverage_do_not_claim_percentages(self):
        add(self.c, 4, "2027年1月13日 14:00", title="ピアノ", category="piano_recital")
        self.assertEqual(ids(discover(self.c, as_of=AS_OF, category="piano_recital")), ["ピアノ"])
        cov = coverage(self.c)
        row = cov["sources"][0]
        self.assertEqual((row["source_id"], row["concerts_official_confirmed"], row["latest_run_status"]), ("japanarts", 3, "succeeded"))
        self.assertNotIn("%", str(cov))


class PersonalStateTests(unittest.TestCase):
    def test_t12_pickup_is_one_row_per_concert_and_never_enables_reminders_or_changes_other_performances(self):
        c = store()
        add(c, 1, ["2027年1月10日 19:00", "2027年1月12日 19:00"], title="二日公演")
        cid = c.execute("SELECT id FROM concert").fetchone()[0]
        a, b = [r[0] for r in c.execute("SELECT id FROM performance ORDER BY local_date")]
        personal.put_pickup(c, "u1", cid, "high")
        personal.put_pickup(c, "u1", cid, "normal", "メモ")
        self.assertEqual(c.execute("SELECT COUNT(*), MAX(priority) FROM user_pickup").fetchone()[:], (1, "normal"))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM reminder_subscription").fetchone()[0], 0)
        personal.put_performance_state(c, "u1", a, "purchased")
        self.assertEqual(c.execute("SELECT COUNT(*) FROM user_performance_state WHERE performance_id=?", (b,)).fetchone()[0], 0)
        self.assertTrue(discover(c, as_of=AS_OF, user_id="u1")["items"][0]["user_pickup"])
        self.assertFalse(discover(c, as_of=AS_OF, user_id="u2")["items"][0]["user_pickup"])
        self.assertTrue(personal.delete_pickup(c, "u1", cid))
        with self.assertRaises(ValueError):
            personal.put_performance_state(c, "u1", a, "bought")

    def test_an_existing_database_without_the_plan_table_gets_it_when_opened(self):
        import os, tempfile
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        conn = db.connect(path)
        db.init(conn)
        conn.execute("DROP TABLE user_plan")  # the shape of every database made before ADR-0012 (the cloud database in the Release included)
        conn.commit()
        conn.close()
        conn = db.connect(path)
        db.init(conn)  # what every run does when it opens the database
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM user_plan").fetchone()[0], 0)  # created by CREATE TABLE IF NOT EXISTS: no migration step
        conn.close()

    def test_plan_to_attend_is_one_row_per_user_and_concert_and_separate_from_pickup_and_states(self):
        c = store()
        add(c, 1, ["2027年1月10日 19:00", "2027年1月12日 19:00"], title="二日公演")
        cid = c.execute("SELECT id FROM concert").fetchone()[0]
        a = c.execute("SELECT id FROM performance ORDER BY local_date").fetchone()[0]
        personal.put_plan(c, "u1", cid)
        personal.put_plan(c, "u1", cid)  # again: still one row, the first date is kept
        self.assertEqual(c.execute("SELECT COUNT(*) FROM user_plan").fetchone()[0], 1)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM user_pickup").fetchone()[0], 0)  # a plan is not a pickup
        self.assertEqual(c.execute("SELECT COUNT(*) FROM user_performance_state").fetchone()[0], 0)  # and sets no per-date status
        self.assertEqual(c.execute("SELECT COUNT(*) FROM reminder_subscription").fetchone()[0], 0)
        personal.put_performance_state(c, "u1", a, "purchased")
        row = personal.list_plans(c, "u1")[0]
        self.assertEqual((row["concert_id"], [p["user_status"] for p in row["performances"]]), (cid, ["purchased", None]))
        self.assertNotIn("priority", row)
        self.assertEqual(personal.list_plans(c, "u2"), [])  # another user sees none
        self.assertTrue(concert_detail(c, cid, "u1")["user_plan"])
        self.assertFalse(concert_detail(c, cid, "u2")["user_plan"])
        with self.assertRaises(LookupError):
            personal.put_plan(c, "u1", "unknown")
        self.assertTrue(personal.delete_plan(c, "u1", cid))
        self.assertFalse(personal.delete_plan(c, "u1", cid))
        self.assertEqual(personal.list_plans(c, "u1"), [])

    def test_pickup_requires_a_confirmed_concert(self):
        c = store()
        ingest_source(c, "japanarts", [candidate("japanarts", "https://www.japanarts.co.jp/concert/p5/", "候補", "2027年1月1日 19:00", "サントリーホール")], AS_OF, complete=True)
        cid = c.execute("SELECT id FROM concert").fetchone()[0]
        with self.assertRaises(LookupError):
            personal.put_pickup(c, "u1", cid)


if __name__ == "__main__":
    unittest.main()
