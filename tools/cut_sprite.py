#!/usr/bin/env python3
"""Cut the CitiBike art out of the recovered reference frame.

The app embeds two images as base64 PNGs: the bike sprite and the bolt icon.
Both are FIXED art with no data-dependent colour, which is why an image is the
right primitive here -- unlike the subway app's route bullet, whose colour
comes from live data and therefore could not be an image (render.Image has no
tint parameter).

Cutting them with a script rather than by hand means the app's art is exactly
the original's pixels, and tools/gate_citibike.py --sprite can re-derive the
cut and prove the embedded copy has not drifted.

Regions, measured off reference/citibike-64x32.png:

  bike sprite  x20-38, rows 11-29  -- x20 is the only band that touches
                                      neither wheel (rear wheel ends at x17,
                                      front wheel starts at x25), which is
                                      what makes the left-shift cut land in
                                      the frame tubes rather than through a
                                      wheel
  bolt icon    x50-53, rows 24-28

Usage:
    python3 tools/cut_sprite.py --emit    # print the two Starlark constants
    python3 tools/cut_sprite.py --png DIR # write sprite.png / bolt.png to DIR
"""
import argparse
import base64
import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_PNG = ROOT / "reference" / "citibike-64x32.png"

SPRITE_BOX = (20, 11, 39, 30)  # x0, y0, x1, y1 (exclusive) -> 19x19
BOLT_BOX = (50, 24, 54, 29)    # -> 4x5


def cut(box):
    """Returns (base64 string, PIL image) for one region of the reference."""
    im = Image.open(REFERENCE_PNG).convert("RGB").crop(box)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode(), im


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", action="store_true", help="print Starlark constants")
    parser.add_argument("--png", metavar="DIR", help="write the cuts as PNGs for inspection")
    args = parser.parse_args()

    sprite_b64, sprite_im = cut(SPRITE_BOX)
    bolt_b64, bolt_im = cut(BOLT_BOX)

    if args.png:
        out = Path(args.png)
        sprite_im.save(out / "sprite.png")
        bolt_im.save(out / "bolt.png")
        print(f"wrote {out}/sprite.png ({sprite_im.size}) and {out}/bolt.png ({bolt_im.size})")

    if args.emit or not args.png:
        print(f'SPRITE_B64 = "{sprite_b64}"')
        print()
        print(f'BOLT_B64 = "{bolt_b64}"')


if __name__ == "__main__":
    main()
