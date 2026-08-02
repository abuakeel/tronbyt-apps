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
# SPRITE_B64 is the bike at original x12-38, rows 11-29 (27x19): seat, most of
# the frame, and the whole front wheel, with the rear wheel running off the
# left edge.
#
# The cut DOES pass through the rear wheel (x4-17), deliberately. It lands at
# the panel's left edge, where a sliced shape reads as continuing past the
# frame; the same slice mid-frame, with black on both sides, reads as a
# rendering bug. Cutting clear of both wheels is only possible in the x18-24
# tube band, which leaves 15-21px of bike against a 27px dead gap -- tried at
# x20 first, and rejected on review of the rendered frame as too aggressive a
# crop.
SPRITE_B64 = "iVBORw0KGgoAAAANSUhEUgAAABsAAAATCAIAAADu5eFvAAACEElEQVR4nK2Tz27aQBDGv11CqEK5gMw9NpgrXOAJoDaRmrbqc7aiUjCB9EGAAAckQFjYSBb/vTs9mCCnicCVOqfdmW9/OzszyxDNJpMJgEQikclkIh6JZFq9o9U7/5MIIFdvnxfw+Xy+Wq2iE4nkBWI2m/U8z3GcxWIxHo8vE+Uh0s25aNXJ3T3l7n5fyPF4M9HFAmmmRSRB8jyUA1CNh4FVIynO4QyL5AFSPDerJPYAlsul67qr9crzvFdStdZQa41gfVv98T7uU1M1Hm6rP4Ot67pqrZHP54Otruu2bbuue8xRih3Ajur3+qjWGlLuSBxGna8AbNuuVCpEot/vB4Jer6coSrlcns/nADi/umGxa351A2D09F0zmq8f22SxD7H4x1HnS+BJJpO9Xm/U+aaZj2Flv99PpVLHOoIIIO1NZzTzESwG0HOzGnjW63WpVHqJk2ZYYX2xWNxutxwgME4kgiefxk0zWyS2IDmwjNMZ3/e73W6wHlgGGNfM1ina7XaJiAFQa7/AGAASO8bjYDEAjHGSh2H7PpyF4zjpdDpcYsavBy0zLOAAhu3PJH2SPpEgEiQPgCQSf+GCHE8tBjBs34dx+XxeypfeRv/am83mfIgD0HVdiHPjHbb9fq/r+lt/oVDwfR8AZrPZYrGIiAtsuVw6jhOe8Nlsdppw9k+ssE2nUyFEPB7nnCuKcvL/AceUE/juiRW1AAAAAElFTkSuQmCC"

# BOLT_B64 is the e-bike lightning bolt at original x50-53, rows 24-28 (4x5).
BOLT_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAFCAIAAADtz9qMAAAARUlEQVR4nAXBMQqAMBBFwfcXUlpq54EU9bKC5wnYJIogiJ2bOCPg2McQzL+iFAeEmbp+EwC81+JeAe48PecMGFC8Nu0K/LfrFWgPimJNAAAAAElFTkSuQmCC"

SPRITE = base64.decode(SPRITE_B64)
BOLT = base64.decode(BOLT_B64)

# Screen placement. The sprite occupies rows 11-29 exactly as in the original;
# only its x moves.
SPRITE_TOP = 11

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
DOCK_GLYPH = [
    "#..#",
    "#..#",
    "#..#",
    "#..#",
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
        delay = 100,
        child = render.Stack(children = [
            render.Padding(pad = (0, SPRITE_TOP, 0, 0), child = render.Image(src = SPRITE)),
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
