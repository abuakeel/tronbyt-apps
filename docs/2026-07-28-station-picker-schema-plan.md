# Station Picker Schema — Implementation Plan

> **STATUS: EXECUTED / SUPERSEDED (2026-07-29).** This plan shipped across commits `45623e7`
> (Task 1), `fc1b247` (Task 2), and `917d082` (a subsequent hardening commit) on branch `testing`.
> It is kept as a historical record of what was proposed and built, NOT as a live spec -- a final
> whole-branch review before hardware shipment found several things below don't match (or never
> matched) the shipped code, and this note is deliberately NOT rewriting the steps to pretend
> otherwise:
>
> - **Task 2 Step 3's `station_label` joins route keys with `"".join(...)`** below -- e.g.
>   `"(DNR)"`. That shipped initially, but a final review found it unreadable (can't tell `"DNR"`
>   apart into route letters) and, separately, sourced from the wrong field (see next point). The
>   shipped `station_label` uses `"/".join(...)` on `scheduled_routes` (falling back to `routes`,
>   then `[id]`) -- e.g. `"(D/N/R)"`. See `docs/2026-07-28-station-picker-schema-design.md`'s
>   "What the data says" correction for why `routes` (used below) was wrong on its own terms: live
>   sampling found real duplicate labels between different stations.
> - **Task 1 Step 3 ("expect the four new cases to FAIL") is self-contradictory with its own next
>   sentence**, which says the cases pass *vacuously* at that stage -- i.e. the gate reports OK,
>   not FAIL. Read "FAIL" there as "this doesn't prove anything yet", not literally a red gate.
> - **Task 2 Step 1's `read_patched_star_source` docstring below says "the last one silently
>   wins"** if `main()` isn't stripped. That's wrong for Starlark: redefining a global raises
>   `"cannot reassign global main"` -- fatal, not a silent overwrite. The shipped docstring in
>   `tools/gate.py` says so correctly.
> - **The backward-compatibility claim this plan's Task 1 Step 5 makes** ("The default gate
>   passing proves backward compatibility") turned out to be incomplete: the default gate only
>   proved the render didn't crash with no config, not that the app actually requested the correct
>   (default) stop id from the API -- a mock-server permissiveness gap a final review caught and
>   fixed. See the final-review fix report referenced below.
>
> For current, accurate behavior read `apps/nyc-subway/nyc-subway.star` and `tools/gate.py`
> directly, the (corrected) design doc, and
> `.superpowers/sdd/2026-07-28-station-picker-schema-plan/final-review-fix-report.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a typeahead station picker so `nyc-subway` can be installed twice on one device — one instance per station — and rotate between them.

**Architecture:** One new schema function and one search handler, plus a JSON decode absorbed entirely inside the existing `get_settings()` seam. The fetch and render layers are untouched, so the pixel-exact gate stays green. The handler is tested via a probe app whose `print()` output the harness captures.

**Tech Stack:** Pixlet v0.53.1 (tronbyt fork), Starlark, Python 3 (gate harness).

**Approved spec:** `docs/2026-07-28-station-picker-schema-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Data source stays KEYLESS.** Never add an API key or cloud dependency.
- **The rendering layer must not change.** `render_row`, `render_app` and every colour/font constant stay exactly as they are. The app currently matches the reference at **0/2048** and must continue to.
- **`get_settings()` is the ONLY place that reads station config.** Nothing else may reference `DEFAULT_STOP_ID` or `DEFAULT_STATION_JSON`.
- **`json.decode` MUST use its two-argument form.** `json.decode(raw)` is **fatal** on malformed input and Starlark has no `try`/`except` — a corrupt config blob would kill every render permanently. `json.decode(raw, None)` returns the default instead. Verified against pixlet v0.53.1.
- **The existing installed instance must keep working with no reconfiguration** — it has no stored config, so the default must resolve to `G35`.
- Use `pixlet` from PATH (v0.53.1). Never `go install` another version.
- `reference/subway-64x32.png` is the source of truth; never hand-edit it.
- Single `.star` at `apps/nyc-subway/nyc-subway.star`.
- Branch `testing`; push `main` for canonical.

## File Structure

| File | Change |
|---|---|
| `apps/nyc-subway/nyc-subway.star` | Add `get_schema()` + `search_stations()`; rewrite `get_settings()` to decode JSON |
| `tools/gate.py` | Let the mock renderer pass app config; add a `--handler` mode |
| `tools/fixtures/failures/*.json` | Four new malformed-config cases |

---

### Task 1: Config seam accepts the typeahead JSON blob

Deliverable: `get_settings()` reads a typeahead config blob and falls back safely, with the gate still at 0/2048 and malformed blobs proven non-fatal.

**Files:**
- Modify: `apps/nyc-subway/nyc-subway.star` (`get_settings`, ~line 110)
- Modify: `tools/gate.py` (`render_source`, `render_via_mock`, `run_one_failure_case`)
- Create: `tools/fixtures/failures/config-not-json.json`, `config-not-dict.json`, `config-missing-value.json`, `config-empty-value.json`

**Interfaces:**
- Consumes: existing `render_via_mock(routes_body, stops_body, stop_template, out_path, http_status=None)`.
- Produces: `render_via_mock(..., app_config=None)` where `app_config` is a dict of `key=value` strings passed to pixlet; fixture files may carry a `"config"` object. Task 2 uses `app_config` for its probe.

- [ ] **Step 1: Let the harness pass app config**

In `tools/gate.py`, thread an optional config through. Pixlet takes config as trailing `key=value` CLI args.

In `render_source(...)`, add an `app_config=None` parameter and extend the argv:

```python
        cmd = [pixlet, "render", str(star_path), "-o", str(out_path)]
        if app_config:
            cmd += [f"{k}={v}" for k, v in app_config.items()]
        return subprocess.run(
            cmd,
```

In `render_via_mock`, add the same parameter and forward it:

```python
def render_via_mock(routes_body, stops_body, stop_template, out_path, http_status=None, app_config=None):
    httpd, port = start_server(routes_body, stops_body, stop_template, http_status=http_status)
    try:
        patched = read_patched_star(port)
        return render_source(patched, out_path, app_config=app_config)
    finally:
        stop_server(httpd)
```

In `run_one_failure_case`, read an optional `config` key from the fixture and pass it:

```python
    app_config = case.get("config")
```

and add `app_config=app_config` to its `render_via_mock(...)` call.

- [ ] **Step 2: Add the four malformed-config fixtures**

Each reuses the default routes/stops and a valid `stop` body, so the ONLY thing under test is the config blob. Create `tools/fixtures/failures/config-not-json.json`:

```json
{
  "_note": "A config blob that is not JSON at all. json.decode's two-argument form must return the default rather than raising -- the one-argument form is fatal and Starlark cannot catch it.",
  "config": {"station": "this is not json"},
  "stop": {"id": "G35", "upcoming_trips": {
    "north": [{"route_id": "G", "destination_stop": "F27", "arrival_offset": 30}],
    "south": [{"route_id": "G", "destination_stop": "G21", "arrival_offset": 30}]}}
}
```

`config-not-dict.json` — same but `"config": {"station": "[1,2,3]"}` and a `_note` saying valid JSON of the wrong type must fall back.

`config-missing-value.json` — `"config": {"station": "{\"display\":\"Somewhere\"}"}`, `_note`: the `value` key is absent.

`config-empty-value.json` — `"config": {"station": "{\"display\":\"Somewhere\",\"value\":\"\"}"}`, `_note`: an empty string must not become the stop ID.

- [ ] **Step 3: Run the failure matrix — expect the four new cases to FAIL**

```bash
cd ~/workspace/tronbyt-apps
python3 tools/gate.py --failures
```

Expected: the four `config-*` cases FAIL. `get_settings` still calls `config.str("stop_id", ...)`, so it ignores the `station` key entirely — the app renders G35 and the cases pass *vacuously*. **If they pass at this step, the fixtures are not exercising anything** — check that `app_config` is actually reaching pixlet before continuing.

To confirm the plumbing works at all, verify config reaches the app:

```bash
pixlet render apps/nyc-subway/nyc-subway.star stop_id=A44 -o /tmp/cfgprobe.webp
```

That should render A-train data (blue bullets), proving `config.str` receives CLI config today.

- [ ] **Step 4: Rewrite `get_settings` to decode the blob**

Add `load("encoding/json.star", "json")` to the loads at the top of the file if absent.

Replace `get_settings` (and the `DEFAULT_STOP_ID` block above it) with:

```starlark
DEFAULT_STOP_ID = "G35"  # Clinton - Washington Avs (G)
DEFAULT_STATION_JSON = '{"display": "Clinton - Washington Avs (G)", "value": "G35"}'
DEFAULT_DIRECTIONS = ["north", "south"]

def get_settings(config):
    """The ONE place station config is read. Adding fields here is contained;
    nothing downstream knows where the stop id came from."""
    stop_id = DEFAULT_STOP_ID
    raw = config.get("station", DEFAULT_STATION_JSON)

    # TWO-ARGUMENT form is load-bearing. json.decode(raw) with one argument is
    # FATAL on malformed input, and Starlark has no try/except -- a corrupt
    # config blob would kill every render with no way to recover. The second
    # argument is returned instead of raising.
    decoded = json.decode(raw, None)

    if type(decoded) == "dict":
        value = decoded.get("value")
        if type(value) == "string" and value:
            stop_id = value

    return {"stop_id": stop_id, "directions": DEFAULT_DIRECTIONS}
```

- [ ] **Step 5: Verify all gates**

```bash
cd ~/workspace/tronbyt-apps
python3 tools/gate.py                 # divider 0/64, whole frame 0/2048, exit 0
python3 tools/gate.py --failures      # ALL cases OK including the four config-* ones
python3 tools/gate.py --live          # exit 0
grep -c DEFAULT_STOP_ID apps/nyc-subway/nyc-subway.star       # must be 2
grep -c DEFAULT_STATION_JSON apps/nyc-subway/nyc-subway.star  # must be 2
```

The default gate passing proves backward compatibility: it renders with no config, so an unconfigured install still resolves to G35.

- [ ] **Step 6: Prove a configured station actually changes the render**

```bash
cd ~/workspace/tronbyt-apps
pixlet render apps/nyc-subway/nyc-subway.star \
  station='{"display":"Clinton - Washington Avs (A)","value":"A44"}' -o /tmp/a44.webp
pixlet render apps/nyc-subway/nyc-subway.star -o /tmp/g35.webp
python3 -c "
from PIL import Image
a=Image.open('/tmp/a44.webp').convert('RGB'); g=Image.open('/tmp/g35.webp').convert('RGB')
d=sum(1 for y in range(32) for x in range(64) if a.load()[x,y]!=g.load()[x,y])
print(f'A44 vs G35: {d}/2048 pixels differ')
print('PASS -- config changes the render' if d>0 else 'FAIL -- config had no effect')
"
```

Expected: a substantial difference (different route letters, colours and destinations).

- [ ] **Step 7: Commit**

```bash
cd ~/workspace/tronbyt-apps
git add apps/nyc-subway/nyc-subway.star tools/gate.py tools/fixtures/failures/
git commit -m "feat(nyc-subway): config seam accepts the typeahead JSON blob

Typeahead hands back {display, value}, not a plain string, so get_settings now
decodes it. Everything downstream is untouched -- that is what the seam was for.

json.decode uses its TWO-ARGUMENT form deliberately: the one-argument version is
fatal on malformed input and Starlark has no try/except, so a corrupt config blob
would kill every render permanently. Four fixtures cover not-JSON, wrong-type,
missing value and empty value.

An unconfigured install still resolves to G35, so the running instance is
unaffected -- proved by the default gate still scoring 0/2048."
```

---

### Task 2: Typeahead schema and search handler

Deliverable: the picker is selectable in tronbyt's UI, returns correctly-labelled options, and is proven to disambiguate identically-named stations.

**Files:**
- Modify: `apps/nyc-subway/nyc-subway.star` (add `get_schema`, `search_stations`)
- Modify: `tools/gate.py` (add `--handler` mode)

**Interfaces:**
- Consumes: `render_via_mock(..., app_config=None)` from Task 1; the existing `fetch_json(url, ttl)` and `STOPS_URL`.
- Produces: `get_schema()` returning a `schema.Schema`; `search_stations(pattern)` returning a list of `schema.Option`.

- [ ] **Step 1: Add the `--handler` gate mode**

The handler is not reachable through `pixlet render`, but Starlark `print()` reaches stdout as `[<app>.star] <line>` (verified against pixlet v0.53.1). So the harness renders a **probe** app that calls the handler and prints its results.

In `tools/gate.py`, add:

```python
def cmd_handler():
    """Assert search_stations() labelling via a probe app that prints results.

    The handler cannot be invoked through `pixlet render` directly, so the probe
    appends a main() that calls it and prints one line per option. Starlark
    print() reaches stdout prefixed with "[<app>.star] ".
    """
    fixture = load_json(REFERENCE_FIXTURE)
    stops_body = {"stops": [
        {"id": "G35", "name": "Clinton - Washington Avs", "routes": {"G": ["north", "south"]}},
        {"id": "A44", "name": "Clinton - Washington Avs", "routes": {"A": ["north", "south"]}},
        {"id": "X01", "name": "Routeless Test Stop"},
    ]}
    checks = [
        ("clinton", ["Clinton - Washington Avs (A)|A44",
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
            "    return render.Root(child = render.Box(color = \"#000000\"))\n"
        )
        got = run_probe(src, stops_body)
        if sorted(got) != sorted(expected):
            failures.append(f"  {pattern!r}: expected {expected}, got {got}")

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

    for line in failures:
        print(line)
    print("handler: OK" if not failures else "handler: FAIL")
    return 1 if failures else 0
```

Add the two helpers it depends on:

```python
def read_patched_star_source():
    """URL-patched app source with its own main() stripped off.

    The probe appends its own main(); leaving the real one in place would mean
    two definitions, and the last one silently wins. Stripping is explicit.
    """
    src = APP_STAR.read_text()
    if src.count(LIVE_HOST) != 2:
        raise SystemExit(
            f"expected exactly 2 occurrences of {LIVE_HOST} in {APP_STAR}, "
            f"found {src.count(LIVE_HOST)} -- refusing to patch"
        )
    marker = "\ndef main(config):"
    idx = src.find(marker)
    if idx == -1:
        raise SystemExit(f"no 'def main(config):' found in {APP_STAR}")
    return src[:idx]


def run_probe(src_without_main, stops_body):
    """Render a probe app against the mock and return its print() lines.

    Starlark print() reaches stdout as '[<app>.star] <line>'; the prefix is
    stripped so callers compare against plain strings.
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
            return lines
    finally:
        stop_server(httpd)
```

`render_source_path(star_path, out_path)` runs `pixlet render` on an existing file and returns the `CompletedProcess` — factor it out of the existing `render_source` if that function writes its own temp file, so both share one invocation path.

Note `read_patched_star_source` patches the URL itself rather than calling the existing `read_patched_star`, because the probe needs the source *as text* to append to. Keep the same "exactly 2 occurrences" assertion so a changed URL literal still fails loudly.

Register `--handler` in the argparse mutually-exclusive group alongside the existing modes.

- [ ] **Step 2: Run it — expect failure**

```bash
cd ~/workspace/tronbyt-apps
python3 tools/gate.py --handler
```

Expected: FAIL — `search_stations` does not exist yet, so `pixlet render` errors on an undefined name. This confirms the probe actually executes the handler rather than silently passing.

- [ ] **Step 3: Add the schema and handler**

Add `load("schema.star", "schema")` to the loads. Then, above `get_settings`:

```starlark
MAX_SEARCH_RESULTS = 20

def station_label(stop):
    """'<name> (<routes>)', e.g. 'Clinton - Washington Avs (G)'.

    Route letters are NOT decoration: 75 of the API's 496 stop names are shared
    by two or more stops ('7 Av' is three different stations), so a name-only
    label is ambiguous. Stops with no routes fall back to the stop id for the
    same reason.
    """
    routes = stop.get("routes")
    if type(routes) == "dict" and len(routes) > 0:
        return stop["name"] + " (" + "".join(sorted(routes.keys())) + ")"
    return stop["name"] + " [" + stop["id"] + "]"

def search_stations(pattern):
    """Typeahead handler. Returns at most MAX_SEARCH_RESULTS options.

    Must never raise -- a failed fetch yields an empty result list, which the
    picker shows as 'no matches'.
    """
    data = fetch_json(STOPS_URL, 86400)
    if data == None:
        return []

    needle = pattern.lower()
    out = []
    for stop in data.get("stops", []):
        if type(stop) != "dict":
            continue
        name = stop.get("name")
        stop_id = stop.get("id")
        if type(name) != "string" or type(stop_id) != "string":
            continue
        if needle in name.lower():
            out.append(schema.Option(display = station_label(stop), value = stop_id))
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
                desc = "Subway station to show arrivals for.",
                icon = "train",
                handler = search_stations,
            ),
        ],
    )
```

- [ ] **Step 4: Run the handler gate — expect PASS**

```bash
cd ~/workspace/tronbyt-apps
python3 tools/gate.py --handler
```

Expected: `handler: OK`. This proves the two identically-named Clinton stations get distinct `(A)` / `(G)` labels, the routeless stop falls back to `[X01]`, and a non-matching search returns nothing.

- [ ] **Step 5: Verify the result cap against real data**

```bash
cd ~/workspace/tronbyt-apps
cat > /tmp/capprobe.star <<'EOF'
load("render.star", "render")
load("http.star", "http")
load("schema.star", "schema")
EOF
python3 - <<'PY'
import re, pathlib
src = pathlib.Path("apps/nyc-subway/nyc-subway.star").read_text()
src = src[:src.index("def main(config):")]
src += ('\ndef main(config):\n'
        '    print("count=" + str(len(search_stations("a"))))\n'
        '    return render.Root(child = render.Box(color = "#000000"))\n')
pathlib.Path("/tmp/capprobe.star").write_text(src)
PY
pixlet render /tmp/capprobe.star -o /tmp/cap.webp 2>/dev/null | grep count
```

Expected: `count=20`. The live API returns 303 matches for `"a"`; anything other than 20 means the cap is not applied.

- [ ] **Step 6: Confirm the schema is well-formed and nothing regressed**

```bash
cd ~/workspace/tronbyt-apps
pixlet render apps/nyc-subway/nyc-subway.star -o /tmp/sanity.webp   # must succeed
python3 tools/gate.py                 # 0/2048, exit 0
python3 tools/gate.py --failures      # all cases OK
python3 tools/gate.py --handler       # handler: OK
python3 tools/gate.py --live          # exit 0
```

A malformed `get_schema()` breaks rendering, so a successful render plus a green default gate is the check that matters.

- [ ] **Step 7: Update the docs**

In `README.md`, add a line to the gate section documenting `--handler` alongside the existing modes.

In `apps/nyc-subway/manifest.yaml`, update `desc` to note the app is station-configurable and can be installed more than once, one per station.

- [ ] **Step 8: Commit**

```bash
cd ~/workspace/tronbyt-apps
git add apps/nyc-subway/nyc-subway.star apps/nyc-subway/manifest.yaml tools/gate.py README.md
git commit -m "feat(nyc-subway): typeahead station picker

Adds get_schema() with a single Typeahead field and a search_stations handler,
so the app can be installed once per station and rotate between them.

Labels are '<name> (<routes>)' matching the original Tidbyt app. The route
letters are required, not decoration: 75 of the API's 496 stop names are shared
by 2+ stops. Routeless stops fall back to '<name> [<id>]'. Results cap at 20
because a search for 'a' matches 303 stops.

Handlers are not reachable through pixlet render, so gate.py gains a --handler
mode that drives a probe app and captures its print() output -- proving the two
identically-named Clinton - Washington Avs stations get distinct (A)/(G) labels."
```

---

## Self-review notes

- **Backward compatibility** is enforced by the default gate: it renders with no config and must stay at 0/2048, which can only happen if an unconfigured install still resolves to `G35`.
- **The seam invariant** is checked explicitly in Task 1 Step 5 — `DEFAULT_STOP_ID` and `DEFAULT_STATION_JSON` at exactly 2 occurrences each.
- **Both tasks have inverted first gates** (Task 1 Step 3, Task 2 Step 2) so a test that passes vacuously is caught before the implementation lands.
- **No rendering change**, so the pixel-exact match is preserved by construction rather than by re-verification alone.
