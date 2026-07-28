#!/usr/bin/env python3
"""Render-vs-reference pixel diff for the NYC Subway recreation.

The reference (reference/subway-64x32.png) is grid-sampled from an LED
simulator screenshot (reference/subway.png) at each LED's dot centre --
see tools/regenerate_reference.py for the exact grid parameters. It is
still dim (max channel well under 255) because each sample is a 5x5 box
average centred on the dot. Both images are brightness-normalised before
comparison so absolute levels do not matter -- only which pixels are lit,
and their relative colour.

Normalisation scale is derived from the REFERENCE image only, then applied
to both images (Task 5 review fix). Scaling each image by its own max
channel independently misreports near-dark frames: a "no trains" frame's
brightest pixel is the #333333 divider (51), which would self-scale by
~5.0x and push the #222222 dim bullet (34 -> ~168) across the `lit`
threshold, even though it is deliberately dim, not lit.
"""
import sys
from PIL import Image

W, H = 64, 32

# Only the divider is truly static. The bullet regions used to be listed
# here too, but they carry the live route's colour and letter -- a bullet
# mismatch there can mean nothing more than "a different route is next"
# (see Task 5 review: the feed legitimately returned an F train ahead of G
# at the reference stop). tools/gate.py's fixture mode is what pins bullet
# content down, by fixing what the "live" data is, not by pretending the
# bullet region is static.
STATIC_REGIONS = {
    "divider": (0, 15, 64, 16),
}

def _load_raw(path):
    im = Image.open(path).convert("RGB")
    if im.size != (W, H):
        sys.exit(f"{path}: expected {W}x{H}, got {im.size}")
    return im.load()

def scale_from(path):
    """Normalisation scale derived from a single (reference) image."""
    px = _load_raw(path)
    mx = max(max(px[x, y]) for x in range(W) for y in range(H)) or 1
    return 255.0 / mx

def load_scaled(path, scale):
    px = _load_raw(path)
    out = Image.new("RGB", (W, H))
    op = out.load()
    for y in range(H):
        for x in range(W):
            op[x, y] = tuple(min(255, int(v * scale)) for v in px[x, y])
    return out.load()

def lit(p):
    return sum(p) > 110

def ascii_frame(px):
    return "\n".join(
        "  " + "".join("#" if lit(px[x, y]) else "." for x in range(W))
        for y in range(H)
    )

def compare_images(got_path, ref_path, strict_whole_frame=False):
    """Compares got_path against ref_path.

    Returns (exit_code, report_text). With strict_whole_frame=True, the
    whole 64x32 frame must be a 0-pixel diff to pass (used by tools/gate.py
    against its fixture, where live-data variability cannot be a factor).
    Otherwise (the default CLI behaviour) only STATIC_REGIONS must be 0-diff,
    and the whole-frame diff is printed as non-gating INFO.
    """
    scale = scale_from(ref_path)
    got = load_scaled(got_path, scale)
    ref = load_scaled(ref_path, scale)

    lines = []
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
        lines.append(f"  {name:<14} {status:<9} {diff}/{total} pixels differ")

    whole = sum(
        1 for y in range(H) for x in range(W) if lit(got[x, y]) != lit(ref[x, y])
    )
    if strict_whole_frame:
        status = "OK" if whole == 0 else "MISMATCH"
        if whole:
            fail = 1
        lines.append(f"  {'whole frame':<14} {status:<9} {whole}/{W * H} pixels differ")
    else:
        lines.append(
            f"  {'whole frame':<14} {'INFO':<9} {whole}/{W * H} pixels differ "
            f"(text/live values expected to differ)"
        )

    lines.append("\n--- rendered ---")
    lines.append(ascii_frame(got))
    lines.append("\n--- reference ---")
    lines.append(ascii_frame(ref))

    return fail, "\n".join(lines)

def main():
    if len(sys.argv) < 2:
        sys.exit("usage: compare.py <rendered.webp|png> [reference.png] [--strict-whole-frame]")

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict-whole-frame" in sys.argv

    got_path = args[0]
    ref_path = args[1] if len(args) > 1 else "reference/subway-64x32.png"

    fail, report = compare_images(got_path, ref_path, strict_whole_frame=strict)
    print(report)
    sys.exit(fail)

if __name__ == "__main__":
    main()
