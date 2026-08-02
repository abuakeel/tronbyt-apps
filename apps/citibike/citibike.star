load("render.star", "render")
load("http.star", "http")
load("encoding/json.star", "json")
load("encoding/base64.star", "base64")

# --- embedded art ---------------------------------------------------------
# Cut from reference/citibike-64x32.png by tools/cut_sprite.py -- NOT drawn by
# hand. Regenerate with `python3 tools/cut_sprite.py --emit`; never edit these
# strings directly. tools/gate_citibike.py --sprite re-derives the cut from
# the reference and fails if what renders here has drifted from it.
#
# SPRITE_B64 is the bike at original x20-38, rows 11-29 (19x19). x20 is the
# only column band that touches neither wheel, so shifting the sprite left to
# x0 cuts through the frame tubes between the seat and the handlebars, and the
# front wheel arrives whole.
SPRITE_B64 = "iVBORw0KGgoAAAANSUhEUgAAABMAAAATCAIAAAD9MqGbAAABUUlEQVR4nJ2Sy26CQBSGf2itOzfGB4Bhxq0+BAr6rrVNU5Davolu1YBxiEak6DBdqJSi2Oi/O5dvzmWOgr+aTqcAqtVqvV7HHSK9EemN7iEBGL2P6wlqWUDK9F4y3V0nHy96jf4noNxck9iulClkavS/biCJ5cp0h1SMHVOKBEAYhpzzTbRZr9elz5Cuo1vvmjk4mJxzvfNKKT2YjLEgCDjnRUzvvGrmQDNfDmYQBIwxzXwupFFKfd/PN+kQ2zNyvx9F0WlsrwBvt9vjnMT2oDwAcuyYGdZut0+Zklhunmy1WnEcK8QeSvGtqE+ToZ3FVqtVrVb77cj2ADlxrXxZFTIFkMcA7Pf7vClFDCmLDevdN5zJ9/1speeilC4Wi7LocQ1XQqV3myQJY+zc32w2C7NcUBiGy+Uyfwnz+Ty7hH/OGsBsNhNCVCoVVVUbjUbm/wEnz5+RapOfUAAAAABJRU5ErkJggg=="

# BOLT_B64 is the e-bike lightning bolt at original x50-53, rows 24-28 (4x5).
BOLT_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAFCAIAAADtz9qMAAAARUlEQVR4nAXBMQqAMBBFwfcXUlpq54EU9bKC5wnYJIogiJ2bOCPg2McQzL+iFAeEmbp+EwC81+JeAe48PecMGFC8Nu0K/LfrFWgPimJNAAAAAElFTkSuQmCC"

SPRITE = base64.decode(SPRITE_B64)
BOLT = base64.decode(BOLT_B64)

# Screen placement. The sprite occupies rows 11-29 exactly as in the original;
# only its x moves.
SPRITE_TOP = 11

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
    title = station_name(settings["station_id"])
    if title == "":
        title = settings["label"]
    return render.Root(
        child = render.Stack(children = [
            render.Padding(pad = (0, SPRITE_TOP, 0, 0), child = render.Image(src = SPRITE)),
            # Scaffolding, replaced by the real layout in the next task. Padded
            # clear of the sprite's x0-18 footprint so the two do not overlap:
            # unpadded, this text draws straight through the bike.
            render.Padding(
                pad = (20, 0, 0, 0),
                child = render.Column(children = [
                    render.Text(title, font = "tb-8", color = "#ffffff"),
                    render.Text(classic + " " + ebikes + " " + docks, font = "tb-8", color = "#ffffff"),
                ]),
            ),
        ]),
    )
