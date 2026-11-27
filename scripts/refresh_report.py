"""Markdown summary of one cloud refresh run (the sync, leads and auto-confirm outputs), for the GitHub job summary.

Usage: python scripts/refresh_report.py SYNC.json LEADS.json|- AUTOCONFIRM.json [--title T] [--note N] [--strict] > summary.md
With --strict the exit status is 1 when a source failed or yielded nothing, or the auto-confirm flood guard tripped (the summary is still printed).
It only formats what the commands already printed; a source that failed or was blocked is flagged with Cloudflare-style plainness: the
error text verbatim, so a 403 from a site that refuses GitHub's servers is visible at a glance.
"""
import json
import sys
from pathlib import Path

PRESENTERS = ("japanarts", "kajimoto", "kanagawa_geikyo")  # the same three as autoconfirm.PRESENTER_SOURCES (this script stays free of the package)


def load(path: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf8"))
    except (OSError, ValueError):
        return None


def sync_rows(results) -> list[str]:
    rows = ["| 来源 | 结果 | 说明 |", "|---|---|---|"]
    for r in results or []:
        status = r.get("status", "?")
        if status == "failed":
            rows.append(f"| {r.get('source_id')} | ❌ 失败 | `{str(r.get('error', ''))[:200]}` |")
        elif status == "skipped":
            rows.append(f"| {r.get('source_id')} | ⏭ 跳过 | {r.get('reason', '')} |")
        elif not r.get("items_listed"):
            rows.append(f"| {r.get('source_id')} | ⚠️ 读到 0 条 | 没报错但一条都没读到，可能被拦截或页面改版 |")
        else:
            facts = ", ".join(f"{k}={v}" for k, v in r.items() if k not in ("source_id", "status") and isinstance(v, (int, str)) and v != "")
            rows.append(f"| {r.get('source_id')} | ✅ {status} | {facts[:200]} |")
    return rows


def blocked(results) -> list[str]:
    return [r["source_id"] for r in results or [] if r.get("status") == "failed" and any(c in str(r.get("error", "")) for c in ("HTTP 401", "HTTP 403", "HTTP 429"))]


def problems(results, auto, leads=None, publish=None, leads_asked=False) -> list[str]:
    """What should turn a scheduled run red. ``sync`` exits 0 even when every source failed, so the job has to look for itself.

    The tour leads (ADR-0018) are read by their own command, so they are judged here too: ``leads`` is the output of ``leads-sync`` (None when the
    command left nothing readable, which only counts when ``leads_asked``), ``publish`` is cloud_publish.py's answer (its ``leads_problems`` are the
    reasons the freshly exported leads file was held back)."""
    found = []
    if leads_asked and not leads:
        found.append("海外线索：没有输出（leads-sync 没有给出结果）")
    elif leads and leads.get("stopped"):
        found.append(f"海外线索：读取中止（{str(leads['stopped'])[:120]}）")
    for p in (publish or {}).get("leads_problems") or []:
        found.append(f"海外线索：这次没有发布（{str(p)[:140]}）")
    if not results:
        found.append("没有抓取结果")
    for r in results or []:
        status = r.get("status")
        if status == "failed":
            found.append(f"{r.get('source_id')}：抓取失败（{str(r.get('error', ''))[:120]}）")
        elif status == "succeeded" and not r.get("items_listed"):
            found.append(f"{r.get('source_id')}：读到 0 条")
        for w in r.get("warnings") or []:  # the source ran, but part of what it should have read was skipped (a missing year file, a pager past the cap)
            found.append(f"{r.get('source_id')}：{str(w)[:160]}")
    if auto and auto.get("flood_guard") and auto.get("mode") == "apply":  # in a report-only run the guard is information, not a failure
        found.append(f"自动确认的防洪触发：{auto.get('note')}")
    return found


def main() -> int:
    argv = sys.argv[1:]
    strict = "--strict" in argv
    opts = {}
    for name in ("--title", "--note", "--publish"):
        if name in argv:
            i = argv.index(name)
            opts[name] = argv[i + 1]
            del argv[i:i + 2]
    argv = [a for a in argv if a != "--strict"]
    sync = load(argv[0])
    leads_asked = len(argv) > 1 and argv[1] != "-"
    leads = load(argv[1]) if leads_asked else None
    auto = load(argv[2]) if len(argv) > 2 else None
    publish = load(opts["--publish"]) if opts.get("--publish") else None  # cloud_publish.py's answer: its leads_problems are shown and make the run red
    out = [f"# {opts.get('--title', '云端试跑结果')}", ""]
    if opts.get("--note"):
        out += [f"> {opts['--note']}", ""]
    b = blocked(sync)
    if b:
        out += [f"> ⚠️ 这些来源拒绝了 GitHub 的服务器（HTTP 401/403/429）：**{', '.join(b)}**。它们在云端读不了，只能手动更新。", ""]
    found = problems(sync, auto, leads, publish, leads_asked)
    if found:
        out += ["## 需要注意", *[f"- {f}" for f in found], ""]
    out += ["## 抓取", *sync_rows(sync), ""]
    if leads is not None or (len(argv) > 1 and argv[1] != "-"):
        out += ["## 海外乐团线索", "```json", json.dumps(leads, ensure_ascii=False, indent=1) if leads is not None else "没有输出", "```", ""]
    mode = auto.get("mode") if auto else None
    out += ["## 自动确认（只报告，不确认）" if mode != "apply" else "## 自动确认"]
    if auto is None:
        out += ["没有输出"]
    else:
        out += [f"- 符合条件：{auto.get('qualifying', 0)}　　保留给人：{len(auto.get('held', []))}　　不在范围内（暂缓的来源等）：{auto.get('outside_scope', 0)}　　更早的候选（本次不处理）：{auto.get('older_candidates', 0)}"]
        if mode == "apply":
            out += [f"- 本次确认：{len(auto.get('confirmed', []))} 场"]
            live = auto.get("went_live") or []
            if live:  # a presenter's concert is published without a person looking at it (ADR-0017): list them so they can be checked afterwards
                out += ["", "### 本次上线的公演（主办方的没有经过人看，请事后抽查）"]
                out += [f"- {'【主办方】' if q.get('source_id') in PRESENTERS else ''}{q.get('source_id')}：{str(q.get('title_ja', ''))[:60]}" for q in live[:80]]
                if len(live) > 80:
                    out += [f"- 另有 {len(live) - 80} 场"]
                out += [""]
        if auto.get("flood_guard"):
            out += [f"- 🚧 {auto.get('note')}"]
        for h in auto.get("held", [])[:20]:
            out += [f"  - {h['source_id']}：{h['title_ja'][:40]}（{h['reason']}）"]
    print("\n".join(out))
    if strict and found:
        print("\n".join(f"问题：{f}" for f in found), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
