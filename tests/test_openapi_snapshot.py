"""docs/openapi.json is the reviewable snapshot of the API. The app and the file must agree (CI runs this)."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _exporter():
    spec = importlib.util.spec_from_file_location("export_openapi", ROOT / "scripts" / "export_openapi.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OpenApiSnapshotTests(unittest.TestCase):
    def test_snapshot_matches_the_running_app(self):
        mod = _exporter()
        self.assertTrue(mod.OUT.exists(), "docs/openapi.json is missing: run python scripts/export_openapi.py")
        self.assertEqual(mod.OUT.read_text(encoding="utf-8"), mod.current(),
                         "the API changed: review it, then run `python scripts/export_openapi.py` and commit docs/openapi.json")

    def test_snapshot_has_no_secrets_or_local_paths(self):
        text = _exporter().OUT.read_text(encoding="utf-8")
        for needle in ("/Users/", "snapshot.db", "x" * 20, "Bearer t"):
            self.assertNotIn(needle, text)


if __name__ == "__main__":
    unittest.main()
