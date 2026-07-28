#!/usr/bin/env python3
"""Render-vs-reference pixel diff for the NYC Subway recreation.

The reference (reference/subway-64x32.png) is grid-sampled from an LED
simulator screenshot (reference/subway.png) at each LED's dot centre --
see tools/regenerate_reference.py for the exact grid parameters. It is
still dim (max channel well under 255) because each sample is a 5x5 box
average centred on the dot. Both images are brightness-normalised before
comparison so absolute levels do not matter -- only which pixels are lit,
and their relative colour.
"""
import sys
from PIL import Image

W, H = 64, 32

# Regions that contain NO text and NO live numbers. These are derived from the
# reference, so any mismatch here is a bug rather than a judgement call.
STATIC_REGIONS = {
    "divider":     (0, 15, 64, 16),
    "bullet_north": (2, 2, 15, 15),
    "bullet_south": (2, 18, 15, 31),
}

def load_norm(path):
    im = Image.open(path).convert("RGB")
    if im.size != (W, H):
        sys.exit(f"{path}: expected {W}x{H}, got {im.size}")
    px = im.load()
    mx = max(max(px[x, y]) for x in range(W) for y in range(H)) or 1
    scale = 255.0 / mx
    out = Image.new("RGB", (W, H))
    op = out.load()
    for y in range(H):
        for x in range(W):
            op[x, y] = tuple(min(255, int(v * scale)) for v in px[x, y])
    return out.load()

def lit(p):
    return sum(p) > 110

def main():
    if len(sys.argv) < 2:
        sys.exit("usage: compare.py <rendered.webp|png> [reference.png]")
    ref_path = sys.argv[2] if len(sys.argv) > 2 else "reference/subway-64x32.png"
    got, ref = load_norm(sys.argv[1]), load_norm(ref_path)

    fail = 0
    for name, (x0, y0, x1, y1) in STATIC_REGIONS.items():
        diff = sum(
            1
            for y in range(y0, y1)
            for x in range(x0, x1)
            if lit(got[x, y]) != lit(ref[x, y])
        )
        total = (x1 - x0) * (y1 - y0)
        status = "OK" if diff == 0 else "MISMATCH"
        if diff:
            fail = 1
        print(f"  {name:<14} {status:<9} {diff}/{total} pixels differ")

    whole = sum(
        1 for y in range(H) for x in range(W) if lit(got[x, y]) != lit(ref[x, y])
    )
    print(f"  {'whole frame':<14} {'INFO':<9} {whole}/{W*H} pixels differ "
          f"(text/live values expected to differ)")

    print("\n--- rendered ---")
    for y in range(H):
        print("  " + "".join("#" if lit(got[x, y]) else "." for x in range(W)))
    print("\n--- reference ---")
    for y in range(H):
        print("  " + "".join("#" if lit(ref[x, y]) else "." for x in range(W)))

    sys.exit(fail)

if __name__ == "__main__":
    main()
