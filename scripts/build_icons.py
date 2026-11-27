"""Draw the app icon (five organ pipes, the middle one lit, over "classical / radar" in Futura) and write the icon files the site serves.

Usage: python scripts/build_icons.py [--chrome PATH]
Writes src/classical_radar/web/icons/: icon.svg (pipes only, the favicon; no text so no font is needed), icon-32.png (pipes only),
apple-touch-icon.png (180), icon-192.png, icon-512.png (pipes + name). The PNGs are rendered by a headless Chrome/Chromium
(Futura is a system font on Apple devices; on other systems the renderer falls back and the result must be checked by eye).
Output is committed; run this only when the design changes.
"""
import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src/classical_radar/web/icons"
SLATE, FOG, OCHRE = "#2e3442", "#e6e4df", "#b8955a"
CHROMES = ["~/Library/Caches/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-mac-arm64/chrome-headless-shell", "/opt/pw-browsers/chromium",
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "chromium", "google-chrome"]


def pipes(heights, w, gap, base):
    x0 = 512 - (len(heights) * w + (len(heights) - 1) * gap) / 2
    return "".join(f'<rect x="{x0 + i * (w + gap):.0f}" y="{base - h}" width="{w}" height="{h}" rx="{w / 2:.0f}" fill="{OCHRE if i == len(heights) // 2 else FOG}"/>'
                   for i, h in enumerate(heights))


def svg(body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><rect width="1024" height="1024" fill="{SLATE}"/>{body}</svg>'


FULL = svg(pipes([200, 280, 350, 280, 200], 60, 22, 500)
           + "".join(f'<text x="512" y="{y}" text-anchor="middle" font-family="Futura, \'Futura PT\', \'Century Gothic\', sans-serif" font-weight="700" font-size="150" fill="{c}">{t}</text>'
                     for t, y, c in (("classical", 700, FOG), ("radar", 830, OCHRE))))
MARK = svg(pipes([380, 520, 640, 520, 380], 110, 40, 832))  # pipes only, larger: what survives at 16-32 px


def chrome(path: str | None) -> str:
    for c in ([path] if path else []) + CHROMES:
        c = os.path.expanduser(c)
        if Path(c).is_file() or shutil.which(c):
            return c
    raise SystemExit("no headless Chrome/Chromium found: pass --chrome PATH")


def render(exe: str, source: str, size: int, out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "icon.html"
        page.write_text(f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0}}svg{{display:block;width:{size}px;height:{size}px}}</style>{source}', encoding="utf8")
        subprocess.run([exe, "--headless", f"--user-data-dir={tmp}/profile", "--hide-scrollbars", "--force-device-scale-factor=1", f"--window-size={size},{size}",
                        f"--screenshot={out}", page.as_uri()], check=True, capture_output=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome")
    exe = chrome(ap.parse_args().chrome)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon.svg").write_text(MARK + "\n", encoding="utf8")
    render(exe, MARK, 32, OUT / "icon-32.png")
    for size, name in ((180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        render(exe, FULL, size, OUT / name)
    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
