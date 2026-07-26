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
python3 test_palettekit.py               # 44 tests, all must pass
python3 -m palettekit x.har --no-themes  # collapse a two-theme site into one
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
 local files)  var(), roles,   merge, name —    TS/Tailwind/HTML)
               theme scopes)   once per theme)
```

| File | Lines | Holds |
|---|---:|---|
| `color.py` | 460 | `Color`, parsing, sRGB↔OKLab, contrast, hue names |
| `cssparse.py` | 448 | Declaration walker, `var()`, `selector_weight`, roles, theme scopes |
| `sources.py` | 292 | `load_har` / `load_url` / `load_paths` → `Bundle` |
| `extract.py` | 793 | `extract()`, per-theme `_build`, ground, merging, statuses, naming |
| `emit.py` | 942 | Emitters; `_HTML` is the report template |
| `images.py` | 148 | Optional image quantisation, not part of the token set |
| `__main__.py` | 248 | CLI |

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

   Within a themed extraction there is one addition: a declaration carrying the
   theme's own marker outranks an unscoped one regardless of order
   (`Usage.cascade_key`). For a selector-scoped theme that is literal
   specificity — `html.dark` beats `html`; for a `prefers-color-scheme` block it
   is the near-universal convention that the override is written after what it
   overrides. On an unthemed site every declaration is unscoped and the tuple
   degrades to the plain `(sheet, order)` pair, so the base path is untouched.

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

12. **A theme is a scope over declarations, so each one is extracted from
    scratch** (`_build`, once per entry in `_theme_plan`). Tagging colors after
    a single pass cannot work: each theme has its own ground, and invariants 2
    and 6 make everything downstream — alpha flattening, every contrast ratio,
    what merges with what — depend on it.

13. **A theme's own rules shadow the unscoped rules they override**, matched on
    `(selector as it reads inside the theme, property)` in `_build`. Without
    this the light `--bg: #fff` and the light `.card` background both turn up
    in the dark palette as colors the dark theme never paints. It is not
    general specificity and does not try to be — a `border` shorthand against a
    `border-color` override still slips through. Test:
    `test_overridden_values_leave_the_theme_that_replaced_them`.

14. **Themed selectors are normalised before weighting or ground-matching**
    (`strip_theme_scope`). `html.dark body` has to read as `body`, or
    `selector_weight` scores the dark theme's page rule as an ordinary class and
    `detect_ground` never sees it — the dark theme then silently inherits the
    light ground and every ratio reported for it is wrong. The class matcher is
    anchored on whole names so `.dark-blue`, `.darken` and `.sidebar-dark` are
    not theme roots. Tests: `TestThemeScopes`.

15. **The two themes share one set of token names** (`_align_names`), paired by
    rank *within a group, against each theme's own ground*. The
    highest-contrast ink in a light theme is the same token as the
    highest-contrast ink in a dark one, though one is nearly black and the
    other nearly white — pairing by lightness gets them backwards. Without
    alignment the toggle swaps one list of names for an unrelated one and
    `--c-ink-1` means two different things in the emitted CSS. Test:
    `test_names_align_across_themes`.

## Status vocabulary

| Status | Means | Detected by |
|---|---|---|
| `live` | Actually painted | default |
| `saved` | Custom property nothing references — usually a design tool's saved swatches | `_status_for` vs `var_refs` |
| `inert` | Declaration that paints nothing, e.g. `drop-shadow(0 0 0 #13330d)` | `is_inert_shadow` |

## Themes

`theme_scope` recognises two mechanisms: a `prefers-color-scheme` media query,
and a class or attribute on a wrapper (`.dark`, `.theme-dark`, `.is-light`,
`[data-theme="dark"]`, `[data-bs-theme=dark]`, …). Both are scopes over
declarations. Selector-scoped is the common case — Tailwind's `dark:` variant
compiles to it — so media-query-only detection would miss most modern sites.

`_theme_plan` decides what to build. Unscoped declarations belong to every
theme, so each palette is those plus one scope's overrides:

| Scopes found | Palettes built |
|---|---|
| none | `base` only — output byte-identical to before themes existed |
| `dark` only | `base` + `dark` |
| `light` only | `base` + `light` — a dark-by-default site with a light override |
| both | `light` + `dark`; neither set of unscoped rules is a theme by itself |

A scope carrying no color of its own is not a theme (`_scopes_present`), and a
scope that produced the same palette anyway is dropped (`_same_palette`).

Each theme carries **both** an `id` — named for the rule that produced it — and
an `appearance` measured from its ground. They disagree on a dark-by-default
site, which is why both exist: the id addresses the theme, the appearance
labels it. When both themes land on the same side of the light/dark line the
appearance is no longer a distinction, so a warning is emitted and the report
labels its toggle by id instead.

`to_document` always emits `themes` (a list of one or more) and `defaultTheme`.
Top-level `ground`, `stats` and `colors` mirror `themes[0]`, so everything that
read this document before themes existed keeps working.

Themes reach the outputs unevenly, and deliberately: the **JSON** and the
**HTML report** carry both; the **CSS** carries both, as a `:root` block plus a
`prefers-color-scheme` media query *and* a `[data-theme]` block, since there is
no telling which mechanism a consuming project uses; **SCSS, TS and Tailwind
carry the default theme only**. If that changes, decide what a two-theme
Tailwind config should even look like first.

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
  custom properties are not modelled — beyond the two narrow theme rules in
  invariants 2 and 13, which exist because getting theme overrides wrong
  produces a whole second palette of colors the site never paints. Fine for
  gathering a palette, wrong for predicting computed styles.

- **A bare channel triplet used raw paints nothing, and is reported rather than
  parsed.** The shadcn/ui convention writes `--background: 0 0% 3.9%` and
  assembles it at the point of use. Assembled — `hsl(var(--background))`,
  `hsl(var(--x) / 50%)`, `rgb(var(--x))` — it parses here and always has; that
  path is covered by `TestChannelTriplets` because nothing advertised it.

  Used raw, as `background-color: var(--background)`, it is **not a colour we
  are failing to read**. It is invalid CSS: verified against a real engine,
  `CSS.supports('background-color', '0 0% 100%')` is `false` and the computed
  value is `rgba(0,0,0,0)`. Reading a color out of it would invent one the page
  never shows. Do not "fix" this by teaching `find_colors` about loose
  triplets — an earlier note in this file suggested exactly that, before the
  computed-style evidence existed.

  `_triplet_warning` names the situation instead, in one aggregated note, so a
  site written this way does not look like an extraction failure.
  `ground.news.har` is the local reproduction: 53 `.dark` declarations are
  detected and the var table diverges correctly across 23 properties, and the
  palette is still nearly identical across themes — correctly, because those
  declarations paint nothing. 11 properties trip the warning.
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
