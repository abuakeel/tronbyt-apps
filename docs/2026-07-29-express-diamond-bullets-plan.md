# Express Diamond Bullets — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the six multi-character route ids correctly in the 11px bullet, so the station picker can be pointed at any station rather than only ones served by single-letter routes.

**Architecture:** One pure function classifies a route id into a bullet form and display letter; `render_row` switches on that. Express services draw a diamond built from stacked `render.Box` rows (so it takes the API's route colour), shuttles collapse to a circled `S`, and the other 23 route ids keep their exact current rendering — which is what holds the pixel-exact gate.

**Tech Stack:** Pixlet v0.53.1 (tronbyt fork), Starlark, Python 3 (gate harness).

**Approved spec:** `docs/2026-07-29-express-diamond-bullets-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **The 23 single-character route ids must render EXACTLY as they do today.** `python3 tools/gate.py` must stay at **whole frame 0/2048**. This is the regression bar for the whole change.
- **Do not change the layout.** The bullet occupies an 11px slot; `BULLET_DIAMETER`, paddings, fonts for local bullets, and every colour constant stay as they are.
- **Express letters use `tom-thumb`.** `Dina_r400-6` is unreadable inside an 11px diamond — the taper clips it. Measured, not preference.
- **No embedded pixel data.** The diamond is built from `render.Box` rows so it takes the route colour; `render.Image` has no tint parameter (`render/image.go:38-45`).
- **Route colours come from the API**, never a hardcoded table.
- Data source stays KEYLESS.
- `get_settings()` remains the only reader of station config; `DEFAULT_STOP_ID` and `DEFAULT_STATION_JSON` at exactly 2 occurrences each.
- Use `pixlet` from PATH (v0.53.1). Never `go install`.
- Never hand-edit `reference/subway-64x32.png`.
- Branch `testing`; push `main` for canonical.

## File Structure

| File | Change |
|---|---|
| `apps/nyc-subway/nyc-subway.star` | Add `bullet_form(route_id)` and `diamond(size, color)`; switch `render_row`'s bullet on the form |
| `tools/gate.py` | Add a `--bullets` mode with deterministic per-form checks |
| `README.md` | Document the new mode |

---

### Task 1: Bullet classification and the diamond widget

Deliverable: express routes render a coloured diamond, shuttles a circled `S`, and the 23 local routes are byte-identical to today — proven by the gate staying at 0/2048.

**Files:**
- Modify: `apps/nyc-subway/nyc-subway.star` (`render_row`, ~line 62)

**Interfaces:**
- Consumes: existing `BULLET_DIAMETER`, `FONT_DEST`, `COLOR_BULLET_TEXT`, and `render_row(route_id, route_color, destination, arrival_text)`.
- Produces: `bullet_form(route_id)` returning a 3-tuple `(form, letter, font)` where `form` is the string `"circle"` or `"diamond"`; and `diamond(size, color)` returning a `render.Column`. Task 2's checks call `bullet_form` directly through a probe.

- [ ] **Step 1: Capture the current render as a baseline**

Before touching anything, confirm the gate is green. Task 1 must not move it.

```bash
cd ~/workspace/tronbyt-apps
python3 tools/gate.py 2>&1 | grep -E "whole frame"; echo "exit=$?"
```

Expected: `whole frame OK 0/2048`. If this is not 0/2048 before you start, stop — something else is wrong and this task cannot be verified.

- [ ] **Step 2: Add the classifier and the diamond widget**

Insert into `apps/nyc-subway/nyc-subway.star`, immediately above `render_row`:

```starlark
# --- route bullet forms ---------------------------------------------------
# The API returns 29 route ids, six of which are multi-character and will not
# fit an 11px bullet: 6X 7X FX (express) and FS GS SI. The other 23 are single
# characters and MUST keep rendering exactly as they do today -- that is what
# holds tools/gate.py at 0/2048.
#
# Express services get a DIAMOND, matching MTA signage: the disc becomes the
# diamond, it is not a circle containing one.
EXPRESS_SUFFIX = "X"
SHUTTLE_IDS = ["FS", "GS", "SI"]

# Express letters need a SMALLER font than local ones. Dina_r400-6 is
# unreadable inside an 11px diamond -- the taper clips the glyph to mush.
# Measured by rendering, not chosen by preference.
FONT_BULLET_EXPRESS = "tom-thumb"

def bullet_form(route_id):
    """Classify a route id -> (form, letter, font).

    form is "circle" or "diamond". Single-character ids are returned unchanged
    with the local font, so their rendering is bit-for-bit what it was before
    this function existed.
    """
    if len(route_id) == 1:
        return ("circle", route_id, FONT_DEST)
    if route_id in SHUTTLE_IDS:
        # Franklin Ave / Grand St shuttles are both signed "S". SI (Staten
        # Island Railway) also collapses to "S" -- its real bullet reads "SIR",
        # which overflows an 11px circle. SIR has no transfer to the subway, so
        # it cannot appear at a station this display serves. Recorded in the
        # design doc as a known limitation, not solved.
        return ("circle", "S", FONT_DEST)
    if route_id.endswith(EXPRESS_SUFFIX):
        return ("diamond", route_id[:-1], FONT_BULLET_EXPRESS)
    # Unknown multi-character id (a new route, or a shape not seen today):
    # truncate rather than overflow. A slightly wrong bullet beats a corrupted row.
    return ("circle", route_id[0], FONT_DEST)

def diamond(size, color):
    """Filled diamond from centred Box rows, so it takes any route colour.

    render.Image has no tint parameter (render/image.go:38-45), so an embedded
    PNG could not be recoloured per route -- and route colours come from the
    API across 29 routes.
    """
    half = size // 2
    rows = []
    for y in range(size):
        w = size - 2 * abs(y - half)
        rows.append(render.Box(
            width = size,
            height = 1,
            child = render.Box(width = w, height = 1, color = color),
        ))
    return render.Column(children = rows)
```

- [ ] **Step 3: Switch `render_row`'s bullet on the form**

Replace the `else:` branch of the bullet block in `render_row` — the branch that currently builds `render.Circle` unconditionally. Leave the `if route_id == "":` dim-placeholder branch untouched.

```starlark
    else:
        form, letter, font = bullet_form(route_id)
        if form == "diamond":
            bullet = render.Stack(children = [
                diamond(BULLET_DIAMETER, route_color),
                render.Padding(
                    pad = (4, 3, 0, 0),
                    child = render.Text(letter, font = font, color = COLOR_BULLET_TEXT),
                ),
            ])
        else:
            bullet = render.Circle(
                diameter = BULLET_DIAMETER,
                color = route_color,
                child = render.Padding(
                    pad = (0, 0, 0, 2),
                    child = render.Text(letter, font = font, color = COLOR_BULLET_TEXT),
                ),
            )
```

The circle branch now renders `letter` and `font` from `bullet_form` rather than `route_id` and `FONT_DEST` directly. For every single-character id those are identical values — which is exactly why the gate must not move.

- [ ] **Step 4: Verify the 23 local routes are unchanged**

```bash
cd ~/workspace/tronbyt-apps
python3 tools/gate.py 2>&1 | grep -E "whole frame"
python3 tools/gate.py --failures 2>&1 | tail -2
python3 tools/gate.py --handler 2>&1 | tail -1
```

Expected: `whole frame OK 0/2048`, all failure cases OK, `handler: OK`. **If the whole frame moved at all, the local path changed and the refactor is wrong** — do not proceed, and do not adjust the reference to match.

- [ ] **Step 5: Eyeball the new forms**

```bash
cd ~/workspace/tronbyt-apps
python3 - <<'PY'
import pathlib, subprocess, tempfile, os
src = pathlib.Path("apps/nyc-subway/nyc-subway.star").read_text()
src = src[:src.index("\ndef main(config):")]
src += '''
def main(config):
    def slot(c): return render.Box(width = 16, height = 14, child = c)
    return render.Root(child = render.Row(children = [
        slot(render_row("6X", "#00933c", "x", "")),
        slot(render_row("FS", "#808183", "x", "")),
        slot(render_row("G",  "#6cbe45", "x", "")),
    ]))
'''
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "p.star"); open(p, "w").write(src)
    out = os.path.join(td, "p.webp")
    r = subprocess.run(["pixlet", "render", p, "-o", out], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr); raise SystemExit("render failed")
    from PIL import Image
    px = Image.open(out).convert("RGB").load()
    for y in range(14):
        print("   " + "".join("#" if sum(px[x, y]) > 60 else "." for x in range(52)))
PY
```

Expected: a diamond for `6X`, a circle for `FS`, a circle for `G`. If `6X` renders as a circle, `bullet_form` is not being reached.

- [ ] **Step 6: Commit**

```bash
cd ~/workspace/tronbyt-apps
git add apps/nyc-subway/nyc-subway.star
git commit -m "feat(nyc-subway): diamond bullets for express services

Six of the API's 29 route ids are multi-character and overflowed the 11px
bullet: 6X 7X FX express, plus FS GS SI. Express now renders a DIAMOND -- the
disc becomes the diamond, matching MTA signage rather than nesting one inside
the other. Shuttles collapse to a circled S.

The diamond is built from stacked Box rows rather than an embedded PNG because
render.Image has no tint parameter, and route colours come from the API.

Express letters use tom-thumb: Dina_r400-6 is unreadable inside an 11px
diamond, the taper clips it. Measured by rendering, not chosen.

The 23 single-character ids take an unchanged path -- gate still 0/2048."
```

---

### Task 2: Deterministic bullet-form coverage

Deliverable: a `--bullets` gate mode that fails if express classification regresses, proven by mutation three ways.

**Files:**
- Modify: `tools/gate.py` (add `cmd_bullets`, register `--bullets`, update the `Modes:` docstring)
- Modify: `README.md`

**Interfaces:**
- Consumes: `bullet_form(route_id)` from Task 1; the existing `read_patched_star_source()`, `run_probe()` and the `PROBE-DONE` sentinel convention in `tools/gate.py`.
- Produces: nothing consumed downstream.

- [ ] **Step 1: Add the `--bullets` mode**

`bullet_form` is a pure function, so a probe can call it directly and print its output — the same mechanism `--handler` already uses. Add to `tools/gate.py`:

```python
def cmd_bullets():
    """Assert route-id -> bullet form classification, deterministically.

    bullet_form() is pure, so the probe calls it directly and prints one line
    per case. No live data: a guard that depends on which trains happen to be
    running is not a guard.
    """
    cases = [
        ("6X", "diamond|6"),
        ("7X", "diamond|7"),
        ("FX", "diamond|F"),
        ("FS", "circle|S"),
        ("GS", "circle|S"),
        ("SI", "circle|S"),
        ("G", "circle|G"),
        ("A", "circle|A"),
        ("6", "circle|6"),
        ("ZZ", "circle|Z"),
    ]
    src = read_patched_star_source()
    src += "\n\ndef main(config):\n"
    for route_id, _ in cases:
        src += (
            '    f, l, _ = bullet_form("%s")\n' % route_id
            + '    print("%s=" + f + "|" + l)\n' % route_id
        )
    src += '    print("PROBE-DONE")\n'
    src += '    return render.Root(child = render.Box(color = "#000000"))\n'

    got = run_probe(src, {"stops": []})
    seen = dict(line.split("=", 1) for line in got if "=" in line)

    failures = []
    for route_id, expected in cases:
        actual = seen.get(route_id)
        if actual != expected:
            failures.append("  %s: expected %r, got %r" % (route_id, expected, actual))

    for line in failures:
        print(line)
    print("bullets: OK" if not failures else "bullets: FAIL")
    return 1 if failures else 0
```

Register `--bullets` in the argparse mutually-exclusive group alongside the existing modes, and add it to the module `Modes:` docstring.

- [ ] **Step 2: Run it — expect PASS**

```bash
cd ~/workspace/tronbyt-apps
python3 tools/gate.py --bullets
```

Expected: `bullets: OK`, exit 0.

- [ ] **Step 3: Prove the guard can fail — this is the point of the task**

Three mutations. After each: run `--bullets`, confirm FAIL, restore, confirm OK.

```bash
cd ~/workspace/tronbyt-apps
cp apps/nyc-subway/nyc-subway.star /tmp/bullet.bak

# (a) express classification disabled -> 6X falls through to the truncating branch
sed -i 's/    if route_id.endswith(EXPRESS_SUFFIX):/    if False:/' apps/nyc-subway/nyc-subway.star
python3 tools/gate.py --bullets; echo "^ expect FAIL"
cp /tmp/bullet.bak apps/nyc-subway/nyc-subway.star

# (b) shuttle mapping disabled -> FS stops returning "S"
sed -i 's/    if route_id in SHUTTLE_IDS:/    if False:/' apps/nyc-subway/nyc-subway.star
python3 tools/gate.py --bullets; echo "^ expect FAIL"
cp /tmp/bullet.bak apps/nyc-subway/nyc-subway.star

# (c) X-strip removed -> 6X would render the letter "6X"
sed -i 's/return ("diamond", route_id\[:-1\], FONT_BULLET_EXPRESS)/return ("diamond", route_id, FONT_BULLET_EXPRESS)/' apps/nyc-subway/nyc-subway.star
python3 tools/gate.py --bullets; echo "^ expect FAIL"
cp /tmp/bullet.bak apps/nyc-subway/nyc-subway.star

python3 tools/gate.py --bullets   # must be OK again
git status --short                # must be empty
```

Record all three verbatim outputs in your report. **If any mutation does not produce a FAIL, the check is not testing what it claims** — fix it before continuing. This project has shipped four assertions that could not fail, every one caught by review rather than by its author.

- [ ] **Step 4: Verify nothing else regressed**

```bash
cd ~/workspace/tronbyt-apps
python3 tools/gate.py              # whole frame 0/2048, exit 0
python3 tools/gate.py --failures   # all cases OK, exit 0
python3 tools/gate.py --handler    # OK, exit 0
python3 tools/gate.py --bullets    # OK, exit 0
python3 tools/gate.py --live       # exit 0
grep -c DEFAULT_STOP_ID apps/nyc-subway/nyc-subway.star       # 2
grep -c DEFAULT_STATION_JSON apps/nyc-subway/nyc-subway.star  # 2
git status --short                                            # empty
```

- [ ] **Step 5: Document the mode**

Add `--bullets` to the gate section of `README.md`, describing what it asserts: route-id → bullet form classification, deterministic, no live data.

- [ ] **Step 6: Commit**

```bash
cd ~/workspace/tronbyt-apps
git add tools/gate.py README.md
git commit -m "test(nyc-subway): deterministic bullet-form coverage

--bullets asserts route-id -> (form, letter) for all six multi-character ids,
representative single-character ones, and an unknown-id fallback.

Mutation-proven three ways: disabling express classification, disabling the
shuttle mapping, or dropping the X-strip each make it fail. No live data -- a
guard that depends on which trains happen to be running is not a guard, which
this project learned when a duplicate-label check passed green with the bug
reinstated."
```

---

## Self-review notes

- **The regression bar is structural**: Task 1 Step 4 requires 0/2048 before Task 2 begins, and every single-character id routes through `bullet_form` returning exactly its previous values.
- **Task 2's gate is mutation-proven three ways** (Step 3), because this project's recurring defect is assertions that cannot fail.
- **No live data in the new checks** — deliberately, after the label-source guard proved non-deterministic.
- **`SI` collapsing to `S` is asserted as intended behaviour**, with the limitation recorded in the design doc rather than silently encoded in a test.
