"""The membership and presale guide of the season page (web/memberships.js, ADR-0020) is a hand-maintained table of facts read from each orchestra's own pages.

The tests cannot know whether a date is still true, so they hold what can be held: the shape, that every link is https and on the orchestra's own hosts, that every date is a real date,
that a sale event names the page it came from, and that an orchestra whose dates are not published has none (an honest blank, never a guess)."""
import datetime
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "src/classical_radar/web/memberships.js"
SEVEN = ["nhkso", "tmso", "tso", "jpo", "njp", "yomikyo", "tpo"]
# the hosts an orchestra's guide may link to: its own site, and the ticket service that site hands the purchase to
HOSTS = {
    "nhkso": {"www.nhkso.or.jp"},
    "tmso": {"www.tmso.or.jp", "yyk1.ka-ruku.com"},
    "tso": {"tokyosymphony.jp", "yyk1.ka-ruku.com"},
    "jpo": {"japanphil.or.jp"},
    "njp": {"www.njp.or.jp"},
    "yomikyo": {"yomikyo.or.jp"},
    "tpo": {"www.tpo.or.jp"},
}


def load():
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    script = "global.window={};require(process.argv[1]);console.log(JSON.stringify(window.CR_MEMBERS))"
    out = subprocess.run([node, "-e", script, str(FILE)], capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


class MembershipTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load()

    def url_ok(self, url, orch, what):
        u = urlparse(url)
        self.assertEqual(u.scheme, "https", f"{orch} {what}: {url}")
        self.assertIn(u.hostname, HOSTS[orch], f"{orch} {what}: {url} is not on {sorted(HOSTS[orch])}")

    def test_the_seven_orchestras_are_all_there_and_the_check_date_is_a_date(self):
        datetime.date.fromisoformat(self.data["checked"])
        self.assertEqual(sorted(self.data["orchestras"]), sorted(SEVEN))

    def test_every_orchestra_has_a_note_links_and_ways_of_a_known_kind(self):
        for orch, m in self.data["orchestras"].items():
            with self.subTest(orch):
                self.assertTrue(m["note"].strip())
                self.assertIsInstance(m["announced"], bool)
                self.assertTrue(m["links"], "at least one official link")
                for link in m["links"]:
                    self.assertTrue(link["label"].strip())
                    self.url_ok(link["url"], orch, "link")
                if m.get("noteSrc"):
                    self.url_ok(m["noteSrc"], orch, "noteSrc")
                self.assertTrue(m["ways"], "at least one way in")
                for w in m["ways"]:
                    self.assertIn(w["kind"], ("series", "presale"))
                    self.assertTrue(w["name"].strip() and w["text"].strip())

    def test_every_sale_event_has_a_real_date_a_who_and_the_official_page_it_came_from(self):
        for orch, m in self.data["orchestras"].items():
            for s in m["sales"]:
                with self.subTest(orch=orch, what=s["what"]):
                    d = datetime.date.fromisoformat(s["d"])
                    self.assertTrue(datetime.date(2026, 1, 1) <= d <= datetime.date(2029, 12, 31))
                    if s.get("t"):
                        self.assertRegex(s["t"], r"^([01]\d|2[0-3]):[0-5]\d$")
                    self.assertTrue(s["what"].strip() and s["who"].strip())
                    self.url_ok(s["src"], orch, "src")

    def test_an_orchestra_whose_dates_are_not_published_has_no_sale_dates(self):
        for orch, m in self.data["orchestras"].items():
            if not m["announced"]:
                with self.subTest(orch):
                    self.assertEqual(m["sales"], [], "unannounced means unannounced: last year's rhythm belongs in lastYear, labelled as such")

    def test_last_years_rhythm_always_names_its_source(self):
        for orch, m in self.data["orchestras"].items():
            with self.subTest(orch):
                self.assertIsInstance(m["lastYear"], list)
                if m["lastYear"]:
                    self.url_ok(m["lastYearSrc"], orch, "lastYearSrc")

    def test_no_text_looks_like_a_markup_or_script_injection_and_nothing_is_a_guess(self):
        text = FILE.read_text("utf8")
        self.assertNotRegex(text, r"<\s*(script|img|iframe)\b")
        self.assertNotRegex(text, r"javascript:", "no javascript: link")
        # a sale date is written as data (`d:`), never as free text that the page cannot count down; an estimate would have to be labelled lastYear
        for orch, m in self.data["orchestras"].items():
            for s in m["sales"]:
                self.assertNotRegex(s["what"], r"(预计|大概|估计|推测)", f"{orch}: {s['what']}")


if __name__ == "__main__":
    unittest.main()
