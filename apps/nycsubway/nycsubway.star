load("render.star", "render")
load("http.star", "http")
load("time.star", "time")

# --- fonts: measured against the reference in tools/fontprobe.py (Task 2) ---
# Dina_r400-6: 21.8% glyph mismatch on destination text, and (Task 3 review,
# 2026-07-27) also renders the bullet's "G" exactly once repositioned -- see
# render_row's bullet below. Used for both destination text and the bullet
# letter, since both need the same visual weight.
FONT_DEST = "Dina_r400-6"

# tom-thumb was the Task 2 pick, but that measurement ran against a
# corrupted reference (reference/subway-64x32.png was a phase-misaligned
# resample of the LED simulator screenshot, not sampled at the LED grid --
# see tools/regenerate_reference.py and the Task 3 fix report). Verified
# directly against the corrected reference: 5x8 reproduces "now" with 0
# pixel difference. (tb-8 renders pixel-identically to 5x8 here; 5x8 is
# the more conventional name.)
FONT_TIME = "5x8"

# --- colours: extracted from reference/subway-64x32.png (Task 3 Step 1) ---
# Peak (brightest, least anti-aliased) pixel found in each hue cluster after
# brightness-normalising the reference -- see tools/compare.py's load_norm().
COLOR_DEST = "#fafafa"
COLOR_TIME = "#f1aa35"
COLOR_DIVIDER = "#333333"

# The bullet's route letter is knocked out in black, not printed in white --
# white would vanish into the lit circle. Confirmed by direct pixel
# inspection of the corrected reference (no white pixel anywhere inside the
# bullet, only shades of the route colour and near-black).
COLOR_BULLET_TEXT = "#000000"

BULLET_DIAMETER = 11
DEST_WIDTH = 48

# Dina_r400-6's FONTBOUNDINGBOX is 10px tall (the "-6" in the name is not the
# pixel height) with ~2px of leading before the glyph. Cropping to 9 with
# render.Box shifts the crop from the *top*, not the bottom (Box centers
# then clips: Go's rounding gives an offset of -1 for a 9-in-10 box), which
# lands the visible glyph exactly 1px higher -- matching the reference's
# destination-text row precisely.
DEST_HEIGHT = 9

# 5x8 has ~3px of leading before its glyph. Placing the arrival Text at this
# fixed absolute offset (measured directly against the reference, not
# derived by stacking font box heights, which don't add up to the right
# gap here) lands its glyph exactly on the reference's arrival row.
ARRIVAL_TOP = 7

def render_row(route_id, route_color, destination, arrival_text):
    """One train: bullet, marquee destination, arrival line."""
    if route_id == "":
        # "no trains" placeholder -- a dim, letterless bullet rather than an
        # empty coloured circle (which would render as a stray black dot).
        bullet = render.Circle(diameter = BULLET_DIAMETER, color = "#222222")
    else:
        bullet = render.Circle(
            diameter = BULLET_DIAMETER,
            color = route_color,
            child = render.Padding(
                pad = (0, 0, 0, 2),
                child = render.Text(route_id, font = FONT_DEST, color = COLOR_BULLET_TEXT),
            ),
        )
    text_col = render.Stack(
        children = [
            render.Box(
                height = DEST_HEIGHT,
                child = render.Marquee(
                    width = DEST_WIDTH,
                    child = render.Text(destination.upper(), font = FONT_DEST, color = COLOR_DEST),
                ),
            ),
            render.Padding(
                pad = (0, ARRIVAL_TOP, 0, 0),
                child = render.Text(arrival_text, font = FONT_TIME, color = COLOR_TIME),
            ),
        ],
    )
    return render.Row(
        cross_align = "center",
        children = [
            render.Padding(pad = (2, 2, 2, 2), child = bullet),
            text_col,
        ],
    )

STOPS_URL = "https://api.subwaynow.app/stops/"
ROUTES_URL = "https://api.subwaynow.app/routes/"

# --- configuration seam -----------------------------------------------------
# Hardcoded today. To add a station picker later, implement get_schema() and
# these config.str() calls start returning user values -- NO other code changes.
# Nothing outside get_settings() may reference this constant by name.
DEFAULT_STOP_ID = "G35"  # Clinton - Washington Avs
DEFAULT_DIRECTIONS = ["north", "south"]

def get_settings(config):
    return {
        "stop_id": config.str("stop_id", DEFAULT_STOP_ID),
        "directions": DEFAULT_DIRECTIONS,
    }

def fetch_json(url, ttl):
    resp = http.get(url, ttl_seconds = ttl)
    if resp.status_code != 200:
        return None
    return resp.json()

def route_colors():
    data = fetch_json(ROUTES_URL, 86400)
    colors = {}
    if data == None:
        return colors

    # The live API keys "routes" by route id (a dict), not a list.
    routes = data.get("routes", {})
    for r in routes.values():
        if r.get("color"):
            colors[r["id"]] = r["color"]
    return colors

def stop_names():
    data = fetch_json(STOPS_URL, 86400)
    names = {}
    if data == None:
        return names
    for s in data.get("stops", []):
        names[s["id"]] = s["name"]
    return names

# A trip whose estimated arrival is further than this many seconds in the past
# is treated as departed/stale rather than "now" -- see format_arrival below.
STALE_GRACE_SECONDS = 30

def format_arrival(seconds_away):
    if seconds_away < 60:
        return "now"
    return str(int(seconds_away // 60)) + " min"

def fetch_trips(settings):
    """Returns exactly len(directions) dicts, padded with placeholders on failure."""
    colors = route_colors()
    names = stop_names()
    data = fetch_json(STOPS_URL + settings["stop_id"] + "?agent=tidbyt", 60)
    now = time.now().unix
    out = []
    for direction in settings["directions"]:
        trip = None
        if data != None:
            upcoming = data.get("upcoming_trips", {}).get(direction, [])
            if len(upcoming) > 0:
                candidate = upcoming[0]
                raw_arrival = candidate.get("estimated_current_stop_arrival_time")
                # Only treat it as upcoming if the arrival time is missing
                # (handled below, tolerantly) or not more than a small grace
                # period in the past. A feed entry whose train departed
                # minutes ago must not be selected here -- format_arrival
                # would otherwise read "now" forever (it has no lower bound
                # of its own).
                if raw_arrival == None or (raw_arrival - now) >= -STALE_GRACE_SECONDS:
                    trip = candidate
        if trip == None:
            out.append({
                "route_id": "",
                "color": "#000000",
                "destination": "no trains",
                "arrival": "",
            })
        else:
            route_id = trip.get("route_id", "")
            # `or ""` (not just a .get default) so a present-but-null
            # destination_stop also falls back cleanly.
            dest_id = trip.get("destination_stop") or ""
            raw_arrival = trip.get("estimated_current_stop_arrival_time")
            arrival_text = "" if raw_arrival == None else format_arrival(raw_arrival - now)
            out.append({
                "route_id": route_id,
                "color": colors.get(route_id, "#888888"),
                "destination": names.get(dest_id, dest_id),
                "arrival": arrival_text,
            })
    return out

def render_app(trips):
    """trips: a list of train dicts (route_id, color, destination, arrival).

    Tolerates any number of trips (0, 1, 2, ...) -- a divider is drawn
    between each consecutive pair; nothing is hard-indexed.
    """
    rows = []
    last = len(trips) - 1
    for i, t in enumerate(trips):
        rows.append(render_row(t["route_id"], t["color"], t["destination"], t["arrival"]))
        if i != last:
            rows.append(render.Box(width = 64, height = 1, color = COLOR_DIVIDER))
    return render.Root(delay = 100, child = render.Column(children = rows))

def main(config):
    return render_app(fetch_trips(get_settings(config)))
