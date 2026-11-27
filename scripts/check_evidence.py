"""Offline consistency checks on the committed P0 evidence bundle."""
from datetime import date
import json
from pathlib import Path
import re

from classical_radar.sources import SOURCES


def main():
    root=Path(__file__).resolve().parents[1]
    def read(name):return json.loads((root/name).read_text())
    probe=read("evidence/probe.json")
    assert {r["source_id"] for r in probe}==set(SOURCES),"source scope drift"
    for row in probe:
        assert row["scheduled_collection"] is False
        assert row["policy_status"]=="unknown"
        assert row["list"]["status"]==200
        assert re.fullmatch(r"[0-9a-f]{64}",row["list"]["sha256"])
    coverage=read("evidence/coverage.json")
    assert {r["source_id"] for r in coverage}==set(SOURCES)
    assert all(r["global_coverage_N"] is None for r in coverage)
    candidates=read("evidence/list-candidates.json")
    assert len(candidates)==254
    assert len({r["performance_id"] for r in candidates})==len(candidates)
    for row in candidates:
        assert row["official_announcement_at"] is None
        assert row["verification_status"]=="candidate"
        if row["local_date"]:date.fromisoformat(row["local_date"])
        if row["date_precision"]!="minute":assert row["starts_at"] is None
    samples=read("evidence/presenter-samples.json")
    assert sum(len(s["performances"]) for s in samples)==10
    assert sum(len(s["ticket_claims"]) for s in samples)==5
    for sample in samples:
        for phase in sample["ticket_claims"]:
            assert phase["linkage_status"]=="needs_review"
            assert phase["performance_ids"]==[]
    manifest=read("tests/fixtures/manifest.json")
    assert len(manifest)==14
    for row in manifest:assert (root/row["file"]).is_file()
    print("OK: 10 source probes; 254 list/JSON candidates; 10 detail performances; 5 unlinked sale claims; 14 HTML fragments + NHK JSON")


if __name__=="__main__":main()
