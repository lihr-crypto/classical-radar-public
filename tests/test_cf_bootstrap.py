import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from cf_bootstrap import CloudflareError, run  # noqa: E402

ENV = {"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "acc", "ACCESS_EMAILS": "Me@Example.com"}


class FakeCloudflare:
    """Just enough of the v4 API: Pages projects, KV namespaces, Access organization/apps/policies."""

    def __init__(self, zero_trust=True):
        self.projects, self.kv, self.apps, self.policies, self.writes = {}, [], [], {}, []
        self.org = {"auth_domain": "myteam.cloudflareaccess.com"} if zero_trust else None

    def ok(self, result, status=200):
        return httpx.Response(status, json={"success": True, "errors": [], "result": result})

    def handler(self, request):
        assert request.headers["authorization"] == "Bearer t"
        path, m = request.url.path.removeprefix("/client/v4/accounts/acc"), request.method
        body = json.loads(request.content) if request.content else None
        if m != "GET":
            self.writes.append((m, path))
        if path.startswith("/pages/projects/") and m == "GET":
            name = path.rsplit("/", 1)[1]
            return self.ok(self.projects[name]) if name in self.projects else httpx.Response(404, json={"success": False, "errors": [{"code": 8000007, "message": "Project not found"}]})
        if path == "/pages/projects" and m == "POST":
            self.projects[body["name"]] = body
            return self.ok(body)
        if path == "/storage/kv/namespaces":
            if m == "GET":
                return self.ok(self.kv)
            ns = {"id": f"kv{len(self.kv) + 1:030d}", "title": body["title"]}
            self.kv.append(ns)
            return self.ok(ns)
        if path == "/access/organizations":
            return self.ok(self.org) if self.org else httpx.Response(404, json={"success": False, "errors": [{"code": 12130, "message": "not found"}]})
        if path == "/access/apps":
            if m == "GET":
                return self.ok(self.apps)
            app = {**body, "id": f"app{len(self.apps) + 1}", "aud": "aud-xyz"}
            self.apps.append(app)
            return self.ok(app)
        if path.startswith("/access/apps/") and "/policies" in path:
            app_id = path.split("/")[3]
            pols = self.policies.setdefault(app_id, [])
            if m == "GET":
                return self.ok(pols)
            if m == "POST":
                pols.append({**body, "id": "p1"})
                return self.ok(pols[-1])
            if m == "PUT":
                pols[0] = {**body, "id": "p1"}
                return self.ok(pols[0])
        return httpx.Response(400, json={"success": False, "errors": [{"code": 1, "message": f"unexpected {m} {path}"}]})


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.toml = self.tmp / "wrangler.toml"
        shutil.copy(ROOT / "wrangler.toml", self.toml)

    def run_with(self, cf, env=ENV):
        return run(env, self.toml, transport=httpx.MockTransport(cf.handler), log=lambda m: None)

    def test_fresh_account_gets_project_kv_access_and_config(self):
        cf = FakeCloudflare()
        out = self.run_with(cf)
        self.assertEqual(out["domain"], "classical-radar.pages.dev")
        self.assertIn("classical-radar", cf.projects)
        self.assertEqual(cf.apps[0]["self_hosted_domains"], ["*.classical-radar.pages.dev", "classical-radar.pages.dev"])
        self.assertEqual(cf.policies["app1"][0]["include"], [{"email": {"email": "me@example.com"}}])
        self.assertEqual(cf.policies["app1"][0]["decision"], "allow")
        toml = self.toml.read_text()
        self.assertIn(f'id = "{cf.kv[0]["id"]}"', toml)
        self.assertIn('ACCESS_TEAM_DOMAIN = "myteam.cloudflareaccess.com"', toml)
        self.assertIn('ACCESS_AUD = "aud-xyz"', toml)

    def test_second_run_changes_nothing(self):
        cf = FakeCloudflare()
        self.run_with(cf)
        before = list(cf.writes)
        self.run_with(cf)
        self.assertEqual(cf.writes, before)  # idempotent: no POST/PUT on a configured account
        self.assertEqual(len(cf.kv), 1)

    def test_changed_email_updates_the_policy(self):
        cf = FakeCloudflare()
        self.run_with(cf)
        self.run_with(cf, {**ENV, "ACCESS_EMAILS": "me@example.com, partner@example.com"})
        self.assertEqual(cf.writes[-1][0], "PUT")
        self.assertEqual(len(cf.policies["app1"][0]["include"]), 2)

    def test_only_the_icons_folder_is_public_everything_else_stays_behind_the_login(self):
        cf = FakeCloudflare()
        self.run_with(cf)
        main, icons = cf.apps
        self.assertEqual(main["self_hosted_domains"], ["*.classical-radar.pages.dev", "classical-radar.pages.dev"])
        self.assertEqual((icons["domain"], icons["self_hosted_domains"]), ("classical-radar.pages.dev/icons/*", ["classical-radar.pages.dev/icons/*"]))
        self.assertEqual((cf.policies["app2"][0]["decision"], cf.policies["app2"][0]["include"]), ("bypass", [{"everyone": {}}]))
        self.assertEqual(cf.policies["app1"][0]["decision"], "allow")  # the main application is untouched

    def test_a_changed_icons_policy_is_repaired_and_a_second_run_writes_nothing(self):
        cf = FakeCloudflare()
        self.run_with(cf)
        cf.policies["app2"][0]["decision"] = "allow"  # someone edited it in the dashboard
        self.run_with(cf)
        self.assertEqual(cf.policies["app2"][0]["decision"], "bypass")
        before = list(cf.writes)
        self.run_with(cf)
        self.assertEqual(cf.writes, before)

    def test_the_public_folder_holds_only_icons_and_the_manifest(self):
        files = sorted(p.name for p in (ROOT / "src/classical_radar/web/icons").rglob("*") if p.is_file())
        self.assertTrue(files and all(f.endswith((".png", ".svg", ".webmanifest")) for f in files), files)

    def test_without_emails_access_is_skipped_and_api_stays_closed(self):
        cf = FakeCloudflare()
        out = self.run_with(cf, {**ENV, "ACCESS_EMAILS": ""})
        self.assertFalse(out["access"])
        self.assertEqual(cf.apps, [])
        self.assertIn('ACCESS_AUD = ""', self.toml.read_text())

    def test_missing_zero_trust_org_and_bad_input_fail_clearly(self):
        with self.assertRaisesRegex(CloudflareError, "Zero Trust is not set up"):
            self.run_with(FakeCloudflare(zero_trust=False))
        with self.assertRaisesRegex(CloudflareError, "not set"):
            self.run_with(FakeCloudflare(), {"ACCESS_EMAILS": "x@y.z"})
        with self.assertRaisesRegex(CloudflareError, "e-mail"):
            self.run_with(FakeCloudflare(), {**ENV, "ACCESS_EMAILS": "not-an-email"})

    def test_cloudflare_error_message_is_passed_through(self):
        def denied(request):
            return httpx.Response(403, json={"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]})
        with self.assertRaisesRegex(CloudflareError, "Authentication error"):
            run(ENV, self.toml, transport=httpx.MockTransport(denied), log=lambda m: None)


if __name__ == "__main__":
    unittest.main()
