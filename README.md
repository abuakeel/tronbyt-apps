# tronbyt-apps

Custom [Pixlet](https://github.com/tronbyt/pixlet) apps for the Tidbyt driven by the
tronbyt server on the grant cluster (see `kubedeploy/apps/tronbyt/`).

Registered with tronbyt as the **user app repo** (Settings -> Repository URL), so
apps here appear in the picker labelled "Git Repository app".

## Layout is dictated by the server

`internal/apps/apps.go:183` scans `<repo>/apps/<name>/` and takes the **first
`*.star`** it finds in each directory.

> **`manifest.yaml` is read on one path and ignored on the other.** This trips people
> up, so be precise about which view you are looking at:
>
> - **The app picker ignores it.** `scanUserAppsDir` (`apps.go:183`) derives ID, Name
>   and PackageName from the **directory name**, Author from your tronbyt username,
>   and hardcodes Summary to "Git Repository app". **The folder name is what shows in
>   the picker**, so name it for humans -- a manifest `name:` will not change it.
> - **The config page DOES read it.** `getAppMetadata` (`helpers.go:514`) falls back to
>   `manifest.yaml` for any app not in the system-apps cache, which is every user-repo
>   app, and `manager/configapp.html` renders `.AppMetadata.Desc` from it.
>
> So `desc:` is **user-facing**. Keep it short and write it for whoever is configuring
> the app. Engineering notes belong in this README.

Optional previews follow a convention: `<starname>.webp` and `<starname>@2x.webp`.

## Render and compare

```bash
pixlet render apps/nyc-subway/nyc-subway.star -o /tmp/out.webp
python3 tools/compare.py /tmp/out.webp
```

`tools/compare.py` diffs against `reference/subway-64x32.png`, a frame recovered
from a screenshot of the original Tidbyt app. Only the **divider** is a truly
static region and must match exactly; the bullet carries the live route's
colour and letter, so it is not static (a different route legitimately next
looks like a "mismatch" that isn't a bug — see `tools/compare.py`'s
`STATIC_REGIONS` comment). Text regions are expected to differ too.

## The real gate: `tools/gate.py`

`compare.py` above is a quick manual spot-check against whatever the live feed
happens to return right now. `tools/gate.py` is the actual pass/fail harness —
it pins *what the "live" data is* via a local mock HTTP server, so results are
deterministic instead of depending on which train is next when you happen to
run it. It never adds a fixture-mode branch to `nyc-subway.star` itself (see the
module docstring for why) — it substitutes the mock server's URL for the real
API host in a tempfile copy of the app before rendering.

```bash
python3 tools/gate.py                 # default: render the pinned reference fixture,
                                       # require the WHOLE 64x32 frame to match
                                       # reference/subway-64x32.png with 0 differing pixels

python3 tools/gate.py --failures      # render every tools/fixtures/failures/*.json case
                                       # (malformed/missing feed data, HTTP errors, stale
                                       # trips, ...); each must render without a Starlark
                                       # error and keep the divider region intact

python3 tools/gate.py --live          # render against the REAL live API; informational
                                       # only (never gates on the whole-frame diff, since
                                       # real destinations/arrivals legitimately differ from
                                       # the reference) -- then cross-checks the mock server
                                       # against a live snapshot and calls --refresh-fixture

python3 tools/gate.py --refresh-fixture   # re-fetch the three live endpoints and diff KEY
                                           # SETS (not values) against the pinned fixture, so
                                           # an API shape change is caught even though no
                                           # other mode exercises the live shape directly

python3 tools/gate.py --handler        # assert search_stations() labelling via a probe app --
                                        # the handler isn't reachable through `pixlet render`
                                        # directly, so this renders a probe that appends its
                                        # own main() calling the handler and printing results
                                        # (Starlark print() reaches stdout as "[<app>.star] <line>")

python3 tools/gate.py --bullets        # assert bullet_form() route-id -> (form, letter)
                                        # classification via the same print()-based probe:
                                        # the six multi-character ids (6X 7X FX express,
                                        # FS GS SI shuttle), representative single-character
                                        # ids, and an unknown-id fallback. Deterministic, no
                                        # live data -- a guard that depends on which trains
                                        # happen to be running is not a guard
```

## Pixlet version matters

Use **v0.53.1 of the tronbyt fork** -- `tronbyt/server` pins
`github.com/tronbyt/pixlet v0.53.1`, so this is what the server renders with.
Prebuilt release binaries need no Go toolchain.

## Failure behaviour

Moved here from `manifest.yaml`'s `desc`, which is user-facing and was being used as
an engineering notebook.

**An HTTP-level feed failure degrades gracefully.** A 4xx/5xx from `api.subwaynow.app`
renders both rows as `NO TRAINS` with a dim bullet. A non-JSON body (a proxy's HTML
error page returned with a 200) is also survivable — `fetch_json` uses
`json.decode(resp.body(), None)` rather than `resp.json()`, which is fatal.

**A WAN or DNS outage is NOT recoverable from app code.** Starlark has no
`try`/`except`, and a transport-level failure inside `http.get()` — DNS resolution,
connection refused, timeout — aborts the whole render with a fatal error before any
app code runs, no matter how defensively `fetch_json` is written. Verified by reading
pixlet's own `runtime/modules/starlarkhttp` and reproducing the fatal error directly.
This is a limitation of every Pixlet app, not something specific to this one.

**But the failure is transient, not sticky** — confirmed by reading `tronbyt/server`'s
source. On a render failure the server sets `EmptyLastRender=true` and rotation skips
the app for that cycle (`rotation.go:217,240,311`), but `LastRender` is updated
regardless, so it retries at the next `UInterval` automatically. A pinned app falls
through to normal rotation without being unpinned (`rotation.go:249`).

`broken` is a **separate, manual, UI-only curation flag** an operator sets by hand; a
failed render never sets it, and no manual re-enable is needed.

Net effect: during an outage the app blinks out of rotation and resumes on its own the
moment the feed is reachable again, with no operator action.
