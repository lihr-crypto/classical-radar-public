"""Idempotent Cloudflare setup, run by .github/workflows/deploy.yml before every deploy.

Ensures (creating only what is missing):
  1. the Pages project ``classical-radar`` (production branch main);
  2. the KV namespace ``classical-radar-state`` for personal state;
  3. a Cloudflare Access self-hosted application covering classical-radar.pages.dev and *.classical-radar.pages.dev, with one allow
     policy for the e-mail addresses in ACCESS_EMAILS (a repository *variable*, comma separated);
  4. a second Access application for ONLY classical-radar.pages.dev/icons/* with a "bypass for everyone" policy: iOS fetches the home-screen
     icon and the web app manifest without the visitor's login cookie, so behind the login they come back as a redirect and the phone
     draws a letter instead. Access applies the most specific path, so everything else stays behind the e-mail login. The folder holds
     only the icon files and the manifest (a test enforces that);
then writes wrangler.toml with the KV id, Access team domain and AUD so the deploy binds them.

Environment: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID (secrets), ACCESS_EMAILS (variable). Any API error stops the job with
Cloudflare's own message; nothing is deployed half-configured. Without ACCESS_EMAILS the Access step is skipped and the API stays closed.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import httpx

API = "https://api.cloudflare.com/client/v4"
PROJECT = "classical-radar"
KV_TITLE = "classical-radar-state"
APP_NAME = "Classical Radar"
POLICY_NAME = "Owner only"
ICONS_PATH = "/icons/*"
ICONS_APP_NAME = "Classical Radar icons"
ICONS_POLICY_NAME = "Public icons"


class CloudflareError(RuntimeError):
    pass


class CF:
    def __init__(self, token: str, account: str, transport=None):
        self.account = account
        self.http = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=30, transport=transport)

    def call(self, method: str, path: str, body=None, ok404: bool = False):
        r = self.http.request(method, f"/accounts/{self.account}{path}", json=body)
        if ok404 and r.status_code == 404:
            return None
        try:
            data = r.json()
        except ValueError as exc:
            raise CloudflareError(f"{method} {path}: HTTP {r.status_code}") from exc
        if not data.get("success", False):
            msgs = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in data.get("errors", [])) or f"HTTP {r.status_code}"
            if ok404 and any(e.get("code") in (8000007, 10007) for e in data.get("errors", [])):
                return None  # "project not found" style errors
            raise CloudflareError(f"{method} {path}: {msgs}")
        return data.get("result")

    def close(self):
        self.http.close()


def ensure_project(cf: CF, log) -> str:
    if cf.call("GET", f"/pages/projects/{PROJECT}", ok404=True) is None:
        cf.call("POST", "/pages/projects", {"name": PROJECT, "production_branch": "main"})
        log(f"created Pages project {PROJECT}")
    return f"{PROJECT}.pages.dev"


def ensure_kv(cf: CF, log) -> str:
    for ns in cf.call("GET", "/storage/kv/namespaces?per_page=100") or []:
        if ns.get("title") == KV_TITLE:
            return ns["id"]
    ns = cf.call("POST", "/storage/kv/namespaces", {"title": KV_TITLE})
    log(f"created KV namespace {KV_TITLE}")
    return ns["id"]


def ensure_access(cf: CF, domain: str, emails: list[str], log) -> tuple[str, str]:
    org = cf.call("GET", "/access/organizations", ok404=True)
    team = (org or {}).get("auth_domain")
    if not team:
        raise CloudflareError("Zero Trust is not set up for this account yet: open dash.cloudflare.com > Zero Trust once, choose a team name "
                              "and the Free plan, then re-run this workflow")
    wanted = {domain, f"*.{domain}"}
    app = next((a for a in cf.call("GET", "/access/apps") or [] if a.get("domain") == domain or wanted & set(a.get("self_hosted_domains") or [])), None)
    if app is None:
        app = cf.call("POST", "/access/apps", {"name": APP_NAME, "type": "self_hosted", "domain": domain, "self_hosted_domains": sorted(wanted),
                                               "session_duration": "720h", "app_launcher_visible": False})
        log(f"created Access application for {domain}")
    include = [{"email": {"email": e}} for e in emails]
    policies = cf.call("GET", f"/access/apps/{app['id']}/policies") or []
    pol = next((p for p in policies if p.get("name") == POLICY_NAME), None)
    body = {"name": POLICY_NAME, "decision": "allow", "include": include, "precedence": 1}
    if pol is None:
        cf.call("POST", f"/access/apps/{app['id']}/policies", body)
        log("created Access allow policy")
    elif sorted(json.dumps(x, sort_keys=True) for x in pol.get("include", [])) != sorted(json.dumps(x, sort_keys=True) for x in include):
        cf.call("PUT", f"/access/apps/{app['id']}/policies/{pol['id']}", body)
        log("updated Access allow policy")
    return team, app["aud"]


def ensure_icons_bypass(cf: CF, domain: str, log) -> None:
    host = f"{domain}{ICONS_PATH}"
    app = next((a for a in cf.call("GET", "/access/apps") or [] if a.get("domain") == host or host in (a.get("self_hosted_domains") or [])), None)
    if app is None:
        app = cf.call("POST", "/access/apps", {"name": ICONS_APP_NAME, "type": "self_hosted", "domain": host, "self_hosted_domains": [host],
                                               "session_duration": "24h", "app_launcher_visible": False})
        log(f"created Access application for {host} (public icons)")
    include = [{"everyone": {}}]
    body = {"name": ICONS_POLICY_NAME, "decision": "bypass", "include": include, "precedence": 1}
    pol = next((p for p in cf.call("GET", f"/access/apps/{app['id']}/policies") or [] if p.get("name") == ICONS_POLICY_NAME), None)
    if pol is None:
        cf.call("POST", f"/access/apps/{app['id']}/policies", body)
        log("created Access bypass policy for the icons")
    elif pol.get("decision") != "bypass" or pol.get("include") != include:
        cf.call("PUT", f"/access/apps/{app['id']}/policies/{pol['id']}", body)
        log("updated Access bypass policy for the icons")


def write_wrangler(path: Path, kv_id: str, team: str, aud: str) -> None:
    text = path.read_text(encoding="utf8")
    text = re.sub(r'(binding = "CR_STATE"\s*\nid = )"[^"]*"', rf'\1"{kv_id}"', text)
    text = re.sub(r'ACCESS_TEAM_DOMAIN = "[^"]*"', f'ACCESS_TEAM_DOMAIN = "{team}"', text)
    text = re.sub(r'ACCESS_AUD = "[^"]*"', f'ACCESS_AUD = "{aud}"', text)
    path.write_text(text, encoding="utf8")


def run(env: dict, wrangler: Path, transport=None, log=print) -> dict:
    token, account = env.get("CLOUDFLARE_API_TOKEN", ""), env.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not token or not account:
        raise CloudflareError("CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID are not set")
    emails = [e.strip().lower() for e in env.get("ACCESS_EMAILS", "").split(",") if e.strip()]
    if any(not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e) for e in emails):
        raise CloudflareError("ACCESS_EMAILS must be comma-separated e-mail addresses")
    cf = CF(token, account, transport)
    try:
        domain = ensure_project(cf, log)
        kv_id = ensure_kv(cf, log)
        team, aud = ("", "")
        if emails:
            team, aud = ensure_access(cf, domain, emails, log)
            ensure_icons_bypass(cf, domain, log)
        else:
            log("ACCESS_EMAILS not set: Access step skipped, /api/me stays closed (401)")
    finally:
        cf.close()
    write_wrangler(wrangler, kv_id, team, aud)
    return {"domain": domain, "kv_id": kv_id, "team": team, "aud": aud, "access": bool(emails)}


def main():
    try:
        out = run(dict(os.environ), Path("wrangler.toml"), log=lambda m: print(m, file=sys.stderr))
    except (CloudflareError, httpx.HTTPError) as exc:
        print(f"::error::Cloudflare setup failed: {exc}")
        sys.exit(1)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf8") as f:
            f.write(f"### Cloudflare\n- Site: https://{out['domain']}\n- Access: {'on' if out['access'] else 'OFF (set the ACCESS_EMAILS variable)'}\n")
    print(json.dumps({k: v for k, v in out.items() if k != "aud"}))


if __name__ == "__main__":
    main()
