#!/usr/bin/env python3
"""Render candidate fonts and score them against the reference glyphs.

The reference destination text occupies rows 2-7 (6px tall) starting at x=16;
the arrival line occupies rows 10-13 (4px tall). Only fonts matching those
heights can be right, and among those we pick the best per-pixel match.

Method (see docs/2026-07-27-nyc-subway-recreation-design.md "Open items" and
kubedeploy's task-2-report.md for the full derivation):

  1. Render each height-matching candidate and measure its true full width
     (not a fixed window) -- a fixed 40px comparison window silently
     truncates wider candidates before ever comparing the rest of their
     glyphs, which flatters narrower fonts.
  2. Search a small horizontal shift (-6..+6 px) for the best alignment
     against the reference, rather than assuming zero left-bearing at x=16 --
     real bitmap fonts vary in left-side bearing by a few px, and without
     this search a genuinely-matching font can look like a near-miss.
  3. Exclude out-of-bounds reference columns (comparison can run past x=63
     for wide candidates at some shifts) from BOTH the mismatch count and
     the total -- scoring them as "reference unlit" inflates the mismatch
     rate for wider candidates for no real reason.

A naive fixed-40px/zero-shift score is also printed for contrast: it is the
number a first-pass probe reports, and it disagrees with the corrected
method for the destination font (it favors a narrower, worse-fitting
candidate). The corrected "best-fit" score is what actually justifies
FONT_DEST / FONT_TIME, and is what should be trusted.
"""
import subprocess, sys, os
from PIL import Image

PIXLET = os.environ.get("PIXLET", "pixlet")
CANDIDATES = ["5x8", "tb-8", "6x10", "Dina_r400-6", "6x13",
              "tom-thumb", "CG-pixel-3x5-mono", "CG-pixel-4x5-mono"]
SHIFT_RANGE = range(-6, 7)

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

def full_width(bm, a, h):
    cols = [x for x in range(64) if any(bm[a + dy][x] for dy in range(h))]
    return (cols[0], cols[-1]) if cols else (None, None)

def naive_diff(bm, a, h, y0, rlit):
    """The brief's original method: fixed 40px window, zero shift. Kept for
    contrast -- see module docstring for why this is not trusted."""
    return sum(1 for dy in range(h) for x in range(40)
               if bm[a + dy][x] != rlit(16 + x, y0 + dy))

def best_alignment(bm, a, w, h, y0, rlit):
    """Shift search over the candidate's true full width, excluding
    out-of-bounds reference columns from both numerator and denominator.
    Returns (shift, mismatches, compared, fraction)."""
    best = None
    for shift in SHIFT_RANGE:
        diff = 0
        counted = 0
        for dy in range(h):
            for x in range(w):
                rx = 16 + x + shift
                ry = y0 + dy
                if rx < 0 or rx > 63:
                    continue  # out of frame -- exclude, don't score as "unlit"
                counted += 1
                if bm[a + dy][x] != rlit(rx, ry):
                    diff += 1
        frac = diff / counted if counted else 1.0
        if best is None or frac < best[3] or (frac == best[3] and abs(shift) < abs(best[0])):
            best = (shift, diff, counted, frac)
    return best

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
            if h != want_h:
                print(f"  {font:<20} height={h}")
                continue
            w0, w1 = full_width(bm, a, want_h)
            width = w1 - w0 + 1
            naive = naive_diff(bm, a, want_h, y0, rlit)
            shift, diff, counted, frac = best_alignment(bm, a, width, want_h, y0, rlit)
            print(f"  {font:<20} height={h}  <- height matches"
                  f"  width={width:<3d}"
                  f"  naive(40px,shift=0) diff={naive}"
                  f"  best-fit diff={diff}/{counted} ({100*frac:.1f}%, shift={shift:+d})")

if __name__ == "__main__":
    main()
