#!/usr/bin/env python3
"""Write the committed OpenAPI snapshot docs/openapi.json from the real app (no network, no real token, throw-away database).

`tests/test_openapi_snapshot.py` fails when the app and this file differ, so API changes show up as a reviewable diff. After an
intentional API change run:  python scripts/export_openapi.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from classical_radar.api import create_app

OUT = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"


def current() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        spec = create_app(str(Path(tmp) / "snapshot.db"), "x" * 20).openapi()
    return json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.write_text(current(), encoding="utf-8")
    print(f"wrote {OUT} ({len(json.loads(OUT.read_text()).get('paths', {}))} paths)", file=sys.stderr)
