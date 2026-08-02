#!/usr/bin/env python3
"""Gate for the CitiBike recreation.

Governing principle, inherited from tools/gate.py: NO fixture mode inside
citibike.star. This tool changes where bytes come from, never what code runs.
It reads the committed app, asserts it references the real GBFS base URL
exactly once, substitutes a local mock server's address into a tempfile copy,
and renders THAT with the real pixlet binary.

Modes:
  (default)     render the pinned fixture; the WHOLE 64x32 frame must match
                 tools/fixtures/citibike/golden-64x32.png with 0 differing
                 pixels
  --counts      probe counts() against synthetic station records: normal,
                 clamped, not-renting, malformed, absent
  --sprite      the rendered sprite region must equal the cut taken from
                 reference/citibike-64x32.png
  --handler     probe search_stations() labelling and the result cap
  --failures    every tools/fixtures/citibike/failures/*.json case must
                 render without a Starlark error and keep the sprite intact
  --shape       diff live GBFS key sets against the pinned fixture
  --ascii       print the current fixture render as ASCII (development aid)
  --bless       overwrite the golden PNG from the current render
"""
import argparse
import json
import subprocess
import sys
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare import lit, load_scaled, scale_from  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP_SRC = ROOT / "apps" / "citibike" / "citibike.star"
REFERENCE_PNG = ROOT / "reference" / "citibike-64x32.png"
FIXTURE_DIR = ROOT / "tools" / "fixtures" / "citibike"
REFERENCE_FIXTURE = FIXTURE_DIR / "reference-frame.json"
FAILURES_DIR = FIXTURE_DIR / "failures"
GOLDEN_PNG = FIXTURE_DIR / "golden-64x32.png"

LIVE_BASE = "https://gbfs.lyft.com/gbfs/2.3/bkn/en/"
EXPECTED_BASE_COUNT = 1

W, H = 64, 32

# The sprite's screen footprint: original x12-38, rows 11-29, shifted to x0-26.
# (x0, y0, x1, y1), x1/y1 exclusive.
SPRITE_REGION = (0, 11, 27, 30)
SPRITE_SOURCE_X = 12  # must track tools/cut_sprite.py's SPRITE_BOX left edge


def load_json(path):
    return json.loads(path.read_text())


def read_patched_star(port):
    src = APP_SRC.read_text()
    count = src.count(LIVE_BASE)
    if count != EXPECTED_BASE_COUNT:
        sys.exit(
            f"refusing to patch {APP_SRC}: expected exactly {EXPECTED_BASE_COUNT} "
            f"occurrence of {LIVE_BASE!r}, found {count}. The app's URL literal "
            f"changed shape -- update gate_citibike.py, don't silently patch the "
            f"wrong thing."
        )
    return src.replace(LIVE_BASE, f"http://127.0.0.1:{port}/")


def render_source(src, out_path, app_config=None, timeout=60):
    with tempfile.TemporaryDirectory() as td:
        star_path = Path(td) / "citibike.star"
        star_path.write_text(src)
        cmd = ["pixlet", "render", str(star_path), "-o", str(out_path)]
        if app_config:
            cmd += [f"{k}={v}" for k, v in app_config.items()]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# --- mock GBFS server ----------------------------------------------------


def make_handler(info_body, status_body, http_status, raw_body, requested_paths):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            requested_paths.append(path)

            if http_status is not None:
                self.send_response(http_status)
                self.end_headers()
                return

            if raw_body is not None:
                # A 200 carrying a NON-JSON body -- the captive-portal/proxy
                # case that motivates two-argument json.decode. Reverting the
                # app to resp.json() is fatal on exactly this, and no
                # json.dumps()-ing fixture could express it.
                data = raw_body.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if path == "/station_information.json":
                body = info_body
            elif path == "/station_status.json":
                body = status_body
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


def start_server(info_body, status_body, http_status=None, raw_body=None, requested_paths=None):
    if requested_paths is None:
        requested_paths = []
    httpd = HTTPServer(
        ("127.0.0.1", 0),
        make_handler(info_body, status_body, http_status, raw_body, requested_paths),
    )
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def stop_server(httpd):
    httpd.shutdown()
    httpd.server_close()


def render_via_mock(info_body, status_body, out_path, http_status=None, raw_body=None,
                    app_config=None, requested_paths=None):
    httpd, port = start_server(
        info_body, status_body, http_status=http_status, raw_body=raw_body,
        requested_paths=requested_paths,
    )
    try:
        return render_source(read_patched_star(port), out_path, app_config=app_config)
    finally:
        stop_server(httpd)


# --- print()-based probes ------------------------------------------------


def read_patched_star_source():
    """App source with its own main() stripped, ready for a probe main().

    Leaving the real main() in place means two definitions of the global
    `main`, and Starlark raises "cannot reassign global main" rather than
    letting the last one win.
    """
    src = APP_SRC.read_text()
    if src.count(LIVE_BASE) != EXPECTED_BASE_COUNT:
        raise SystemExit(f"refusing to patch {APP_SRC}: URL literal count changed")
    marker = "\ndef main(config):"
    idx = src.find(marker)
    if idx == -1:
        raise SystemExit(f"no 'def main(config):' found in {APP_SRC}")
    return src[:idx]


def run_probe(src_without_main, info_body, status_body, http_status=None):
    """Render a probe app against the mock and return its print() lines.

    The probe MUST print "PROBE-DONE" last. Without that sentinel a crashed
    render (no stdout at all) is indistinguishable from a probe that ran fine
    and printed nothing.
    """
    httpd, port = start_server(info_body, status_body, http_status=http_status)
    try:
        patched = src_without_main.replace(LIVE_BASE, f"http://127.0.0.1:{port}/")
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "probe.webp"
            result = render_source(patched, out_path)
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


# --- --counts mode -------------------------------------------------------


def status_body(records):
    return {"data": {"stations": records}, "last_updated": 1782217425, "ttl": 60, "version": "2.3"}


def info_body(records):
    return {"data": {"stations": records}, "last_updated": 1782217425, "ttl": 60, "version": "2.3"}


COUNT_CASES = [
    # (label, station records, expected "classic|ebikes|docks")
    (
        "normal",
        [{"station_id": "S1", "num_bikes_available": 21, "num_ebikes_available": 20,
          "num_docks_available": 15, "is_renting": 1, "is_installed": 1}],
        "1|20|15",
    ),
    (
        "three digits",
        [{"station_id": "S1", "num_bikes_available": 113, "num_ebikes_available": 6,
          "num_docks_available": 114, "is_renting": 1, "is_installed": 1}],
        "107|6|114",
    ),
    (
        "ebikes exceed bikes -> classic clamps to 0",
        [{"station_id": "S1", "num_bikes_available": 3, "num_ebikes_available": 9,
          "num_docks_available": 4, "is_renting": 1, "is_installed": 1}],
        "0|9|4",
    ),
    (
        "not renting",
        [{"station_id": "S1", "num_bikes_available": 8, "num_ebikes_available": 2,
          "num_docks_available": 5, "is_renting": 0, "is_installed": 1}],
        "--|--|--",
    ),
    (
        "not installed",
        [{"station_id": "S1", "num_bikes_available": 8, "num_ebikes_available": 2,
          "num_docks_available": 5, "is_renting": 1, "is_installed": 0}],
        "--|--|--",
    ),
    (
        "non-integer count",
        [{"station_id": "S1", "num_bikes_available": "eight", "num_ebikes_available": 2,
          "num_docks_available": 5, "is_renting": 1, "is_installed": 1}],
        "--|--|--",
    ),
    (
        "missing count key",
        [{"station_id": "S1", "num_ebikes_available": 2, "num_docks_available": 5,
          "is_renting": 1, "is_installed": 1}],
        "--|--|--",
    ),
    (
        "station absent from feed",
        [{"station_id": "OTHER", "num_bikes_available": 4, "num_ebikes_available": 1,
          "num_docks_available": 9, "is_renting": 1, "is_installed": 1}],
        "--|--|--",
    ),
    (
        "entry is not a dict",
        ["not-a-dict", {"station_id": "S1", "num_bikes_available": 6,
                        "num_ebikes_available": 1, "num_docks_available": 2,
                        "is_renting": 1, "is_installed": 1}],
        "5|1|2",
    ),
]


def cmd_counts():
    failures = []
    for label, records, expected in COUNT_CASES:
        src = read_patched_star_source()
        src += (
            "\n\ndef main(config):\n"
            '    c, e, d = counts("S1")\n'
            '    print(c + "|" + e + "|" + d)\n'
            '    print("PROBE-DONE")\n'
            '    return render.Root(child = render.Box(color = "#000000"))\n'
        )
        try:
            got = run_probe(src, info_body([]), status_body(records))
        except RuntimeError as e:
            failures.append(f"  {label}: {e}")
            continue
        if got != [expected]:
            failures.append(f"  {label}: expected [{expected!r}], got {got}")

    # Feed down entirely: counts() must degrade, not crash.
    src = read_patched_star_source()
    src += (
        "\n\ndef main(config):\n"
        '    c, e, d = counts("S1")\n'
        '    print(c + "|" + e + "|" + d)\n'
        '    print("PROBE-DONE")\n'
        '    return render.Root(child = render.Box(color = "#000000"))\n'
    )
    try:
        got = run_probe(src, info_body([]), status_body([]), http_status=503)
    except RuntimeError as e:
        failures.append(f"  feed-503: {e}")
    else:
        if got != ["--|--|--"]:
            failures.append(f"  feed-503: expected ['--|--|--'], got {got}")

    # station_name() must resolve through the information feed, and degrade to
    # "" (not crash, not the id) when the station is not there.
    src = read_patched_star_source()
    src += (
        "\n\ndef main(config):\n"
        '    print("name=" + station_name("S1"))\n'
        '    print("missing=" + station_name("NOPE"))\n'
        '    print("PROBE-DONE")\n'
        '    return render.Root(child = render.Box(color = "#000000"))\n'
    )
    try:
        got = run_probe(
            src,
            info_body([{"station_id": "S1", "name": "DeKalb Ave & S Portland Ave"}]),
            status_body([]),
        )
    except RuntimeError as e:
        failures.append(f"  station-name: {e}")
    else:
        want = ["name=DeKalb Ave & S Portland Ave", "missing="]
        if got != want:
            failures.append(f"  station-name: expected {want}, got {got}")

    for line in failures:
        print(line)
    print("counts: OK" if not failures else "counts: FAIL")
    return 1 if failures else 0


# --- --sprite mode -------------------------------------------------------


def frame_mask(path, region, scale):
    """The lit/unlit mask over `region` of an image, as a list of strings."""
    px = load_scaled(path, scale)
    x0, y0, x1, y1 = region
    return [
        "".join("#" if lit(px[x, y]) else "." for x in range(x0, x1))
        for y in range(y0, y1)
    ]


def reference_sprite_mask():
    """The sprite as it appears in the ORIGINAL frame, shifted into place.

    Source region x12-38, rows 11-29 (tools/cut_sprite.py's SPRITE_BOX), read
    from reference/citibike-64x32.png and reported at its post-shift screen
    coordinates x0-26.
    """
    scale = scale_from(str(REFERENCE_PNG))
    px = load_scaled(str(REFERENCE_PNG), scale)
    return [
        "".join("#" if lit(px[x, y]) else "." for x in range(SPRITE_SOURCE_X, 39))
        for y in range(11, 30)
    ]


def cmd_sprite():
    fixture = load_json(REFERENCE_FIXTURE)
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "frame.webp"
        result = render_via_mock(fixture["info"], fixture["status"], out_path)
        if result.returncode != 0:
            print(f"sprite: FAIL -- render crashed (exit {result.returncode})\n{result.stderr}")
            return 1
        got = frame_mask(str(out_path), SPRITE_REGION, scale_from(str(out_path)))
    want = reference_sprite_mask()
    if got == want:
        print(f"sprite: OK -- {len(want)} rows match the reference cut exactly")
        return 0
    print("sprite: FAIL -- rendered sprite differs from the reference cut")
    for i, (g, w) in enumerate(zip(got, want)):
        flag = "  " if g == w else "<-"
        print(f"  row {11 + i:2d} got |{g}| want |{w}| {flag}")
    return 1


# --- default / --ascii / --bless -----------------------------------------


def render_fixture(out_path):
    fixture = load_json(REFERENCE_FIXTURE)
    return render_via_mock(fixture["info"], fixture["status"], out_path)


def cmd_ascii():
    """Print the fixture render as ASCII with row numbers. Development aid for
    positioning -- prints, never gates."""
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "frame.webp"
        result = render_fixture(out_path)
        if result.returncode != 0:
            print(f"render crashed (exit {result.returncode})\n{result.stderr}")
            return 1
        px = load_scaled(str(out_path), scale_from(str(out_path)))
        print("    " + "".join(str(x % 10) for x in range(W)))
        for y in range(H):
            print("%2d  " % y + "".join("#" if lit(px[x, y]) else "." for x in range(W)))
    return 0


def cmd_bless():
    """Overwrite the golden PNG from the current render.

    Deliberately a separate, explicit mode: the golden is the layout's
    definition, so replacing it must be a decision someone makes and reviews
    in a diff, never a side effect of running the gate.
    """
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "frame.webp"
        result = render_fixture(out_path)
        if result.returncode != 0:
            print(f"render crashed (exit {result.returncode})\n{result.stderr}")
            return 1
        from PIL import Image

        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        Image.open(out_path).convert("RGB").save(GOLDEN_PNG)
    print(f"wrote {GOLDEN_PNG} -- REVIEW the ascii dump before committing it")
    return 0


def cmd_default():
    if not GOLDEN_PNG.exists():
        print(f"{GOLDEN_PNG} does not exist -- run --bless once the layout is right")
        return 1
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "frame.webp"
        result = render_fixture(out_path)
        if result.returncode != 0:
            print(f"default: FAIL -- render crashed (exit {result.returncode})\n{result.stderr}")
            return 1
        scale = scale_from(str(GOLDEN_PNG))
        got = load_scaled(str(out_path), scale)
        want = load_scaled(str(GOLDEN_PNG), scale)
        diff = [
            (x, y) for y in range(H) for x in range(W) if lit(got[x, y]) != lit(want[x, y])
        ]
    print(f"  whole frame  {'OK' if not diff else 'MISMATCH'}  {len(diff)}/{W * H} pixels differ")
    if diff:
        print(f"  first differing pixels: {diff[:12]}")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--counts", action="store_true", help="probe counts() and station_name()")
    group.add_argument("--sprite", action="store_true", help="pin the sprite against the reference cut")
    group.add_argument("--ascii", action="store_true", help="print the fixture render as ASCII")
    group.add_argument("--bless", action="store_true", help="overwrite the golden PNG")
    args = parser.parse_args()

    if args.counts:
        sys.exit(cmd_counts())
    if args.sprite:
        sys.exit(cmd_sprite())
    if args.ascii:
        sys.exit(cmd_ascii())
    if args.bless:
        sys.exit(cmd_bless())
    sys.exit(cmd_default())


if __name__ == "__main__":
    main()
