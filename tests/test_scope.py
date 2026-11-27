import re
import unittest
from pathlib import Path

from classical_radar.sources import DEFERRED, SOURCES

DOMESTIC = {"nhkso", "tmso", "tso", "jpo", "njp", "yomikyo", "tpo"}
SRC = Path(__file__).resolve().parents[1] / "src" / "classical_radar"


class ScopeTests(unittest.TestCase):
    def test_t01_domestic_whitelist_is_exactly_the_seven(self):
        self.assertEqual({s.id for s in SOURCES.values() if s.category == "domestic_orchestra"}, DOMESTIC)

    def test_excluded_orchestras_have_no_source_or_adapter(self):
        names = ("tokyo_city", "tcpo", "kanagawa_phil", "pacific", "chiba")
        self.assertFalse([k for k in SOURCES if any(n in k for n in names)])
        # "kanagawa_geikyo" is the presenter (神奈川芸術協会), a different organisation from the excluded 神奈川フィル
        self.assertIn("kanagawa_geikyo", SOURCES)

    def test_deferred_source_is_never_fetched_by_the_importer_or_scripts(self):
        self.assertEqual(DEFERRED, {"tpo"})
        for script in Path(__file__).resolve().parents[1].joinpath("scripts").glob("p02_*.py"):
            text = script.read_text()
            self.assertNotRegex(text, r"tpo\.or\.jp", script.name)


if __name__ == "__main__":
    unittest.main()
