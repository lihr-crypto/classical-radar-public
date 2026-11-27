import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from classical_radar import db
from classical_radar.api import create_app
from classical_radar.discover import discover, facets
from classical_radar.ingest import Confirmation, ingest_source
from classical_radar.parsers import candidate
from classical_radar.works import build_artists, parse_artist, parse_programme

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=JST)
TOKEN = "f" * 24
H = {"Authorization": f"Bearer {TOKEN}"}


def add(conn, n, title, raw, venue, prog, people, *, confirm=True, source="japanarts"):
    c = candidate(source, f"https://www.japanarts.co.jp/concert/p{n}/", title, raw, venue)
    c["programme_items"] = parse_programme(prog)
    c["artists_items"] = build_artists([a for a in (parse_artist(x) for x in people) if a])
    ingest_source(conn, source, [c], NOW, complete=True, confirm=Confirmation(at=NOW) if confirm else None)


def seed(conn):
    add(conn, 1, "第九", "2027年1月5日 19:00", "サントリーホール", ["ベートーヴェン：交響曲 第9番 ニ短調 op.125「合唱付」", "武満徹：うた"], ["指揮：沼尻竜典", "ソプラノ：船越亜弥", "合唱：東響コーラス"])
    add(conn, 2, "ブラームスとマーラー", "2027年1月6日 19:00", "横浜みなとみらいホール", ["ブラームス：ピアノ協奏曲第1番", "マーラー：交響曲第5番"], ["指揮：小林研一郎", "ピアノ：船越亜弥"])
    add(conn, 3, "ピアノ独奏", "2027年1月7日 19:00", "東京オペラシティ コンサートホール", ["ベートーヴェン：ピアノ・ソナタ 第32番", "カプースチン：8つの演奏会用エチュード"], ["桑原志織 Shiori Kuwahara (ピアノ, Piano)"])
    add(conn, 4, "未確認の第九", "2027年1月8日 19:00", "サントリーホール", ["ベートーヴェン：交響曲 第9番"], ["指揮：沼尻竜典"], confirm=False)
    # two performances of one concert in different venues (performance-level venue filter)
    c1 = candidate("japanarts", "https://www.japanarts.co.jp/concert/p5/", "二会場", "2027年2月1日 19:00", "サントリーホール")
    c2 = candidate("japanarts", "https://www.japanarts.co.jp/concert/p5/", "二会場", "2027年2月2日 19:00", "フェスティバルホール(大阪)")
    for c in (c1, c2):
        c["programme_items"] = parse_programme(["ショパン：ピアノ協奏曲第1番"])
        c["artists_items"] = []
    ingest_source(conn, "japanarts", [c1, c2], NOW, complete=True, confirm=Confirmation(at=NOW))


def store():
    c = db.connect()
    db.init(c)
    unittest.addModuleCleanup(c.close)
    seed(c)
    return c


def titles(res):
    return sorted(i["title_ja"] for i in res["items"])


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.c = store()

    def q(self, **flt):
        return discover(self.c, as_of=NOW, filters=flt)

    def test_composer_by_alias_spelling_and_by_latin_name(self):
        for v in ("ベートーヴェン", "ベートーベン", "Beethoven", "beethoven"):
            self.assertEqual(titles(self.q(composer=[v])), ["ピアノ独奏", "第九"], v)

    def test_unconfirmed_concerts_never_match_even_when_the_filter_fits(self):
        self.assertNotIn("未確認の第九", titles(self.q(composer=["ベートーヴェン"])))

    def test_unknown_composer_found_by_displayed_text(self):
        self.assertEqual(titles(self.q(composer=["カプースチン"])), ["ピアノ独奏"])
        self.assertEqual(self.q(composer=["存在しない作曲家"])["total"], 0)

    def test_same_dimension_is_or_different_dimensions_are_and(self):
        self.assertEqual(titles(self.q(composer=["ブラームス", "武満徹"])), ["ブラームスとマーラー", "第九"])
        self.assertEqual(titles(self.q(composer=["ベートーヴェン"], conductor=["沼尻"])), ["第九"])
        self.assertEqual(titles(self.q(composer=["ベートーヴェン"], conductor=["小林"])), [])
        self.assertEqual(titles(self.q(composer=["ブラームス"], conductor=["小林"], performer=["船越"])), ["ブラームスとマーラー"])

    def test_work_by_key_and_by_text_ignoring_spaces(self):
        self.assertEqual(titles(self.q(work=["beethoven:symphony-9"])), ["第九"])
        self.assertEqual(titles(self.q(work=["交響曲第9番"])), ["第九"])  # page writes "交響曲 第9番"
        self.assertEqual(titles(self.q(work=["ピアノ・ソナタ第32番"])), ["ピアノ独奏"])
        self.assertEqual(titles(self.q(work=["ピアノ協奏曲第1番"])), ["ブラームスとマーラー", "二会場"])

    def test_conductor_filter_is_role_restricted_but_performer_is_not(self):
        self.assertEqual(titles(self.q(conductor=["船越"])), [])  # a soprano soloist is not a conductor
        self.assertEqual(titles(self.q(performer=["船越"])), ["ブラームスとマーラー", "第九"])
        self.assertEqual(titles(self.q(performer=["桑原志織"])), ["ピアノ独奏"])
        self.assertEqual(titles(self.q(performer=["東響コーラス"])), ["第九"])

    def test_venue_filter_lists_only_matching_performances(self):
        res = self.q(venue=["フェスティバル"])
        self.assertEqual(titles(res), ["二会場"])
        self.assertEqual([p["venue_name"] for p in res["items"][0]["performances"]], ["フェスティバルホール(大阪)"])
        full = {i["title_ja"]: i for i in self.q()["items"]}["二会場"]
        self.assertEqual(len(full["performances"]), 2)

    def test_filters_are_echoed_only_when_used_and_cards_carry_summaries(self):
        self.assertNotIn("composer", self.q()["filters"])
        res = self.q(composer=["ベートーヴェン"])
        self.assertEqual(res["filters"]["composer"], ["ベートーヴェン"])
        card = {i["title_ja"]: i for i in res["items"]}["第九"]
        self.assertEqual((card["composers"], card["conductors"], card["soloists"]), (["ベートーヴェン", "武満徹"], ["沼尻竜典"], ["船越亜弥"]))

    def test_cards_carry_every_programme_row_as_pieces_for_the_browse_pages(self):
        # ADR-0010: the browse pages group concerts by composer and by piece in the browser, so a card lists ALL programme rows in order (composers is the short, capped list)
        card = {i["title_ja"]: i for i in self.q()["items"]}["第九"]
        self.assertEqual([(p["composer"], p["composer_key"], p["work_key"]) for p in card["pieces"]], [("ベートーヴェン", "beethoven", "beethoven:symphony-9"), ("武満徹", "takemitsu", None)])
        self.assertTrue(card["pieces"][0]["work"].startswith("交響曲"))
        self.assertEqual(set(card["pieces"][0]), {"composer", "composer_key", "work", "work_key"})

    def test_invalid_filters_rejected(self):
        with self.assertRaises(ValueError):
            discover(self.c, as_of=NOW, filters={"genre": ["x"]})
        with self.assertRaises(ValueError):
            self.q(composer=["x"] * 11)
        with self.assertRaises(ValueError):
            self.q(composer=["x" * 101])

    def test_facets_count_only_matching_confirmed_concerts(self):
        f = facets(self.c, as_of=NOW)
        comps = {x["value"]: x["concerts"] for x in f["composer"]}
        self.assertEqual((comps["ベートーヴェン"], comps["ブラームス"]), (2, 1))
        self.assertEqual({x["value"]: x["concerts"] for x in f["conductor"]}, {"沼尻竜典": 1, "小林研一郎": 1})
        narrowed = facets(self.c, as_of=NOW, filters={"composer": ["ベートーヴェン"]})
        self.assertEqual(narrowed["total_concerts"], 2)
        self.assertNotIn("ブラームス", {x["value"] for x in narrowed["composer"]})


class FilterApiTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = str(Path(tmp.name) / "f.db")
        boot = db.connect(path)
        db.init(boot)
        seed(boot)
        boot.close()
        self.client = TestClient(create_app(path, TOKEN, clock=lambda: NOW))

    def test_repeated_query_params_and_echoed_filters(self):
        r = self.client.get("/api/v1/discover?composer=ブラームス&composer=武満徹&conductor=沼尻", headers=H).json()
        self.assertEqual([i["title_ja"] for i in r["items"]], ["第九"])
        self.assertEqual(r["filters"]["composer"], ["ブラームス", "武満徹"])
        self.assertEqual(r["filters"]["category"], "all")

    def test_over_long_value_lists_and_values_are_422_and_openapi_documents_filters(self):
        many = "&".join(f"composer=c{i}" for i in range(11))
        self.assertEqual(self.client.get("/api/v1/discover?" + many, headers=H).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/discover?composer=" + "x" * 101, headers=H).status_code, 422)
        names = {p["name"] for p in self.client.get("/openapi.json").json()["paths"]["/api/v1/discover"]["get"]["parameters"]}
        self.assertTrue({"composer", "work", "conductor", "performer", "venue"} <= names)

    def test_the_http_response_keeps_pieces(self):
        # DiscoverItem is a typed response model: a field it does not declare would be dropped silently, and the browse pages would show nothing
        items = self.client.get("/api/v1/discover?work=beethoven:symphony-9", headers=H).json()["items"]
        self.assertEqual([(p["composer_key"], p["work_key"]) for p in items[0]["pieces"]][:1], [("beethoven", "beethoven:symphony-9")])

    def test_review_queue_shows_programme_and_conductor_to_help_the_decision(self):
        q = self.client.get("/api/v1/review/candidates", headers=H).json()
        item = next(i for i in q["items"] if i["title_ja"] == "未確認の第九")
        self.assertEqual((item["composers"], item["conductors"]), (["ベートーヴェン"], ["沼尻竜典"]))

    def test_facets_endpoint_and_detail_carry_programme_and_artists(self):
        f = self.client.get("/api/v1/discover/facets?composer=ベートーヴェン", headers=H).json()
        self.assertEqual(f["total_concerts"], 2)
        cid = self.client.get("/api/v1/discover?work=beethoven:symphony-9", headers=H).json()["items"][0]["concert_id"]
        d = self.client.get(f"/api/v1/concerts/{cid}", headers=H).json()
        self.assertEqual([p["work_key"] for p in d["program_items"]][:1], ["beethoven:symphony-9"])
        self.assertEqual([a["role"] for a in d["concert_artists"]], ["conductor", "concerto_soloist", "other"])


if __name__ == "__main__":
    unittest.main()
