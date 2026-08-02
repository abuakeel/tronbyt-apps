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
>   app, populating the whole `Manifest` struct -- `manager/configapp.html` renders
>   `.AppMetadata.Desc`, `.AppMetadata.Summary`, and `.AppMetadata.RecommendedInterval`
>   from it.
>
> So `desc:` **and** `summary:` are **user-facing on the config page** -- only the
> *picker* hardcodes Summary to "Git Repository app". Keep them short and write them for
> whoever is configuring the app. Engineering notes belong in this README.

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

python3 tools/gate.py --bullets        # assert bullet_form() route-id -> (form, letter, font)
                                        # classification via the same print()-based probe:
                                        # the six multi-character ids (6X 7X FX express,
                                        # FS GS SI shuttle), representative single-character
                                        # ids, and an unknown-id fallback -- PLUS a pixel-level
                                        # render check that pins an actual rendered bullet's
                                        # pixels, so a broken connection between bullet_form()
                                        # and the renderer can't hide behind an all-green
                                        # classification probe. Deterministic, no live data --
                                        # a guard that depends on which trains happen to be
                                        # running is not a guard
```

## CitiBike: `tools/gate_citibike.py`

A sibling of `tools/gate.py` (which is **subway-only** — its constants, mock
routes and bullet regions are all `nyc-subway`-specific). Same governing
principle: no fixture branch inside the app; the harness substitutes a local
mock GBFS server's URL into a tempfile copy and renders that. The two share
only `tools/compare.py`'s pixel primitives.

```bash
python3 tools/gate_citibike.py             # whole 64x32 frame must match
                                            # tools/fixtures/citibike/golden-64x32.png
                                            # with 0 differing pixels
python3 tools/gate_citibike.py --sprite    # the rendered bike must equal the cut
                                            # taken from reference/citibike-64x32.png,
                                            # so the embedded base64 art cannot drift
python3 tools/gate_citibike.py --counts    # probe counts()/station_name() against
                                            # synthetic records: the classic-bike
                                            # subtraction and its clamp, not-renting,
                                            # malformed, absent, feed down
python3 tools/gate_citibike.py --handler   # probe search_stations(): labelling,
                                            # duplicate-name disambiguation, the
                                            # 20-result cap, the real 2463-station
                                            # feed -- PLUS `pixlet schema`, the same
                                            # call the server makes to build the config
                                            # page (nothing else reaches get_schema(),
                                            # so a typo'd field id would otherwise
                                            # surface only as a broken config page)
python3 tools/gate_citibike.py --failures  # every fixtures/citibike/failures/*.json
                                            # case must render and keep the sprite intact
python3 tools/gate_citibike.py --shape     # diff live GBFS key sets vs the fixture
python3 tools/gate_citibike.py --ascii     # print the fixture render (development aid)
python3 tools/gate_citibike.py --bless     # overwrite the golden PNG -- deliberate,
                                            # never a side effect of running the gate
```

**The golden PNG is not the reference.** `reference/citibike-64x32.png` is the
recovered ORIGINAL Tidbyt frame and can never match this app: the original has
two numbers, this has three. `tools/fixtures/citibike/golden-64x32.png` is the
new layout's own pinned render. The original's authority survives where it
still applies — the sprite, the bolt, the colours and the fonts all trace back
to it, and `--sprite` enforces that.

**Deliberate divergences from the original:**

- Three numbers instead of two: **classic** bikes, **e-bikes**, **open docks**.
  GBFS's `num_bikes_available` includes e-bikes, so classic is derived by
  subtraction and clamped at 0.
- The bike sprite is shifted 12px left, so the rear wheel runs off the panel's
  left edge and the seat, frame, handlebars and front wheel all stay. The cut
  lands at the frame boundary on purpose: a shape cut there reads as continuing
  past the panel, where the same cut mid-frame would read as a rendering bug.
  Cutting clear of both wheels is only possible in the x18-24 tube band, which
  leaves 15-21px of bike against a 27px dead gap -- tried, and rejected on
  review of the rendered frame.

**Art is cut, not drawn.** `tools/cut_sprite.py --emit` regenerates the two
base64 constants from the reference frame. Never hand-edit them, and never
hand-edit `reference/citibike-64x32.png` -- regenerate it with
`tools/regenerate_citibike_reference.py` (`--check` verifies the committed PNG
round-trips, and six landmark pixels guard the LED grid fit itself).

The **dock icon is the exception**: it is new art with no original to cut from,
so it is drawn from `render.Box` rows in `DOCK_GLYPH`, where it stays
reviewable in a diff instead of hidden inside a base64 blob.

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

**CitiBike degrades the same way**, and for the same reason: an unreachable or
malformed GBFS feed, a station missing from it, or a station that is not renting all
render the full layout — sprite, icons, station name — with `--` in place of each of
the three numbers. All of it is pinned by `tools/gate_citibike.py --failures`.

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
