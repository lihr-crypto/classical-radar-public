"""Turn the workflow's SOURCES input into repeated ``--source X`` flags, refusing anything that is not a supported source id.
The input only ever arrives through an environment variable and is never interpolated into a shell line."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from classical_radar.sync import SUPPORTED  # noqa: E402


def build(raw: str) -> str:
    names = raw.split()
    bad = [n for n in names if n not in SUPPORTED]
    if bad:
        raise SystemExit("unknown source ids (not in the supported list): " + " ".join(bad)[:200])
    return " ".join(f"--source {n}" for n in names)


if __name__ == "__main__":
    print(build(os.environ.get("SOURCES", "")))
