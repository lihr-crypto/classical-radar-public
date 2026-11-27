#!/usr/bin/env python3
"""Summarise what the sale-time parsers put into a database (counts only, no page text).

Usage: p03_sale_sync_summary.py --run LABEL=DB[:REQUESTS[:NOTE]] [--run ...] [--now ISO] [--out evidence/p03/sale-sync-YYYY-MM-DD.json]

Used after a manual `classical-radar sync` (the real run, REQUESTS = requests it made) and after a REPLAY of the cached detail pages
(list pages are fetched again; REQUESTS = requests the replay made). It reads only ticket_phase / performance / concert, per source: concerts and performances
with phases, phases by type, how many start after ``--now``, and three sanity counts that must be zero (duplicate phases for the same
performance/type/start, sale starts after the performance date, starts before 2024).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("japanarts", "kanagawa_geikyo", "tso")


def summarise(db_path: str, now: str) -> dict:
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    out = {}
    for sid in SOURCES:
        like = f"{sid}|%"
        base = "FROM ticket_phase t JOIN performance p ON p.id=t.performance_id JOIN concert c ON c.id=p.concert_id WHERE c.identity_key LIKE ?"
        by_type = {r["phase_type"]: r["n"] for r in c.execute(f"SELECT t.phase_type, COUNT(*) n {base} GROUP BY 1", (like,))}
        labels = {r["eligibility"]: r["n"] for r in c.execute(f"SELECT t.eligibility, COUNT(*) n {base} GROUP BY 1 ORDER BY 2 DESC", (like,))}
        out[sid] = {
            "concerts": c.execute("SELECT COUNT(*) FROM concert WHERE identity_key LIKE ?", (like,)).fetchone()[0],
            "performances": c.execute("SELECT COUNT(*) FROM performance p JOIN concert c ON c.id=p.concert_id WHERE c.identity_key LIKE ?", (like,)).fetchone()[0],
            "performances_with_phases": c.execute(f"SELECT COUNT(DISTINCT p.id) {base}", (like,)).fetchone()[0],
            "phases": sum(by_type.values()), "by_type": by_type,
            "future_phases": c.execute(f"SELECT COUNT(*) {base} AND t.starts_at > ?", (like, now)).fetchone()[0],
            "performances_with_future_phases": c.execute(f"SELECT COUNT(DISTINCT p.id) {base} AND t.starts_at > ?", (like, now)).fetchone()[0],
            # the same season-wide sale is repeated on every concert page of the series, so count the distinct (start time, label) pairs too
            "distinct_future_start_label_pairs": c.execute(f"SELECT COUNT(*) FROM (SELECT DISTINCT t.starts_at, t.eligibility {base} AND t.starts_at > ?)", (like, now)).fetchone()[0],
            "eligibility_labels": labels,
            "sanity": {
                "duplicate_phase_groups": c.execute(f"SELECT COUNT(*) FROM (SELECT 1 {base} GROUP BY p.id, t.phase_type, t.starts_at HAVING COUNT(*) > 1)", (like,)).fetchone()[0],
                "sale_starts_after_the_performance_date": c.execute(f"SELECT COUNT(*) {base} AND substr(t.starts_at,1,10) > p.local_date", (like,)).fetchone()[0],
                "sale_starts_before_2024": c.execute(f"SELECT COUNT(*) {base} AND t.starts_at < '2024-01-01'", (like,)).fetchone()[0]}}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", action="append", required=True, help="LABEL=DB[:REQUESTS[:NOTE]]")
    ap.add_argument("--now", default=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    ap.add_argument("--out", type=Path, default=ROOT / f"evidence/p03/sale-sync-{datetime.now().date().isoformat()}.json")
    a = ap.parse_args()
    runs = {}
    for spec in a.run:
        label, rest = spec.split("=", 1)
        db_path, *more = rest.split(":", 2)
        runs[label] = {"requests": int(more[0]) if more else None, "note": more[1] if len(more) > 1 else None, "sources": summarise(db_path, a.now)}
    doc = {"generated_at": datetime.now(timezone.utc).isoformat(), "tool": "scripts/p03_sale_sync_summary.py", "now": a.now, "runs": runs}
    a.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
