"""The data-PR decision of the daily cloud refresh (ADR-0008, step 2): what counts as a change, and the safety gates. No network."""
import contextlib
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cloud_publish  # noqa: E402

AS_OF = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def concert(i, title="定期演奏会", image=None):
    return {"id": f"{i:032d}", "source_id": "tso", "source_url": f"https://tokyosymphony.jp/concert/{i}/", "title_ja": f"{title}{i}", "category": "domestic_orchestra",
            "image": image, "artists": [{"name_display": "指揮者", "role": "conductor", "image": None}], "program": [],
            "performances": [{"id": f"{i + 1000:032d}", "local_date": "2027-01-10", "venue_name": "サントリーホール", "status": "scheduled", "last_seen_at": "2026-11-10T00:00:00+00:00", "ticket_phases": []}]}


def site(n=10, as_of=AS_OF):
    return {"as_of": as_of.isoformat(), "snapshot_label": as_of.date().isoformat() + " 更新", "coverage": {"sources": [{"source_id": "tso", "stored": n}]},
            "concerts": [concert(i) for i in range(1, n + 1)]}


class PublishDecisionTests(unittest.TestCase):
    def test_the_daily_noise_alone_is_not_a_change(self):
        old, new = site(), site()
        new["as_of"], new["snapshot_label"] = (AS_OF + timedelta(days=1)).isoformat(), "x"
        new["coverage"]["sources"][0]["stored"] = 99
        for c in new["concerts"]:
            c["performances"][0]["last_seen_at"] = "2026-11-11T00:00:00+00:00"
        r = cloud_publish.decide(old, new, AS_OF + timedelta(days=1))
        self.assertEqual((r["publish"], r["added"], r["modified"], r["problems"]), (False, 0, 0, []))

    def test_a_real_change_is_published_and_listed(self):
        old, new = site(), site()
        new["concerts"].append(concert(11, "新しい公演"))
        new["concerts"][0]["performances"][0]["venue_name"] = "東京文化会館"
        r = cloud_publish.decide(old, new, AS_OF + timedelta(days=1))
        self.assertEqual((r["publish"], r["added"], r["modified"], r["removed"]), (True, 1, 1, 0))
        self.assertIn("新しい公演11", r["body"])
        self.assertIn("performances", r["body"])

    def test_an_unchanged_file_is_still_refreshed_after_a_week(self):
        old, new = site(), site()
        self.assertFalse(cloud_publish.decide(old, new, AS_OF + timedelta(days=6))["publish"])
        r = cloud_publish.decide(old, new, AS_OF + timedelta(days=8))
        self.assertTrue(r["publish"])
        self.assertIn("超过 7 天", r["reasons"][0])

    def test_losing_more_than_a_tenth_of_the_published_concerts_stops_everything(self):
        old, new = site(20), site(20)
        new["concerts"] = new["concerts"][:17]
        r = cloud_publish.decide(old, new, AS_OF + timedelta(days=1))
        self.assertFalse(r["publish"])
        self.assertIn("fewer than 90%", r["problems"][0])
        ok = site(20)
        ok["concerts"] = ok["concerts"][:19]  # 95% kept: still fine
        self.assertEqual(cloud_publish.decide(old, ok, AS_OF + timedelta(days=1))["problems"], [])

    def test_the_cloud_must_not_wash_out_images_it_cannot_fetch(self):
        old = site()
        old["concerts"][0]["image"] = {"src": "data:image/jpeg;base64,xx", "credit": "c"}
        new = copy.deepcopy(old)
        new["concerts"][0]["image"] = None
        r = cloud_publish.decide(old, new, AS_OF + timedelta(days=1))
        self.assertFalse(r["publish"])
        self.assertIn("images", r["problems"][0])

    def test_a_flood_of_new_concerts_is_not_a_review(self):
        old, new = site(200), site(200)
        new["concerts"] += [concert(i) for i in range(1000, 1000 + cloud_publish.MAX_ADDED + 1)]
        r = cloud_publish.decide(old, new, AS_OF + timedelta(days=1))
        self.assertFalse(r["publish"])
        self.assertIn("a person should look first", r["problems"][0])

    def test_the_auto_confirm_report_goes_into_the_pr_body_and_a_bootstrap_is_said_so(self):
        old, new = site(), site()
        new["concerts"].append(concert(11, "新しい公演"))
        auto = {"mode": "apply", "confirmed": ["a", "b"], "held": [{}, {}, {}], "older_candidates": 7, "flood_guard": False}
        body = cloud_publish.decide(old, new, AS_OF + timedelta(days=1), auto)["body"]
        self.assertIn("本次确认 2 场", body)
        self.assertIn("留给人 3 场；更早的候选 7 个", body)
        report_only = cloud_publish.decide(old, new, AS_OF + timedelta(days=1), {**auto, "mode": "dry-run", "qualifying": 4}, bootstrapped=True)["body"]
        self.assertIn("只报告，没有确认：符合条件 4 场", report_only)
        self.assertIn("从线上数据还原", report_only)

    def test_the_command_line_writes_the_body_and_exits_3_only_when_a_gate_fails(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        def write(name, data):
            (tmp / name).write_text(json.dumps(data), encoding="utf8")
            return str(tmp / name)
        old = write("old.json", site(20))
        changed = site(20)
        changed["concerts"].append(concert(99, "追加"))
        code = cloud_publish.main([old, write("new.json", changed), "--body-out", str(tmp / "body.md"), "--now", (AS_OF + timedelta(days=1)).isoformat()])
        self.assertEqual(code, 0)
        self.assertIn("追加99", (tmp / "body.md").read_text(encoding="utf8"))
        (tmp / "auto.json").write_text("", encoding="utf8")  # auto-confirm crashed and left an empty file
        self.assertEqual(cloud_publish.main([old, str(tmp / "new.json"), "--autoconfirm", str(tmp / "auto.json"), "--now", (AS_OF + timedelta(days=1)).isoformat()]), 0)
        broken = site(20)
        broken["concerts"] = broken["concerts"][:5]
        self.assertEqual(cloud_publish.main([old, write("broken.json", broken), "--now", (AS_OF + timedelta(days=1)).isoformat()]), 3)


def lead(i, name="プラハ交響楽団", cities=("東京", "大阪")):
    return {"lead_id": f"lead-{i:020x}", "orchestra_name": f"{name}{i}", "period_raw": "2027年3月", "date_from": None, "date_to": None, "month_hint": "2027-03",
            "cities": list(cities), "conductor": "指揮者", "soloists": None, "article_url": f"https://okemin.com/tour{i}/", "performances": [],
            "last_changed_at": "2026-11-12T00:29:48+00:00", "orchestra": None, "more_cities": False}


def leads_file(n=10, read_at="2026-11-12T00:29:48+00:00", as_of="2026-11-12"):
    return {"source": {"name": "オケミン！", "url": "https://okemin.com/"}, "as_of": as_of, "read_at": read_at, "leads": [lead(i) for i in range(1, n + 1)]}


class LeadsDecisionTests(unittest.TestCase):
    """The overseas tour leads (okemin.com, ADR-0018) are a second file with their own gates; they never stop the concerts."""
    NOW = AS_OF + timedelta(days=1)

    def decide(self, old_leads, new_leads, concerts_changed=False, **kw):
        old, new = site(), site()
        if concerts_changed:
            new["concerts"].append(concert(11, "新しい公演"))
        return cloud_publish.decide(old, new, self.NOW, leads={"old": old_leads, "new": new_leads}, **kw)

    def test_the_daily_noise_alone_is_not_a_change(self):
        new = leads_file(read_at="2026-11-17T00:00:00+00:00", as_of="2026-11-17")
        for x in new["leads"]:
            x["last_changed_at"] = "2026-11-17T00:00:00+00:00"
        r = self.decide(leads_file(), new)
        self.assertEqual((r["publish"], r["concerts"], r["leads"], r["leads_problems"], r["leads_added"], r["leads_modified"]), (False, False, False, [], 0, 0))

    def test_a_leads_only_change_opens_a_pr_that_carries_only_the_leads(self):
        new = leads_file(11)
        new["leads"][0]["cities"] = ["東京", "名古屋"]
        r = self.decide(leads_file(), new)
        self.assertEqual((r["publish"], r["concerts"], r["leads"]), (True, False, True))
        self.assertEqual((r["leads_added"], r["leads_modified"], r["leads_removed"]), (1, 1, 0))
        self.assertIn("海外乐团线索", r["body"])
        self.assertIn("プラハ交響楽団11", r["body"])
        self.assertIn("演出没有变化，这次只更新海外乐团线索", r["body"])

    def test_a_removed_lead_is_listed_and_counted(self):
        r = self.decide(leads_file(), leads_file(8))
        self.assertEqual((r["publish"], r["leads_removed"], r["leads_problems"]), (True, 2, []))
        self.assertIn("减少：プラハ交響楽団9", r["body"])

    def test_the_leads_file_rides_along_with_a_concerts_change_so_its_dates_stay_fresh(self):
        new = leads_file(read_at="2026-11-17T00:00:00+00:00", as_of="2026-11-17")
        r = self.decide(leads_file(), new, concerts_changed=True)
        self.assertEqual((r["publish"], r["concerts"], r["leads"]), (True, True, True))

    def test_a_held_leads_file_never_stops_the_concerts(self):
        r = self.decide(leads_file(20), leads_file(10), concerts_changed=True)  # 50% kept
        self.assertEqual((r["publish"], r["concerts"], r["leads"], r["problems"]), (True, True, False, []))
        self.assertIn("fewer than 70%", r["leads_problems"][0])
        self.assertIn("已发布的文件保持不变", r["body"])
        self.assertEqual(self.decide(leads_file(20), leads_file(14))["leads_problems"], [])  # 70% kept is fine

    def test_a_flood_of_new_leads_is_held_and_the_manual_switch_lifts_only_the_count_gates(self):
        old, new = leads_file(10), leads_file(10 + cloud_publish.MAX_ADDED_LEADS + 1)
        held = self.decide(old, new)
        self.assertEqual((held["publish"], held["leads"]), (False, False))
        self.assertIn("a person should look first", held["leads_problems"][0])
        lifted = self.decide(old, new, accept_leads=True)
        self.assertEqual((lifted["publish"], lifted["leads"], lifted["leads_problems"]), (True, True, []))
        also = self.decide(leads_file(20), leads_file(2), accept_leads=True)  # the kept-share gate is lifted too
        self.assertEqual(also["leads_problems"], [])
        broken = leads_file(20)
        broken["leads"][3]["lead_id"] = "x"
        self.assertTrue(self.decide(leads_file(20), broken, accept_leads=True)["leads_problems"])  # the structure check always runs

    def test_a_missing_or_malformed_file_and_a_repeated_id_hold_the_leads(self):
        self.assertIn("missing or unreadable", self.decide(leads_file(), None)["leads_problems"][0])
        self.assertTrue(self.decide(leads_file(), {"leads": "nope"})["leads_problems"])
        dup = leads_file()
        dup["leads"][1]["lead_id"] = dup["leads"][0]["lead_id"]
        self.assertIn("twice", self.decide(leads_file(), dup)["leads_problems"][0])
        nameless = leads_file()
        nameless["leads"][0]["orchestra_name"] = ""
        self.assertTrue(self.decide(leads_file(), nameless)["leads_problems"])

    def test_an_empty_published_file_has_nothing_to_keep_so_the_first_reading_goes_in(self):
        r = self.decide(None, leads_file(52))
        self.assertEqual((r["publish"], r["leads"], r["leads_problems"], r["leads_added"]), (True, True, [], 52))

    def test_a_failed_concert_gate_stops_the_leads_too(self):
        old, new = site(20), site(20)
        new["concerts"] = new["concerts"][:5]
        r = cloud_publish.decide(old, new, self.NOW, leads={"old": leads_file(), "new": leads_file(11)})
        self.assertEqual((r["publish"], r["concerts"]), (False, False))  # the workflow reads ``publish``: nothing is pushed, leads included
        self.assertTrue(r["problems"])

    def test_without_leads_arguments_nothing_about_leads_appears(self):
        old, new = site(), site()
        new["concerts"].append(concert(11, "新しい公演"))
        r = cloud_publish.decide(old, new, self.NOW)
        self.assertEqual((r["publish"], r["concerts"], r["leads"], r["leads_problems"], r["leads_added"]), (True, True, False, [], 0))
        self.assertNotIn("海外乐团线索", r["body"])

    def test_the_command_line_reads_the_leads_files_and_only_the_concert_gate_sets_exit_3(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)

        def write(name, data):
            (tmp / name).write_text(json.dumps(data), encoding="utf8")
            return str(tmp / name)
        old, new = write("old.json", site(20)), write("new.json", site(20))
        now = ["--now", self.NOW.isoformat()]

        def run(*extra):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cloud_publish.main([old, new, *now, *extra])
            return code, json.loads(out.getvalue())
        code, r = run("--leads-old", write("lo.json", leads_file()), "--leads-new", write("ln.json", leads_file(11)))
        self.assertEqual((code, r["publish"], r["concerts"], r["leads"]), (0, True, False, True))
        code, r = run("--leads-old", str(tmp / "lo.json"), "--leads-new", str(tmp / "absent.json"))  # leads-export failed: reported, not a crash, not exit 3
        self.assertEqual((code, r["publish"], r["leads"]), (0, False, False))
        self.assertIn("missing or unreadable", r["leads_problems"][0])
        (tmp / "garbled.json").write_text("{not json", encoding="utf8")
        code, r = run("--leads-old", str(tmp / "lo.json"), "--leads-new", str(tmp / "garbled.json"))
        self.assertEqual((code, r["leads"]), (0, False))
        code, r = run("--leads-old", str(tmp / "lo.json"), "--leads-new", write("flood.json", leads_file(100)))
        self.assertEqual((code, r["leads"]), (0, False))
        code, r = run("--leads-old", str(tmp / "lo.json"), "--leads-new", str(tmp / "flood.json"), "--accept-leads")
        self.assertEqual((code, r["leads"], r["leads_problems"]), (0, True, []))


if __name__ == "__main__":
    unittest.main()
