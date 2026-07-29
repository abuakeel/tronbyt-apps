# Station picker schema — design

**Date:** 2026-07-28
**Repo:** `~/workspace/tronbyt-apps`
**App:** `apps/nyc-subway/nyc-subway.star`

**Goal:** Add a typeahead station picker so the app can be installed **twice** on one device —
one instance per station — and rotate between them via tronbyt's normal app rotation.

Immediate need: `G35` Clinton - Washington Avs (G) and `A44` Clinton - Washington Avs (A).

## Why two instances rather than one app showing both

The display is 64×32 and the layout is two 16px rows — one station, both directions. There is no
room for a second station without abandoning the reference geometry the app currently matches
pixel-for-pixel (`gate.py` → 0/2048).

tronbyt stores config **per installation** (`/devices/{id}/{iname}/config`), so the same app added
twice can hold two different stations. Each gets its own slot in the device's rotation and its own
dwell time. That is the platform's native model; nothing custom is required.

> **Decided 2026-07-28: nothing on screen identifies the station.** The rendered display keeps
> showing exactly what it shows today — the line bullet and the terminal station, e.g. a green `G`
> with `Church Av` / `Court Sq`. `G35` renders green `G` bullets while `A44` renders blue `A`/`C`
> bullets, so the two instances are distinguishable at a glance. Adding a station name would mean
> shrinking or displacing part of a layout that currently matches the reference exactly. Revisit
> only if the two prove confusable in practice.

## What the data says

Measured against `api.subwaynow.app/stops/` on 2026-07-28:

| Fact | Value | Consequence |
|---|---|---|
| Total stops | **496** | Needs search, not a dropdown |
| Names shared by 2+ stops | **75** | **Route labels are required, not cosmetic** |
| `"clinton"` | 2 hits: `(A)`, `(G)` | The two target stations, correctly disambiguated |
| `"a"` | **303 hits** | Needs a result cap |
| Stops with no `routes` | at least one (`14 St`) | A name-only label collides with two other `14 St` stops |

The label format matches the original Tidbyt app's: station name, then the lines in parentheses.
Verified against live data:

```
Atlantic Av (L)                    -> L24
Atlantic Av - Barclays Ctr (DNR)   -> R31
Atlantic Av - Barclays Ctr (Q)     -> D24
Atlantic Av - Barclays Ctr (45)    -> 235
Clinton - Washington Avs (A)       -> A44
Clinton - Washington Avs (G)       -> G35
```

> Note the API models each platform complex as its own stop, so Atlantic Av - Barclays Ctr appears
> as **three** entries rather than the two a rider might expect. This is the upstream data's
> grouping, not a labelling choice, and the parenthesised routes keep them unambiguous.

> **The `(A)` / `(G)` route letters above are a snapshot, not a permanent label.** They reflect
> whatever service is currently running: `A44` shows `(C)` in the afternoon and `(A)` overnight,
> once the C stops running. Harmless for the picker -- only the bare stop id (`value`) is read
> back by `get_settings()`, never the display label -- but don't treat this table as a fixed
> mapping from stop id to route letter.

## How pixlet typeahead works

Confirmed from `pixlet/docs/schema/typeahead/example.star`:

- `schema.Typeahead(id, name, desc, icon, handler)`, where `handler` takes one argument.
- The handler receives the user's search string and returns a list of
  `schema.Option(display = ..., value = ...)`.
- **The app reads back a JSON blob, not a plain string**: `config.get("<id>", '<json default>')`
  yields `{"display": ..., "value": ...}`, which the app must `json.decode`.

That last point is the only thing in the app that changes shape.

## Components

### 1. `get_schema()`

One field. Station is the only thing that differs between instances; anything else is YAGNI.

```starlark
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

### 2. `search_stations(pattern)`

- Fetches `/stops/` with `ttl_seconds = 86400` — the **same endpoint and TTL the app already uses**
  for destination-name resolution, so repeat keystrokes hit pixlet's HTTP cache and cost nothing.
- Case-insensitive substring match on the stop name.
- Returns **at most 20** options. `"a"` truncates silently; acceptable because the user types a
  station name (decided 2026-07-28).
- Label: `"<name> (<routes>)"` with route keys sorted for stability.
- **Routeless stops fall back to `"<name> [<stop_id>]"`** so they stay distinguishable from
  same-named neighbours.
- Value: the bare stop ID (`"G35"`).

### 3. The config seam — the only change to existing code

`get_settings()` is the single place that reads station configuration, by design. It absorbs the
JSON shape entirely:

```starlark
DEFAULT_STOP_ID = "G35"   # Clinton - Washington Avs (G)
DEFAULT_STATION_JSON = '{"display": "Clinton - Washington Avs (G)", "value": "G35"}'

def get_settings(config):
    stop_id = DEFAULT_STOP_ID
    raw = config.get("station", DEFAULT_STATION_JSON)

    # TWO-ARGUMENT form is load-bearing. json.decode(raw) with one argument is
    # FATAL on malformed input, and Starlark has no try/except -- a corrupt
    # config blob would kill every render with no way to recover. The second
    # argument is returned instead of raising. Verified 2026-07-28 against
    # pixlet v0.53.1 with non-JSON and non-dict inputs; both rendered cleanly.
    decoded = json.decode(raw, None)

    if type(decoded) == "dict":
        value = decoded.get("value")
        if type(value) == "string" and value:
            stop_id = value
    return {"stop_id": stop_id, "directions": DEFAULT_DIRECTIONS}
```

`fetch_trips`, `render_row` and `render_app` are **untouched**. This is what the seam was built for.

> The existing invariant holds: `DEFAULT_STOP_ID` is referenced in exactly two places — its
> definition and its single use in `get_settings`. `DEFAULT_STATION_JSON` is likewise referenced
> only there.

## Backward compatibility

**The currently-installed instance must keep working untouched.** It has no stored config, so
`config.get("station", DEFAULT_STATION_JSON)` returns the default encoding `G35` — the station it
already shows. No reconfiguration, no visible change.

The second station is added as a **new installation** of the same app, configured to `A44`.

## Error handling

Consistent with the posture established in Task 5:

- **`/stops/` fetch fails in the handler:** return an empty list. The picker shows no results
  rather than erroring; it must never crash the schema request.
- **Config blob malformed, not a dict, or missing/empty `value`:** fall back to `DEFAULT_STOP_ID`.
  A bad config must not break rendering. **This depends entirely on `json.decode`'s two-argument
  form** — the one-argument version raises fatally and Starlark cannot catch it, so a corrupt blob
  would kill every render permanently. Same failure class as the DNS fatality documented in
  `manifest.yaml`: in Starlark, anything that can raise must be given a non-raising form instead.
- **Configured stop ID no longer exists upstream:** already handled — `fetch_json` returns `None`
  and both rows render `no trains`. No new code needed.

## Testing

The existing gate is the regression guard and **must stay green**:

- `python3 tools/gate.py` → divider 0/64, whole frame **0/2048**, exit 0. Still holds because
  `gate.py` renders through the real code path with no config set, so `get_settings` returns the
  `G35` default exactly as before.
- `python3 tools/gate.py --failures` → all existing cases still pass.

New coverage:

- **Configured station:** render with a config blob selecting `A44`; assert the app fetches `A44`
  (its bullets and destinations differ from `G35`).
- **Malformed config:** not JSON, not a dict, missing `value`, `value: ""` — each renders
  successfully at the `G35` default rather than crashing.
- **Handler with feed down:** `search_stations` returns `[]` and does not raise.
- **Handler labelling:** `"clinton"` returns exactly 2 options with distinct `(A)` / `(G)` labels;
  a routeless stop yields the `[stop_id]` fallback; `"a"` returns exactly 20.

## Non-goals

- No second configurable field. Direction stays both-directions; nothing else varies.
- No change to the rendering layer. The layout is pixel-verified and stays that way.
- No station name on screen (decided above).
- No "show more" past the 20-result cap.
