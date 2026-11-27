"""Cross-source duplicate review (ADR-0003): hints, reversible decisions, nothing merged. No network."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from classical_radar import db, duplicates
from classical_radar.api import create_app
from classical_radar.ingest import Confirmation, confirm_stored, ingest_source, review_candidates
from classical_radar.parsers import candidate

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)
TOKEN = "t" * 24
H = {"Authorization": f"Bearer {TOKEN}"}
GEIKYO = "https://kanagawa-geikyo.com/concert/concert-9615/"
JAPANARTS = "https://www.japanarts.co.jp/concert/p2267/"


def cand(source, url, title, date="2027年3月4日 19:00", venue="ミューザ川崎シンフォニーホール", artists=()):
    c = candidate(source, url, title, date, venue)
    c["artists_items"] = [{"name_display": a, "role": "recital_headliner"} for a in artists]
    return c


def load(conn, *cands, confirm=False):
    for c in cands:
        ingest_source(conn, c["source_id"], [c], NOW, complete=True, confirm=Confirmation(at=NOW) if confirm else None)


def cid(conn, url_part):
    return conn.execute("SELECT id FROM concert WHERE identity_key LIKE ?", (f"%{url_part}",)).fetchone()[0]


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        db.init(self.conn)
        load(self.conn,
             cand("japanarts", JAPANARTS, "牛田智大 ピアノ・リサイタル [川崎・東京]", venue="ミューザ川崎 シンフォニーホール MUZA Kawasaki Symphony Hall", artists=["牛田智大"]),
             cand("kanagawa_geikyo", GEIKYO, "牛田智大 ピアノ・リサイタル", venue="ミューザ川崎", artists=["牛田智大"]))
        self.ja, self.kg = cid(self.conn, "p2267"), cid(self.conn, "concert-9615")
        self.today = "2026-11-04"

    def hints(self, c):
        return duplicates.hints_for(self.conn, [c], self.today)[c]


class HintTests(Base):
    def test_same_day_compatible_venue_other_source_is_a_hint_with_reasons(self):
        (h,) = self.hints(self.ja)
        self.assertEqual((h["concert_id"], h["source_id"], h["strength"]), (self.kg, "kanagawa_geikyo", "strong"))
        self.assertEqual(h["reasons"], ["same_day", "venue_prefix", "shared_artists", "title_contains"])
        self.assertEqual(h["shared_artists"], ["牛田智大"])
        self.assertEqual(self.hints(self.kg)[0]["concert_id"], self.ja)  # symmetric

    def test_same_date_and_venue_alone_is_only_a_weak_hint(self):
        load(self.conn, cand("tso", "https://www.tokyosymphony.jp/x/", "ニューイヤーコンサート", date="2027年3月4日 14:00", venue="ミューザ川崎シンフォニーホール"))
        weak = [h for h in self.hints(self.ja) if h["source_id"] == "tso"]
        self.assertEqual((len(weak), weak[0]["strength"], weak[0]["reasons"]), (1, "weak", ["same_day", "venue_exact"]))
        self.assertEqual([h["strength"] for h in self.hints(self.ja)], ["strong", "weak"])  # strongest first

    def test_not_a_hint_when_same_source_other_day_other_venue_or_not_day_level_or_past(self):
        load(self.conn,
             cand("japanarts", "https://www.japanarts.co.jp/concert/p1/", "同じ来源", venue="ミューザ川崎"),                           # same source
             cand("tso", "https://www.tokyosymphony.jp/day/", "別日", date="2027年3月5日 19:00", venue="ミューザ川崎"),            # other day
             cand("njp", "https://www.njp.or.jp/venue/", "別会場", venue="サントリーホール"),                                       # other venue
             cand("jpo", "https://japanphil.or.jp/month/", "月のみ", date="2027年3月", venue="ミューザ川崎"),                       # month only
             cand("yomikyo", "https://yomikyo.example/past/", "過去", date="2026年10月1日 19:00", venue="ミューザ川崎"))           # already past
        self.assertEqual([h["concert_id"] for h in self.hints(self.ja)], [self.kg])

    def test_exact_venue_match_counts_even_for_a_two_character_label_but_a_short_prefix_does_not(self):
        load(self.conn,
             cand("tso", "https://www.tokyosymphony.jp/oji/", "王子", date="2027年4月1日 19:00", venue="王子ホール"),
             cand("njp", "https://www.njp.or.jp/oji/", "王子2", date="2027年4月1日 19:00", venue="王子ホール"),
             cand("jpo", "https://japanphil.or.jp/short/", "短い", date="2027年4月1日 19:00", venue="王子ホール別館"))   # key 王子別館: 王子 is only a 2-char prefix of it
        tso = cid(self.conn, "tokyosymphony.jp/oji")
        self.assertEqual([h["source_id"] for h in self.hints(tso)], ["njp"])
        self.assertEqual(duplicates._venue_reason("王子ホール", "王子ホール"), "venue_exact")
        self.assertIsNone(duplicates._venue_reason("王子ホール", "王子ホール別館"))
        self.assertEqual(duplicates._venue_reason("ミューザ川崎", "ミューザ川崎シンフォニーホール"), "venue_prefix")

    def test_a_concert_already_hidden_behind_a_keeper_is_not_offered_to_a_third_one(self):
        load(self.conn, cand("tso", "https://www.tokyosymphony.jp/x/", "三つ目", venue="ミューザ川崎"))
        tso = cid(self.conn, "tokyosymphony.jp/x")
        self.assertEqual({h["concert_id"] for h in self.hints(tso)}, {self.ja, self.kg})
        duplicates.decide(self.conn, self.kg, self.ja, "duplicate_of", NOW)
        self.assertEqual({h["concert_id"] for h in self.hints(tso)}, {self.ja})  # kg is hidden behind ja; only the keeper is offered
        self.conn.execute("UPDATE performance SET local_date='2027-06-01' WHERE concert_id=?", (self.ja,))  # the decision goes stale, so kg is a real candidate again
        self.assertEqual({h["concert_id"] for h in self.hints(tso)}, {self.kg})

    def test_a_different_decision_silences_the_hint_for_both_sides(self):
        duplicates.decide(self.conn, self.ja, self.kg, "different", NOW)
        self.assertEqual((self.hints(self.ja), self.hints(self.kg)), ([], []))
        duplicates.undo(self.conn, self.kg, self.ja)  # the pair is order-free
        self.assertEqual(len(self.hints(self.ja)), 1)


class DecisionTests(Base):
    def queue(self, **kw):
        return review_candidates(self.conn, NOW, **kw)

    def test_review_items_carry_hints_and_marking_a_duplicate_moves_it_out_and_back(self):
        q = self.queue()
        self.assertEqual((q["total"], {i["concert_id"]: len(i["possible_duplicates"]) for i in q["items"]}), (2, {self.ja: 1, self.kg: 1}))
        duplicates.decide(self.conn, self.kg, self.ja, "duplicate_of", NOW)
        q = self.queue()
        self.assertEqual((q["total"], q["by_source"], [i["concert_id"] for i in q["items"]]), (1, {"japanarts": 1}, [self.ja]))
        self.assertEqual(q["items"][0]["possible_duplicates"], [])  # the pair is decided: no hint on the keeper either
        (m,) = q["marked_duplicates"]
        self.assertEqual((m["concert_id"], m["duplicate_of"]["concert_id"]), (self.kg, self.ja))
        self.assertEqual(self.queue(source_id="japanarts")["marked_duplicates"], [])  # same source filter as the items
        self.assertEqual(len(self.queue(source_id="kanagawa_geikyo")["marked_duplicates"]), 1)
        duplicates.undo(self.conn, self.kg, self.ja)
        q = self.queue()
        self.assertEqual((q["total"], q["marked_duplicates"], len(q["items"][0]["possible_duplicates"])), (2, [], 1))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM concert").fetchone()[0], 2)  # nothing was merged or deleted

    def test_confirm_stored_refuses_the_duplicate_but_the_keeper_confirms(self):
        duplicates.decide(self.conn, self.kg, self.ja, "duplicate_of", NOW)
        out = confirm_stored(self.conn, [self.kg, self.ja], NOW, prefecture_overrides={})
        self.assertIn("marked as a duplicate", out["failed"][self.kg])
        self.assertEqual(out["confirmed"], [self.ja])
        self.assertEqual(self.conn.execute("SELECT verification_status FROM concert WHERE id=?", (self.kg,)).fetchone()[0], "needs_review")

    def test_a_url_import_cannot_promote_a_hidden_duplicate_either(self):
        duplicates.decide(self.conn, self.kg, self.ja, "duplicate_of", NOW)
        res = ingest_source(self.conn, "kanagawa_geikyo", [cand("kanagawa_geikyo", GEIKYO, "牛田智大 ピアノ・リサイタル", venue="ミューザ川崎")], NOW, complete=True, confirm=Confirmation(at=NOW))
        self.assertEqual(res["status"], "failed")
        self.assertIn("marked as a duplicate", res["error"])
        self.assertEqual(self.conn.execute("SELECT verification_status FROM concert WHERE id=?", (self.kg,)).fetchone()[0], "needs_review")

    def test_chains_and_cycles_are_refused_so_a_keeper_always_stays_visible(self):
        load(self.conn, cand("tso", "https://www.tokyosymphony.jp/x/", "三つ目", venue="ミューザ川崎"))
        tso = cid(self.conn, "tokyosymphony.jp/x")
        duplicates.decide(self.conn, self.kg, self.ja, "duplicate_of", NOW)
        for a, b in ((self.ja, self.kg), (self.ja, tso), (tso, self.kg)):  # 2-cycle; hide the keeper; point at a hidden concert
            with self.assertRaisesRegex(ValueError, "hidden as a duplicate|keeper"):
                duplicates.decide(self.conn, a, b, "duplicate_of", NOW)
        duplicates.decide(self.conn, tso, self.ja, "duplicate_of", NOW)  # two duplicates of one keeper is fine
        self.assertEqual({m["concert_id"] for m in self.queue()["marked_duplicates"]}, {self.kg, tso})
        self.assertEqual([i["concert_id"] for i in self.queue()["items"]], [self.ja])

    def test_choosing_another_keeper_replaces_the_old_choice(self):
        load(self.conn, cand("tso", "https://www.tokyosymphony.jp/x/", "三つ目", venue="ミューザ川崎"))
        tso = cid(self.conn, "tokyosymphony.jp/x")
        duplicates.decide(self.conn, self.kg, self.ja, "duplicate_of", NOW)
        duplicates.decide(self.conn, self.kg, tso, "duplicate_of", NOW)
        rows = self.conn.execute("SELECT concert_id, other_concert_id FROM duplicate_review WHERE decision='duplicate_of'").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(self.kg, tso)])

    def test_validation(self):
        with self.assertRaises(ValueError):
            duplicates.decide(self.conn, self.ja, self.kg, "merge", NOW)
        with self.assertRaises(ValueError):
            duplicates.decide(self.conn, self.ja, self.ja, "different", NOW)
        with self.assertRaises(LookupError):
            duplicates.decide(self.conn, self.ja, "nope", "different", NOW)
        load(self.conn, cand("tso", "https://www.tokyosymphony.jp/far/", "遠い", date="2027年5月5日 19:00", venue="東京文化会館"))
        with self.assertRaisesRegex(ValueError, "not a possible duplicate"):
            duplicates.decide(self.conn, self.ja, cid(self.conn, "/far"), "different", NOW)
        with self.assertRaises(LookupError):
            duplicates.undo(self.conn, self.ja, self.kg)

    def test_a_confirmed_concert_can_be_the_keeper_but_is_never_hidden_behind_an_unconfirmed_one(self):
        self.assertEqual(confirm_stored(self.conn, [self.ja], NOW)["confirmed"], [self.ja])
        self.assertEqual(self.hints(self.kg)[0]["verification_status"], "official_confirmed")  # the hint says the other card is already live
        with self.assertRaisesRegex(ValueError, "only be merged into another confirmed card"):  # ADR-0006: confirmed pairs only (tests/test_merged_cards.py)
            duplicates.decide(self.conn, self.ja, self.kg, "duplicate_of", NOW)
        duplicates.decide(self.conn, self.kg, self.ja, "duplicate_of", NOW)
        self.assertEqual(self.queue()["total"], 0)

    def test_a_decision_goes_stale_when_the_match_goes_away_and_the_concert_returns_to_the_queue(self):
        duplicates.decide(self.conn, self.kg, self.ja, "duplicate_of", NOW)
        self.assertEqual(self.queue()["total"], 1)
        self.conn.execute("UPDATE performance SET local_date='2027-06-01' WHERE concert_id=?", (self.ja,))  # the keeper moved to another day on re-sync
        q = self.queue()
        self.assertEqual((q["total"], q["marked_duplicates"]), (2, []))  # both are in the queue again
        self.assertEqual(confirm_stored(self.conn, [self.kg], NOW)["confirmed"], [self.kg])  # no longer blocked
        self.conn.execute("UPDATE performance SET local_date='2027-03-04' WHERE concert_id=?", (self.ja,))
        self.conn.execute("UPDATE performance SET status='cancelled' WHERE concert_id=?", (self.ja,))  # a cancelled keeper does not hide anything either
        self.assertEqual(self.queue()["marked_duplicates"], [])

    def test_stale_decisions_do_not_block_new_ones(self):
        duplicates.decide(self.conn, self.kg, self.ja, "duplicate_of", NOW)
        self.conn.execute("UPDATE performance SET local_date='2027-06-01' WHERE concert_id=?", (self.ja,))  # ja moved: "kg is a duplicate of ja" is now stale
        load(self.conn, cand("tso", "https://www.tokyosymphony.jp/x/", "三つ目", date="2027年6月1日 19:00", venue="ミューザ川崎"))
        tso = cid(self.conn, "tokyosymphony.jp/x")
        duplicates.decide(self.conn, self.ja, tso, "duplicate_of", NOW)  # the stale row must not make ja look like somebody's keeper
        self.assertEqual({m["concert_id"] for m in duplicates.marked_duplicates(self.conn, self.today)}, {self.ja})
        self.assertEqual({i["concert_id"] for i in self.queue()["items"]}, {self.kg, tso})  # kg is back in the queue


class ApiTests(Base):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = str(Path(self.tmp.name) / "d.db")
        file_conn = db.connect(path)
        db.init(file_conn)
        load(file_conn,
             cand("japanarts", JAPANARTS, "牛田智大 ピアノ・リサイタル [川崎・東京]", venue="ミューザ川崎 シンフォニーホール", artists=["牛田智大"]),
             cand("kanagawa_geikyo", GEIKYO, "牛田智大 ピアノ・リサイタル", venue="ミューザ川崎", artists=["牛田智大"]))
        self.ja2, self.kg2 = cid(file_conn, "p2267"), cid(file_conn, "concert-9615")
        file_conn.close()
        self.client = TestClient(create_app(path, TOKEN, raw_dir=Path(self.tmp.name) / "raw", clock=lambda: NOW))

    def test_decide_list_and_undo_over_http(self):
        body = {"concert_id": self.kg2, "other_concert_id": self.ja2, "decision": "duplicate_of"}
        self.assertEqual(self.client.put("/api/v1/review/duplicates", json=body).status_code, 401)
        self.assertEqual(self.client.put("/api/v1/review/duplicates", headers=H, json=body).json()["decision"], "duplicate_of")
        q = self.client.get("/api/v1/review/candidates", headers=H).json()
        self.assertEqual((q["total"], len(q["marked_duplicates"])), (1, 1))
        self.assertEqual(self.client.put("/api/v1/review/duplicates", headers=H, json={**body, "decision": "merge"}).status_code, 422)
        self.assertEqual(self.client.put("/api/v1/review/duplicates", headers=H, json={**body, "other_concert_id": "nope"}).status_code, 404)
        self.assertEqual(self.client.put("/api/v1/review/duplicates", headers=H, json={**body, "concert_id": self.ja2, "other_concert_id": self.kg2}).status_code, 422)  # would be a cycle
        r = self.client.post("/api/v1/review/confirm", headers=H, json={"concert_ids": [self.kg2]}).json()
        self.assertIn("marked as a duplicate", r["failed"][self.kg2])
        self.assertEqual(self.client.delete(f"/api/v1/review/duplicates/{self.kg2}/{self.ja2}").status_code, 401)
        self.assertEqual(self.client.delete(f"/api/v1/review/duplicates/{self.kg2}/{self.ja2}", headers=H).status_code, 204)
        self.assertEqual(self.client.delete(f"/api/v1/review/duplicates/{self.kg2}/{self.ja2}", headers=H).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/review/candidates", headers=H).json()["total"], 2)


if __name__ == "__main__":
    unittest.main()
