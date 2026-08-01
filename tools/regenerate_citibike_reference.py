#!/usr/bin/env python3
"""Regenerate reference/citibike-64x32.png by grid-sampling reference/citibike.png.

Same method and the same trap as tools/regenerate_reference.py: the source is
an LED screenshot with individually resolvable dots, so the frame is recovered
by sampling AT the dot centres, not by resizing (a resize is phase-misaligned
against the LED grid and silently corrupts whole glyphs).

The grid was fit against reference/citibike.png directly. X0 and PITCH are
identical to the subway screenshot's -- same capture format, same panel -- and
only Y0 differs, because the panel sits lower in this screenshot:

    X0    = 105.00   # x of column 0's dot centre
    Y0    = 193.00   # y of row 0's dot centre
    PITCH = 15.78    # dot spacing, both axes

Fit evidence: 59 dot columns are lit; the first centre is at x=105.5 and the
last at x=1099.0, and (1099 - 105) / 15.78 = 62.99 -- exactly column 63.

Each LED is a 5x5 box average about its centre, then the whole frame is
brightness-normalised (the box average blends the dot with the dark gaps
around it, so the peak channel comes out at 253, not 255).

Usage:
    python3 tools/regenerate_citibike_reference.py           # write the PNG
    python3 tools/regenerate_citibike_reference.py --check   # verify, write nothing
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "reference" / "citibike.png"
DST = ROOT / "reference" / "citibike-64x32.png"
W, H = 64, 32
X0, Y0, PITCH = 105.00, 193.00, 15.78
BOX = 2  # +/- 2 -> 5x5 average

# Landmarks measured off the recovered frame. These are what make --check a
# real verification rather than a tautology: a grid that drifts by even one
# LED moves every one of them.
LANDMARKS = [
    # (x, y, expected #RRGGBB, what it is)
    (28, 16, "#244bbd", "sprite blue, brightest body pixel"),
    (8, 19, "#d72e1f", "the single red highlight pixel"),
    (52, 26, "#f5ed4e", "bolt yellow"),
    (2, 8, "#ffffff", "station-name white"),
    (0, 0, "#000000", "top-left, unlit"),
    (63, 31, "#000000", "bottom-right, unlit"),
]


def recover():
    im = Image.open(SRC).convert("RGB")
    px = im.load()
    sw, sh = im.size
    out = Image.new("RGB", (W, H))
    op = out.load()
    for row in range(H):
        for col in range(W):
            cx, cy = X0 + col * PITCH, Y0 + row * PITCH
            total = [0, 0, 0]
            n = 0
            for dy in range(-BOX, BOX + 1):
                for dx in range(-BOX, BOX + 1):
                    x, y = int(round(cx + dx)), int(round(cy + dy))
                    if 0 <= x < sw and 0 <= y < sh:
                        p = px[x, y]
                        total[0] += p[0]
                        total[1] += p[1]
                        total[2] += p[2]
                        n += 1
            op[col, row] = tuple(v // n for v in total)
    peak = max(max(op[c, r]) for r in range(H) for c in range(W)) or 1
    for r in range(H):
        for c in range(W):
            op[c, r] = tuple(min(255, int(v * 255 / peak)) for v in op[c, r])
    return out


def check_landmarks(im):
    px = im.load()
    problems = []
    for x, y, expected, what in LANDMARKS:
        got = "#%02x%02x%02x" % px[x, y]
        if got != expected:
            problems.append(f"  ({x},{y}) {what}: expected {expected}, got {got}")
    return problems


def main():
    recovered = recover()
    problems = check_landmarks(recovered)
    if problems:
        print("landmark check FAILED -- the grid fit is wrong, do not commit:")
        print("\n".join(problems))
        return 1

    if "--check" in sys.argv:
        if not DST.exists():
            print(f"{DST} does not exist")
            return 1
        committed = Image.open(DST).convert("RGB").load()
        fresh = recovered.load()
        diff = sum(
            1 for y in range(H) for x in range(W) if committed[x, y] != fresh[x, y]
        )
        print(f"landmarks OK; committed vs regenerated: {diff}/{W * H} pixels differ")
        return 0 if diff == 0 else 1

    recovered.save(DST)
    print(f"landmarks OK; wrote {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
