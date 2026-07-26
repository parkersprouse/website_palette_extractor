# palettekit

Reads a website's color palette out of its stylesheets and emits an
interactive HTML report plus JSON/CSS/SCSS/TS/Tailwind. Values are **parsed
from CSS, never sampled from pixels** — that is the whole premise, and it is
what makes the output exact rather than approximate.

Python 3.9+ nominal — the syntax actually parses back to 3.7, but it has only
been *run* on 3.12, so treat the floor as unverified until CI says otherwise.
**The core is stdlib-only and must stay that way.** Pillow/numpy are optional
and reached only through `images.py`, behind `--images`.

## Commands

```bash
python3 -m palettekit <target> -o out    # target: .har | URL | .html/.css path
python3 test_palettekit.py               # 30 tests, all must pass
ruff check .                             # must stay clean; config in pyproject
python3 -m palettekit x.har --list-sources   # diagnose framework noise first

pip install -e ".[dev]"                  # editable install + ruff/build/pytest
pip install -e ".[images]"               # adds pillow+numpy for --images
python3 -m build                         # wheel + sdist into dist/
```

Installing exposes a `palettekit` console script (`[project.scripts]`), so the
three ways to run it are `python3 -m palettekit`, `palettekit`, and the zipapp.
**All three must produce identical JSON for the same input** — that is the
cheapest possible regression check and worth keeping.

Build the single-file distributable (zipapp refuses a source tree that already
has `__main__.py`, so it needs a staging dir with a shim):

```bash
rm -rf /tmp/stage && mkdir -p /tmp/stage
cp -r palettekit /tmp/stage/ && rm -rf /tmp/stage/palettekit/__pycache__
printf 'import sys\nfrom palettekit.__main__ import main\nsys.exit(main())\n' \
  > /tmp/stage/__main__.py
python3 -m zipapp /tmp/stage -o palettekit.pyz -p "/usr/bin/env python3"
```

The package keeps its own `__main__.py` so `python3 -m palettekit` works from a
checkout. Both builds must produce identical JSON for the same input — worth
asserting in CI.

## Layout and data flow

```
sources.py   →  cssparse.py  →  extract.py  →  emit.py
(HAR/URL/     (tokenise,      (score, ground,  (JSON/CSS/SCSS/
 local files)  var(), roles)   merge, name)     TS/Tailwind/HTML)
```

| File | Lines | Holds |
|---|---:|---|
| `color.py` | 461 | `Color`, parsing, sRGB↔OKLab, contrast, hue names |
| `cssparse.py` | 353 | Declaration walker, `var()`, `selector_weight`, roles |
| `sources.py` | 293 | `load_har` / `load_url` / `load_paths` → `Bundle` |
| `extract.py` | 580 | `extract()`, ground, merging, statuses, naming |
| `emit.py` | 758 | Emitters; `_HTML` is the report template |
| `images.py` | 148 | Optional image quantisation, not part of the token set |
| `__main__.py` | 229 | CLI |

`emit.to_document(palette)` returns the dict the JSON file holds — that dict is
the public data contract. The HTML report consumes the same dict, inlined into
a `<script type="application/json">`.

## Invariants — do not "simplify" these

Each of these looks like an over-complication and is not. Every one exists
because the obvious implementation produced plausible but wrong output.

1. **Contrast is computed from quantised `rgb255`, not the float channels**
   (`Color.luminance`). We print an 8-bit hex next to every ratio; computing
   from unrounded floats prints ratios that disagree with our own hex. Test:
   `test_contrast_matches_reported_hex`.

2. **Ground is resolved by cascade order, not by weight** (`detect_ground`).
   The last `html`/`body`/`:root` background rule wins. Weighting instead picks
   the framework's default background on any site that loads a framework before
   its own CSS. Everything downstream depends on this — alpha flattening and
   every contrast ratio are measured against the ground. Test:
   `test_ground_follows_cascade_not_weight`.

3. **Stylesheets are collected in document order** (`collect_sheets`,
   `_document_order`), walking `<style>` and `<link rel=stylesheet>` together
   and matching hrefs to fetched assets. Inline `style=` attributes go last.
   Invariant 2 is meaningless without this.

4. **Two chroma thresholds, on purpose.** `Color.is_neutral` is 0.02 ("is this
   achromatic"). `extract.MUTED_CHROMA` is 0.06 ("would a person call this a
   color"). The tinted greys every framework ships — Tailwind slate/zinc —
   sit at ~0.03. Collapsing these thresholds names a dark slate body color
   `blue-2`.

5. **Hue names use OKLCH angles, not HSL angles** (`_HUE_BUCKETS`). Pure red is
   ~29° in OKLCH, not 0°. HSL-derived boundaries name `#ff0000` "orange". Test:
   `test_hue_names_use_oklch_angles`.

6. **Merging compares the *rendered* color, within a role, and never merges
   the ground away** (`_merge_near_duplicates`). Rendered, because two alphas
   that flatten to the same thing are one color to a reader. Within a role,
   because a grey used for text and the same grey used for a background are two
   tokens in any usable theme. Ground protected, because merging it into a
   neighbour leaves the palette describing a background no token holds. `token`
   is a wildcard role — a custom property takes the role of whatever consumes
   it. Tests: `TestMerging`.

7. **Buckets are keyed `(hexa, role)`** unless `--flat`. Keying on value alone
   made role separation depend on whether two uses happened to be *written* the
   same way (`rgba(...)` vs a literal), which nobody means to express.

8. **Fully transparent colors are dropped** (`alpha < 0.02`). Flattened, they
   are indistinguishable from the ground and manufacture phantom duplicates.

9. **Strings and comments are masked before any color scan**
   (`_mask_strings`, `strip_comments`). `content: "#fff"` is not a color.
   `_mask_strings` preserves length so offsets stay valid.

10. **Code emitters ship `live` colors only** by default (`_for_code`). What
    you paste into a project should be what the site paints; `saved` and
    `inert` stay in the JSON and the report, labelled. `--include-unused`
    overrides.

11. **The HTML report is standalone.** No `<link>`, no `fetch()` — it must open
    from `file://`. Its own reading colors are contrast-checked with a derived
    fallback (`_pick_report_theme`); an earlier version picked whatever cleared
    the bar and produced red body text. Tests:
    `test_html_report_is_standalone_and_valid`, `test_report_theme_is_readable`.

## Status vocabulary

| Status | Means | Detected by |
|---|---|---|
| `live` | Actually painted | default |
| `saved` | Custom property nothing references — usually a design tool's saved swatches | `_status_for` vs `var_refs` |
| `inert` | Declaration that paints nothing, e.g. `drop-shadow(0 0 0 #13330d)` | `is_inert_shadow` |

## Conventions

- No dependencies in the core. Anything needing numpy/Pillow goes in
  `images.py` behind a capability check that degrades with a message.
- Parsers return `None` for anything not understood rather than guessing.
  `color-mix()`, `light-dark()` and relative color syntax are skipped, not
  approximated.
- Comments explain *why*, especially where a line looks redundant. Most of the
  invariants above are also stated at their call site — keep them in sync.
- Emitted token names sort naturally (`_natural`): `ink-2` before `ink-10`.
- British/American spelling is mixed in comments; not worth a pass.

## Known limits (documented, not bugs)

- **No JavaScript is executed.** A HAR captures runtime-injected styles up to
  export time; a color computed in JS and set as an element property is in no
  stylesheet and will not be found.
- **The cascade is approximated, not implemented.** Ground follows document
  order; `var()` resolution takes the last definition. Specificity and scoped
  custom properties are not modelled. Fine for gathering a palette, wrong for
  predicting computed styles.
- **Scoring is a heuristic** (`selector_weight`). Treat ordering as a hint.
- **Framework CSS cannot be reliably auto-detected** when it is inlined in the
  document, which is the common case for page builders. This is deliberately
  left to the user via `--list-sources` / `--only` / `--exclude` rather than
  guessed at. Note that excluding a sheet also removes its `var()` references,
  so a property defined in site CSS but consumed only by the framework flips
  `live` → `saved`. Accurate for the input; surprising if unexpected.

## Reference fixture

`example/` is the output for `fleshandbonedesign.com/crass`, generated with
`--exclude static-css --exclude cargo.site --images`. Useful as a regression
anchor: ground `#151515`, `rgba(255,255,255,.75)` flattening to exactly
`#c4c4c4` at 10.47:1, `#ffc600` as `saved`, `#13330d` as `inert`, and the
imagery measuring 99.7% neutral. If a change moves any of those, understand why
before accepting it.

## Migration TODO

Not yet present, needed for a real repo:

- [x] `pyproject.toml` — hatchling backend, version read from
      `palettekit/__init__.py`, console script, `images`/`images-fast`/`dev`
      extras, ruff config. Verified by building and installing the wheel.
- [ ] `LICENSE` + the `[project.license]` and classifier entries left commented
      out in `pyproject.toml`, and `.gitignore` (`__pycache__/`, `dist/`,
      `*.pyz`, `out/`)
- [ ] Fill in `[project.urls]` and the `authors` entry once the repo exists
- [ ] CI: run tests on 3.9–3.13, `ruff check`, and assert the package, zipapp
      and installed-console-script outputs match
- [ ] `Makefile` or `build.py` for the zipapp incantation above
- [ ] Move `test_palettekit.py` into `tests/` and split by module
- [ ] Fixture corpus of small HTML files per site archetype (framework-heavy,
      page-builder, dark, light, CSS-variable-driven) — the current suite leans
      on synthetic fixtures inline in the test file
- [ ] Decide whether `emit.to_document`'s dict shape is a versioned public API
      before anyone builds on it
