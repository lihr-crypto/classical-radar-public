"""Sale-start extraction used by the P0.3 coverage measurement. Lines are copied from real pages (short snippets); no network."""
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

from classical_radar.salecoverage import classify, japanarts_ticket_block, sale_starts

REF = date(2026, 11, 21)
TODAY = date(2026, 11, 9)


def one(line, ref=REF):
    (s,) = sale_starts([line], ref)
    return s


class ExtractionTests(unittest.TestCase):
    def test_japanarts_line_without_a_year_is_fixed_by_the_weekday(self):
        s = one("② 7月25日(土) 10：00a.m.～発売 一般")  # 2026-07-25 is a Saturday; 2025-07-25 was a Friday
        self.assertEqual((s["date"], s["time"], s["year_basis"]), ("2026-07-25", "10:00", "weekday"))

    def test_the_weekday_picks_the_previous_year_when_that_is_the_one_that_fits(self):
        s = one("① 2月28日(土) 10：00a.m.～発売 ジャパン･アーツぴあオンラインチケット", ref=date(2026, 5, 1))  # 2026-02-28 is a Saturday
        self.assertEqual(s["date"], "2026-02-28")
        s = one("① 11月8日(土) 10：00a.m.～発売 一般", ref=date(2026, 3, 1))  # 2025-11-08 is a Saturday; 2026-11-08 would be after the performance
        self.assertEqual((s["date"], s["year_basis"]), ("2025-11-08", "weekday"))

    def test_written_years_in_the_formats_the_sites_use(self):
        self.assertEqual(one("東響会員先行発売…2025年11/27（木）10:00")["date"], "2025-11-27")
        self.assertEqual(one("チケット販売を一度終了いたしましたが、【2026/11/2（月）10:00】より追加販売を行います。")["date"], "2026-11-02")
        starts = sale_starts(["一般発売：2026年6月7日（日）10:00～ （神奈川芸術協会の電話受付は6月8日～）"], date(2026, 8, 1))
        self.assertEqual((starts[0]["date"], starts[0]["time"], starts[0]["year_basis"]), ("2026-06-07", "10:00", "explicit"))
        self.assertEqual((starts[1]["date"], starts[1]["time"]), ("2026-06-08", None))  # the phone line is a second, date-only start

    def test_no_weekday_and_no_year_is_only_a_guess(self):
        s = one("チケット発売は10/22から！")
        self.assertEqual((s["time"], s["year_basis"]), (None, "assumed"))
        self.assertEqual(classify([one("一般発売 7月1日 10:00")], TODAY), "year_assumed")

    def test_pm_and_the_end_of_a_window_are_handled(self):
        self.assertEqual(one("先行 7月25日(土) 1：30p.m.～")["time"], "13:30")
        starts = sale_starts(["受付 2026年7月23日(木)12:00〜7月26日(日)23:59"], date(2026, 9, 1))
        self.assertEqual([(s["date"], s["time"]) for s in starts], [("2026-07-23", "12:00")])  # 7/26 is the end of the window, not a start
        spaced = sale_starts(["受付 2026年7月23日(木)12:00 〜 7月26日(日)23:59"], date(2026, 9, 1))
        self.assertEqual([(s["date"], s["time"]) for s in spaced], [("2026-07-23", "12:00")])  # also when the dash has spaces around it

    def test_biographies_and_cd_releases_are_not_sale_lines(self):
        self.assertEqual(sale_starts(["2024年にCDを発売。" , "あ" * 130 + "発売 2026年1月1日 10:00"], REF), [])
        self.assertEqual(sale_starts(["2025年11月27日にアルバムを発売"], REF), [])

    def test_a_date_on_the_line_under_a_short_sale_label_counts(self):
        # KAJIMOTO lays the block out as a label line followed by a date line
        starts = sale_starts(["カジモト・イープラス会員限定先行受付(Webのみ)", "2026年7月23日(木)12:00〜7月26日(日)23:59", "ピアノ・リサイタル"], date(2026, 12, 1))
        self.assertEqual([(s["date"], s["time"]) for s in starts], [("2026-07-23", "12:00")])
        self.assertEqual(sale_starts(["お知らせ", "2026年7月23日(木)12:00"], date(2026, 12, 1)), [])  # no sale label above it: just a date
        self.assertEqual(sale_starts(["出演者紹介…", "2026年7月23日(木)19:00 開演"], date(2026, 12, 1)), [])
        # a short line under a dated sale line is not a sale line itself just because of its neighbour (it has no date)
        starts = sale_starts(["一般発売：2026年6月24日（水）10:00～", "未だ20代ながら紛れもない世界最高峰"], date(2026, 12, 1))
        self.assertEqual([(s["date"], s["time"]) for s in starts], [("2026-06-24", "10:00")])

    def test_a_sale_line_without_a_date_is_kept_as_no_date(self):
        (s,) = sale_starts(["チケット発売中"], REF)
        self.assertEqual((s["date"], s["time"]), (None, None))


class ClassTests(unittest.TestCase):
    def test_classes(self):
        fut = [one("② 12月5日(土) 10：00a.m.～発売 学生", ref=date(2027, 3, 4))]  # a 2027 concert: its student sale opens on 2026-12-05 (a Saturday)
        past = [one("② 7月25日(土) 10：00a.m.～発売 一般")]
        self.assertEqual(classify(fut, TODAY), "exact_future")
        self.assertEqual(classify(past, TODAY), "exact_past_only")
        self.assertEqual(classify(past + fut, TODAY), "exact_future")
        self.assertEqual(classify([one("一般発売 2026年11月30日")], TODAY), "date_only")
        self.assertEqual(classify(sale_starts(["チケット発売中"], REF), TODAY), "no_date")
        self.assertEqual(classify([], TODAY), "none")

    def test_today_itself_counts_as_future(self):
        self.assertEqual(classify([one("一般発売：2026年11月9日（月）10:00～")], TODAY), "exact_future")


class JapanArtsBlockTests(unittest.TestCase):
    def test_only_the_pages_own_block_is_used(self):
        lines = ["公演", "一般発売日：2026/11/07〜", "チケット発売情報", "① 7月18日(土) 10：00a.m.～発売 ジャパン･アーツぴあオンラインチケット", "WEB",
                 "② 7月25日(土) 10：00a.m.～発売 一般", "チケット残席状況", "他の公演", "一般発売日：2026/12/01〜"]
        block = japanarts_ticket_block(lines)
        self.assertEqual(len(block), 3)
        self.assertEqual([s["date"] for s in sale_starts(block, REF)], ["2026-07-18", "2026-07-25"])  # the navigation cards' dates are not this page's
        self.assertEqual(japanarts_ticket_block(["公演", "チケット詳細"]), [])


class MeasureScriptTests(unittest.TestCase):
    """scripts/p03_sale_time_coverage.py end to end on a synthetic page in a temporary raw cache (no network, nothing from evidence/raw)."""

    def test_measure_counts_a_future_start_that_the_parser_does_not_read(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("sale_cov", root / "scripts" / "p03_sale_time_coverage.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        html = ("<html><head><link rel='canonical' href='https://www.japanarts.co.jp/concert/p1/'></head><body><h1>公演</h1><p>チケット発売情報</p>"
                "<p>① 7月18日(土) 10：00a.m.～発売 ぴあ</p><p>② 12月5日(土) 10：00a.m.～発売 学生</p><p>チケット残席状況</p></body></html>")
        with tempfile.TemporaryDirectory() as raw:
            (Path(raw) / "abc.html").write_text(html)
            announcement = {"sources": {sid: {"N_offered": 1, "pages": []} for sid in mod.SOURCES}}
            announcement["sources"]["japanarts"]["pages"] = [{"url": "https://www.japanarts.co.jp/concert/p1/", "status": 200, "performance_dates": ["2027-03-04"]}]
            announcement["sources"]["kajimoto"]["pages"] = [{"url": "https://www.kajimotomusic.com/concerts/missing/", "status": 200, "performance_dates": ["2027-03-04"]}]
            out = mod.measure(date(2026, 11, 9), announcement, Path(raw))
        ja = out["japanarts"]
        self.assertEqual((ja["n_measured"], ja["text_exact_pages"], ja["text_exact_future_pages"], ja["parser_pages_with_claims"]), (1, 1, 1, 0))
        self.assertEqual([(x["date"], x["time"]) for x in ja["pages"][0]["sale_starts"]], [("2026-07-18", "10:00"), ("2026-12-05", "10:00")])
        self.assertEqual((out["kajimoto"]["n_measured"], out["kajimoto"]["counts"]["not_measured"]), (0, 1))  # a page that is not in the cache is reported, not invented


if __name__ == "__main__":
    unittest.main()
