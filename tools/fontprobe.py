#!/usr/bin/env python3
"""Render candidate fonts and score them against the reference glyphs.

The reference destination text occupies rows 2-7 (6px tall) starting at x=16;
the arrival line occupies rows 10-13 (4px tall). Only fonts matching those
heights can be right, and among those we pick the best per-pixel match.
"""
import subprocess, sys, os
from PIL import Image

PIXLET = os.environ.get("PIXLET", "pixlet")
CANDIDATES = ["5x8", "tb-8", "6x10", "Dina_r400-6", "6x13",
              "tom-thumb", "CG-pixel-3x5-mono", "CG-pixel-4x5-mono"]

def render_text(text, font, path):
    star = f'''load("render.star", "render")
def main(config):
    return render.Root(child = render.Text("{text}", color = "#ffffff", font = "{font}"))
'''
    with open("/tmp/_probe.star", "w") as f:
        f.write(star)
    subprocess.run([PIXLET, "render", "/tmp/_probe.star", "-o", path],
                   check=True, capture_output=True)

def bitmap(path):
    im = Image.open(path).convert("RGB")
    px = im.load()
    return [[sum(px[x, y]) > 100 for x in range(64)] for y in range(32)]

def extent(bm):
    rows = [y for y, r in enumerate(bm) if any(r)]
    return (rows[0], rows[-1]) if rows else (None, None)

def main():
    ref = Image.open("reference/subway-64x32.png").convert("RGB")
    rp = ref.load()
    mx = max(max(rp[x, y]) for x in range(64) for y in range(32)) or 1
    def rlit(x, y):
        return sum(tuple(min(255, int(v * 255.0 / mx)) for v in rp[x, y])) > 110

    for label, text, y0, y1 in (("DEST", "CHURCH AV", 2, 7),
                                ("TIME", "now", 10, 13)):
        want_h = y1 - y0 + 1
        print(f"\n=== {label}: reference is {want_h}px tall (rows {y0}-{y1}) ===")
        for font in CANDIDATES:
            try:
                render_text(text, font, "/tmp/_probe.webp")
            except subprocess.CalledProcessError:
                print(f"  {font:<20} render failed")
                continue
            bm = bitmap("/tmp/_probe.webp")
            a, b = extent(bm)
            if a is None:
                print(f"  {font:<20} empty")
                continue
            h = b - a + 1
            mark = "  <- height matches" if h == want_h else ""
            score = ""
            if h == want_h:
                diff = sum(1 for dy in range(want_h) for x in range(40)
                           if bm[a + dy][x] != rlit(16 + x, y0 + dy))
                score = f"  glyph diff over first 40px: {diff}"
            print(f"  {font:<20} height={h}{mark}{score}")

if __name__ == "__main__":
    main()
