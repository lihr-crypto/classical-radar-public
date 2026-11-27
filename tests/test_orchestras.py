import unittest
from datetime import datetime, timedelta, timezone

from classical_radar import db
from classical_radar.discover import discover, facets
from classical_radar.ingest import Confirmation, ingest_source
from classical_radar.orchestras import ORCHESTRAS, SEVEN, concert_orchestras, detect, suggest_category
from classical_radar.parsers import candidate
from classical_radar.works import build_artists, parse_artist

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=JST)


class DetectTests(unittest.TestCase):
    def test_seven_are_exactly_the_whitelist(self):
        self.assertEqual(SEVEN, ["nhkso", "tmso", "tso", "jpo", "njp", "yomikyo", "tpo"])

    def test_longest_alias_wins_and_spellings_match(self):
        self.assertEqual(detect(["新日本フィル 定期"]), ["njp"])  # never also 日本フィル
        self.assertEqual(detect(["YUJA WANG& MAHLER CHAMBER ORCHESTRA"]), ["ov-mco"])
        self.assertEqual(detect(["ユジャ・ワン& マーラー・チェンバー・オーケストラ"]), ["ov-mco"])
        self.assertEqual(detect(["Symphonieorchester des Bayerischen Rundfunks"]), ["ov-br-so"])

    def test_affiliation_mentions_are_not_the_orchestra_on_stage(self):
        self.assertEqual(detect(["ウィーン・フィルの至宝 リュック・マンホルツを迎えて"]), [])
        self.assertEqual(detect(["ベルリン・フィル首席奏者によるリサイタル"]), [])
        self.assertEqual(detect(["ウィーン・フィル 来日公演"]), ["ov-vienna-phil"])

    def test_orchestra_sites_use_the_source_and_only_performer_names(self):
        # real NJP title that mentions a Vienna Phil member: still only NJP
        self.assertEqual(concert_orchestras("njp", "ウィーン・フィルの至宝 リュック・マンホルツを迎えて", ["リュック・マンホルツ"]), ["njp"])
        self.assertEqual(concert_orchestras("jpo", "第九", ["日本フィルハーモニー協会合唱団"]), ["jpo"])
        self.assertEqual(concert_orchestras("japanarts", "リオネル・ブランギエ指揮 東京フィルハーモニー交響楽団", []), ["tpo"])

    def test_category_hint_order(self):
        self.assertEqual(suggest_category("japanarts", "サー・サイモン・ラトル指揮 バイエルン放送交響楽団", [], "needs_review"), "overseas_orchestra_visit")
        self.assertEqual(suggest_category("kanagawa_geikyo", "牛田智大 ピアノ・リサイタル", [], "piano_recital"), "piano_recital")
        self.assertEqual(suggest_category("tso", "名曲全集", [], "domestic_source_candidate"), "domestic_orchestra")
        self.assertEqual(suggest_category("kajimoto", "大阪フィルハーモニー交響楽団 東京定期", [], "needs_review"), "other")  # Japanese, not one of the seven
        self.assertEqual(suggest_category("kanagawa_geikyo", "エリザベート弦楽アンサンブル", ["エリザベート弦楽アンサンブル"], "needs_review"), "other")  # unknown: never guessed overseas


def add(conn, src, n, title, people=(), confirm=True):
    c = candidate(src, f"https://example.{src}.test/c/{n}/", title, "2027年1月10日 19:00", "サントリーホール")
    c["artists_items"] = build_artists([a for a in (parse_artist(x) for x in people) if a])
    ingest_source(conn, src, [c], NOW, complete=True, confirm=Confirmation(at=NOW) if confirm else None)


class OrchestraFilterTests(unittest.TestCase):
    def setUp(self):
        self.c = db.connect()
        db.init(self.c)
        self.addCleanup(self.c.close)
        add(self.c, "japanarts", 1, "サー・サイモン・ラトル指揮 バイエルン放送交響楽団")
        add(self.c, "kanagawa_geikyo", 2, "プラハ交響楽団 ニューイヤー名曲コンサート")
        add(self.c, "nhkso", 3, "第2075回 定期公演 Aプログラム")
        add(self.c, "japanarts", 4, "リオネル・ブランギエ指揮 東京フィルハーモニー交響楽団")
        add(self.c, "tso", 5, "名曲全集", ["指揮：沼尻竜典"])

    def titles(self, **flt):
        return sorted(i["title_ja"] for i in discover(self.c, as_of=NOW, filters=flt)["items"])

    def test_filter_by_key_group_and_text(self):
        self.assertEqual(self.titles(orchestra=["nhkso"]), ["第2075回 定期公演 Aプログラム"])
        self.assertEqual(self.titles(orchestra=["overseas"]), ["サー・サイモン・ラトル指揮 バイエルン放送交響楽団", "プラハ交響楽団 ニューイヤー名曲コンサート"])
        self.assertEqual(len(self.titles(orchestra=["seven"])), 3)  # NHK, TSO, and Tokyo Phil via a presenter
        self.assertEqual(self.titles(orchestra=["東京フィル"]), ["リオネル・ブランギエ指揮 東京フィルハーモニー交響楽団"])
        self.assertEqual(self.titles(orchestra=["tpo", "tso"]), ["リオネル・ブランギエ指揮 東京フィルハーモニー交響楽団", "名曲全集"])  # OR within the dimension
        self.assertEqual(self.titles(orchestra=["tso"], conductor=["沼尻"]), ["名曲全集"])  # AND across

    def test_chinese_search_names_are_unambiguous_and_never_change_detection_of_japanese_titles(self):
        from collections import Counter
        from classical_radar.orchestras import _ZH, detect
        zh = Counter(name for names in _ZH.values() for name in (x.strip() for x in names.split(",") if x.strip()))
        self.assertEqual([n for n, c in zh.items() if c > 1], [])  # one Chinese name, one orchestra
        self.assertEqual(detect(["伦敦爱乐乐团"]), ["ov-lpo"])  # the usual name of the London Philharmonic, not the Philharmonia
        self.assertEqual(detect(["爱乐管弦乐团"]), ["ov-philharmonia"])
        self.assertEqual(detect(["柏林爱乐乐团"]), ["ov-berlin-phil"])  # the longer generic word alone names nobody
        self.assertEqual(detect(["爱乐乐团"]), [])
        self.assertEqual(detect(["ベルリン・フィルハーモニー管弦楽団 来日公演"]), ["ov-berlin-phil"])  # Japanese titles read as before
        self.assertEqual(detect(["東京フィルハーモニー交響楽団 定期演奏会"]), ["tpo"])

    def test_overseas_visits_get_the_category_and_cards_name_the_orchestra(self):
        res = discover(self.c, as_of=NOW, category="overseas_orchestra_visit")
        self.assertEqual(res["total"], 2)
        card = next(i for i in res["items"] if "ラトル" in i["title_ja"])
        self.assertEqual([{k: v for k, v in o.items() if k != "names"} for o in card["orchestras"]], [{"key": "ov-br-so", "display": "バイエルン放送交響楽団", "origin": "overseas"}])
        self.assertIn("巴伐利亚广播交响乐团", card["orchestras"][0]["names"])  # typed Chinese, English and short names find it in the filter

    def test_facet_lists_orchestras_with_origin(self):
        f = {x["value"]: x for x in facets(self.c, as_of=NOW)["orchestra"]}
        self.assertEqual((f["ov-prague-so"]["origin"], f["ov-prague-so"]["concerts"]), ("overseas", 1))
        self.assertEqual(f["nhkso"]["label"], "NHK交響楽団")

    def test_candidate_category_hint_updates_but_a_confirmed_category_never_changes(self):
        add(self.c, "kajimoto", 6, "未定の公演", confirm=False)
        add(self.c, "kajimoto", 6, "ウィーン・フィル 来日公演", confirm=False)
        self.assertEqual(self.c.execute("SELECT category FROM concert WHERE identity_key LIKE '%/c/6'").fetchone()[0], "overseas_orchestra_visit")
        self.c.execute("UPDATE concert SET category='other' WHERE identity_key LIKE '%/c/1'")  # a human decided
        self.c.commit()
        add(self.c, "japanarts", 1, "サー・サイモン・ラトル指揮 バイエルン放送交響楽団")
        self.assertEqual(self.c.execute("SELECT category FROM concert WHERE identity_key LIKE '%/c/1'").fetchone()[0], "other")


if __name__ == "__main__":
    unittest.main()
