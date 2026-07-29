# tronbyt-apps

Custom [Pixlet](https://github.com/tronbyt/pixlet) apps for the Tidbyt driven by the
tronbyt server on the grant cluster (see `kubedeploy/apps/tronbyt/`).

Registered with tronbyt as the **user app repo** (Settings -> Repository URL), so
apps here appear in the picker labelled "Git Repository app".

## Layout is dictated by the server

`internal/apps/apps.go:183` scans `<repo>/apps/<name>/` and takes the **first
`*.star`** it finds in each directory.

> **`manifest.yaml` is IGNORED for user-repo apps.** Metadata is derived from the
> directory name -- ID, Name and PackageName all equal it, Author becomes your
> tronbyt username, Summary is hardcoded to "Git Repository app". **The folder
> name is what shows in the picker**, so name it for humans. Manifests here are
> documentation only.

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
```

## Pixlet version matters

Use **v0.53.1 of the tronbyt fork** -- `tronbyt/server` pins
`github.com/tronbyt/pixlet v0.53.1`, so this is what the server renders with.
Prebuilt release binaries need no Go toolchain.
