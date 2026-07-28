#!/usr/bin/env python3
"""Regenerate reference/subway-64x32.png by grid-sampling reference/subway.png.

reference/subway.png is an LED-simulator screenshot with individually
resolvable dots (not a blurry photo). The committed subway-64x32.png used to
be a naive resample/resize of that screenshot, which is phase-misaligned
against the actual LED grid -- it differs from true ground truth on 517/2048
pixels (Task 3 review, 2026-07-27), including large chunks of both route
bullets.

The correct approach is to sample AT the LED dot centres, not resize. The
grid parameters below were fit directly against reference/subway.png (a
64-wide, 32-tall dot grid, uniform pitch on both axes):

    x0 = 105.00   # pixel x of column 0's dot centre
    y0 = 210.30   # pixel y of row 0's dot centre
    pitch = 15.78 # pixel spacing between dot centres, both axes

At each of the 64x32 dot centres, average a 5x5 pixel box (the dot's visible
extent, plus a little bleed) to get that LED's colour. This recovers the
exact ground truth: diffed against a hand-fit grid, the recovered image
round-trips essentially exactly (see the Task 3 fix report for the specific
verification: bullet_north and bullet_south become pixel-identical at the
correct 16-row vertical pitch, which the previous file did not have).

Usage:
    python3 tools/regenerate_reference.py
"""
from PIL import Image

SRC = "reference/subway.png"
DST = "reference/subway-64x32.png"
W, H = 64, 32
X0, Y0, PITCH = 105.00, 210.30, 15.78
BOX = 2  # +/- 2 -> 5x5 average

def main():
    im = Image.open(SRC).convert("RGB")
    px = im.load()
    sw, sh = im.size
    out = Image.new("RGB", (W, H))
    op = out.load()
    for row in range(H):
        for col in range(W):
            cx = X0 + col * PITCH
            cy = Y0 + row * PITCH
            rs = gs = bs = cnt = 0
            for dy in range(-BOX, BOX + 1):
                for dx in range(-BOX, BOX + 1):
                    sx = int(round(cx + dx))
                    sy = int(round(cy + dy))
                    if 0 <= sx < sw and 0 <= sy < sh:
                        r, g, b = px[sx, sy]
                        rs += r
                        gs += g
                        bs += b
                        cnt += 1
            op[col, row] = (rs // cnt, gs // cnt, bs // cnt)
    out.save(DST)
    print(f"wrote {DST} ({W}x{H}) sampled from {SRC}")

if __name__ == "__main__":
    main()
