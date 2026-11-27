import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .discover import coverage, discover
from .ingest import ingest_source
from .parsers import JST, ParseError, parse_list, parse_presenter_detail
from .sources import SOURCES


def _now(text: str | None) -> datetime:
    return datetime.fromisoformat(text) if text else datetime.now(timezone.utc)


def default_lead_years(now: datetime) -> list[int]:
    """The year pages ``leads-sync`` reads by default: this year and next, by the date in Japan. The daily cloud job starts at 19:23 UTC, which on
    31 December is already 1 January in Tokyo (ADR-0018)."""
    year = now.astimezone(JST).year
    return [year, year + 1]


def build_parser():
    parser = argparse.ArgumentParser(prog="classical-radar", description="Offline parsers + local SQLite store. Only import-url touches the network, one registered page at a time.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("list", "detail"):
        p = sub.add_parser(name, help=f"parse a saved {name} page to JSON (offline)")
        p.add_argument("source", choices=sorted(SOURCES))
        p.add_argument("file", type=Path)
        p.add_argument("--url", required=True, help="Original evidence URL; not fetched")
    p = sub.add_parser("db-init", help="create the SQLite schema")
    p.add_argument("db", type=Path)
    p = sub.add_parser("ingest", help="parse a saved page and store candidates as needs_review (never official_confirmed)")
    p.add_argument("db", type=Path)
    p.add_argument("kind", choices=["list", "detail"])
    p.add_argument("source", choices=sorted(SOURCES))
    p.add_argument("file", type=Path)
    p.add_argument("--url", required=True)
    p.add_argument("--observed-at")
    p = sub.add_parser("import-url", help="fetch ONE registered official page and stage candidates (needs import-confirm)")
    p.add_argument("db", type=Path)
    p.add_argument("url")
    p.add_argument("--raw-dir", type=Path, default=Path("evidence/raw"))
    p = sub.add_parser("import-confirm", help="human confirmation: publish a staged import as official_confirmed")
    p.add_argument("db", type=Path)
    p.add_argument("import_id")
    p.add_argument("--category", required=True, choices=["domestic_orchestra", "overseas_orchestra_visit", "piano_recital", "other"])
    p.add_argument("--prefecture", action="append", default=[], metavar="PERFORMANCE_ID=JIS_CODE", help="needed only when the venue is not in venues.py")
    p.add_argument("--note")
    p = sub.add_parser("import-reject", help="reject a staged import")
    p.add_argument("db", type=Path)
    p.add_argument("import_id")
    p.add_argument("--note")
    p = sub.add_parser("discover", help="run the 3.5 discover query")
    p.add_argument("db", type=Path)
    p.add_argument("--as-of")
    p.add_argument("--category", default="all")
    p.add_argument("--months", type=int, default=12)
    p.add_argument("--region-mode", default="kanto_first")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("coverage", help="what is stored per source (no percentages)")
    p.add_argument("db", type=Path)
    p = sub.add_parser("sync", help="MANUAL rate-limited fetch of the registered sources into the store (needs_review only; no scheduler)")
    p.add_argument("db", type=Path)
    p.add_argument("--source", action="append", choices=sorted(SOURCES), help="repeatable; default: all supported sources")
    p.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    p.add_argument("--no-details", action="store_true", help="list pages only for tso/njp/jpo/kanagawa_geikyo (skips ~260 detail requests: no programme/performers/sale times)")
    p = sub.add_parser("monitor", help="ONE manual, polite monitoring round over the registered sources (never 都响; skips a source seen less than --min-interval-hours ago). Run by hand: this project installs no scheduler")
    p.add_argument("db", type=Path)
    p.add_argument("--source", action="append", choices=sorted(SOURCES), help="repeatable; default: every monitorable source")
    p.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    p.add_argument("--min-interval-hours", type=float, default=6.0)
    p.add_argument("--force", action="store_true", help="ignore the minimum interval (use sparingly)")
    p = sub.add_parser("monitor-report", help="cadence of the rounds so far and, per detected change, an UPPER BOUND of how late we noticed it (the official change time is unknown)")
    p.add_argument("db", type=Path)
    p = sub.add_parser("remind-run", help="deliver due reminders through the LOCAL FAKE sender (appends to an outbox file, sends nothing anywhere); run by hand, no scheduler is installed")
    p.add_argument("db", type=Path)
    p.add_argument("--now", help="ISO-8601 instant to act as 'now' (default: the real clock)")
    p.add_argument("--outbox", type=Path, default=Path("data/outbox.jsonl"))
    p.add_argument("--no-retry", action="store_true", help="do not retry deliveries that failed on an earlier run")
    p = sub.add_parser("duplicates-dump", help="write this database's same-concert / not-the-same decisions into the reviewed file (merges; never shrinks it unless --prune)")
    p.add_argument("db", type=Path)
    p.add_argument("--file", type=Path, default=Path("site-data/same_concert.json"))
    p.add_argument("--prune", action="store_true", help="also drop file entries whose two concerts are in this database but undecided there (i.e. an undo)")
    p = sub.add_parser("duplicates-apply", help="replay the reviewed decisions file into this database (same guards as the review page; unknown or refused entries are skipped and listed)")
    p.add_argument("db", type=Path)
    p.add_argument("--file", type=Path, default=Path("site-data/same_concert.json"))
    p = sub.add_parser("leads-sync", help="ONE polite reading of okemin.com's overseas-orchestra pages into tour leads (second-hand, unverified; robots.txt first, 2 s per request, at most 80 requests; run by hand or by the daily cloud job, ADR-0018)")
    p.add_argument("db", type=Path)
    p.add_argument("--year", type=int, action="append", help="repeatable; default: this year and next, by the date in Japan")
    p.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    p = sub.add_parser("leads-export", help="write the tour leads to site-data/leads.json (facts and a credit; reviewed in a PR like concerts.json)")
    p.add_argument("db", type=Path)
    p.add_argument("--out", type=Path, default=Path("site-data/leads.json"))
    p = sub.add_parser("auto-confirm", help="confirm new concerts of the official sites (six orchestras and, ADR-0017, the three presenters) whose fields are complete (dry run unless --apply; leads are never touched)")
    p.add_argument("db", type=Path)
    p.add_argument("--apply", action="store_true", help="really confirm (default: only report)")
    p.add_argument("--max", type=int, default=120, help="flood guard: confirm nothing if more than this many qualify in one run")
    p.add_argument("--first-seen-after", metavar="ISO", help="only consider candidates a sync first saw at or after this instant (the cloud run passes its own start time); older ones stay for a person")
    p.add_argument("--no-presenters", action="store_true", help="leave Japan Arts, KAJIMOTO and 神奈川芸術協会 to a person (the cloud job's AUTO_CONFIRM_PRESENTERS=false switch)")
    p = sub.add_parser("restore-site", help="rebuild an EMPTY database from the published site data under its original ids (the cloud database starts here); then replays the reviewed same-concert decisions")
    p.add_argument("db", type=Path)
    p.add_argument("--concerts", type=Path, default=Path("site-data/concerts.json"))
    p.add_argument("--same", type=Path, default=Path("site-data/same_concert.json"))
    p = sub.add_parser("images", help="look up freely licensed photos (Wikidata/Commons) for performers and orchestras of confirmed concerts")
    p.add_argument("db", type=Path)
    p.add_argument("--media-dir", type=Path, default=Path("data/media"))
    p.add_argument("--limit", type=int, help="look up at most N names this run")
    p = sub.add_parser("serve", help="run the local HTTP API; token from CLASSICAL_RADAR_TOKEN (>=16 chars), binds 127.0.0.1 by default")
    p.add_argument("db", type=Path)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    conn = None
    try:
        if args.cmd in ("list", "detail"):
            html = args.file.read_text()
            if args.cmd == "list":
                performances, cov = parse_list(args.source, html, args.url)
                result = {"performances": performances, "coverage": cov}
            else:
                result = parse_presenter_detail(args.source, html, args.url)
        elif args.cmd == "serve":
            import os
            import uvicorn
            from .api import create_app
            app = create_app(str(args.db), os.environ.get("CLASSICAL_RADAR_TOKEN", ""), raw_dir=args.raw_dir, media_dir=Path("data/media"))
            uvicorn.run(app, host=args.host, port=args.port)
            return
        elif args.cmd == "db-init":
            conn = db.connect(str(args.db))
            db.init(conn)
            result = {"db": str(args.db), "schema_version": db.SCHEMA_VERSION}
        else:
            conn = db.connect(str(args.db))
            db.init(conn)
            if args.cmd == "ingest":
                html = args.file.read_text()
                if args.kind == "list":
                    cands, _ = parse_list(args.source, html, args.url)
                else:
                    cands = parse_presenter_detail(args.source, html, args.url)["performances"]
                result = ingest_source(conn, args.source, cands, _now(args.observed_at), complete=args.kind == "detail", doc_kind=args.kind)
            elif args.cmd == "sync":
                from .network import Reader
                from .sync import SUPPORTED, sync_source
                reader = Reader(args.raw_dir)
                try:
                    result = [sync_source(conn, reader, sid, log=lambda m: print(m, file=sys.stderr), details=not args.no_details) for sid in (args.source or SUPPORTED)]
                finally:
                    reader.close()
            elif args.cmd == "monitor":
                from .monitor import run_round
                from .network import Reader
                reader = Reader(args.raw_dir)
                try:
                    result = run_round(conn, reader, args.source, _now(None), min_interval_hours=args.min_interval_hours, force=args.force, log=lambda m: print(m, file=sys.stderr))
                finally:
                    reader.close()
            elif args.cmd == "monitor-report":
                from .monitor import report
                result = report(conn)
            elif args.cmd == "remind-run":
                from .reminders import FakeSender, run_due
                result = run_due(conn, _now(args.now), FakeSender(args.outbox), retry_failed=not args.no_retry)
            elif args.cmd == "duplicates-dump":
                from .duplicates import merge_file
                result = merge_file(conn, args.file, prune=args.prune)
            elif args.cmd == "duplicates-apply":
                from .duplicates import apply_file
                result = apply_file(conn, args.file, _now(None))
            elif args.cmd == "leads-sync":
                from . import leads as leads_mod
                from .network import Reader
                reader = Reader(args.raw_dir)
                try:
                    years = args.year or default_lead_years(_now(None))
                    result = leads_mod.sync_leads(conn, reader, years, log=lambda m: print(m, file=sys.stderr))
                finally:
                    reader.close()
            elif args.cmd == "leads-export":
                import json as _json
                from . import leads as leads_mod
                data = leads_mod.export_file(conn, _now(None).astimezone(JST).date().isoformat())
                leads_mod.validate_file(data)
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(_json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf8")
                result = {"file": str(args.out), "leads": len(data["leads"])}
            elif args.cmd == "auto-confirm":
                from . import autoconfirm
                result = autoconfirm.run(conn, _now(None), apply=args.apply, max_confirm=args.max, first_seen_after=args.first_seen_after, presenters=not args.no_presenters)
            elif args.cmd == "restore-site":
                from .restore import restore_site
                result = restore_site(conn, args.concerts, args.same, _now(None))
            elif args.cmd == "images":
                from .images import run
                result = run(conn, args.media_dir, limit=args.limit, log=lambda m: print(m, file=sys.stderr))
            elif args.cmd == "import-url":
                from .import_url import stage_import
                from .network import Reader
                reader = Reader(args.raw_dir)
                try:
                    result = stage_import(conn, args.url, reader, _now(None))
                finally:
                    reader.close()
            elif args.cmd == "import-confirm":
                from .import_url import confirm_import
                overrides = dict(x.split("=", 1) for x in args.prefecture)
                result = confirm_import(conn, args.import_id, _now(None), category=args.category, prefecture_overrides=overrides, note=args.note)
            elif args.cmd == "import-reject":
                from .import_url import reject_import
                reject_import(conn, args.import_id, _now(None), args.note)
                result = {"rejected": args.import_id}
            elif args.cmd == "discover":
                result = discover(conn, as_of=_now(args.as_of), category=args.category, months=args.months, region_mode=args.region_mode, page=args.page, limit=args.limit)
            else:
                result = coverage(conn)
    except Exception as exc:  # noqa: BLE001 - CLI boundary: one readable line, non-zero exit
        parser.exit(2, f"{args.cmd} failed: {type(exc).__name__}: {exc}\n")
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
