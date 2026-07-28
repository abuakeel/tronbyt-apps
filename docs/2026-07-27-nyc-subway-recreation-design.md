# Recreating Tidbyt's NYC Subway app — design

**Date:** 2026-07-27
**Goal:** A faithful recreation of Tidbyt's closed-source **NYC Subway** app as a Pixlet `.star` app
for the tronbyt server on grant.

**Scope: Subway only.** CitiBike is deferred to its own spec → plan → implementation cycle. The two
apps are independent, and the CitiBike bike sprite is the larger unknown, so doing Subway first
derisks the shared parts (repo layout, delivery, dev loop) before taking that on.

> **This work does not belong in `kubedeploy`.** It is Starlark app code, not cluster manifests.
> It lives in a new repo — see [Repository](#repository-workspacetronbyt-apps).

## Background

The tronbyt deployment (`kubedeploy/apps/tronbyt/`) is live and the Tidbyt is polling it. The
bundled catalogue does not contain the app actually wanted, and the original cannot be obtained.

### The source is unobtainable — search exhausted 2026-07-27

| Avenue | Result |
|---|---|
| `tidbyt` GitHub org (32 repos) | No apps repo. Only `community`, `pixlet`, `hdk` |
| `tidbyt/community` current manifests | 4 Tidbyt-authored apps: Better On Call, Retrograde Planet, Yule Log, Zapier |
| `tidbyt/community` full history (2566 commits) | 23 apps ever removed; the only transit ones were 2 renames |
| `tronbyt/apps` (1041 apps, superset of community) | Same 4, plus one *recreation* (`timeuntil`) |
| `pixlet` repo | No bundled apps, only doc examples |
| GitHub-wide repo search | No archive or mirror |
| `api.tidbyt.com/v0/apps` | **App exists**: `nyc-subway`, `developer: "Tidbyt"`, `private: false` |
| `/v0/apps/nyc-subway/{source,star,manifest,preview,render,schema}` | All **404** |

Pixlet's own source settles it: every `/v0/apps/{id}/*` route it knows is `deploy`, `versions`, or
`logs` — authenticated **write** paths for uploading your own private app. Tidbyt's API is
deploy-only; apps execute server-side and are never downloadable. Recreation is the only path.

### The reference frame was recovered exactly

`~/Downloads/subway.png` is a 64×32 LED panel captured at ~17× scale. Cropping the panel
(rows 179–732, cols 74–1131) and box-downsampling to 64×32 recovers **the original frame
pixel-for-pixel**; normalising brightness (the box filter blends each LED with the dark gaps
around it, so max channel ≈ 57) makes it directly comparable to pixlet output.

Artifacts: `subway-64x32.png`, `subway-bright.png` in the scratchpad.

> **The text is mid-scroll in the reference.** The app marquees right-to-left, so `CHURCH A.` and
> `QUEENS` are truncation artifacts of `Church Av` and a Queens-bound terminus — not fixed layout.
> Only **static** elements (bullet, divider, positions, colours) are exact-fidelity targets.

## Goals

1. Visually indistinguishable from the original at 64×32, as far as Pixlet's font set allows.
2. Keyless, cloud-free data — consistent with the point of the tronbyt deployment.
3. **Adding a station-picker schema later must be a small, contained change** (see
   [Configuration seam](#configuration-seam)).

## Non-goals

- **No config schema now.** Hardcoded to one station.
- CitiBike — separate cycle.
- Not offline-capable: real-time transit data requires WAN by nature.

## Repository: `~/workspace/tronbyt-apps`

A new git repo, peer to `kubedeploy` and `pikube`. Follows the established workflow: work on
`testing`, push `main` for canonical, GitHub auth via a per-repo deploy key (not `gh`).

**The layout is dictated by the server**, verified in `internal/apps/apps.go:183`:

```
tronbyt-apps/
├── apps/
│   └── nycsubway/
│       ├── nycsubway.star          <- first *.star found in the dir wins
│       ├── nycsubway.webp          <- optional preview (convention)
│       └── nycsubway@2x.webp       <- optional 2x preview
├── tools/
│   └── compare.py                  <- render + pixel-diff harness
├── reference/
│   ├── subway-64x32.png            <- recovered reference frame
│   └── subway.png                  <- original screenshot
└── README.md
```

The server clones this to `data/users/<username>/repo` and scans `<repo>/apps/*/`.

> **User-repo apps ignore `manifest.yaml` completely.** Unlike system apps, metadata is derived
> from the **directory name** — ID, Name and PackageName all equal it, Author becomes the tronbyt
> username, and Summary is hardcoded to "Git Repository app". **The folder name is what shows in
> the app picker**, so name it for humans. A `manifest.yaml` may be included for documentation, but
> the server will not read it.

## Data source: `api.subwaynow.app` (keyless)

The same source the `goodservice` community app uses. No API key, no registration.

| Endpoint | Purpose |
|---|---|
| `GET /stops/` | All stops (197 KB); resolves `destination_stop` IDs to names |
| `GET /stops/{id}?agent=tidbyt` | `upcoming_trips` keyed `north`/`south` |
| `GET /routes/` | Official MTA route colours — `G` → `#6cbe45` |

Each trip carries `route_id`, `destination_stop`, `estimated_current_stop_arrival_time` (unix), and
`is_delayed`.

Live check of `G35` (**Clinton - Washington Avs**, G-only, `routes: {'G': ['north','south']}`):

```
north: G -> Court Sq    6.8 min
south: G -> Church Av   5.4 min
```

Consistent with the reference frame.

## Configuration seam

Hardcoded now, but **schema-ready by construction**. All station-dependent values are read through
a single accessor rather than scattered as constants:

```starlark
DEFAULT_STOP_ID = "G35"          # Clinton - Washington Avs
DEFAULT_DIRECTIONS = ["north", "south"]

def get_settings(config):
    return {
        "stop_id": config.str("stop_id", DEFAULT_STOP_ID),
        "directions": DEFAULT_DIRECTIONS,
    }
```

`config.str(...)` already falls back to the default when nothing is set, so this behaves exactly
like a hardcoded app today. **Adding a picker later means adding a `get_schema()` and a station
search handler — no change to render or fetch code.** That is the whole point of routing every
lookup through `get_settings`.

Nothing else in the app may reference `DEFAULT_STOP_ID` directly.

## Layout

From the recovered frame. Two 16px rows, full-width divider at y=15.

```
rows  1-14 : train 1 (north)
row     15 : divider, full width
rows 17-30 : train 2 (south)

per row:  bullet  x3-13   11px filled circle, route colour, white letter centred
          dest    x16+    UPPERCASE, white, ~6px font, marquee right-to-left
          arrival x16+    orange, 4px font, below dest: "now" under 1 min, else minutes
```

Bullet colour comes from `/routes/`, not a hardcoded table, so any route renders correctly if the
station configuration ever changes to one serving multiple lines.

## Development loop — objective fidelity measurement

**pixlet v0.53.1** is installed at `scratchpad/pixlet-bin/pixlet` (prebuilt `linux-amd64` release,
sha256 `8585ae29652bec004c31c1c5af2d9aa682ae86a87e037db6597a86e52fa2cfac`).

> **The tronbyt fork, deliberately.** `tronbyt/server` pins `github.com/tronbyt/pixlet v0.53.1` in
> its `go.mod`, so this exact version guarantees local renders match what the server produces.
> `tidbyt/pixlet` would risk divergence. No Go toolchain or `libwebp-dev` needed — the release
> binary is self-contained.

`tools/compare.py` implements the loop:

1. `pixlet render apps/nycsubway/nycsubway.star -o /tmp/out.webp`
2. Pillow reads the webp (verified) and converts to RGB
3. Pixel-diff against `reference/subway-64x32.png`, reporting per-region differences

This makes fidelity measurable rather than a judgement call.

## Delivery

The repo is registered as the tronbyt **user app repo** (Settings → Repository URL →
`POST /set_user_repo`). Apps appear in the picker labelled "Git Repository app";
`refresh_user_repo` pulls updates.

Chosen over `.zip` uploads for versioning, iteration without re-uploading, and consistency with the
GitOps pattern used everywhere else. The 900s HTTPRoute timeout in
`kubedeploy/apps/tronbyt/httproute.yaml` already covers the clone and refresh.

> Do **not** point the *system* apps repo anywhere — see `kubedeploy/apps/tronbyt/README.md`. That
> re-clone is destructive.

## Error handling

Pixlet apps are stateless per render, so there is no cache to fall back on.

- **Feed unreachable / HTTP error:** render the static layout with `--` in place of every arrival
  rather than failing. A blank or errored app in rotation is worse than a stale-looking one.
- **No upcoming trains in a direction** (overnight, service change): keep the row and its bullet,
  render the literal text `no trains` in place of the destination, leave the arrival line blank.
  Dropping the row would reflow the other and change the layout.
- **Malformed/missing `destination_stop`:** fall back to the raw stop ID rather than erroring.

## Testing

- `pixlet render` succeeds with no Starlark errors.
- **Static-element fidelity is exact.** Over regions containing no text or live numbers — the
  bullet, the divider — every pixel must match the reference. These are derived from it, so a
  mismatch is a bug, not a judgement call.
- **Text regions compared by position and colour**, not glyph shape: baseline row, left edge and
  colour of each text element must match. Glyph differences are the one accepted residual.
- Arrival minutes match a direct API call made at render time.
- Renders correctly when the feed errors (simulate with an unroutable URL).
- Appears in the tronbyt picker after the user repo is set, and renders on the device.

## Open items

- ~~**Exact font identification.**~~ **Resolved** by `tools/fontprobe.py` (Task 2). Height-filter
  first (destination is 6px tall, arrival is 4px), then compare glyph bitmaps against the
  reference at the best-fit horizontal alignment (the naive "x=16, no offset" assumption undercounts
  real matches by 1-4px of font-internal left-bearing):

  | Line | Chosen font | Match quality | Runner-up |
  |---|---|---|---|
  | Destination (`FONT_DEST`) | **`Dina_r400-6`** | 72/318 px mismatch (23%) at best alignment, vs 103/264 (39%) for `5x8` and 102/258 (40%) for `tb-8` — a clear, decisive win | `5x8` (39% mismatch) |
  | Arrival (`FONT_TIME`) | **`tom-thumb`** | 13/44 px mismatch (30%) at best alignment | `5x8` / `tb-8` (tied, 32% mismatch — both render "now" identically) |

  **Honest caveat on match quality:** neither is a clean pixel match. `Dina_r400-6` is a
  reasonably strong candidate (77% agreement, and the mismatched pixels are concentrated at the
  leading edge — consistent with the known mid-scroll clipping, not a wrong font). `tom-thumb` is
  a weak win: only a 2-point margin over `5x8`/`tb-8` on a 44-pixel sample, and ~30% residual
  mismatch either way. This could mean Tidbyt used a custom font for the arrival line, or that the
  4px scale is simply too small for reliable discrimination against a photographically blurred
  reference (max channel ≈ 57, box-downsampled from a photo — see
  [The reference frame was recovered exactly](#the-reference-frame-was-recovered-exactly)).
  `tom-thumb` is the best available evidence, not a confident identification.

  Full methodology and probe output: `tools/fontprobe.py` plus the shift-corrected, full-width
  comparison in the Task 2 report (`kubedeploy/.superpowers/sdd/2026-07-27-nyc-subway-recreation/task-2-report.md`).

## Future work

- **CitiBike recreation.** Reference frame already recovered (`citibike-64x32.png`), data source
  verified (GBFS, keyless), and semantics confirmed against live data: the top number is **total
  bikes**, the bottom is **e-bikes** — `num_bikes_available=21` / `num_ebikes_available=20` matched
  the screenshot's `21` / `⚡20` exactly. Its own spec when Subway is done.
- **Station picker schema**, enabled by the configuration seam above.
