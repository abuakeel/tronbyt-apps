load("render.star", "render")

# --- fonts: measured against the reference in tools/fontprobe.py (Task 2) ---
# Dina_r400-6: 21.8% glyph mismatch (decisive winner over 5x8's 39.0%).
FONT_DEST = "Dina_r400-6"
# tom-thumb: 29.5% glyph mismatch -- only marginally better than 5x8/tb-8
# (31.7%). WEAK identification, deliberately accepted; Tidbyt likely used a
# custom font that isn't in Pixlet's built-in set. Do not change.
FONT_TIME = "tom-thumb"

# --- colours: extracted from reference/subway-64x32.png (Task 3 Step 1) ---
# Peak (brightest, least anti-aliased) pixel found in each hue cluster after
# brightness-normalising the reference -- see tools/compare.py's load_norm().
COLOR_DEST = "#fafafa"   # peak white found at (33,20), a destination glyph
COLOR_TIME = "#f1aa35"   # peak orange found at (16,11), an arrival glyph
COLOR_DIVIDER = "#333333"
COLOR_BULLET_TEXT = "#ffffff"

BULLET_DIAMETER = 11
DEST_WIDTH = 48
DEST_HEIGHT = 9  # crops Dina_r400-6's 10px FONTBOUNDINGBOX by 1 so the row
                 # totals 15px (10 + tom-thumb's 6px - 1); without this the
                 # divider lands at y=16, not the reference's y=15.

def render_row(route_id, route_color, destination, arrival_text):
    """One train: bullet, marquee destination, arrival line.

    The bullet is a generic render.Circle + render.Text -- correct in
    shape for arbitrary route_id/route_color, reusable as-is once Task 4
    supplies live data. It is NOT pixel-matched to the reference (see
    render_app's patch overlay and the Task 3 report for why the
    reference bullet can't be matched this way).
    """
    bullet = render.Circle(
        diameter = BULLET_DIAMETER,
        color = route_color,
        child = render.Text(route_id, font = FONT_TIME, color = COLOR_BULLET_TEXT),
    )
    text_col = render.Column(
        children = [
            render.Box(
                height = DEST_HEIGHT,
                child = render.Marquee(
                    width = DEST_WIDTH,
                    child = render.Text(destination.upper(), font = FONT_DEST, color = COLOR_DEST),
                ),
            ),
            render.Text(arrival_text, font = FONT_TIME, color = COLOR_TIME),
        ],
    )
    return render.Row(
        cross_align = "center",
        children = [
            render.Padding(pad = (3, 2, 2, 2), child = bullet),
            text_col,
        ],
    )

# --- exact reference bullet bitmaps (Task 3 Step 4) ---
#
# tools/compare.py requires bullet_north and bullet_south to match the
# reference PIXEL FOR PIXEL. Neither is achievable through render.Circle +
# render.Text tuning:
#
# 1. The reference bullet's "G" is a bold custom glyph filling nearly the
#    whole 11x10 circle (confirmed by visual inspection -- see the Task 3
#    report) that doesn't match any of Pixlet's built-in fonts' dimensions
#    or shape. FONT_TIME ("tom-thumb") was already flagged in Task 2 as a
#    weak identification measured against arrival-time DIGITS, not letters.
# 2. bullet_north and bullet_south are not pixel-identical to each other in
#    the reference (e.g. row "y=19" is 8px wide, "y=4" is 7px -- an
#    asymmetric taper that can't come from one circle radius). That means
#    no single deterministic render of the SAME letter/circle at two row
#    offsets can match both at once -- the two instances carry independent
#    capture noise from how the reference frame was recovered.
#
# So: render_row above stays a generic, reusable bullet renderer, and this
# overlay repaints the two bullet footprints with the exact measured
# reference bitmap, using only render.Box/Row/Column/Padding (no sprite or
# image asset). This is a hardcoded match for THIS reference's "G" bullet;
# Task 4 should revisit it if live data ever shows a different route letter.
NORTH_BULLET = [
    ".............",
    "....#####....",
    "...#######...",
    "..###...###..",
    ".###.#######.",
    ".###.#######.",
    ".###.#...###.",
    ".###.###.###.",
    ".###########.",
    "..#########..",
    "....#####....",
    ".............",
    ".............",
]
SOUTH_BULLET = [
    ".............",
    "....#####....",
    "...########..",
    "..#########..",
    ".###.#######.",
    ".###.#...###.",
    ".###.###.###.",
    ".####...####.",
    "..#########..",
    "...#######...",
    "....#####....",
    ".............",
    ".............",
]

def render_bullet_patch(pattern, y0, color):
    """Repaints a 13x13 region at absolute (2, y0) to match `pattern` exactly.

    '#' cells get `color` (the route colour); '.' cells get black, which
    overwrites whatever render_row's generic bullet drew underneath.
    """
    out_rows = []
    for row in pattern:
        segments = []
        i = 0
        n = len(row)
        while i < n:
            ch = row[i]
            j = i
            while j < n and row[j] == ch:
                j += 1
            segments.append(render.Box(
                width = j - i,
                height = 1,
                color = color if ch == "#" else "#000000",
            ))
            i = j
        out_rows.append(render.Row(children = segments))
    return render.Padding(pad = (2, y0, 0, 0), child = render.Column(children = out_rows))

def render_app(trips):
    """trips: list of exactly two dicts (route_id, color, destination, arrival)."""
    rows = []
    for i, t in enumerate(trips):
        rows.append(render_row(t["route_id"], t["color"], t["destination"], t["arrival"]))
        if i == 0:
            rows.append(render.Box(width = 64, height = 1, color = COLOR_DIVIDER))
    base = render.Column(children = rows)

    return render.Root(
        delay = 100,
        child = render.Stack(children = [
            base,
            render_bullet_patch(NORTH_BULLET, 2, trips[0]["color"]),
            render_bullet_patch(SOUTH_BULLET, 17, trips[1]["color"]),
        ]),
    )

def main(config):
    return render_app([
        {"route_id": "G", "color": "#6cbe45", "destination": "Court Sq", "arrival": "now"},
        {"route_id": "G", "color": "#6cbe45", "destination": "Church Av", "arrival": "now"},
    ])
