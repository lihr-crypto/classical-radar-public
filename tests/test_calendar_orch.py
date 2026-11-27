"""The calendar rows say which orchestras play (so the page can filter by orchestra); the page-side rules live in tests/js/orch.test.mjs. No network."""
import shutil
import subprocess
import unittest
from datetime import date
from pathlib import Path

from classical_radar import db
from classical_radar.discover import calendar_range
from classical_radar.ingest import confirm_stored, ingest_source

from test_duplicates import NOW, cand, cid

ROOT = Path(__file__).resolve().parents[1]


class CalendarOrchestraTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        db.init(self.conn)
        ingest_source(self.conn, "tso", [cand("tso", "https://tokyosymphony.jp/concert/detail/a/", "ニューイヤーコンサート", date="2027年1月10日 14:00", venue="横浜みなとみらいホール")], NOW, complete=True)
        ingest_source(self.conn, "japanarts", [cand("japanarts", "https://www.japanarts.co.jp/concert/p1/", "ベルリン・フィルハーモニー管弦楽団 来日公演", date="2027年1月10日 19:00", venue="サントリーホール")], NOW, complete=True)
        ingest_source(self.conn, "japanarts", [cand("japanarts", "https://www.japanarts.co.jp/concert/p2/", "ピアノ・リサイタル", date="2027年1月11日 19:00", venue="浜離宮朝日ホール")], NOW, complete=True)
        confirm_stored(self.conn, [r[0] for r in self.conn.execute("SELECT id FROM concert")], NOW)

    def rows(self):
        cal = calendar_range(self.conn, date(2027, 1, 1), date(2027, 1, 31), NOW)
        return {r["title_ja"][:6]: [o["key"] for o in r["orchestras"]] for r in cal["performances"]}, cal

    def test_every_performance_row_names_its_orchestras_and_a_row_with_none_has_an_empty_list(self):
        by_title, cal = self.rows()
        self.assertEqual(by_title["ニューイヤー"], ["tso"])  # the source orchestra
        self.assertEqual(by_title["ベルリン・フ"], ["ov-berlin-phil"])  # a name found in the title
        self.assertEqual(by_title["ピアノ・リサ"], [])
        first = cal["performances"][0]["orchestras"]
        self.assertEqual(set(first[0]), {"key", "display", "origin", "names"})

    def test_sale_rows_carry_them_too(self):
        tid = cid(self.conn, "/detail/a")
        pid = self.conn.execute("SELECT id FROM performance WHERE concert_id=?", (tid,)).fetchone()[0]
        doc = self.conn.execute("SELECT id FROM source_document LIMIT 1").fetchone()[0]
        self.conn.execute("INSERT INTO ticket_phase (id, performance_id, phase_type, channel, eligibility, starts_at, start_precision, end_precision, current_status, source_document_id) VALUES ('t1', ?, 'general_sale', 'official', '一般', '2027-01-05T01:00:00+00:00', 'exact_time', 'unknown', 'announced', ?)", (pid, doc))
        sales = calendar_range(self.conn, date(2027, 1, 1), date(2027, 1, 31), NOW)["sales"]
        self.assertEqual([[o["key"] for o in s["orchestras"]] for s in sales], [["tso"]])

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_the_page_side_filter_rules(self):
        run = subprocess.run(["node", str(ROOT / "tests/js/orch.test.mjs")], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertRegex(run.stdout, r"\d+ checks passed")


if __name__ == "__main__":
    unittest.main()
