"""Decide whether a cloud refresh has something worth a data PR, and say what changed (ADR-0008, step 2).

Usage: python scripts/cloud_publish.py OLD.json NEW.json [--autoconfirm AUTOCONFIRM.json] [--body-out BODY.md] [--now ISO] [--bootstrapped]
                                       [--leads-old LEADS.json] [--leads-new NEW-LEADS.json] [--accept-leads]
Prints one JSON object: {"publish": bool, "concerts": bool, "leads": bool, "reasons": [...], "problems": [...], "leads_problems": [...], "added": n, "removed": n, "modified": n, ...}.
``publish`` = a data PR is worth opening (the concerts, the tour leads or both); ``concerts`` / ``leads`` say which of the two files go into it.
Exit status: 0 = decision made (publish or not), 3 = a safety gate on the CONCERTS failed (the caller must not upload or push anything, leads included).

Every export differs from the last one in places nobody needs to review: the as_of stamp, the snapshot label, the coverage block and each
performance's ``last_seen_at``. Those are ignored when asking "did anything change". A PR is still opened when the published file is
more than STALE_DAYS old, so the page's "updated on" date does not drift far from the last check.

The overseas tour leads (okemin.com, ADR-0007 / ADR-0018) are a second, separate file with their own gates. A failed leads gate holds only the leads:
the published file stays, the concerts go on, and the problem is reported in ``leads_problems`` (the workflow turns the run red at the end).
``--accept-leads`` (a manual one-off) skips the two COUNT gates for leads; the structure check always runs.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

STALE_DAYS = 7
MIN_KEPT = 0.9      # fewer than this share of the published concerts in the new file: something broke, publish nothing
MAX_ADDED = 150     # more new concerts than this in one PR is not a review, it is a flood (the auto-confirm guard is 120)
NOISE_TOP = ("as_of", "snapshot_label", "coverage")
MIN_KEPT_LEADS = 0.7   # fewer than this share of the published leads in the new file: a layout change or an empty database, hold the leads
MAX_ADDED_LEADS = 60   # a first full reading is about 50; more than this at once is a parser gone wrong, not new tours
LEAD_NOISE = ("last_changed_at",)  # moves only when a fact changed, so it never says anything the facts do not


def load(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def load_or_none(path):
    """A file that is missing or not valid JSON is None (the caller says so), not a crash."""
    try:
        return load(path) if path and Path(path).is_file() else None
    except ValueError:
        return None


def _core(c: dict) -> dict:
    """A concert without the fields that change on every sync."""
    out = {k: v for k, v in c.items() if k != "performances"}
    out["performances"] = [{k: v for k, v in p.items() if k != "last_seen_at"} for p in c.get("performances", [])]
    return out


def images(data: dict) -> int:
    return sum(bool(c.get("image")) + sum(bool(a.get("image")) for a in c.get("artists", [])) for c in data.get("concerts", []))


def compare(old: dict, new: dict) -> dict:
    o = {c["id"]: c for c in old.get("concerts", [])}
    n = {c["id"]: c for c in new.get("concerts", [])}
    added = [n[i] for i in n if i not in o]
    removed = [o[i] for i in o if i not in n]
    modified = []
    for i in n:
        if i in o:
            a, b = _core(o[i]), _core(n[i])
            if a != b:
                modified.append({"id": i, "title_ja": n[i]["title_ja"], "fields": sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))})
    return {"added": added, "removed": removed, "modified": modified}


def gate(old: dict, new: dict, diff: dict) -> list[str]:
    problems = []
    kept = len(old.get("concerts", []))
    if kept and len(new.get("concerts", [])) < MIN_KEPT * kept:
        problems.append(f"the new file has {len(new.get('concerts', []))} concerts, fewer than {int(MIN_KEPT * 100)}% of the published {kept}")
    if images(new) < images(old):
        problems.append(f"the new file has fewer images ({images(new)}) than the published one ({images(old)}): the cloud cannot fetch images, so it must not wash them out")
    if len(diff["added"]) > MAX_ADDED:
        problems.append(f"{len(diff['added'])} new concerts at once (limit {MAX_ADDED}): a person should look first")
    return problems


def _lead_core(lead: dict) -> dict:
    return {k: v for k, v in lead.items() if k not in LEAD_NOISE}


def compare_leads(old: dict | None, new: dict | None) -> dict:
    """What changed between two leads files, by ``lead_id``. The file's as_of / read_at and each lead's last_changed_at are noise."""
    o = {x["lead_id"]: x for x in (old or {}).get("leads", []) if isinstance(x, dict) and "lead_id" in x}
    n = {x["lead_id"]: x for x in (new or {}).get("leads", []) if isinstance(x, dict) and "lead_id" in x}
    modified = []
    for i in n:
        if i in o and _lead_core(o[i]) != _lead_core(n[i]):
            a, b = _lead_core(o[i]), _lead_core(n[i])
            modified.append({"lead_id": i, "orchestra_name": n[i].get("orchestra_name", ""), "period_raw": n[i].get("period_raw") or "",
                             "fields": sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))})
    return {"added": [n[i] for i in n if i not in o], "removed": [o[i] for i in o if i not in n], "modified": modified}


def leads_structure(data) -> list[str]:
    """The same rule as ``leads.validate_file`` (written out here: this script stays free of the package), plus no repeated id."""
    if not isinstance(data, dict) or not isinstance(data.get("leads"), list):
        return ["the new leads file is not {leads: [...]}"]
    seen = set()
    for lead in data["leads"]:
        if not isinstance(lead, dict) or not str(lead.get("lead_id", "")).startswith("lead-") or not lead.get("orchestra_name"):
            return ["every lead needs a lead_id (lead-…) and an orchestra_name"]
        if lead["lead_id"] in seen:
            return [f"the lead {lead['lead_id']} appears twice"]
        seen.add(lead["lead_id"])
    return []


def leads_gate(old: dict | None, new: dict | None, diff: dict, accept: bool = False) -> list[str]:
    """Why the leads must NOT be published this run. ``accept`` (a manual one-off) lifts only the two count gates."""
    if new is None:
        return ["the new leads file is missing or unreadable (leads-export failed)"]
    problems = leads_structure(new)
    if problems or accept:
        return problems
    kept = len((old or {}).get("leads", []))
    if kept and len(new["leads"]) < MIN_KEPT_LEADS * kept:
        problems.append(f"the new leads file has {len(new['leads'])} leads, fewer than {int(MIN_KEPT_LEADS * 100)}% of the published {kept}")
    if len(diff["added"]) > MAX_ADDED_LEADS:
        problems.append(f"{len(diff['added'])} new leads at once (limit {MAX_ADDED_LEADS}): a person should look first")
    return problems


def stale(old: dict, now: datetime) -> bool:
    try:
        as_of = datetime.fromisoformat(old["as_of"])
    except (KeyError, ValueError):
        return True
    return now - as_of > timedelta(days=STALE_DAYS)


def body(diff: dict, auto: dict | None, reasons: list[str], bootstrapped: bool, leads: dict | None = None) -> str:
    """``leads`` = {"diff": ..., "problems": [...], "published": bool} when the tour leads were checked, else None (no section)."""
    lines = ["云端自动采集生成的数据更新。合并后网站会自动部署。", ""]
    if bootstrapped:
        lines += ["> 这次的数据库是从线上数据还原的，自动确认只报告、没有真确认。", ""]
    lines += ["## 数据变化", f"- 新增 {len(diff['added'])} 场，变更 {len(diff['modified'])} 场，减少 {len(diff['removed'])} 场"]
    for c in diff["added"][:30]:
        lines.append(f"  - 新增：{c['source_id']}：{c['title_ja'][:50]}")
    for m in diff["modified"][:30]:
        lines.append(f"  - 变更：{m['title_ja'][:50]}（{', '.join(m['fields'])}）")
    for c in diff["removed"][:30]:
        lines.append(f"  - 减少：{c['source_id']}：{c['title_ja'][:50]}")
    if sum(len(diff[k]) for k in diff) > 90:
        lines.append("  - （只列出每类前 30 条）")
    if not any(diff.values()) and reasons:
        lines.append("- 没有实质变化，只是刷新日期：" + "；".join(reasons))
    elif not any(diff.values()):
        lines.append("- 演出没有变化，这次只更新海外乐团线索")
    if leads is not None:
        ld = leads["diff"]
        lines += ["", "## 海外乐团线索（オケミン！，第三方整理，未核实）"]
        if leads["problems"]:
            lines += [f"- 🚧 这次没有发布线索，已发布的文件保持不变：{p}" for p in leads["problems"]]
        else:
            lines.append(f"- 新增 {len(ld['added'])} 条，变更 {len(ld['modified'])} 条，减少 {len(ld['removed'])} 条")
            for x in ld["added"][:30]:
                lines.append(f"  - 新增：{x.get('orchestra_name', '')}：{x.get('period_raw') or ''}")
            for x in ld["modified"][:30]:
                lines.append(f"  - 变更：{x['orchestra_name']}：{x['period_raw']}（{', '.join(x['fields'])}）")
            for x in ld["removed"][:30]:
                lines.append(f"  - 减少：{x.get('orchestra_name', '')}：{x.get('period_raw') or ''}")
            if sum(len(ld[k]) for k in ld) > 90:
                lines.append("  - （只列出每类前 30 条）")
    if auto is not None:
        lines += ["", "## 自动确认"]
        if auto.get("mode") == "apply":
            lines.append(f"- 本次确认 {len(auto.get('confirmed', []))} 场")
        else:
            lines.append(f"- 只报告，没有确认：符合条件 {auto.get('qualifying', 0)} 场")
        lines.append(f"- 留给人 {len(auto.get('held', []))} 场；更早的候选 {auto.get('older_candidates', 0)} 个本次没处理")
        if auto.get("flood_guard"):
            lines.append(f"- 🚧 {auto.get('note')}")
    return "\n".join(lines) + "\n"


def decide(old: dict, new: dict, now: datetime, auto: dict | None = None, bootstrapped: bool = False,
           leads: dict | None = None, accept_leads: bool = False) -> dict:
    """``leads`` = {"old": the published leads file or None, "new": the freshly exported one or None}, or None when the leads are not part of this run."""
    diff = compare(old, new)
    problems = gate(old, new, diff)
    reasons = []
    if any(diff.values()):
        reasons.append(f"新增 {len(diff['added'])}、变更 {len(diff['modified'])}、减少 {len(diff['removed'])}")
    elif stale(old, now):
        reasons.append(f"已发布的文件超过 {STALE_DAYS} 天没更新日期")
    concerts = bool(reasons) and not problems
    ldiff = {"added": [], "removed": [], "modified": []}
    lproblems: list[str] = []
    leads_ok = leads_changed = False
    if leads is not None:
        ldiff = compare_leads(leads.get("old"), leads.get("new"))
        lproblems = leads_gate(leads.get("old"), leads.get("new"), ldiff, accept_leads)
        leads_changed = any(ldiff.values())
        leads_ok = not lproblems
    # a data PR is worth opening for real concert changes, for real lead changes, or for the stale-date refresh; the leads file rides along with any of them
    # (its dates stay fresh), but a failed leads gate never stops the concerts, and a failed CONCERT gate (exit 3 in main) stops everything
    publish = not problems and (bool(reasons) or (leads_ok and leads_changed))
    leads_in = leads_ok and (leads_changed or concerts)
    return {"publish": publish, "concerts": concerts, "leads": leads_in, "reasons": reasons, "problems": problems, "leads_problems": lproblems,
            "added": len(diff["added"]), "removed": len(diff["removed"]), "modified": len(diff["modified"]),
            "leads_added": len(ldiff["added"]), "leads_removed": len(ldiff["removed"]), "leads_modified": len(ldiff["modified"]),
            "body": body(diff, auto, reasons, bootstrapped, None if leads is None else {"diff": ldiff, "problems": lproblems})}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    def opt(name, default=None, flag=False):
        if name in args:
            i = args.index(name)
            if flag:
                args.pop(i)
                return True
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return False if flag else default
    auto_path, body_out, now_text, boot = opt("--autoconfirm"), opt("--body-out"), opt("--now"), opt("--bootstrapped", flag=True)
    leads_old, leads_new, accept = opt("--leads-old"), opt("--leads-new"), opt("--accept-leads", flag=True)
    old_path, new_path = args[0], args[1]
    now = datetime.fromisoformat(now_text) if now_text else datetime.now(timezone.utc)
    auto = None
    if auto_path and Path(auto_path).is_file():
        try:
            auto = load(auto_path)
        except ValueError:  # auto-confirm crashed and left an empty or broken file: publish on the data alone, the report says there is no auto-confirm output
            auto = None
    # --leads-new names the freshly exported file; asking for it and not finding it is a leads problem (reported), never a crash
    leads = {"old": load_or_none(leads_old), "new": load_or_none(leads_new)} if leads_new else None
    result = decide(load(old_path), load(new_path), now, auto, boot, leads, accept)
    if body_out:
        Path(body_out).write_text(result.pop("body"), encoding="utf8")
    else:
        result.pop("body")
    print(json.dumps(result, ensure_ascii=False))
    return 3 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
