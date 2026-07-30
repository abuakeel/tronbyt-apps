#!/usr/bin/env python3
"""Gate for the NYC Subway recreation.

Governing principle: NO fixture mode inside nyc-subway.star's main(). Any
`if config.bool("fixture")` branch would be a code path that exists only for
the gate -- exactly the shape that let the earlier bitmap-overlay defect
through (Task 3 review). Instead, this tool changes *where bytes come from*,
never *what code runs*:

  1. Read the committed apps/nyc-subway/nyc-subway.star verbatim.
  2. Assert it references the real API host ("https://api.subwaynow.app/")
     exactly twice (STOPS_URL, ROUTES_URL) -- if that ever changes, this
     script is out of sync with the app and must be updated, not silently
     patch the wrong thing.
  3. Textually substitute that host for a local mock HTTP server's
     127.0.0.1:<ephemeral port>, write the result to a tempfile, and render
     THAT with the real `pixlet` binary.

For the render-based modes (default, --failures, --live), every downstream
line of nyc-subway.star -- fetch_json, route_colors, stop_names, fetch_trips,
render_row, render_app, main -- runs completely unmodified. A broken app
cannot pass by special-casing a fixture flag, because there is no such flag
to special-case. (--handler is the exception: it strips the real main() and
substitutes a probe main() so search_stations()/station_label() can be
invoked and their output printed -- see cmd_handler and
read_patched_star_source below. Everything the probe calls into --
fetch_json, station_label, search_stations -- still runs unmodified; only
main() itself is swapped.)

Modes:
  (default)           render the reference fixture, require the WHOLE 64x32
                       frame to match reference/subway-64x32.png with 0
                       differing pixels (stronger and more deterministic
                       than checking a handful of static regions).
  --failures          render every tools/fixtures/failures/*.json case;
                       each must render without a Starlark error and keep
                       the divider region intact.
  --live              render against the real, live API; informational only
                       (asserts render succeeds and the divider stays OK,
                       never gates on the live whole-frame diff, since real
                       destinations/arrivals legitimately differ from the
                       reference). Also cross-checks the mock server against
                       a live snapshot, then calls --refresh-fixture.
  --refresh-fixture   re-fetch the three live endpoints and diff KEY SETS
                       (not values) against reference-frame.json, so an API
                       shape change is caught even though nothing else here
                       exercises the live shape directly.
  --handler           probe search_stations() via a print()-based harness:
                       labelling, case-insensitivity, the MAX_SEARCH_RESULTS
                       cap against a synthetic over-cap fixture, and
                       must-never-raise on a fetch failure.
"""
import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare import compare_images, lit, load_scaled, scale_from  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP_SRC = ROOT / "apps" / "nyc-subway" / "nyc-subway.star"
REFERENCE_PNG = ROOT / "reference" / "subway-64x32.png"
FIXTURE_DIR = ROOT / "tools" / "fixtures"
REFERENCE_FIXTURE = FIXTURE_DIR / "reference-frame.json"
FAILURES_DIR = FIXTURE_DIR / "failures"

LIVE_HOST = "https://api.subwaynow.app/"
EXPECTED_LIVE_HOST_COUNT = 2

# Same bullet coordinates Task 3/4 established. Used ONLY by --live's
# live-vs-mock identity check below -- NOT for comparing against the static
# reference image (compare.py's STATIC_REGIONS no longer includes these;
# see that file for why).
BULLET_REGIONS = {
    "bullet_north": (2, 2, 15, 15),
    "bullet_south": (2, 18, 15, 31),
}


def load_json(path):
    return json.loads(path.read_text())


def find_pixlet():
    pixlet = shutil.which("pixlet")
    if not pixlet:
        sys.exit("pixlet not found on PATH")
    return pixlet


def read_patched_star(port):
    src = APP_SRC.read_text()
    count = src.count(LIVE_HOST)
    if count != EXPECTED_LIVE_HOST_COUNT:
        sys.exit(
            f"refusing to patch {APP_SRC}: expected exactly "
            f"{EXPECTED_LIVE_HOST_COUNT} occurrences of {LIVE_HOST!r}, found "
            f"{count}. The app's URL literals changed shape -- update gate.py, "
            f"don't silently patch the wrong thing."
        )
    return src.replace(LIVE_HOST, f"http://127.0.0.1:{port}/")


def render_source_path(star_path, out_path, timeout=30, app_config=None):
    pixlet = find_pixlet()
    cmd = [pixlet, "render", str(star_path), "-o", str(out_path)]
    if app_config:
        cmd += [f"{k}={v}" for k, v in app_config.items()]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def render_source(src, out_path, timeout=30, app_config=None):
    with tempfile.TemporaryDirectory() as td:
        star_path = Path(td) / "nyc-subway.star"
        star_path.write_text(src)
        return render_source_path(star_path, out_path, timeout=timeout, app_config=app_config)


# --- mock server -------------------------------------------------------


def resolve_stop_body(template):
    """Resolves arrival_offset (seconds from now) -> an absolute unix time
    in estimated_current_stop_arrival_time. Fields already set explicitly
    (including explicit null) pass through untouched."""
    if template is None:
        return None
    now = int(time.time())
    body = copy.deepcopy(template)
    trips = body.get("upcoming_trips")
    if not trips:
        return body
    for direction, lst in trips.items():
        if not lst:
            continue
        for trip in lst:
            if "arrival_offset" in trip:
                offset = trip.pop("arrival_offset")
                trip["estimated_current_stop_arrival_time"] = now + offset
    return body


def make_handler(routes_body, stops_body, stop_template, http_status, strict_stop_id=False, requested_ids=None, stop_raw_body=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if http_status is not None:
                self.send_response(http_status)
                self.end_headers()
                return

            path = self.path.split("?", 1)[0]
            if path == "/routes/":
                body = routes_body
            elif path == "/stops/":
                body = stops_body
            elif path.startswith("/stops/"):
                requested_id = path[len("/stops/"):]
                if requested_ids is not None:
                    requested_ids.append(requested_id)

                # Strict id matching (final review, IMPORTANT 1/2): without
                # this, EVERY /stops/<id> request -- whatever <id> the app
                # actually asked for -- got served the same stop_template
                # regardless, so no fixture could distinguish "app requested
                # the right stop" from "app requested the wrong stop"; only
                # "crashed" vs "didn't crash". A mismatch here is a 404 --
                # distinguishable from real trip data, not a silent 200 with
                # the wrong body. Only active when the caller is exercising
                # real app_config (see render_via_mock) -- every pre-existing
                # fixture passes no app_config and keeps the original
                # unconditional-serve behavior untouched.
                expected_id = stop_template.get("id") if isinstance(stop_template, dict) else None
                if strict_stop_id and requested_id != expected_id:
                    self.send_response(404)
                    self.end_headers()
                    return

                if stop_raw_body is not None:
                    # Escape hatch (final review, IMPORTANT 4): serves a
                    # LITERAL non-JSON body with a 200 status, e.g. the
                    # HTML interstitial a captive-portal proxy might return.
                    # make_handler otherwise always json.dumps()'s its body,
                    # so no fixture could previously express the realistic
                    # "200 but not JSON" case that motivated fetch_json's
                    # two-argument json.decode in the first place -- reverting
                    # that to resp.json() is FATAL on exactly this body, and
                    # nothing here could catch the regression.
                    data = stop_raw_body.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return

                body = resolve_stop_body(stop_template)
            else:
                self.send_response(404)
                self.end_headers()
                return

            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def start_server(routes_body, stops_body, stop_template, http_status=None, strict_stop_id=False, requested_ids=None, stop_raw_body=None):
    httpd = HTTPServer(
        ("127.0.0.1", 0),
        make_handler(
            routes_body, stops_body, stop_template, http_status,
            strict_stop_id=strict_stop_id, requested_ids=requested_ids, stop_raw_body=stop_raw_body,
        ),
    )
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


def stop_server(httpd):
    httpd.shutdown()
    httpd.server_close()


def render_via_mock(routes_body, stops_body, stop_template, out_path, http_status=None, app_config=None, requested_stop_ids=None, stop_raw_body=None):
    # Strict stop-id matching activates only when real app_config is being
    # exercised for THIS render. run_one_failure_case's 'assert_matches_stop'
    # oracle render deliberately passes no app_config, so it stays
    # permissive and always answers with its own fixture body regardless of
    # which (config-independent, always-default) id gets requested -- that
    # is what makes it a valid ground truth to compare the real render
    # against, rather than something that could pass or fail in lockstep
    # with the same bug.
    # `is not None`, NOT `bool(app_config)` (final review, M9): a fixture
    # whose config is legitimately `{}` is falsy but is still real
    # app_config being exercised -- `bool({})` would silently degrade that
    # case back to permissive matching.
    strict_stop_id = app_config is not None
    httpd, port = start_server(
        routes_body, stops_body, stop_template,
        http_status=http_status, strict_stop_id=strict_stop_id, requested_ids=requested_stop_ids,
        stop_raw_body=stop_raw_body,
    )
    try:
        patched = read_patched_star(port)
        return render_source(patched, out_path, app_config=app_config)
    finally:
        stop_server(httpd)


# --- default mode: reference fixture, whole-frame, 0 pixels -------------


def cmd_default():
    fixture = load_json(REFERENCE_FIXTURE)
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "frame.webp"
        # No app_config is passed here on purpose -- this is the "app was
        # never configured" production path, and it must resolve to
        # DEFAULT_STOP_ID via DEFAULT_STATION_JSON. requested_stop_ids
        # records what the app actually asked the mock for (final review,
        # IMPORTANT 1): without this, render_via_mock's mock server answers
        # /stops/<ANYTHING> with the same fixture body regardless of which id
        # was requested (strict_stop_id is only active when app_config is
        # passed), so a whole-frame pixel match alone can't prove the app
        # requested the right stop -- it would pass identically even if
        # DEFAULT_STATION_JSON's "value" silently drifted from G35.
        requested_stop_ids = []
        result = render_via_mock(
            fixture["routes"], fixture["stops"], fixture["stop"], out_path,
            requested_stop_ids=requested_stop_ids,
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            print(f"pixlet render failed against the reference fixture (exit {result.returncode})")
            return 1
        expected_id = fixture["stop"]["id"]
        if requested_stop_ids != [expected_id]:
            print(
                f"default gate FAIL -- unconfigured app requested stop id(s) "
                f"{requested_stop_ids}, expected exactly [{expected_id!r}]. "
                f"DEFAULT_STATION_JSON no longer drives the no-config production "
                f"path to the expected stop."
            )
            return 1
        fail, report = compare_images(str(out_path), str(REFERENCE_PNG), strict_whole_frame=True)
        print(report)
        return fail


# --- --failures mode -----------------------------------------------------


def run_one_failure_case(case_path, default_routes, default_stops):
    case = load_json(case_path)
    name = case_path.stem
    http_status = case.get("http_status")
    routes_body = case.get("routes", default_routes)
    stops_body = case.get("stops", default_stops)
    stop_template = case.get("stop")
    stop_raw_body = case.get("stop_raw_body")
    app_config = case.get("config")

    if http_status is None and stop_template is None and stop_raw_body is None:
        return False, f"{name}: FAIL -- fixture has none of 'http_status', 'stop', 'stop_raw_body'"

    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "frame.webp"
        requested_stop_ids = []
        result = render_via_mock(
            routes_body, stops_body, stop_template, out_path,
            http_status=http_status, app_config=app_config, requested_stop_ids=requested_stop_ids,
            stop_raw_body=stop_raw_body,
        )
        if result.returncode != 0:
            return False, (
                f"{name}: FAIL -- pixlet render crashed (exit {result.returncode})\n"
                f"{result.stderr}"
            )

        # Divider must stay intact. Use the default (non-strict) comparator,
        # which only gates on STATIC_REGIONS (divider) -- these fixtures
        # deliberately produce non-reference content (different bullets,
        # different or absent destinations), so whole-frame equality is not
        # the bar here.
        fail, report = compare_images(str(out_path), str(REFERENCE_PNG), strict_whole_frame=False)
        if fail:
            return False, f"{name}: FAIL -- divider region broken\n{report}"

        assert_stop = case.get("assert_matches_stop")
        if assert_stop is not None:
            expected_path = Path(td) / "expected.webp"
            result2 = render_via_mock(routes_body, stops_body, assert_stop, expected_path)
            if result2.returncode != 0:
                return False, f"{name}: FAIL -- expected-equivalent render crashed (exit {result2.returncode})"
            fail2, report2 = compare_images(str(out_path), str(expected_path), strict_whole_frame=True)
            if fail2:
                return False, (
                    f"{name}: FAIL -- did not render the expected trip "
                    f"(pixel diff vs the equivalent single-trip render)\n"
                    f"requested stop id(s): {requested_stop_ids}\n{report2}"
                )

        # 'assert_matches_reference': true -- a stronger check than the
        # divider-only gate above, for cases engineered to reproduce the
        # reference fixture's exact trips (same route/destination/arrival)
        # through a different code path (e.g. a bare-hex route colour that
        # must normalize to the same colour the reference fixture spells
        # with a leading '#'). Requires a 0-pixel whole-frame diff against
        # reference/subway-64x32.png itself, not just a second mock render.
        if case.get("assert_matches_reference"):
            fail3, report3 = compare_images(str(out_path), str(REFERENCE_PNG), strict_whole_frame=True)
            if fail3:
                return False, (
                    f"{name}: FAIL -- did not reproduce the reference frame "
                    f"(pixel diff vs reference/subway-64x32.png)\n{report3}"
                )

        return True, f"{name}: OK"


def read_patched_star_source():
    """URL-patched app source with its own main() stripped off.

    The probe appends its own main(); leaving the real one in place would
    mean two definitions of the global `main`, and Starlark raises "cannot
    reassign global main" rather than letting the last one silently win.
    """
    src = APP_SRC.read_text()
    if src.count(LIVE_HOST) != EXPECTED_LIVE_HOST_COUNT:
        raise SystemExit(
            f"expected exactly {EXPECTED_LIVE_HOST_COUNT} occurrences of "
            f"{LIVE_HOST} in {APP_SRC}, found {src.count(LIVE_HOST)} -- "
            f"refusing to patch"
        )
    marker = "\ndef main(config):"
    idx = src.find(marker)
    if idx == -1:
        raise SystemExit(f"no 'def main(config):' found in {APP_SRC}")
    return src[:idx]


def run_probe(src_without_main, stops_body):
    """Render a probe app against the mock and return its print() lines.

    Starlark print() reaches stdout as '[<app>.star] <line>'; the prefix is
    stripped so callers compare against plain strings.

    The caller's probe source MUST print a "PROBE-DONE" sentinel as its last
    line. Without this, a crashing render (returncode != 0) yields no stdout
    lines at all, which collapses to the same empty list as a probe that ran
    fine and legitimately found zero matches -- making a real crash
    indistinguishable from "no matches" to anything that only looks at
    `lines`. Asserting the sentinel (and a clean exit) turns that silent
    swallow into a loud RuntimeError.
    """
    httpd, port = start_server({"routes": {}}, stops_body, None)
    try:
        patched = src_without_main.replace(LIVE_HOST, f"http://127.0.0.1:{port}/")
        with tempfile.TemporaryDirectory() as td:
            star_path = Path(td) / "probe.star"
            star_path.write_text(patched)
            out_path = Path(td) / "probe.webp"
            result = render_source_path(star_path, out_path)
            lines = []
            for line in result.stdout.splitlines():
                if line.startswith("[") and "] " in line:
                    lines.append(line.split("] ", 1)[1])
            if result.returncode != 0 or "PROBE-DONE" not in lines:
                raise RuntimeError(
                    f"probe crashed or never completed (exit {result.returncode}):\n"
                    f"{result.stderr}"
                )
            lines.remove("PROBE-DONE")
            return lines
    finally:
        stop_server(httpd)


def cmd_handler():
    """Assert search_stations() labelling via a probe app that prints results.

    The handler cannot be invoked through `pixlet render` directly, so the probe
    appends a main() that calls it and prints one line per option. Starlark
    print() reaches stdout prefixed with "[<app>.star] ".
    """
    stops_body = {"stops": [
        {"id": "G35", "name": "Clinton - Washington Avs", "routes": {"G": ["north", "south"]}},
        {"id": "A44", "name": "Clinton - Washington Avs", "routes": {"A": ["north", "south"]}},
        {"id": "X01", "name": "Routeless Test Stop"},
    ]}
    checks = [
        # Mixed-case pattern -- covers needle = pattern.lower() (a mutation
        # that drops .lower() would find nothing here, since none of the
        # fixture's stop names contain the literal substring "CLINton").
        ("CLINton", ["Clinton - Washington Avs (A)|A44",
                     "Clinton - Washington Avs (G)|G35"]),
        ("routeless", ["Routeless Test Stop [X01]|X01"]),
        ("zzzznomatch", []),
    ]
    failures = []
    for pattern, expected in checks:
        src = read_patched_star_source()
        src += (
            "\n\ndef main(config):\n"
            f"    for o in search_stations(\"{pattern}\"):\n"
            "        print(o.display + \"|\" + o.value)\n"
            "    print(\"PROBE-DONE\")\n"
            "    return render.Root(child = render.Box(color = \"#000000\"))\n"
        )
        try:
            got = run_probe(src, stops_body)
        except RuntimeError as e:
            failures.append(f"  {pattern!r}: {e}")
            continue
        if sorted(got) != sorted(expected):
            failures.append(f"  {pattern!r}: expected {expected}, got {got}")

    # MAX_SEARCH_RESULTS cap: the 3-stop fixture above never has more than 2
    # matches for anything, so it cannot exercise the 20-result cap at all --
    # deleting the cap's `break`, or loosening MAX_SEARCH_RESULTS to 21 or
    # 999, would still pass every check above. 25 synthetic stops, all
    # matching "cap", forces the cap to actually bind.
    cap_stops_body = {"stops": [
        {"id": "CAP%02d" % i, "name": "Captain Stop %d" % i, "routes": {"C": ["north"]}}
        for i in range(25)
    ]}
    src = read_patched_star_source()
    src += (
        "\n\ndef main(config):\n"
        "    print(\"cap=\" + str(len(search_stations(\"cap\"))))\n"
        "    print(\"PROBE-DONE\")\n"
        "    return render.Root(child = render.Box(color = \"#000000\"))\n"
    )
    try:
        cap_lines = run_probe(src, cap_stops_body)
    except RuntimeError as e:
        failures.append(f"  cap: {e}")
    else:
        if cap_lines != ["cap=20"]:
            failures.append(f"  cap: expected ['cap=20'], got {cap_lines}")

    # Feed down: the handler must return [] and MUST NOT raise. A raising
    # handler would break the config UI itself, not just the render, and
    # Starlark has no try/except for the caller to fall back on.
    src = read_patched_star_source()
    src += (
        "\n\ndef main(config):\n"
        "    print(\"n=\" + str(len(search_stations(\"clinton\"))))\n"
        "    return render.Root(child = render.Box(color = \"#000000\"))\n"
    )
    httpd, port = start_server({"routes": {}}, stops_body, None, http_status=503)
    try:
        patched = src.replace(LIVE_HOST, f"http://127.0.0.1:{port}/")
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "probe.star"
            sp.write_text(patched)
            res = render_source_path(sp, Path(td) / "p.webp")
            if res.returncode != 0:
                failures.append("  feed-down: handler CRASHED (must return [] instead)")
            elif "n=0" not in res.stdout:
                failures.append(f"  feed-down: expected n=0, got {res.stdout.strip()!r}")
    finally:
        stop_server(httpd)

    check_live_duplicate_labels(failures)
    check_field_preference_order(failures)

    for line in failures:
        print(line)
    print("handler: OK" if not failures else "handler: FAIL")
    return 1 if failures else 0


def check_field_preference_order(failures):
    """Deterministic synthetic guard pinning station_label's field-preference
    order: scheduled_routes, then routes, then the bare [id] fallback.

    check_live_duplicate_labels above is real-world but non-deterministic --
    it re-derives its expectation (zero duplicates) from whatever the live
    API happens to be serving RIGHT NOW, so a `for key in ("routes",):`
    regression can pass it whenever the colliding stops' currently-running
    service happens not to overlap, and it structurally cannot see the
    routeless-fallback half of the bug at all (two different stops both
    falling back to `name [id]` are never *duplicates* of each other). This
    check instead pins the three cases directly against synthetic stops
    served through the mock, so the expectation never depends on time of day
    or live service state:

      1. scheduled_routes AND routes present and DIFFERENT -> label uses
         scheduled_routes. The two route letters are chosen so a
         routes-only implementation produces a visibly different, wrong
         label ('(Q)' instead of '(Z)') -- this is the one that catches the
         regression.
      2. Only routes present -> label falls back to routes.
      3. Neither present -> label falls back to the bare '[id]' form.
    """
    stops_body = {"stops": [
        {"id": "PREF1", "name": "Preference Stop", "scheduled_routes": {"Z": ["north"]}, "routes": {"Q": ["north"]}},
        {"id": "PREF2", "name": "Fallback Stop", "routes": {"R": ["north"]}},
        {"id": "PREF3", "name": "Bare Stop"},
    ]}
    expected = {
        "PREF1": "Preference Stop (Z)",
        "PREF2": "Fallback Stop (R)",
        "PREF3": "Bare Stop [PREF3]",
    }
    src = read_patched_star_source()
    src += (
        "\n\ndef main(config):\n"
        "    data = fetch_json(STOPS_URL, 86400)\n"
        "    for s in (data.get(\"stops\") or []):\n"
        "        print(s[\"id\"] + \"=\" + station_label(s))\n"
        "    print(\"PROBE-DONE\")\n"
        "    return render.Root(child = render.Box(color = \"#000000\"))\n"
    )
    try:
        lines = run_probe(src, stops_body)
    except RuntimeError as e:
        failures.append(f"  field-preference-order: {e}")
        return

    got = {}
    for line in lines:
        stop_id, _, label = line.partition("=")
        got[stop_id] = label

    for stop_id, want in expected.items():
        have = got.get(stop_id)
        if have != want:
            failures.append(
                f"  field-preference-order: stop {stop_id!r} expected label "
                f"{want!r}, got {have!r}"
            )


def check_live_duplicate_labels(failures):
    """Guard (final review, IMPORTANT 2/3): station_label must not produce
    duplicate labels against REAL station data.

    Every other check in cmd_handler runs against a tiny (<=25-stop)
    synthetic fixture -- none of them could ever have caught the bug a human
    reviewer found by hand-sampling the live API: `routes` (current service)
    produced duplicate labels between DIFFERENT stations (e.g. two unrelated
    stops both labelled 'Gun Hill Rd (2)') and left ~20 stops with no label
    disambiguator at all at any given hour. Nothing here ran the real
    station_label() against real data, which is exactly why that was
    invisible until someone looked by hand. This fetches the live /stops/
    list once, serves it back through the mock (so the app's own
    fetch_json/STOPS_URL path is exercised unmodified), and asserts zero
    duplicate display labels across all of it.
    """
    try:
        live_stops = fetch_url(LIVE_HOST + "stops/")
    except Exception as e:
        failures.append(f"  live-duplicate-labels: FAIL -- could not fetch live stops: {e}")
        return

    src = read_patched_star_source()
    src += (
        "\n\ndef main(config):\n"
        "    data = fetch_json(STOPS_URL, 86400)\n"
        "    for s in (data.get(\"stops\") or []):\n"
        "        print(station_label(s))\n"
        "    print(\"PROBE-DONE\")\n"
        "    return render.Root(child = render.Box(color = \"#000000\"))\n"
    )
    try:
        labels = run_probe(src, live_stops)
    except RuntimeError as e:
        failures.append(f"  live-duplicate-labels: {e}")
        return

    counts = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    dups = sorted(label for label, n in counts.items() if n > 1)
    if dups:
        failures.append(
            f"  live-duplicate-labels: FAIL -- {len(dups)} duplicate label(s) "
            f"across {len(labels)} live stops, e.g. {dups[:5]}"
        )


def cmd_failures():
    fixture = load_json(REFERENCE_FIXTURE)
    default_routes = fixture["routes"]
    default_stops = fixture["stops"]

    cases = sorted(FAILURES_DIR.glob("*.json"))
    if not cases:
        print(f"no failure fixtures found in {FAILURES_DIR}")
        return 1

    overall_ok = True
    for case_path in cases:
        ok, message = run_one_failure_case(case_path, default_routes, default_stops)
        print(message)
        overall_ok = overall_ok and ok

    return 0 if overall_ok else 1


# --- --live mode -----------------------------------------------------


def fetch_url(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())


def default_stop_id():
    src = APP_SRC.read_text()
    m = re.search(r'DEFAULT_STOP_ID\s*=\s*"([^"]+)"', src)
    if not m:
        sys.exit(f"could not find DEFAULT_STOP_ID in {APP_SRC}")
    return m.group(1)


def fetch_live_json():
    stop_id = default_stop_id()
    routes = fetch_url(LIVE_HOST + "routes/")
    stops = fetch_url(LIVE_HOST + "stops/")
    stop = fetch_url(LIVE_HOST + "stops/" + stop_id + "?agent=tidbyt")
    return routes, stops, stop


def compare_bullet_regions(path_a, path_b):
    scale = scale_from(path_a)
    a = load_scaled(path_a, scale)
    b = load_scaled(path_b, scale)
    lines = []
    fail = 0
    for name, (x0, y0, x1, y1) in BULLET_REGIONS.items():
        diff = sum(
            1
            for y in range(y0, y1)
            for x in range(x0, x1)
            if lit(a[x, y]) != lit(b[x, y])
        )
        total = (x1 - x0) * (y1 - y0)
        status = "OK" if diff == 0 else "MISMATCH"
        if diff:
            fail = 1
        lines.append(f"  {name:<14} {status:<9} {diff}/{total} pixels differ (live vs mock-from-live)")
    return fail, "\n".join(lines)


def cmd_live():
    src = APP_SRC.read_text()
    count = src.count(LIVE_HOST)
    if count != EXPECTED_LIVE_HOST_COUNT:
        print(f"expected exactly {EXPECTED_LIVE_HOST_COUNT} occurrences of {LIVE_HOST!r}, found {count}")
        return 1

    with tempfile.TemporaryDirectory() as td:
        live_out = Path(td) / "live.webp"
        result = render_source(src, live_out)
        if result.returncode != 0:
            print(f"live render failed (exit {result.returncode}):\n{result.stderr}")
            return 1

        fail, report = compare_images(str(live_out), str(REFERENCE_PNG), strict_whole_frame=False)
        print("--- live render vs reference (divider gates; whole-frame is informational) ---")
        print(report)
        if fail:
            print("live render: divider region broken")
            return 1

        live_routes, live_stops, live_stop = fetch_live_json()
        mock_out = Path(td) / "mock-from-live.webp"
        result2 = render_via_mock(live_routes, live_stops, live_stop, mock_out)
        if result2.returncode != 0:
            print(f"mock-from-live render failed (exit {result2.returncode}):\n{result2.stderr}")
            return 1

        bullet_fail, bullet_report = compare_bullet_regions(str(live_out), str(mock_out))
        print("\n--- live vs mock-from-live (same underlying data; bullets should match exactly) ---")
        print(bullet_report)
        if bullet_fail:
            print("mock server did not faithfully reproduce the live payload")
            return 1

    return cmd_refresh_fixture()


# --- --refresh-fixture mode -----------------------------------------------


def _keys(d):
    return set(d.keys()) if isinstance(d, dict) else set()


def diff_key_shape(fixture, live):
    """Compares KEY SETS (not values) between the fixture and a live pull.
    Only flags keys the fixture/app relies on that have DISAPPEARED from
    live -- new live-only keys are informational, not gating."""
    problems = []

    f_routes = fixture["routes"].get("routes", {})
    l_routes = live[0].get("routes", {})
    f_route_keys = _keys(next(iter(f_routes.values()))) if f_routes else set()
    l_route_keys = _keys(next(iter(l_routes.values()))) if l_routes else set()
    missing = f_route_keys - l_route_keys
    if missing:
        problems.append(f"routes entry: fixture keys missing from live: {sorted(missing)}")

    f_stops = fixture["stops"].get("stops", [])
    l_stops = live[1].get("stops", [])
    f_stop_keys = _keys(f_stops[0]) if f_stops else set()
    l_stop_keys = _keys(l_stops[0]) if l_stops else set()
    missing = f_stop_keys - l_stop_keys
    if missing:
        problems.append(f"stops entry: fixture keys missing from live: {sorted(missing)}")

    f_stop = fixture["stop"]
    l_stop = live[2]
    missing_top = _keys(f_stop) - _keys(l_stop)
    if missing_top:
        problems.append(f"stop: fixture top-level keys missing from live: {sorted(missing_top)}")

    f_north = f_stop.get("upcoming_trips", {}).get("north") or [{}]
    l_north = (l_stop.get("upcoming_trips") or {}).get("north") or [{}]
    f_trip_keys = _keys(f_north[0])
    f_trip_keys.discard("arrival_offset")
    f_trip_keys.add("estimated_current_stop_arrival_time")
    l_trip_keys = _keys(l_north[0])
    missing_trip = f_trip_keys - l_trip_keys
    if missing_trip:
        problems.append(f"trip entry: fixture keys missing from live: {sorted(missing_trip)}")

    return problems


def cmd_refresh_fixture():
    fixture = load_json(REFERENCE_FIXTURE)
    live = fetch_live_json()
    problems = diff_key_shape(fixture, live)
    if problems:
        print(f"API shape drift detected vs {REFERENCE_FIXTURE}:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK -- live API shape matches {REFERENCE_FIXTURE}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--failures", action="store_true", help="run tools/fixtures/failures/*.json")
    group.add_argument("--live", action="store_true", help="informational check against the real API")
    group.add_argument("--refresh-fixture", action="store_true", help="diff live API key shape vs the fixture")
    group.add_argument("--handler", action="store_true", help="probe search_stations() via a print()-based harness")
    args = parser.parse_args()

    if args.refresh_fixture:
        sys.exit(cmd_refresh_fixture())
    elif args.handler:
        sys.exit(cmd_handler())
    elif args.failures:
        sys.exit(cmd_failures())
    elif args.live:
        sys.exit(cmd_live())
    else:
        sys.exit(cmd_default())


if __name__ == "__main__":
    main()
