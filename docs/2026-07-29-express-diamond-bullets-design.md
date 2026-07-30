# Express diamond bullets — design

**Date:** 2026-07-29
**Repo:** `~/workspace/tronbyt-apps`
**App:** `apps/nyc-subway/nyc-subway.star`

**Goal:** Render the six multi-character route ids correctly in the 11px bullet, so the station
picker can be pointed at any station rather than only ones served by single-letter routes.

## The gap

`station_label` and the bullet both assume a single-character route id. The API returns **29** route
ids, of which **six are multi-character**:

```
1 2 3 4 5 6 6X 7 7X A B C D E F FS FX G GS H J L M N Q R SI W Z
                ^^    ^^          ^^ ^^    ^^          ^^
```

`render.Text("6X")` in an 11px circle overflows. The other 23 render correctly today — proven live
when an F train appeared at G35 (normally G-only) and drew an F bullet with no code change.

This does not affect the two configured stations (`G35` is G-only plus occasional F reroutes;
`A44` is A/C — all single-character). It becomes reachable the moment the station picker is
pointed at a station served by express or shuttle service.

## Decisions

**The disc becomes the diamond.** Express services render as a **filled diamond in the route
colour with the letter knocked out** — not a circle containing a diamond. This is MTA's actual
express bullet form, confirmed by the user 2026-07-29 after comparing four rendered variants.

| Route ids | Bullet | Letter | Font |
|---|---|---|---|
| `6X`, `7X`, `FX` | **Diamond** | id minus the trailing `X` → `6`, `7`, `F` | `tom-thumb` |
| `FS`, `GS` | Circle | `S` (Franklin Ave / Grand St shuttles) | `Dina_r400-6` |
| `SI` | Circle | `S` | `Dina_r400-6` |
| the other 23 | Circle — **unchanged** | the id itself | `Dina_r400-6` |

## The font constraint, measured

**Express letters must use a smaller font than local ones.** `Dina_r400-6` — what every local
bullet uses — is unreadable inside an 11px diamond: the taper clips the glyph to mush. Verified by
rendering; `tom-thumb`, `CG-pixel-3x5-mono` and `CG-pixel-4x5-mono` are all legible, `tom-thumb`
chosen as the cleanest.

Enlarging the diamond is not an option: the 11px slot is what the pixel-exact layout depends on
(`gate.py` → 0/2048 against the recovered reference).

So an express letter is visibly smaller than a local one. Unavoidable at this resolution, and
accepted.

## The diamond is built from widgets, not an embedded asset

**`render.Image` has no tint parameter** — its fields are `src`, `width`, `height`, `delay` only
(`render/image.go:38-45`). A single embedded PNG therefore cannot take the route colour, and route
colours come from the API across 29 routes. Pre-generating one PNG per colour would break the
moment MTA changes a palette entry.

So the diamond is a staircase of centred `render.Box` rows inside a `render.Column`, which takes
any colour as a parameter:

```starlark
def diamond(size, color):
    """Filled diamond built from centred Box rows -- takes any route colour."""
    half = size // 2
    rows = []
    for y in range(size):
        w = size - 2 * abs(y - half)
        rows.append(render.Box(width = size, height = 1,
            child = render.Box(width = w, height = 1, color = color)))
    return render.Column(children = rows)
```

At `size = 11` this yields the Manhattan-distance mask `|x−c| + |y−c| ≤ c`:

```
.....#.....      ..#######..
....###....      .#########.
...#####...      ###########
..#######..      .#########.
.#########.      ..#######..
###########      ...#####...
                 ....###....
                 .....#.....
```

Verified by rendering `6X` green, `7X` purple and `FX` orange from the live API palette — all
three legible, all correctly coloured, with no embedded data of any kind.

> This also sidesteps the embedded-pixel-data question entirely. There is no blob to regenerate,
> so the rule that bit `reference/subway-64x32.png` — a checked-in asset nobody could reproduce —
> cannot apply here.

## Known limitation

**`SI` is indistinguishable from a shuttle.** Staten Island Railway's real bullet is a blue circle
reading `SIR`; at 11px both `SIR` and `SI` overflow badly (verified by rendering). It collapses to
`S`, identical to the Franklin Ave and Grand St shuttles.

Accepted because SIR is a physically separate system with no transfer to the subway — it cannot
appear at any station reachable from the ones this display serves. Documented rather than solved.

## Non-goals

- No change to local bullets. The other 23 route ids keep their exact current rendering, which is
  what keeps the gate at 0/2048.
- No station-name display, no layout change, no new config field.
- No attempt to render `SIR` legibly.

## Error handling

- An unrecognised multi-character id (a new express or a route id shape not seen today) falls back
  to the **circle** with the id truncated to its first character, rather than overflowing. Better a
  slightly wrong bullet than a corrupted row.
- The existing empty-`route_id` path (dim bullet, no letter) is untouched.

## Testing

The regression bar is that the shipped display must not move:

- `python3 tools/gate.py` → whole frame **0/2048**, exit 0. This holds by construction: `G`, `A`
  and `C` are single-character and take the unchanged circle path.
- `python3 tools/gate.py --failures` → all existing cases still pass.

New deterministic coverage, all through the mock — **no live data**, because a guard that depends
on which trains happen to be running is not a guard (learned the hard way on the label-source
check):

- A `6X` trip renders a **diamond** showing `6`, not a circle showing `6X`.
- A `FS` trip renders a **circle** showing `S`.
- A `G` trip renders exactly what it renders today — pixel-identical to the current output.
- An unknown multi-char id (e.g. `ZZ`) renders a circle with `Z` and does not crash.

Each new check must be **mutation-proven**: disable the express mapping and confirm the `6X` check
fails; restore. A guard nobody has watched fail is not a guard — this project has shipped four of
those, every one caught by review rather than by its author.
