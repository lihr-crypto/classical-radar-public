import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("refresh_report", ROOT / "scripts" / "refresh_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class WarningsTurnTheRunRedTests(unittest.TestCase):
    def test_a_source_warning_is_a_problem_even_though_the_source_succeeded(self):
        results = [{"source_id": "njp", "status": "succeeded", "items_listed": 70, "warnings": ["分页器显示 25 页，只读了前 20 页"]}]
        self.assertEqual(report.problems(results, None), ["njp：分页器显示 25 页，只读了前 20 页"])

    def test_no_warnings_no_problem(self):
        results = [{"source_id": "njp", "status": "succeeded", "items_listed": 70, "warnings": []},
                   {"source_id": "tso", "status": "succeeded", "items_listed": 74}]
        self.assertEqual(report.problems(results, None), [])


OK = [{"source_id": "tso", "status": "succeeded", "items_listed": 74}]


class TourLeadsTurnTheRunRedTests(unittest.TestCase):
    """ADR-0018: the leads are read by their own command, so a stopped read, a missing output or a held file must show."""

    def test_a_stopped_read_is_a_problem_and_a_clean_one_is_not(self):
        stats = {"requests": 3, "new": 0, "stopped": "HTTP 403 for https://okemin.com/robots.txt"}
        found = report.problems(OK, None, stats, None, True)
        self.assertEqual(len(found), 1)
        self.assertIn("读取中止", found[0])
        self.assertIn("HTTP 403", found[0])
        self.assertEqual(report.problems(OK, None, {"requests": 20, "new": 2, "stopped": None}, None, True), [])

    def test_no_output_is_a_problem_only_when_leads_were_asked_for(self):
        self.assertIn("没有输出", report.problems(OK, None, None, None, True)[0])
        self.assertEqual(report.problems(OK, None, None, None, False), [])  # "-" on the command line: the leads are switched off

    def test_a_held_leads_file_is_a_problem_with_its_reason(self):
        found = report.problems(OK, None, {"stopped": None}, {"leads_problems": ["the new leads file has 10 leads, fewer than 70% of the published 52"]}, True)
        self.assertEqual(len(found), 1)
        self.assertIn("这次没有发布", found[0])
        self.assertIn("fewer than 70%", found[0])

    def test_the_command_line_with_strict_exits_1_for_a_held_file_and_0_when_all_is_well(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for name, data in (("sync.json", OK), ("leads.json", {"requests": 20, "stopped": None}), ("held.json", {"publish": False, "leads_problems": ["x"]}), ("fine.json", {"publish": True, "leads_problems": []})):
            (tmp / name).write_text(json.dumps(data), encoding="utf8")

        def run(publish):
            return subprocess.run([sys.executable, str(ROOT / "scripts/refresh_report.py"), str(tmp / "sync.json"), str(tmp / "leads.json"), "-", "--publish", str(tmp / publish), "--strict"],
                                  capture_output=True, text=True)
        held = run("held.json")
        self.assertEqual(held.returncode, 1)
        self.assertIn("海外线索", held.stderr)
        self.assertIn("## 需要注意", held.stdout)
        self.assertEqual(run("fine.json").returncode, 0)
        self.assertEqual(run("absent.json").returncode, 0)  # no publish file (the gate step never ran): nothing to add


if __name__ == "__main__":
    unittest.main()
