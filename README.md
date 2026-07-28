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
pixlet render apps/nycsubway/nycsubway.star -o /tmp/out.webp
python3 tools/compare.py /tmp/out.webp
```

`tools/compare.py` diffs against `reference/subway-64x32.png`, a frame recovered
from a screenshot of the original Tidbyt app. Static regions (bullet, divider)
must match exactly; text regions are expected to differ.

## Pixlet version matters

Use **v0.53.1 of the tronbyt fork** -- `tronbyt/server` pins
`github.com/tronbyt/pixlet v0.53.1`, so this is what the server renders with.
Prebuilt release binaries need no Go toolchain.
