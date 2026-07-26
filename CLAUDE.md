# palettekit

Reads a website's color palette out of its stylesheets and emits an
interactive HTML report plus JSON/CSS/SCSS/TS/Tailwind. Values are **parsed
from CSS, never sampled from pixels** — that is the whole premise, and it is
what makes the output exact rather than approximate.

**Python 3.10+, verified** — the suite passes on 3.10, 3.11, 3.12, 3.13 and
3.14, and 3.10 produces byte-identical JSON to 3.14 on the reference fixture.
Raised from a nominal, never-tested 3.9 because `tinycss2`/`cssselect2`
(`PLAN.md`) need 3.10 and 3.9 went end-of-life in October 2025. Re-run the
matrix rather than trusting this line:

```bash
for v in 3.10 3.11 3.12 3.13 3.14; do
  uv run --python "$v" --no-project python test_palettekit.py; done
```

**Priority order, set by the owner (2026-07-26): accuracy and breadth first,
slimness second.** The core is stdlib-only today and there is no rule that it
must stay that way — if a dependency makes the tool read more sites correctly,
take it. This reverses an earlier constraint, and several decisions below were
made under the old one and should be re-read in that light: the `color-mix()`
skip, and the argument against modelling the cascade. Pillow/numpy remain
optional and reached only through `images.py`, behind `--images`.

## Commands

```bash
python3 -m palettekit <target> -o out    # target: .har | URL | .html/.css path
python3 test_palettekit.py               # 65 tests, all must pass
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

Compare with the `generated` key removed. It holds a wall-clock timestamp, so a
plain `diff` of two runs fails whenever they straddle a second boundary — which
looks exactly like a real mismatch and wasted a diagnostic pass once already.

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
| `color.py` | 528 | `Color`, parsing, sRGB↔OKLab, CIE Lab/LCH, contrast, hue names |
| `cssparse.py` | 718 | Declaration walker, `var()`, `selector_weight`, roles, theme scopes, page element |
| `sources.py` | 292 | `load_har` / `load_url` / `load_paths` → `Bundle` |
| `extract.py` | 916 | `extract()`, per-theme `_build`, ground, merging, statuses, naming |
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

   Resolution is cascade order and nothing else. What invariant 16 changes is
   the *candidate set*, not how the winner is picked among them.

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

   **A backslash outside a string is an escape, and the next character is
   never a delimiter.** Tailwind arbitrary values put escaped quotes in the
   *selector* — `.bg-\[url\(\"…\"\)\]` — and reading one as a string opener
   masks through the following `{`, leaving the brace walker a level deep for
   the rest of the file. The parse still succeeds and quietly returns less,
   which is the worst way for this to fail: on `ground.news.har` it cost 178 of
   181 themed rules and two thirds of every declaration, and made a site with
   two obvious themes look like it had one. Test:
   `test_escaped_quote_in_a_selector_does_not_swallow_the_rest`.

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

    **A backslash ends a class name too**, which is why it is in the anchor's
    lookahead. Tailwind compiles `dark:bg-x` to a class *named* `dark:bg-x`,
    written `.dark\:bg-x:is(.dark *)`. The scope is the `:is()`; the name is
    just a name. Reading the name as the marker strips it out of the middle of
    the class and leaves `\:bg-x`, which then matches nothing — including the
    body's own class, which is how invariant 16 finds the ground. The `:is()`
    form has to come off as a unit for the same reason: removing only the
    `.dark` inside it leaves `:is( *)` glued to the selector. Test:
    `test_tailwind_variant_class_is_not_a_theme_root`.

15. **The two themes share one set of token names** (`_align_names`), paired by
    rank *within a group, against each theme's own ground*. The
    highest-contrast ink in a light theme is the same token as the
    highest-contrast ink in a dark one, though one is nearly black and the
    other nearly white — pairing by lightness gets them backwards. Without
    alignment the toggle swaps one list of names for an unrelated one and
    `--c-ink-1` means two different things in the emitted CSS. Test:
    `test_names_align_across_themes`.

16. **A rule is page-level if it *selects* `<html>`/`<body>`, not only if it
    reads like it** (`page_elements`, `matches_page_element`). A utility
    framework paints the page from the element: ground.news writes
    `<body class="… bg-light-primary dark:bg-dark-primary …">`, and those beat
    its own `body { background-color: var(--background) }` on specificity. Match
    on `html|body|:root` alone and the reported ground is `#ffffff`/`#0a0a0a`
    — the value `--background` resolves to, which the page never paints —
    instead of `#eeefe9`/`#262626`.

    The class attribute is the only place this information exists; nothing in
    the stylesheet distinguishes `.bg-light-primary` on the body from
    `.bg-dark-primary` on a card. **Document order cannot substitute for it**:
    on ground.news the dark theme's `.dark\:bg-light-primary` is declared
    *after* the `.dark\:bg-dark-primary` the body actually carries, so ordering
    alone picks the wrong one. Test:
    `test_a_later_utility_the_body_lacks_does_not_win`.

    The matcher is deliberately narrow — one compound, no combinators, no
    pseudo-class but `:root` — because anything less certain than "this paints
    the page element" should defer to `_PAGE_SEL`. `.foo .bar` is a rule about
    a descendant; `.foo:hover` is not a resting background. Selector escapes
    are unescaped before comparing (`unescape_ident`, both `\:` and `\3a `),
    since CSS writes `.dark\:bg-x` for the class HTML spells `dark:bg-x`.

    `page_elements` returns `None` when it could not read the tags at all,
    which is **not** the same as an element with no classes. Treating unknown
    as empty would state a ground confidently on no evidence. Test:
    `test_unreadable_document_is_not_an_empty_one`.

17. **A selector list splits on commas at depth zero** (`split_selector_list`),
    never on the ones inside `:is()`, `:where()`, `:not()`, `:nth-child()`, an
    attribute value, or an escape. `.a:is(.b, .c), .d` is two selectors and a
    bare `split(",")` makes it three broken ones.

    This is load-bearing rather than pedantic because **Tailwind v4 compiles
    its dark variant to `.dark\:bg-x:where(.dark,.dark *)`** — with a comma
    inside the scope. Splitting there leaves `:where(, *)`, the theme's own
    rules stop being recognised as the theme's, and its ground silently falls
    back to a guess. Tailwind v3 emits `:is(.dark *)`, no comma, which is why
    this survived a corpus of one v3 site. Tests:
    `test_selector_list_splits_outside_parens_only`,
    `test_tailwind_v4_dark_variant_survives_the_split`,
    `test_tailwind_v4_shape_on_the_html_element`.

    Everything that reads a selector list splits it — `theme_scope`,
    `strip_theme_scope`, `selector_weight`, `detect_ground`, `build_var_table`.
    An earlier version had `theme_scope` judge the list as a whole, on the
    reasoning that "authors do not mix scoped and unscoped selectors in one
    rule." **Bootstrap 5.3 does, in its most important rule** —
    `:root,[data-bs-theme=light]` holds the entire base token set — so one
    unscoped selector in a list now makes the whole rule unscoped, and a list
    whose parts disagree is unscoped too. Test:
    `test_a_list_mixing_scoped_and_unscoped_is_unscoped`.

18. **A statement at-rule is consumed, not accumulated** (`parse_stylesheet`).
    `@charset`, `@import`, `@namespace` and `@layer a, b;` end in a semicolon
    rather than a block. Left in the prelude buffer they are glued onto the
    next rule's selector, so the *first rule of the sheet is lost*. Bootstrap
    opens with `@charset "UTF-8";`, which cost its entire `:root` token block
    and left 550 `var()` references resolving to nothing — printing
    `color:` and `rgba(,1)` into the palette. Test:
    `test_statement_at_rules_do_not_eat_the_first_rule`.

19. **A custom property defined on the page outranks one defined off it**
    (`build_var_table`). `var()` resolution is otherwise last-definition-wins,
    which is fine until a site ships a named theme nobody selected: Bootstrap's
    own docs carry `[data-bs-theme=blue] { --bs-body-bg: var(--bs-blue) }`, and
    last-wins reports the page background as Bootstrap blue. Definitions whose
    selector reaches `html`/`body`/`:root` — or a class the document actually
    carries, per invariant 16 — are laid down over the rest. Properties that
    reach no page element still resolve among themselves, because one consumed
    only by `.btn` is still worth reading. Test:
    `test_a_var_defined_off_the_page_does_not_win`.

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

- Anything needing numpy/Pillow goes in `images.py` behind a capability check
  that degrades with a message. A dependency in the core is now allowed where
  it buys accuracy — see the priority note at the top — but it should still
  earn its place against the corpus.
- Parsers return `None` for anything not understood rather than guessing.
  `color-mix()`, `light-dark()` and relative color syntax are skipped, not
  approximated.

  **`color-mix()` is now the largest single category of skipped color** — 631
  declarations on tailwindcss.com, 211 on ui.shadcn.com — and unlike a bare
  channel triplet it is not ambiguous: it is defined interpolation in a named
  space, and the OKLab/Lab machinery to evaluate it is already in `color.py`.
  Skipping it was right when slimness ranked first. It is now the highest-value
  parsing gap. `light-dark()` is two values and a theme choice, which this tool
  already models, so it is nearly free and directly relevant.
- Comments explain *why*, especially where a line looks redundant. Most of the
  invariants above are also stated at their call site — keep them in sync.
- Emitted token names sort naturally (`_natural`): `ink-2` before `ink-10`.
- British/American spelling is mixed in comments; not worth a pass.

## Known limits (documented, not bugs)

- **No JavaScript is executed.** A HAR captures runtime-injected styles up to
  export time; a color computed in JS and set as an element property is in no
  stylesheet and will not be found.
- **The cascade is approximated, not implemented.** Ground follows document
  order; `var()` resolution takes the last definition. Specificity, `@layer`
  and scoped custom properties are not modelled — beyond the narrow rules in
  invariants 2, 13 and 16, which exist because getting theme overrides or the
  ground wrong produces a whole palette of colors the site never paints. Fine
  for gathering a palette, wrong for predicting computed styles.

  Invariant 16 is a candidate-set rule, not a specificity model. It happens to
  land right on ground.news because the utility is declared after the `body`
  rule it beats, so document order agrees with specificity there. A site whose
  element-matched utility came *earlier* than a competing `body` rule would
  still be read wrongly.

  **Why not just compute specificity.** Specificity alone is computable from
  the selector — it is a mechanical `(ids, classes, elements)` count. It is
  also not enough on its own. The real cascade is
  `importance → layer → specificity → document order`, and a single page
  (tailwindcss.com) exercises all four: `!important` in values, `@layer` used
  structurally by Tailwind v4, `:where()` contributing zero specificity while
  `:is()`/`:not()`/`:has()` take the max of their arguments. Adding specificity
  *without* layers makes layered sites worse than document order does, because
  an unlayered rule beats any layered one regardless of how specific it is. So
  the options are all four or none, and all four is a cascade engine — which
  contradicts both the stated limit above and the stdlib-only core.

  The narrow version worth considering if a real case turns up: `!important` as
  a tiebreak *inside `detect_ground` only*, where the candidate set is already
  small and filtered. One bit, unambiguous, testable. Not implemented — no site
  in the corpus changes answer with it, and adding cascade machinery on
  speculation is how invariant 2 earned its warning.

  **The "all four or none" argument above assumed a stdlib-only core, which is
  no longer a constraint.** See **`PLAN.md`** — a phased migration to
  `tinycss2` + `cssselect2` that makes the full cascade tractable, with the
  library capabilities probed rather than assumed and the current corpus
  numbers recorded as its baseline. Proposed, not started.

- **A bare channel triplet used raw paints nothing, and is reported rather than
  parsed.** The shadcn/ui convention writes `--background: 0 0% 3.9%` and
  assembles it at the point of use. Assembled — `hsl(var(--background))`,
  `hsl(var(--x) / 50%)`, `rgb(var(--x))` — it parses here and always has; that
  path is covered by `TestChannelTriplets` because nothing advertised it.

  Used raw, as `background-color: var(--background)`, it is **not a color we
  are failing to read**. It is invalid CSS: verified against a real engine,
  `CSS.supports('background-color', '0 0% 100%')` is `false` and the computed
  value is `rgba(0,0,0,0)`. Reading a color out of it would invent one the page
  never shows. Do not "fix" this by teaching `find_colors` about loose
  triplets. `_triplet_warning` names the situation instead, in one aggregated
  note, so a site written this way does not look like an extraction failure.

  **`ground.news.har` is no longer an example of this**, and the story of why
  is worth keeping, because getting there took three passes and the first two
  answers were both wrong in the same way.

  It looked like a triplet site: the light and dark palettes came out nearly
  identical and the visible `--background: 0 0% 100%` seemed to explain it. It
  did not. The parse had been truncated by the `_mask_strings` escape bug in
  invariant 9, and two thirds of the declarations — including the `--background`
  hex definitions and their `lab()` equivalents — were being dropped.

  Fixing that gave `#ffffff` / `#0a0a0a`, which was still wrong, just less
  obviously: those are what `--background` resolves to, and `body {
  background-color: var(--background) }` really is in the CSS. But the page
  never paints it. `<body class="bg-light-primary dark:bg-dark-primary">`
  overrides it from the element, and the real grounds are `#eeefe9` / `#262626`
  — invariant 16.

  Two lessons, and the second is the one that cost the most. **Confirm the parse
  is complete before explaining a thin palette**, because a truncated parse
  produces a plausible wrong theory and there was one ready to hand. And **a
  ground that resolves cleanly is not thereby correct** — `#ffffff` came from a
  real rule, by a defensible mechanism, and was still not the color on the
  screen. Both wrong answers were self-consistent. What settled it each time was
  evidence from outside the parse: a screenshot of the running site.
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

## Breadth check

One site cannot tell you whether a parser change is general. Two of the bugs
above were found only by running a spread of stacks and diffing the grounds
before and after:

```bash
for u in getbootstrap.com ui.shadcn.com www.djangoproject.com \
         news.ycombinator.com developer.mozilla.org tailwindcss.com; do
  python3 -m palettekit "https://$u" -o "out/$u"
done
```

Bootstrap, shadcn/Next, a classic server-rendered site, plain hand-written CSS,
Tailwind v4, and a docs site — deliberately not all one framework. Expect most
grounds to be *unchanged* by any given fix; a change on a site you were not
targeting is the signal worth chasing. `tailwindcss.com` earns its place
specifically because it is **Tailwind v4** and `ground.news.har` is v3: v4's
`:where(.dark,.dark *)` broke invariant 17 in a way no v3 site could reveal.

URL fetches run no JavaScript, so several of these land on the inferred-ground
fallback. That is fine — the point is the *diff*, not the absolute answer.

## Migration TODO

Not yet present, needed for a real repo:

- [x] `pyproject.toml` — hatchling backend, version read from
      `palettekit/__init__.py`, console script, `images`/`images-fast`/`dev`
      extras, ruff config. Verified by building and installing the wheel.
- [ ] `LICENSE` + the `[project.license]` and classifier entries left commented
      out in `pyproject.toml`, and `.gitignore` (`__pycache__/`, `dist/`,
      `*.pyz`, `out/`)
- [ ] Fill in `[project.urls]` and the `authors` entry once the repo exists
- [ ] CI: run tests on 3.10–3.14, `ruff check`, and assert the package, zipapp
      and installed-console-script outputs match
- [ ] `Makefile` or `build.py` for the zipapp incantation above
- [ ] Move `test_palettekit.py` into `tests/` and split by module
- [ ] Fixture corpus of small HTML files per site archetype (framework-heavy,
      page-builder, dark, light, CSS-variable-driven) — the current suite leans
      on synthetic fixtures inline in the test file
- [ ] Decide whether `emit.to_document`'s dict shape is a versioned public API
      before anyone builds on it
