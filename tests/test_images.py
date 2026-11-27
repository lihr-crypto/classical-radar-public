import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import httpx

from classical_radar import db
from classical_radar.discover import concert_detail, discover
from classical_radar.images import Client, image_for, lookup, name_key, pick_entity, run
from classical_radar.ingest import Confirmation, ingest_source
from classical_radar.parsers import candidate
from classical_radar.works import build_artists, parse_artist

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)


def ent(qid, label, *, p31=("Q5",), p106=("Q158852",), p18=None, alias=(), desc=""):
    claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": x}}}} for x in p31],
              "P106": [{"mainsnak": {"datavalue": {"value": {"id": x}}}} for x in p106]}
    if p18:
        claims["P18"] = [{"mainsnak": {"datavalue": {"value": p18}}}]
    return {"id": qid, "labels": {"ja": {"value": label}}, "aliases": {"ja": [{"value": a} for a in alias]}, "claims": claims,
            "descriptions": {"ja": {"value": desc}} if desc else {}}


def wikimedia(entities, licence="CC BY-SA 4.0", search_ids=None, status=None):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if status:
            return httpx.Response(status, headers={"retry-after": "0"})
        q = dict(request.url.params)
        if request.url.host == "upload.wikimedia.org":
            return httpx.Response(200, content=b"\xff\xd8fakejpeg")
        if q.get("action") == "wbsearchentities":
            return httpx.Response(200, json={"search": [{"id": i} for i in (search_ids or [e["id"] for e in entities])]})
        if q.get("action") == "wbgetentities":
            return httpx.Response(200, json={"entities": {e["id"]: e for e in entities}})
        if q.get("action") == "query":
            return httpx.Response(200, json={"query": {"pages": {"1": {"imageinfo": [{"thumburl": "https://upload.wikimedia.org/x.jpg", "descriptionurl": "https://commons.wikimedia.org/wiki/File:X.jpg",
                                                                                       "extmetadata": {"LicenseShortName": {"value": licence}, "Artist": {"value": "<a href='#'>Jane Photographer</a>"}}}]}}}})
        return httpx.Response(404)
    return handler, calls


class PickTests(unittest.TestCase):
    def test_exact_name_and_music_occupation_required(self):
        good = ent("Q1", "小林研一郎", p18="A.jpg")
        self.assertEqual(pick_entity("小林研一郎", "person", [good])["id"], "Q1")
        self.assertIsNone(pick_entity("小林研", "person", [good]))  # partial name never matches
        self.assertIsNone(pick_entity("小林研一郎", "person", [ent("Q2", "小林研一郎", p106=("Q82955",))]))  # a politician namesake
        self.assertEqual(pick_entity("サー・サイモン・ラトル", "person", [ent("Q3", "サイモン・ラトル")])["id"], "Q3")  # honorific removed

    def test_namesakes_are_never_resolved_by_guessing(self):
        a, b = ent("Q1", "佐藤健"), ent("Q2", "佐藤健", p106=("Q486748",))
        self.assertIsNone(pick_entity("佐藤健", "person", [a, b]))  # two musicians with the same name: no image

    def test_orchestras_must_be_ensembles_not_people(self):
        orch = ent("Q10", "バイエルン放送交響楽団", p31=("Q42998",), p106=())
        self.assertEqual(pick_entity("バイエルン放送交響楽団", "orchestra", [orch])["id"], "Q10")
        self.assertIsNone(pick_entity("バイエルン放送交響楽団", "orchestra", [ent("Q11", "バイエルン放送交響楽団")]))
        by_desc = ent("Q12", "プラハ交響楽団", p31=("Q43229",), p106=(), desc="チェコの交響楽団")
        self.assertEqual(pick_entity("プラハ交響楽団", "orchestra", [by_desc])["id"], "Q12")


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.media = Path(self.tmp.name)

    def client(self, handler):
        c = Client(interval=0, transport=httpx.MockTransport(handler), max_backoffs=1, backoff=0)
        self.addCleanup(c.close)
        return c

    def test_free_image_is_cached_with_licence_credit_and_source(self):
        handler, _ = wikimedia([ent("Q1", "小林研一郎", p18="Kobayashi.jpg")])
        row = lookup(self.client(handler), "小林研一郎", "person", self.media)
        self.assertEqual((row["status"], row["license"], row["credit"]), ("matched", "CC BY-SA 4.0", "Jane Photographer"))
        self.assertTrue((self.media / row["local_file"]).is_file())
        self.assertTrue(row["page_url"].startswith("https://commons.wikimedia.org/"))

    def test_non_free_licence_and_missing_image_are_not_used(self):
        handler, _ = wikimedia([ent("Q1", "小林研一郎", p18="K.jpg")], licence="Fair use")
        self.assertEqual(lookup(self.client(handler), "小林研一郎", "person", self.media)["status"], "not_free")
        handler, _ = wikimedia([ent("Q1", "小林研一郎")])
        self.assertEqual(lookup(self.client(handler), "小林研一郎", "person", self.media)["status"], "no_image")
        self.assertEqual(list(self.media.iterdir()), [])

    def test_repeated_429_stops_the_run_and_nothing_is_stored(self):
        handler, calls = wikimedia([], status=429)
        conn = db.connect()
        db.init(conn)
        self.addCleanup(conn.close)
        c = candidate("japanarts", "https://www.japanarts.co.jp/concert/p1/", "公演", "2027年1月5日 19:00", "サントリーホール")
        c["artists_items"] = build_artists([parse_artist("指揮：小林研一郎")])
        ingest_source(conn, "japanarts", [c], NOW, complete=True, confirm=Confirmation(at=NOW))
        stats = run(conn, self.media, client=self.client(handler), log=lambda m: None)
        self.assertEqual(stats, {"stopped_rate_limited": 1})
        self.assertEqual(len(calls), 2)  # one try + one backoff, then stop
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM media_image").fetchone()[0], 0)


class DisplayTests(unittest.TestCase):
    def test_cards_and_detail_carry_the_photo_with_credit_and_fall_back_to_none(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        conn = db.connect()
        db.init(conn)
        self.addCleanup(conn.close)
        for n, title, people in ((1, "定期", ["指揮：小林研一郎", "ピアノ：無名の新人"]), (2, "無写真", ["指揮：写真なし"])):
            c = candidate("japanarts", f"https://www.japanarts.co.jp/concert/p{n}/", title, "2027年1月5日 19:00", "サントリーホール")
            c["artists_items"] = build_artists([parse_artist(x) for x in people])
            ingest_source(conn, "japanarts", [c], NOW, complete=True, confirm=Confirmation(at=NOW))
        handler, _ = wikimedia([ent("Q1", "小林研一郎", p18="K.jpg")])
        client = Client(interval=0, transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        run(conn, Path(tmp.name), client=client, log=lambda m: None)
        self.assertIsNotNone(image_for(conn, "小林研一郎"))
        items = {i["title_ja"]: i for i in discover(conn, as_of=NOW)["items"]}
        img = items["定期"]["image"]
        self.assertEqual((img["subject"], img["license"], img["credit"]), ("小林研一郎", "CC BY-SA 4.0", "Jane Photographer"))
        self.assertTrue(img["src"].startswith("/media/"))
        self.assertIsNone(items["無写真"]["image"])
        d = concert_detail(conn, items["定期"]["concert_id"])
        self.assertEqual([a["image"] is not None for a in d["concert_artists"]], [True, False])
        self.assertEqual(name_key("サー・サイモン・ラトル"), name_key("サイモン・ラトル"))


if __name__ == "__main__":
    unittest.main()
