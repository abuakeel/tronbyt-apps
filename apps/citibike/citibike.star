load("render.star", "render")
load("http.star", "http")
load("encoding/json.star", "json")
load("encoding/base64.star", "base64")
load("schema.star", "schema")

# --- embedded art ---------------------------------------------------------
# Cut from reference/citibike-64x32.png by tools/cut_sprite.py -- NOT drawn by
# hand. Regenerate with `python3 tools/cut_sprite.py --emit`; never edit these
# strings directly. tools/gate_citibike.py --sprite re-derives the cut from
# the reference and fails if what renders here has drifted from it.
#
# SPRITE_B64 is the WHOLE bike -- original x4-38, rows 11-29 (35x19), its exact
# bounding box, shifted left 4 so it starts at x0. Nothing is cut.
#
# The third number row costs VERTICAL space, not horizontal: the rows are
# right-aligned at x63 and even the widest 3-digit case only reaches x43, so
# the full sprite fits at x0-34 with 8px to spare. Two cropped versions (x20,
# then x12) were built and looked at on the device before that became obvious
# -- both gave up bike for a gap that did not need to exist.
SPRITE_B64 = "iVBORw0KGgoAAAANSUhEUgAAACMAAAATCAIAAACVwSOjAAACnElEQVR4nL2UzU7bQBSFz0wcQoJYIJRsq9ix2YKAwgOAYwe1iHVfoQ/Sp+i2G9SWtsQhaRdt1V1fIIBhkUJQovxIEdgEz9wurKYmhJC2Us9u5h7fb+bMjBn+Tefn5wASicT8/Pw/tppIWqGiFSr/gwQgVyiPN/D7Co1G4/LycnISkfxLUiaT6fV67Xa71WrVarWHSfJm8mWNUG6y9HNbH3Nbn8Z77t1TKCJ68AA02yGSIDkepkQHav49YzGwGECuY6nWvuuYmuWMw1gOyRvGcFyyQ2e32yWiqcSUFHJ2dnZ4T5q1n93Y3a8/JylAAclANfcgAwBuyc5uvh6NyRcJkqRwSzaA76/WVXNvdXV1bm5uJjWzvLzcbDY7nc7vPWXNtySDzy8fA1+/xePJ5LTvX68/+8Jj09nNN6eVHYy6V6q5J+U1wE4rOwCazeba2ho9enF0dBQaDg8P0+m0ruuNRiOTyTAAWqEMkiT7jCkAZzwGQIprxhWAuU4egGYV3VIhEloRLMYYPy5uhjNXV1epVAqAZh+EnwzkeV4ymVR6vd7Kykq1Wr0VS3gLiMCgFcpu0bxVtQ8AABTFLC0t/aqTZjlhnqEWFxd93+dBEAxhALhFEyAwTiTC6AbPRbNLJHyQdB1r4I82cR0LjGt2aVCtVqtEpAgh7p4BgJODJ6r5DowRyezGLgA1/wFACI4uOSRFhyR8xqeiM57n8SAIdF0fDSs/JRmQDIgEkSB5A0gicVLeHnIONTkpb0eXouu6lBIAxvzfJv/1eZ43vsQBCCEMw7jrMAzjvmzvqt/vj2yysLBwK9tOp1Or1QYJGIZxcXHRarUmxITqdrvtdnuoyeDlsqj17OwH5zEAiqKk0+k/wgxUr9eFEPF4nHMebfITsz9e09wAe3kAAAAASUVORK5CYII="

# BOLT_B64 is the e-bike lightning bolt at original x50-53, rows 24-28 (4x5).
BOLT_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAFCAIAAADtz9qMAAAARUlEQVR4nAXBMQqAMBBFwfcXUlpq54EU9bKC5wnYJIogiJ2bOCPg2McQzL+iFAeEmbp+EwC81+JeAe48PecMGFC8Nu0K/LfrFWgPimJNAAAAAElFTkSuQmCC"

SPRITE = base64.decode(SPRITE_B64)
BOLT = base64.decode(BOLT_B64)

# Screen placement. The sprite occupies rows 11-29 exactly as in the original;
# only its x moves.
SPRITE_TOP = 11
SPRITE_WIDTH = 35

# --- the roll-in ----------------------------------------------------------
# The bike rolls in from the left edge once, then parks for the rest of the
# slot: 1.0s still, 1.5s of motion, then nothing moves again.
#
# FRAME_MS x TOTAL_FRAMES is the whole webp, not the animation. pixlet caps a
# render at 150 frames, which at 100ms is the 15s an app gets on screen. The
# frames after the roll are IDENTICAL copies of the parked sprite, and they
# are load-bearing: render.Animation LOOPS its children, so a 25-frame
# animation would roll the bike in again every 2.5s. Padding the list to the
# full render length is what makes it happen exactly once.
# The bike parks one pixel clear of the left edge rather than flush against
# it, so the rear wheel is not the panel's own border.
PARK_X = 1

FRAME_MS = 100
TOTAL_FRAMES = 150
ROLL_HOLD_FRAMES = 10   # 1.0s parked off-screen before anything moves
ROLL_CONST_FRAMES = 7   # 0.7s at constant speed
ROLL_EASE_FRAMES = 5    # 0.5s decelerating to a stop

# The roll totals 1.2s, not the 1.25s asked for: at FRAME_MS = 100 that would
# be 12.5 frames, which is not a thing that can be rendered. Rounded to the
# FASTER side, since the point of the change was "quicker". Hitting 1.25s
# exactly would mean FRAME_MS = 125, which also slows the station-name marquee
# by a quarter -- a worse trade for 50ms.

def roll_x(frame):
    """Sprite x offset on `frame`: -SPRITE_WIDTH (fully off-screen) to PARK_X.

    Speed is solved, not tuned by eye: a constant phase of v px/frame followed
    by a linear decel from v to 0 covers v*const + v*ease/2 pixels, so
    v = distance / (const + ease/2) makes the bike arrive exactly on PARK_X on
    the last frame of the roll -- no overshoot to clamp away, and no fractional
    remainder parked one pixel short.
    """
    if frame < ROLL_HOLD_FRAMES:
        return -SPRITE_WIDTH

    step = frame - ROLL_HOLD_FRAMES + 1
    if step >= ROLL_CONST_FRAMES + ROLL_EASE_FRAMES:
        return PARK_X

    distance = SPRITE_WIDTH + PARK_X
    v = distance / (ROLL_CONST_FRAMES + ROLL_EASE_FRAMES / 2.0)
    if step <= ROLL_CONST_FRAMES:
        travelled = v * step
    else:
        t = step - ROLL_CONST_FRAMES
        travelled = v * ROLL_CONST_FRAMES + v * (t - t * t / (2.0 * ROLL_EASE_FRAMES))
    return int(travelled) - SPRITE_WIDTH

def rolling_sprite():
    """The sprite layer: one frame per rendered frame, rolling then parked."""
    frames = []
    for i in range(TOTAL_FRAMES):
        frames.append(render.Padding(
            pad = (roll_x(i), SPRITE_TOP, 0, 0),
            child = render.Image(src = SPRITE),
        ))
    return render.Animation(children = frames)

# --- layout ---------------------------------------------------------------
# Row positions are the ORIGINAL frame's, where the original had a row: the
# station name occupies rows 3-8 and the sprite rows 11-29. The three number
# rows are new -- the original had two, at rows 14-19 and 24-29 -- and are
# spaced evenly down the same band the original's two used.
#
# tb-8 renders its glyph one pixel below the top of its own box, so each
# padding value below is (target row - 1).
#
# tb-8 is measured, not preferred: it reproduces the reference's station-name
# text at 0/240 pixels, where Dina_r400-6 misses 87 and 5x8 misses 49. Its
# digits match the reference's 2/1/0 glyphs exactly too.
FONT = "tb-8"
TITLE_TOP = 2           # glyph lands on row 3
ROW_TOPS = [9, 17, 25]  # glyphs land on rows 10, 18, 26

COLOR_TEXT = "#ffffff"

# The dock icon is the one piece of art with no original to copy: the field
# does not exist in the Tidbyt app. Cyan sits clearly apart from both the
# sprite's #244bbd and the bolt's #f5ed4e.
COLOR_DOCK = "#3fd2ff"

# A 4x5 open dock -- a receptacle a bike slides into, drawn open at the top so
# it cannot be misread as a digit at this size (the reference's own '0' is an
# oval with single top and bottom pixels).
#
# The base is TWO rows thick, not one. At one row it read as a plain letter U
# on the device; the heavier base reads as a dock a bike stands in.
DOCK_GLYPH = [
    "#..#",
    "#..#",
    "#..#",
    "####",
    "####",
]

def dock_icon():
    """The dock glyph as stacked 1px boxes.

    Drawn rather than embedded because, unlike the sprite and the bolt, there
    is no reference pixel data to cut it from -- this is new art, and a
    literal bitmap keeps it reviewable in the diff instead of hidden inside a
    base64 blob.
    """
    rows = []
    for line in DOCK_GLYPH:
        cells = []
        for ch in line.elems():
            color = COLOR_DOCK if ch == "#" else None
            cells.append(render.Box(width = 1, height = 1, color = color))
        rows.append(render.Row(children = cells))
    return render.Column(children = rows)

def stat_row(top, icon, value):
    """One number row: optional icon, then the value, flush to the right edge.

    Right-aligned rather than left: it is where the original puts its numbers,
    and it keeps a 3-digit value (real -- 113 bikes and 114 docks exist in the
    live feed) growing leftwards into empty space instead of shoving the icon
    off screen.
    """
    children = []
    if icon != None:
        children.append(icon)
        children.append(render.Box(width = 2, height = 1))
    children.append(render.Text(value, font = FONT, color = COLOR_TEXT))
    return render.Padding(
        pad = (0, top, 0, 0),
        child = render.Box(
            width = 64,
            height = 7,
            # expanded = True is LOAD-BEARING, not decoration: without it the
            # Row shrinks to its children and main_align = "end" has nothing
            # to align against, so the row renders CENTRED instead of flush
            # right. Verified by rendering both ways.
            child = render.Row(
                main_align = "end",
                cross_align = "center",
                expanded = True,
                children = children,
            ),
        ),
    )

# --- data source ----------------------------------------------------------
# Lyft GBFS, keyless. Version 2.3 for BOTH feeds, deliberately: v1.1 also
# serves this system and also carries num_ebikes_available, but the two
# versions do not use the same station_id values (v1.1 identifies stations by
# UUID with a separate legacy_id), so an id read from one will not join
# against the other.
#
# This literal appears EXACTLY ONCE in this file. tools/gate_citibike.py
# asserts that before substituting its mock server's address, and refuses to
# run if the count drifts.
GBFS_BASE = "https://gbfs.lyft.com/gbfs/2.3/bkn/en/"

STATION_INFO_URL = GBFS_BASE + "station_information.json"
STATION_STATUS_URL = GBFS_BASE + "station_status.json"

# The information feed is 730 KB and changes when stations are built; the
# status feed is 1.0 MB and is the live one. Fetching AND decoding both inside
# pixlet, then scanning all 2463 stations, measures at 0.25s end to end -- no
# proxy or pre-digested mirror is needed.
INFO_TTL = 86400
STATUS_TTL = 60

# Shown in place of a number whenever the feed cannot answer.
NO_DATA = "--"

# --- configuration seam ---------------------------------------------------
# Nothing outside get_settings() may reference these constants by name.
DEFAULT_STATION_ID = "1861271680294357158"  # DeKalb Ave & S Portland Ave
DEFAULT_STATION_JSON = '{"display": "DeKalb Ave & S Portland Ave", "value": "1861271680294357158"}'

def fetch_json(url, ttl):
    """Fetches url and decodes the body as JSON, or None on any failure.

    TWO-ARGUMENT json.decode (returning None instead of raising) is
    load-bearing: resp.json() is FATAL on a non-JSON body (a proxy's HTML
    error page returned with a 200), and Starlark has no try/except for a
    caller to recover with.
    """
    resp = http.get(url, ttl_seconds = ttl)
    if resp.status_code != 200:
        return None
    return json.decode(resp.body(), None)

def station_records(url, ttl):
    """The list under data.stations, or [] on any malformed shape.

    Every level is type-checked rather than direct-indexed: a missing "data",
    a null "stations", or a top-level list instead of a dict must all degrade
    to [] rather than aborting the render.
    """
    data = fetch_json(url, ttl)
    if type(data) != "dict":
        return []
    inner = data.get("data")
    if type(inner) != "dict":
        return []
    stations = inner.get("stations")
    if type(stations) != "list":
        return []
    return stations

def station_name(station_id):
    """The station's display name, or "" if the feed cannot supply one."""
    for s in station_records(STATION_INFO_URL, INFO_TTL):
        if type(s) != "dict":
            continue
        if s.get("station_id") == station_id:
            name = s.get("name")
            if type(name) == "string":
                return name
    return ""

def is_off(v):
    """True for GBFS's "not in service", spelled either 0 or False.

    Starlark's bool is not an int subtype, so `False == 0` is False here --
    both spellings have to be checked explicitly. The live feed uses ints
    today; nothing guarantees it keeps doing so.
    """
    return v == 0 or v == False

def is_int(v):
    return type(v) == "int"

def counts(station_id):
    """(classic, ebikes, docks) as DISPLAY STRINGS, NO_DATA on any failure.

    classic is derived, not fetched: GBFS's num_bikes_available INCLUDES
    e-bikes, so the classic (pedal) count is the difference. Clamped at 0 --
    nothing guarantees the subtraction stays non-negative across a feed
    update, and a negative count would be nonsense on screen.

    A station that is not renting or not installed reports NO_DATA rather
    than its counts: the numbers exist but are not actionable, and showing
    them would be a lie of omission.
    """
    for s in station_records(STATION_STATUS_URL, STATUS_TTL):
        if type(s) != "dict":
            continue
        if s.get("station_id") != station_id:
            continue
        if is_off(s.get("is_renting")) or is_off(s.get("is_installed")):
            return (NO_DATA, NO_DATA, NO_DATA)
        bikes = s.get("num_bikes_available")
        ebikes = s.get("num_ebikes_available")
        docks = s.get("num_docks_available")
        if not is_int(bikes) or not is_int(ebikes) or not is_int(docks):
            return (NO_DATA, NO_DATA, NO_DATA)
        classic = bikes - ebikes
        if classic < 0:
            classic = 0
        return (str(classic), str(ebikes), str(docks))
    return (NO_DATA, NO_DATA, NO_DATA)

MAX_SEARCH_RESULTS = 20

def search_stations(pattern):
    """Typeahead handler. Returns at most MAX_SEARCH_RESULTS options.

    Must never raise -- a failed fetch yields an empty list, which the picker
    shows as "no matches". A raising handler would break the config UI itself.

    Two passes, deliberately: station names are intersection-derived and
    almost always unique, but "almost" is not "always", and two identically
    named entries are indistinguishable to whoever is choosing one. The first
    pass counts names so the second can append short_name to ONLY the
    colliding ones, instead of noising up every label with a dock number.
    """
    needle = pattern.lower()
    matches = []
    name_counts = {}
    for s in station_records(STATION_INFO_URL, INFO_TTL):
        if type(s) != "dict":
            continue
        name = s.get("name")
        station_id = s.get("station_id")
        if type(name) != "string" or type(station_id) != "string":
            continue
        if needle not in name.lower():
            continue
        matches.append((name, station_id, s.get("short_name")))
        name_counts[name] = name_counts.get(name, 0) + 1

    out = []
    for name, station_id, short_name in matches:
        display = name
        if name_counts[name] > 1 and type(short_name) == "string" and short_name:
            display = name + " (" + short_name + ")"
        out.append(schema.Option(display = display, value = station_id))
        if len(out) >= MAX_SEARCH_RESULTS:
            break
    return out

def get_schema():
    return schema.Schema(
        version = "1",
        fields = [
            schema.Typeahead(
                id = "station",
                name = "Station",
                desc = "CitiBike station to show availability for.",
                icon = "bicycle",
                handler = search_stations,
            ),
        ],
    )

def get_settings(config):
    """The ONE place station config is read.

    Two-argument json.decode again: a corrupt config blob must not kill every
    render, and there is no try/except to catch it with.
    """
    station_id = DEFAULT_STATION_ID
    label = ""
    raw = config.get("station", DEFAULT_STATION_JSON)
    decoded = json.decode(raw, None)
    if type(decoded) == "dict":
        value = decoded.get("value")
        if type(value) == "string" and value:
            station_id = value
        display = decoded.get("display")
        if type(display) == "string":
            label = display
    return {"station_id": station_id, "label": label}

def main(config):
    settings = get_settings(config)
    classic, ebikes, docks = counts(settings["station_id"])
    # The live feed's name is preferred over the config blob's stored label: a
    # station can be renamed after it was picked, and the feed is the
    # authority. The label is the fallback, and only if both are empty does the
    # app fall back to its own name.
    title = station_name(settings["station_id"])
    if title == "":
        title = settings["label"]
    if title == "":
        title = "CitiBike"

    return render.Root(
        delay = FRAME_MS,
        child = render.Stack(children = [
            rolling_sprite(),
            render.Padding(
                pad = (0, TITLE_TOP, 0, 0),
                child = render.Marquee(
                    width = 64,
                    child = render.Text(title, font = FONT, color = COLOR_TEXT),
                ),
            ),
            stat_row(ROW_TOPS[0], None, classic),
            stat_row(ROW_TOPS[1], render.Image(src = BOLT), ebikes),
            stat_row(ROW_TOPS[2], dock_icon(), docks),
        ]),
    )
