# palettekit

Reads a website's color palette out of its stylesheets and emits an
interactive HTML report plus JSON/CSS/SCSS/TS/Tailwind. Values are **parsed
from CSS, never sampled from pixels** — that is the whole premise, and it is
what makes the output exact rather than approximate.

**Work directly on `main`, set by the owner 2026-07-26.** No feature branches
for task completion — commit to `main` as work lands.

**Python 3.11+, verified** — the suite passes on 3.11, 3.12, 3.13 and 3.14, and
3.11 produces byte-identical JSON to 3.14 on the reference fixture. Raised from
a verified 3.10 on 2026-07-26 (owner decision, `PLAN.md` T2) because 3.10
reaches end-of-life in October 2026 — a calendar decision, not a technical one;
nothing in the codebase needs 3.11+ itself. Re-run the matrix rather than
trusting this line:

```bash
for v in 3.11 3.12 3.13 3.14; do
  uv run --python "$v" --with tinycss2 --with cssselect2 --no-project \
    python -m unittest discover
done
```

**Priority order, set by the owner (2026-07-26): accuracy and breadth first,
slimness second.** If a dependency makes the tool read more sites correctly,
take it. This reverses an earlier constraint, and two decisions were made under
the old one and have both since been acted on: the cascade is implemented
(invariant 21), and `color-mix()`/`light-dark()` are parsed rather than skipped
(invariants 22–23). `PLAN.md`'s four phases are all landed.

**Corollary, set by the owner (2026-07-26): defer to a library already in the
dependency set for anything it already does correctly; hand-roll only what it
cannot do.** This applies everywhere in the codebase, not only in the parser.
`color.py`'s `calc()` evaluator is the example that prompted stating it
explicitly: it tokenizes a `calc()` body with `tinycss2` (which already
handles CSS numeric syntax, dimension units, and paren/function nesting
correctly) and hand-rolls only the arithmetic and CSS-type-checking evaluation
on top — the one part no CSS tokenizer performs. An earlier version of that
evaluator hand-rolled its own regex tokenizer instead, alongside a comment
claiming `color.py` was "standard library only"; both were wrong under this
priority and have been corrected. Read this alongside invariants 16 and 17
before assuming every remaining hand-rolled scanner in the codebase is stale
by the same reasoning, though — some already weighed the library option and
were kept for a stated reason unrelated to slimness (`dom.py`'s tree shim
rules out `lxml` because it is a C extension and the zipapp's vendoring model
assumes pure Python; `split_selector_list` survived cssselect2 because several
of its callers run over selectors that are not guaranteed to compile).
Whether a broader dependency, like trading the pure-Python floor for `lxml`,
is worth taking is still the owner's call to make explicitly, the same way the
`tinycss2`/`cssselect2` migration itself was.

The core takes two dependencies, both pure Python and both by the same authors:
**`tinycss2`** (one transitive dep, `webencodings`) tokenises, and
**`cssselect2`** (whose only dep is `tinycss2`) parses selectors, matches them,
and counts their specificity. Everything above them — theme scopes, weighting,
`var()`, what counts as a theme, the cascade itself — is still ours. These are
phases 1, 2 and 3 of `PLAN.md`, all landed. Pillow/numpy remain optional and
reached only through `images.py`, behind `--images`.

## Commands

```bash
python3 -m palettekit <target> -o out    # target: .har | URL | .html/.css path
python3 -m unittest discover             # 113 tests, all must pass (needs the deps)
python3 -m palettekit x.har --no-themes  # collapse a two-theme site into one
ruff check .                             # must stay clean; config in pyproject
python3 -m palettekit x.har --list-sources   # diagnose framework noise first

pip install -e ".[dev]"                  # editable install + ruff/build/pytest
pip install -e ".[images]"               # adds pillow+numpy for --images
python3 -m build                         # wheel + sdist into dist/
python3 build.py                         # rebuild palettekit.pyz (see below)
```

Installing exposes a `palettekit` console script (`[project.scripts]`), so the
three ways to run it are `python3 -m palettekit`, `palettekit`, and the zipapp.
**All three must produce identical JSON for the same input** — that is the
cheapest possible regression check and worth keeping.

Compare with the `generated` key removed. It holds a wall-clock timestamp, so a
plain `diff` of two runs fails whenever they straddle a second boundary — which
looks exactly like a real mismatch and wasted a diagnostic pass once already.

Build the single-file distributable with **`build.py`** (`PLAN.md` T12):

```bash
python3 build.py
```

It does what used to be a six-command incantation copied from here into a
terminal: stages `palettekit/` into a temp dir with the `__main__.py` shim
zipapp requires (zipapp refuses a source tree that already has one), vendors
`tinycss2`, `cssselect2` and `webencodings` into that staging dir via `uv pip
install --target` (or plain `pip` if `uv` isn't on `PATH`) — a zipapp carries
no dependency metadata, so without this the `.pyz` imports fine on a machine
that happens to have them installed and fails everywhere else — strips
`__pycache__`/`*.dist-info`/uv's `.lock` marker, and zips the result. It then
**structurally asserts** all four vendored top-level packages
(`palettekit`, `tinycss2`, `cssselect2`, `webencodings`) are physically inside
the archive rather than smoke-testing by running it: running the built `.pyz`
on the same machine that built it would pass whether or not vendoring
happened, since site-packages is still on `sys.path` and a dev interpreter has
these installed regardless. That structural check is what actually catches a
skipped vendoring step — the failure mode the six-command version was silently
exposed to.

Reading `[project.dependencies]` out of `pyproject.toml` (via `tomllib`, free
at this project's floor) means the dependency list can't drift from the one
`pip install -e .` uses, the same discipline `PYTHON_FLOOR` applies to the
version guard below.

**Still a manual step, and still required**: run the built `.pyz` on an
interpreter that has *neither* dependency installed —

```bash
uv run --python 3.11 --no-project python palettekit.pyz <target> -o out
```

— because that is the one thing `build.py` cannot check from inside the same
environment it just built in. On a development machine every interpreter has
`tinycss2`/`cssselect2` already, so a broken vendoring step is invisible to it.

The package keeps its own `__main__.py` so `python3 -m palettekit` works from a
checkout. Module / console-script / zipapp builds must produce identical JSON
for the same input — checked by hand each session rather than in CI
(`PLAN.md` T11, decided against 2026-08-01: this project doesn't get a CI
pipeline).

**`main()` guards the Python floor before doing anything else**
(`palettekit.PYTHON_FLOOR`, read from one place and checked by
`test_pyproject_floor_matches_python_floor` against `pyproject.toml`'s
`requires-python`). A zipapp carries no `requires-python` of its own, so
without this an old interpreter used to fail deep inside `extract.py`'s
`zip(strict=)` calls — on two-theme sites only, looking exactly like a bug in
the tool — instead of at start-up with a readable message. Verified: `uv run
--python 3.10 --no-project python palettekit.pyz …` now prints `error:
palettekit requires Python 3.11+ (running 3.10.20).` and exits 1, instead of
the `TypeError` `PLAN.md` T1 diagnosed.

### Rebuild the zipapp before a work session is finished

**Process, set by the owner 2026-07-26: a session that changed anything under
`palettekit/` is not done until `palettekit.pyz` has been rebuilt from it.**
The tracked artifact is a shipped program, not a build leftover — `README.md`
tells readers to run it — so leaving it behind ships the previous version of
the tool under the current version's name.

This is not hypothetical. The committed `.pyz` sat four phases stale: it ran
the pre-`tinycss2` walker with every parsing bug the migration removed,
reproduced the reference fixture's anchors *exactly* so no check caught it, and
crashed on `ground.news.har` under a 3.9 interpreter. See `PLAN.md` **T1** for
the full diagnosis.

Two things were meant to make the rule stick; only one landed, and the other
was decided against rather than left open:

- **Automate it** (`PLAN.md` **T12** — done). `python3 build.py` replaces the
  six-command incantation, and its structural vendoring check replaces the
  silently-skippable step that let a human forget it.
- ~~**Assert it** (`PLAN.md` **T11** — still open). Module / console-script /
  zipapp JSON identity is already the rule two paragraphs up; in CI it turns a
  stale artifact into a failed build instead of a silent one.~~ — **T11
  decided against, 2026-08-01.** This project doesn't get a CI pipeline; a
  solo, unpublished tool doesn't carry the check's own maintenance surface
  well enough to justify it. The identity check itself is not abandoned, just
  manual.

So this stays a manual step, permanently rather than "until T11 lands":
rebuild with `python3 build.py` at the end of a session that touched
`palettekit/`, and **verify with an interpreter that has neither dependency
installed** — on a development machine every interpreter has them and a
missing vendoring step is invisible to a smoke test, though not to
`build.py`'s own structural check.

## Layout and data flow

```
sources.py   →  cssparse.py  →  extract.py  →  emit.py
(HAR/URL/     (tokenise,      (score, ground,  (JSON/CSS/SCSS/
 local files)  var(), roles,   merge, name —    TS/Tailwind/HTML)
               theme scopes)   once per theme)
                    ↑               ↑
                  dom.py  (which rules land on <html>/<body>)
```

| File | Lines | Holds |
|---|---:|---|
| `color.py` | 1182 | `Color`, parsing, sRGB↔OKLab/CIE Lab/XYZ both ways, `color-mix()`, `light-dark()`, `calc()`, contrast, hue names |
| `cssparse.py` | 926 | `tinycss2` integration, `var()`, `selector_weight`, roles, theme scopes, `@layer` names |
| `dom.py` | 300 | `html.parser` → `ElementTree` shim, `cssselect2` matching of `<html>`/`<body>`, specificity |
| `sources.py` | 292 | `load_har` / `load_url` / `load_paths` → `Bundle` |
| `extract.py` | 1209 | `extract()`, the cascade, per-theme `_build`, ground, merging, statuses, naming |
| `emit.py` | 952 | Emitters; `_HTML` is the report template |
| `images.py` | 148 | Optional image quantisation, not part of the token set |
| `__main__.py` | 255 | CLI; `main()` guards `PYTHON_FLOOR` before anything else |

`emit.to_document(palette)` returns the dict the JSON file holds — that dict is
the public data contract. The HTML report consumes the same dict, inlined into
a `<script type="application/json">`.

**It is a versioned contract, since `PLAN.md` T3.** A top-level
`schemaVersion` (`emit.SCHEMA_VERSION`, currently `1`) is separate from
`palettekit.__version__` and moves on its own schedule — an additive key never
bumps it, a removed or re-typed one does. The compatibility promise lives in
`README.md`'s Output section, not only here.

**`Declaration` is the parser seam for the declaration-producing pipeline.**
`tinycss2` stops at `cssparse._walk` for *that* purpose — turning a
stylesheet into `Declaration` objects — which is what made the phase-1 swap
reviewable and revertible, and still describes how a `Declaration`'s `value`
reaches everything downstream: as a plain string, not a token stream.

That is narrower than "nothing downstream of `Declaration` knows a tokeniser
exists," which this file used to claim outright and which the T5 corollary
above supersedes: `color.py`'s `calc()` evaluator (downstream of
`Declaration` by any reading) tokenizes a `calc()` body with `tinycss2`
directly, because it is the right tool for that narrow, self-contained
sub-problem and re-deriving it by hand was the actual mistake. The
distinction that still matters is that this is a **library used directly for
what it's good at**, not the cascade-aware pipeline the seam language was
protecting — nothing about var() resolution, theme scoping, or the cascade
itself moved into `color.py`, and `color.py`'s own tests still call
`parse_color()`/`find_colors()` on a plain string with no `Declaration`
involved. Notes on what `_walk` produces:

- **An at-rule nested *inside* a style rule takes the enclosing rule's
  selector** (`PLAN.md` T6, landed 2026-07-27). `.a { color: red; @media
  (min-width:1px) { color: blue } }` is native CSS nesting, and `blue` belongs
  to `.a` exactly as if the `@media` wrapper weren't there. `_walk` used to
  reset `selector`/`theme`/`theme_media` to empty for *every* at-rule block,
  which is right for a **top-level** at-rule (a qualified rule found inside
  `@media { .b {...} }` computes its own selector regardless) but was wrong
  here: with no selector, the declaration is read for its `var()` references
  only and then dropped, so the brace walker and `_walk` alike lost `blue`
  entirely. Fixed by carrying the enclosing `selector` through instead of
  resetting it, conditioned on whether one was already set.

  **`theme`/`theme_media` are not simply carried through unchanged** — a
  nested `@media (prefers-color-scheme: dark)` still has to be *found* as a
  scope, exactly as `media_theme(at_rules)` would find it if the enclosing
  rule weren't there. Carrying the enclosing theme through verbatim was the
  first draft of this fix and is a real regression, not a harmless
  simplification: `_theme_plan`/`_scopes_present` (`extract.py`) read
  `Declaration.theme` directly rather than recomputing it, so an unscoped
  enclosing rule would make the nested dark declaration come back
  `theme == ""` — unscoped, meaning every theme gets it, inventing a color the
  light theme never paints. The corrected version mirrors the qualified-rule
  branch's own `scoped or media` precedence: a selector-derived theme on the
  enclosing rule wins outright, and only an unscoped enclosing rule lets the
  nested media query supply one.

  Not observed on the frozen corpus either way — no bundle happens to nest an
  at-rule directly inside a style rule yet — which is exactly why `PLAN.md`
  called this "the one that gets worse on its own" as native nesting spreads.
  Tests: `test_an_at_rule_nested_in_a_style_rule_keeps_the_enclosing_selector`,
  `test_a_nested_media_theme_is_still_found_as_a_scope` — the second was
  written after a first-draft fix passed the first test while still recording
  the nested dark declaration as unscoped, and required to fail against that
  draft before being trusted.

- `var_refs` is collected from **every** declaration, including properties the
  role table drops. It decides `live` vs `saved` (invariant 10), and narrowing
  it to color-bearing properties would silently reclassify real tokens. It is
  no longer collected from at-rule *preludes*, which is a deliberate
  correction: `@supports not (hanging-punctuation:var(--tw))` is a Tailwind
  feature probe, and `--tw` is never defined or painted.
- `!important` is read off the token stream onto `Declaration.important` and is
  **no longer part of `value`**. It is the first term of the cascade
  (invariant 21).
- **`@layer` names ride on `Declaration.layer`, but their order does not.**
  Layers are global to the document — a sheet writing `@layer utilities {…}` is
  filling in a layer another sheet reserved — so the name is all a single sheet
  can know. `Stylesheet.layers` records first-mention order within the sheet
  and `extract.layer_order` merges those into the document's one true order.
  The statement form `@layer a, b;` and `@import url(…) layer(x)` (`PLAN.md`
  T8) are the only reasons `_walk` looks at statement at-rules at all
  (invariant 18): both declare no properties, and both reserve positions —
  `@import`'s `layer(x)` found as a `FunctionBlock` in `node.prelude`, not by
  regexing the serialized prelude (the T5/T15 corollary). `@import` itself is
  still not followed, so the reservation is all this route contributes; see
  "Known limits" below.
- `tinycss2`'s serializer inserts `/**/` where two tokens would otherwise
  re-merge, so `:nth-child(3n+1)` round-trips as `:nth-child(3n/**/+1)`. Valid
  CSS, and it reaches the selector strings in the JSON and the report. Cosmetic
  only — 38 declarations on tailwindcss.com, none of them page-level. Left
  alone deliberately: stripping it would need a string-aware scan over the
  serializer's output, which is the exact class of hand-rolled code this phase
  removed.

## Invariants — do not "simplify" these

Each of these looks like an over-complication and is not. Every one exists
because the obvious implementation produced plausible but wrong output.

1. **Contrast is computed from quantised `rgb255`, not the float channels**
   (`Color.luminance`). We print an 8-bit hex next to every ratio; computing
   from unrounded floats prints ratios that disagree with our own hex. Test:
   `test_contrast_matches_reported_hex`.

2. **Ground is resolved by the cascade, not by weight** (`detect_ground`).
   Weighting instead picks the framework's default background on any site that
   loads a framework before its own CSS. Everything downstream depends on this
   — alpha flattening and every contrast ratio are measured against the ground.
   Test: `test_ground_follows_cascade_not_weight`.

   **This warning is about `selector_weight`, the usage heuristic — not about
   CSS specificity, which is part of the cascade and does not conflict with
   it.** Keep that distinction in view: it is the one a reader arriving at
   invariant 21 will otherwise stall on.

   Since phase 3 the resolution is the real cascade
   (`importance → layer → specificity → order`, invariant 21) rather than
   document order alone. What invariant 16 changes is the *candidate set*, not
   how the winner is picked among them.

   The theme addendum this invariant used to carry is now one term of that key
   and is narrowed to the media case — see invariant 21.

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

9. **Strings and comments cannot be read as color** — now because `tinycss2`
   tokenises them as strings and comments. `content: "#fff"` is not a color.

   This *was* a hand-written masking pass, and the way it failed is a large
   part of why the parser was replaced. A backslash outside a string is an
   escape and the next character is never a delimiter; Tailwind arbitrary
   values put escaped quotes in the *selector* — `.bg-\[url\(\"…\"\)\]` — and
   reading one as a string opener masked through the following `{`, leaving the
   brace walker a level deep for the rest of the file. The parse still
   succeeded and quietly returned less, which is the worst way for this to
   fail: on `ground.news.har` it cost 178 of 181 themed rules and two thirds of
   every declaration, and made a site with two obvious themes look like it had
   one. The test stays and now guards the *integration*:
   `test_escaped_quote_in_a_selector_does_not_swallow_the_rest`.

   **What the swap changed downstream is that string contents are no longer
   blanked**, so `[role="complementary"]` reads as itself instead of
   `[role=" "]`. That corrected real misreadings — django's
   `html[data-theme="dark"]` theme was entirely invisible, and a
   `url(data:image/png;base64,…)` value was being truncated at the semicolon
   inside it — and it exposed one latent bug, which is invariant 20.

   **The claim that `find_colors` itself refuses a string was not fully true
   until T17 (2026-07-27, `PLAN.md`).** `content: "#fff"` never reached
   `find_colors` at all — `content` is not in `PROPERTY_ROLE`, so `_record`
   drops the declaration before this module ever sees it, which is a
   different protection than the one this invariant describes. A property
   that *is* color-bearing and legitimately carries a quoted string —
   `background-image: url("data:image/svg+xml,...stroke='black'...")`, real
   shapes on `tailwindcss.com.har`'s bundled DocSearch CSS and
   `fleshandbonedesign.com.har` — did reach
   the old regex-based scanner, which read the SVG markup's own
   `stroke='black'`/`fill='white'` attributes as CSS colors: exactly this
   invariant's mistake, one `url()` layer past where its own test looks. T17's
   token walk never opens a `url()`'s argument, quoted or not, so this is now
   true the way it was already written. See T17's write-up for the corpus
   count (58 declarations, all one `url()` shape or the other, all removals).

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

    **`PLAN.md` predicted phase 3 would retire this as a specificity
    approximation. It does not, and the prediction misread what the rule
    does.** This decides **which colors enter the palette at all**; the cascade
    decides **which value a property resolves to**. Those are different
    questions, and no amount of ranking answers the first — a color the dark
    theme never paints is still in the bucket, correctly ranked and still
    wrong. Kept verbatim, its test untouched.

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
    reads like it** (`dom.py`). A utility
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

    **This is a candidate-set rule, and phase 3 did not retire it** — `PLAN.md`
    predicted "the matcher decides" and that is only half true. A real matcher
    over-matches, which is what `_is_blanket` below exists for, so *which*
    rules are candidates stays a decision made here. What phase 3 did retire is
    the limit that used to sit under this: ground.news happened to declare its
    utility after the `body` rule it beats, so document order agreed with
    specificity **by luck**, and a site written the other way round was read
    wrongly. Invariant 21 now decides it on specificity. Test:
    `test_specificity_beats_a_later_rule_of_lower_specificity`.

    **The matcher is `cssselect2`'s, over a real tree** (phase 2). It used to
    be a regex over one compound selector, deliberately narrow because a
    hand-rolled matcher cannot be trusted past `.foo.bar[x=y]` — a combinator,
    an `:is()` or an unfamiliar pseudo-class simply failed to match and
    deferred to `_PAGE_SEL`. `.foo .bar` and `.foo:hover` are still False, and
    that is now a *conclusion* rather than a refusal to answer: the body is not
    a descendant of itself, and a hover state is skipped by an explicit rule.
    Escapes need no special handling now — `.dark\:bg-x` and `.dark\3a bg-x`
    both reach the class HTML spells `dark:bg-x`, because the selector parser
    unescapes them.

    **Three kinds of selector are refused, and all three are rules**
    (`dom.matches_page_element`): one carrying a pseudo-element (`body::after`
    paints a generated box, not the page); one standing on a dynamic state
    (`:hover`, `:focus`, `:target` — the ground is what the page looks like at
    rest); and one that lands on **everything**.

    That last is the only place a real matcher needed reining in, and it is
    measured rather than theoretical (`dom._is_blanket`). `*` and `:root *` do
    select `<html>`, so `cssselect2` says yes — and counting them as page-level
    is how Tailwind v4's reset block (`* { --tw-gradient-from: #0000;
    --tw-ring-offset-color: #fff; … }`) comes to outrank every utility that
    sets those properties to a color the site actually paints. On the corpus
    that moved 11 named colors on ground.news to `#0000`/`#fff`, and took
    MDN's `light-dark()` polyfill from a light/dark pair to its dark branch
    alone. A blanket rule reaches the unselected theme too, so it earns nothing
    by the argument invariant 19 exists for; and the universal selector is the
    weakest thing in CSS, so promoting it inverts the cascade. Tested by
    matching against a nondescript element rather than by pattern-matching the
    selector text. Test:
    `test_a_blanket_rule_is_not_a_statement_about_the_page`.

    A selector `cssselect2` cannot compile is False rather than an error, which
    is required and not defensive: `strip_theme_scope` can emit `:is( , …)`
    (the nesting `_not_spans` documents as unmodelled), and real CSS carries
    pseudo-classes no library knows. Test:
    `test_a_selector_that_will_not_compile_is_false_not_an_error`.

    **The tree is a ~60-line `html.parser` shim, not `html5lib`**
    (`dom._TreeBuilder`). It does no implied-tag insertion beyond one rule —
    `<head>` and `<body>` are children of `<html>`, always — so misnesting
    below the page element is preserved as written. That cannot reach an answer
    here, because the only elements ever tested are `<html>` and `<body>` and
    the only structure a selector can ask about them is their ancestry. The one
    implied tag is not optional: `</head>` is routinely omitted, and without it
    the body nests inside the head, `html > body` stops matching and
    `head .foo` starts. `lxml` is a C extension and is ruled out by the
    pure-Python floor. Tests: `test_messy_markup_still_places_the_page_element`,
    `test_a_real_matcher_answers_what_the_narrow_one_refused`.

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
    The *parser* no longer needs it (`tinycss2` hands back one prelude per
    rule), which is why `PLAN.md` phase 1 listed it for deletion.

    **Phase 2 kept it too, deliberately.** `cssselect2` splits a list while
    compiling it, but every one of those five callers works on selectors that
    may not compile — `theme_scope` and `selector_weight` run over raw preludes
    from any stylesheet on the page, and `strip_theme_scope` can *produce*
    something invalid (`:is( , …)`, per `_not_spans`).

    **Phase 2 predicted it would go in phase 3, "once every selector has a
    compiled form it can rely on." It did not, and the prediction should not be
    made a third time.** Phase 3 added a sixth caller rather than removing any:
    `_page_specificity` has to walk the *matched* form of a selector list and
    the *declared* form in step, part by part, because it matches on one and
    scores on the other. Nothing compiled gives you that pairing, and either
    form may fail to compile. It stays.

    An earlier version had `theme_scope` judge the list as a whole, on the
    reasoning that "authors do not mix scoped and unscoped selectors in one
    rule." **Bootstrap 5.3 does, in its most important rule** —
    `:root,[data-bs-theme=light]` holds the entire base token set — so one
    unscoped selector in a list now makes the whole rule unscoped, and a list
    whose parts disagree is unscoped too. Test:
    `test_a_list_mixing_scoped_and_unscoped_is_unscoped`.

18. **A statement at-rule declares nothing** — `@charset`, `@import`,
    `@namespace` and `@layer a, b;` end in a semicolon rather than a block, and
    `_walk` skips them on `node.content is None`.

    The brace walker had to be told this, and left in its prelude buffer they
    were glued onto the next rule's selector, so the *first rule of the sheet
    was lost*. Bootstrap opens with `@charset "UTF-8";`, which cost its entire
    `:root` token block and left 550 `var()` references resolving to nothing —
    printing `color:` and `rgba(,1)` into the palette. Test:
    `test_statement_at_rules_do_not_eat_the_first_rule`.

    **`@layer a, b;` is the one exception, and it declares no *property*.** It
    declares the **order**, which is the entire reason a site writes the line —
    it reserves positions before any block fills them, and Tailwind v4 opens
    with one. `_walk` registers the names and still skips the rule. Test:
    `test_a_later_layer_wins_and_the_statement_form_sets_the_order`.

19. **A custom property defined on the page outranks one defined off it**
    (`build_var_table`). A site ships a named theme nobody selected:
    Bootstrap's own docs carry `[data-bs-theme=blue] { --bs-body-bg:
    var(--bs-blue) }`, and last-definition-wins reports the page background as
    Bootstrap blue. Definitions whose selector reaches `html`/`body`/`:root` —
    or a class the document actually carries, per invariant 16 — are laid down
    over the rest. Properties that reach no page element still resolve among
    themselves, because one consumed only by `.btn` is still worth reading.
    Test: `test_a_var_defined_off_the_page_does_not_win`.

    **`PLAN.md` predicted this would become "a specificity consequence rather
    than a special case." It is not, and believing so would have reintroduced
    the exact bug it prevents:** `:root` and `[data-bs-theme=blue]` are **both
    `(0, 1, 0)`**, so specificity cannot separate them at all, and the blue
    block is written later. This is a **matching** rule, and matching is the
    cascade's own first step — only declarations from rules that match the
    element are ranked against each other, and the document's `<html>` carries
    no `data-bs-theme=blue`.

    What phase 3 changed is only how the page-reaching set resolves among
    itself: the full key of invariant 21 instead of last-wins. **Off-page
    definitions stay on last-wins**, deliberately — they are a fallback, and
    ranking declarations that match *different* elements by specificity is
    precisely the error above.

20. **A theme marker inside `:not()` is a negation, not a scope**
    (`_not_spans`, `_negation_free`). `theme_scope` takes its match outside
    every top-level `:not(...)`, and `strip_theme_scope` leaves the negation
    untouched — stripping the marker out of it would leave `html:not()`, which
    selects nothing and is how the ground stops being found.

    django's docs are the case:

    ```css
    @media (prefers-color-scheme: dark) {
      html:not([data-theme="light"]) { --body-bg: #0e1117; --sidebar-bg: #181d27 }
    }
    ```

    Read that marker as a scope and the dark theme's entire token block — 124
    declarations, the ground among them — is filed under *light*. Skipped, the
    rule falls through to the media query, which says dark. With no media query
    around it, "everything except light" is not attributable to one theme, so
    it comes back unscoped, which is the honest answer rather than a guess.

    This bug predates the `tinycss2` swap; it was hidden because the old
    masking blanked `"light"` to `" "` and the attribute matcher never fired.
    Worth remembering as a shape: **a correctness fix can uncover a second bug
    that the first one was masking**, and the count that exposed it here was a
    declaration-level diff of old parser against new, not the test suite.
    Test: `test_a_marker_inside_not_is_a_negation_not_a_scope`.

21. **The cascade is `importance → layer → specificity → document order`, and
    it is all four terms or none** (`_cascade_key`, phase 3). Two call sites
    use it and only two: `detect_ground` and `build_var_table`.

    **Not three terms, and not a subset.** `!important` is not a tiebreak
    bolted onto the end — among important declarations the **layer order
    reverses**, so the *earlier* layer wins and an unlayered important
    declaration is the weakest important one there is. Importance changes what
    the next term means. And specificity without layers is worse than plain
    document order on any layered site, because an unlayered rule beats every
    layered one however specific it is — which is most of Tailwind v4.
    Tests: `TestCascade`.

    **Specificity is `cssselect2`'s, not a count of our own.** `:where()`
    contributes zero, `:is()`/`:not()`/`:has()` take the *maximum* of their
    arguments. Counting those by pattern is how a hand-rolled cascade gets
    Tailwind v4 backwards — `.dark\:bg-x:where(.dark,.dark *)` is one class,
    not two.

    **Matching reads the themed selector; scoring reads the declared one**
    (`_page_specificity`). `html.dark body` has to be *seen* as the dark
    theme's `body` rule, because that is the form this tool's theme model
    recognises — and *scored* as `html.dark body`, because that is what a
    browser counts. Keeping both is what makes a selector-scoped theme outrank
    what it overrides with no rule saying so, which is half of invariant 2's
    old theme addendum now retired into the key.

    The other half survives as one term. A `prefers-color-scheme` block has no
    specificity advantage at all over what it overrides, so it needs
    `Usage.theme_media` to beat a later unscoped rule. **That term sits between
    specificity and document order, and the placement is load-bearing**: a
    media-dark `body` must beat a later unscoped `body`, and must *lose* to an
    unscoped `.bg-x` the body carries, because a browser applying the dark
    theme still applies the class on top of it. Above specificity it would get
    the second backwards. Test:
    `test_a_media_theme_loses_to_specificity_but_beats_order`.

    **Ordering is still the last term and still decides most real ties.** On
    the corpus this key changed **no ground and no candidate rank** — every
    site's answer was already right. What it moved was twelve custom-property
    resolutions across three sites, each one a fix, none of them a color: see
    `PLAN.md`'s phase 3 outcome. **The value of this invariant is insurance
    against a class of site the corpus does not contain**, which is a real
    result and an easy one to mistake for a no-op.

    **`<html>` and `<body>` candidates are resolved in separate pools, body
    preferred** (`detect_ground`, T7, landed 2026-07-27). The cascade never
    ranks the two elements together — it resolves each on its own, and the
    page's visible color is the body's background where it has one, because
    `<body>`'s own box paints over the `<html>` canvas wherever it covers it,
    which in practice is the whole viewport. That preference holds however
    important or specific `<html>`'s rule is; it is not itself a cascade term
    and does not compete with one.

    **One exception, found by a test built to demonstrate it rather than by
    the corpus: an `<html>` rule written specifically for this theme still
    outranks an unscoped `<body>` rule.** Tailwind v4's `dark:bg-gray-950` on
    `<html>` is exactly this shape, and `test_tailwind_v4_shape_on_the_html_element`
    already asserted it before T7 existed — an unscoped `body {}` rule
    (present in every theme's build by definition) is not a statement about
    the dark theme, and preferring it over a rule that *is* the theme would be
    invariant 16's own mistake relocated to the other pool. So body wins
    unless `<html>`'s candidate is theme-scoped (`Usage.theme_scoped`, true for
    either scoping mechanism) and body's is not. Implementing the plain
    unconditional reading of "prefer body" first broke that pre-existing test
    — the discriminating case this note exists to save a future rewrite from
    rediscovering.

    Measured rather than assumed either way: instrumenting every candidate
    with the element it reaches showed no corpus site has page-level
    backgrounds on both `<html>` and `<body>` — every candidate on all four
    frozen bundles targets `<body>` except tailwindcss.com's dark theme, which
    is `<html>`-only with no competing `<body>` candidate to prefer or defer
    to. All four bundles are byte-identical before and after. This is
    insurance, like most of phase 3.

22. **A `color-mix()` this tool cannot evaluate contributes nothing — not the
    colors written inside it** (`find_colors`, phase 4). `color-mix(in oklch,
    #b4d455 calc(50% - var(--x)), transparent)` has a perfectly readable hex in
    it and the page paints a translucent version of it, not that. Before
    phase 4 the token scan reached inside and reported the hex at full
    opacity; now the call is evaluated as a unit or skipped as a unit. Same
    for `light-dark()`: if the branch this theme selects will not parse, the
    *other* branch is not a fallback, because it is a color this theme does
    not use. Tests: `test_a_mix_that_cannot_be_evaluated_yields_nothing`,
    `test_a_branch_that_will_not_parse_yields_nothing`.

    **A `calc()` percentage evaluates when it is literal arithmetic** (`T5`,
    `color.eval_calc_percentage`) — `calc(60 * 1%)` is the shape
    ui.shadcn.com's `.shimmer-color-*` declarations ship, six of them
    corpus-wide, and defaulting them to 50% would have printed a color the
    page does not paint, same reasoning as everywhere else in this invariant.
    The evaluator is a small recursive-descent grammar over `+ - * /` and
    parens, typed the way CSS itself types `calc()`: like units add,
    `<number> * <percentage>` is a percentage, `<percentage> * <percentage>`
    and division by a percentage are not (there is no percentage-squared or
    percentage-reciprocal type to hand back). **`var()` inside the `calc()`,
    any unit other than `%`, and anything else outside that grammar returns
    `None`** — the guaranteed-invalid-keyword handling invariant 26 needed for
    `initial` is a narrow, deliberate exception to "parse or refuse" made at
    one call site for one keyword; this is the opposite shape, a generic
    evaluator that refuses everything it wasn't built to type-check, rather
    than special-casing the one shape the corpus happens to ship. Verified
    against a frozen `ui.shadcn.com` bundle, old code against new, at the
    per-declaration color list: exactly six declarations move, three per
    theme, all `.shimmer-color-blue-500\/60 { --shimmer-color }` — the whole
    predicted blast radius. Ground and every other token are unchanged. Tests:
    `test_a_literal_calc_percentage_in_a_mix_is_evaluated`,
    `test_calc_outside_the_supported_subset_yields_nothing`.

    **The zero-alpha short circuit in `mix_colors` is accuracy, not speed.**
    `color-mix(in <space>, X p%, transparent)` is Tailwind's opacity modifier
    and ~90% of every mix on the corpus. With the other alpha at zero the
    premultiplied algebra collapses exactly — every weighted coordinate is X's
    own — so the answer is X at `alpha × p` with no interpolation at all.
    Converting to OKLab and back instead lands ±1 off on some channels, and
    invariant 7 keys buckets on the quantised `hexa`, so that drift invents
    palette entries out of rounding. Test:
    `test_a_mix_with_transparent_is_the_color_at_that_alpha`.

    **The powerless-hue thresholds are per-space and are noise floors, not
    perceptual ones** (`_SPACES`). A true grey converts to a chroma of ~1e-5 in
    CIE Lab and ~4e-8 in OKLab, all of it accumulated rounding; the nearest
    genuinely tinted grey, `#808081`, sits at 0.56 and 1.5e-3. One shared
    epsilon cannot serve both — Lab chroma runs to ~150 and OKLab chroma to
    ~0.4 — and getting it wrong means a grey's arbitrary hue angle is averaged
    into every polar mix. Test: `test_a_powerless_hue_is_carried_forward`.

23. **`light-dark()` is a theme mechanism, not just a value** (`_scopes_present`,
    phase 4). A site that writes it ships both themes by definition, so one
    `light-dark()` carrying color declares both scopes — while the declaration
    itself stays *unscoped*, so each palette reads it once and takes a
    different branch.

    Resolving the branch without registering the scope is the tempting half of
    this and is worse than doing nothing. developer.mozilla.org ships no
    `prefers-color-scheme` block and no theme class worth the name; the
    function is the entire declaration of its dark theme. Branch-only would
    have picked light everywhere and **deleted** every dark color the tool
    used to report. With the scope, MDN goes from one theme to two —
    `#ffffff` / `#18191b`, both read from `html { background-color }` rather
    than inferred. Tests: `TestLightDark`.

    **"Ships both themes by definition" overreaches slightly, and the caveat is
    worth carrying.** `light-dark()` resolves against the *used* `color-scheme`,
    whose initial value is `normal` — light. A page that writes `light-dark()`
    and never declares `color-scheme: light dark` renders the light branch
    whatever the OS says, and calling that page two-themed is wrong. **This
    tool cannot currently tell the difference**: `color-scheme` is neither a
    custom property nor in `PROPERTY_ROLE`, so `_record` drops it and it never
    reaches a `Declaration`. Checked against the corpus rather than assumed —
    MDN's CSS carries nine `color-scheme` declarations including
    `color-scheme:light dark`, so its two themes are real, and it is also the
    only corpus site using the function at all. Reading `color-scheme` is the
    fix if a counter-example turns up; it has not.

24. **`resolve_vars` substitutes tokens, not spliced text, so no separator has
    to be guessed by hand.** CSS substitutes *tokens*; a text splice has to
    guess whether two adjacent values need a separator, and guessing wrong
    manufactures colors. Tailwind v4 minifies to

    ```css
    color-mix(in oklab,var(--color-white)var(--tw-shadow-alpha),transparent)
    ```

    — two component values needing no separator. Pasted together as text they
    give `#fff100%`, which the color scanner read as the hex `#fff100`: a
    bright yellow, 18 occurrences on ground.news, painted nowhere on it. Two
    correct values and one missing space invent a whole color.

    **Originally fixed (phase 4) with a hand-derived padding heuristic,
    `_GLUE_LEFT`/`_GLUE_RIGHT`** — a character-class check of what may abut
    what, run against the surrounding text before splicing. **T16 (2026-07-27)
    replaced the whole text-splice design**: `resolve_vars` now tokenizes
    `value` once with `tinycss2.parse_component_value_list`, walks it for
    `var()` `FunctionBlock`s (`cssparse._substitute_vars`), and splices each
    one's resolved value in as *tokens*, before re-serializing the whole list
    with `tinycss2.serialize()` — the library's own adjacency rule (the same
    one that inserts `/**/` to stop `:nth-child(3n+1)` from re-merging into
    `:nth-child(3n)`, above) decides spacing instead of a hand-derived
    character-class check.

    **That rule disambiguates with a `/**/`, and it is turned into a plain
    space before the result leaves `resolve_vars`.** A comment is the
    textually-correct fix and `tinycss2` itself reads it back losslessly, but
    it is not invisible to this codebase's own downstream `color-mix()`
    parsing (`_split_component`, `_split_top`) — both re-tokenize a serialized
    text body rather than reusing a token list already free of comments, and
    neither treats a `comment` token as insignificant the way they treat
    whitespace. `find_colors`'s own outer scan (`color._collect_colors`, T17,
    2026-07-27) stopped needing this note: it tokenizes with
    `skip_comments=True` directly, so a stray `/**/` is dropped before the walk
    ever sees it. `_split_component`/`_split_top` are not, which is why the
    blind replace below is still load-bearing. Left as `/**/`,
    `color-mix(in oklab,var(--white)var(--alpha),transparent)` resolves to
    `#fff/**/100%`, and `_split_component` reads the color half as `#fff/**/`
    — which `parse_color` cannot parse — silently losing the color instead of
    reading it. **This is safe as a blind string replace, not merely
    convenient**: no declaration value this project ever holds can contain a
    real comment in the first place — `tinycss2.parse_stylesheet`/
    `parse_blocks_contents` are both called with `skip_comments=True`
    throughout `cssparse.py` — so the only `/**/` that can ever appear in
    `value` or in a table-stored value is one this same replacement already
    turned into a space one recursion level down. Test:
    `test_var_substitution_does_not_glue_two_tokens_into_one`, which fails
    without the replacement — checked directly, per the "a test that passes
    before and after tests nothing" discipline below.

25. **A `var()` call's fallback is read off its own already-parsed
    `.arguments`, because a fallback is a whole value.** A fallback can hold
    functions of its own:

    ```css
    background-image: var(--shimmer-image, linear-gradient(…, color-mix(…) …))
    ```

    — ui.shadcn.com. **Originally fixed (phase 4) by delimiting the call with
    `_var_call`, counting parentheses via `color.balanced_end`** rather than
    stopping at the first `)` the way a non-greedy regex had — that regex used
    to cut this shape at the `)` closing `calc(`, leaving a truncated call and
    the rest of the declaration behind as an orphaned tail that then resolved
    a second time, doubling the weight of every color in a discarded fallback:
    204 declarations across ground.news, tailwindcss.com and ui.shadcn.com,
    most of them Tailwind's `--tw-gradient-stops: var(--tw-gradient-via-stops,
    <the same stops>)`.

    That is why this had to be diffed at the per-declaration color list and not
    at the palette: **every hex set, ground and warning on all eight corpus
    sites is identical before and after** that phase-4 fix. What moved was
    occurrence counts, and through them the ranking that names tokens — on
    ui.shadcn.com `#378add` goes from `blue-7` to `blue-14` and `#303030`
    moves from the grey group to surface. A palette-level check would have
    called this a no-op and a hex-set check would have agreed with it. Tests:
    `test_a_var_fallback_may_contain_parentheses`,
    `test_a_discarded_fallback_does_not_come_back_as_a_second_copy`.

    **T16 (2026-07-27) replaced `_var_call`/`balanced_end`-counting with the
    structural version of the same guarantee.** `tinycss2` already groups a
    fallback's own nested functions and parens into single nodes inside the
    `var()` call's `.arguments`, so the first top-level comma is just a
    `LiteralToken` sitting directly in that flat list
    (`cssparse._var_name_and_fallback`) — no parenthesis-counting scanner is
    needed to find it. The discard-fallback behavior falls out for the same
    structural reason: a resolved name's replacement tokens are spliced in
    place of the whole `FunctionBlock`, fallback included, so there is no
    orphaned tail left over to be found and resolved a second time — the class
    of bug this invariant exists for cannot occur by construction, not merely
    by a scanner finding the right boundary. Both tests above continued to
    pass through the rewrite, though neither discriminates it: they were
    already passing against the phase-4 `_var_call` implementation this
    replaced, so their value here is regression coverage, not proof the new
    code is right — see the corpus-diff and the string-splice hazard invariant
    24 documents above for what actually exercised T16 itself. Kept rather
    than dropped: they still guard the next rewrite of this area, which is not
    hypothetical — T17 below touches the color scanners these same fallback
    shapes flow into.

    The removals the original phase-4 diff surfaced — 124 of them — were *not*
    this bug. One of them, `initial` read as a plain value, is invariant 26
    below. The other — a property resolved from a rule the consuming element
    never matched — is still written up under "Known limits".

26. **A custom property whose stored value is the literal keyword `initial`
    is treated as absent, not substituted as text** (`resolve_vars`). On a
    custom property, `initial` **is** the guaranteed-invalid value — a
    browser resolving `var(name, fallback)` against it uses the fallback, it
    does not paste in the four letters `initial`.

    Tailwind v4 guards every registered property this way for browsers with
    no `@property`: `@layer properties { *, ::before, ::after, ::backdrop {
    --tw-gradient-via-stops: initial; … } }`. Reading `initial` as an ordinary
    stored value — which a browser cannot do either — resolved
    `var(--tw-gradient-via-stops, <the real stops>)` to the inert text
    `initial` and found no color in it, at 108 declarations on
    tailwindcss.com's dark theme.

    **Matched on the stored value, not the substring.** `--a: initial-value`
    is a real, readable value and must not be treated as the keyword; the
    check trims and case-folds, then compares for equality. No other
    CSS-wide keyword is handled here — `unset` on a custom property is
    equivalent to `inherit`, which is a real resolvable value once
    inheritance is modelled, and that is the "scoped custom properties are not
    modelled" limit below, not this one.

    **Verified against a frozen `tailwindcss.com` bundle**, old code against
    new: the dark theme's dominant `violet` token (`#ad46ff`) goes from 29 to
    137 occurrences and its dominant `teal` token (`#00d5be`) goes from 22 to
    130 — an exact match to the numbers this invariant's fix was predicted
    against, reproduced on a fresh fetch. No ground moved, and total token
    count was unchanged in both themes — usages restored on existing entries,
    no hue invented. `ground.news.har` and `fleshandbonedesign.com.har` are
    byte-identical before and after (neither uses this guard shape). Test:
    `test_initial_custom_property_falls_back`,
    required to fail against the prior implementation before it was trusted.

    **ui.shadcn.com's `--shimmer-image` looks like the same bug and is only
    half of it** — it is `initial` in the guard *and* `none` from two
    utilities the shimmering element never carries, so this invariant alone
    still leaves `none` winning by last-wins. That half is the "scoped custom
    properties are not modelled" limit below, not this one.

## Status vocabulary

| Status | Means | Detected by |
|---|---|---|
| `live` | Actually painted | default |
| `saved` | Custom property nothing references — usually a design tool's saved swatches | `_status_for` vs `var_refs` |
| `inert` | Declaration that paints nothing, e.g. `drop-shadow(0 0 0 #13330d)` | `is_inert_shadow` |

## Themes

`theme_scope` recognises two mechanisms: a `prefers-color-scheme` media query
(`media_theme`), and a class or attribute on a wrapper (`selector_theme` —
`.dark`, `.theme-dark`, `.is-light`, `[data-theme="dark"]`,
`[data-bs-theme=dark]`, …). Both are scopes over declarations. Selector-scoped
is the common case — Tailwind's `dark:` variant compiles to it — so
media-query-only detection would miss most modern sites.

**A third arrives from a different direction: `light-dark()`** (invariant 23).
It is not a scope over declarations but over one *value*, so it is detected in
`_scopes_present` rather than in `theme_scope`, and the declaration carrying it
stays unscoped — each palette reads it and takes its own branch. A site using
it ships both themes whether or not it says so any other way, which is how
developer.mozilla.org's dark theme is found at all.

**Which of the two answered is recorded on `Declaration.theme_media`**, and it
is a cascade input rather than bookkeeping: a selector-scoped theme states its
scope in the selector, so it outranks what it overrides on real specificity,
while a media-scoped one is identical to it on every term there is. See
invariant 21.

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
  Relative color syntax (`oklch(from white l c h)`) is skipped, not
  approximated.

  **`color-mix()` and `light-dark()` are parsed** since phase 4 — 895 and 70
  declarations on the corpus respectively — in eleven interpolation spaces:
  `srgb`, `srgb-linear`, `hsl`, `hwb`, `lab`, `lch`, `oklab`, `oklch`, `xyz`,
  `xyz-d50`, `xyz-d65`. A space outside that list returns `None`. A `calc()`
  percentage evaluates when it is literal arithmetic (`T5`) and returns `None`
  outside that subset — see invariant 22's `calc()` note. Invariants 22–23 are
  what the implementation is *not* allowed to do; read them before touching
  `mix_colors`.
- Comments explain *why*, especially where a line looks redundant. Most of the
  invariants above are also stated at their call site — keep them in sync.
- Emitted token names sort naturally (`_natural`): `ink-2` before `ink-10`.
- British/American spelling is mixed in comments; not worth a pass.

## Known limits (documented, not bugs)

- **No JavaScript is executed.** A HAR captures runtime-injected styles up to
  export time; a color computed in JS and set as an element property is in no
  stylesheet and will not be found.

- **A nested *qualified rule* is not combined with its parent selector.**
  `.a { .b { color } }` records the inner declaration's selector as `.b`, not
  `.a .b`, and `&:hover` is kept literally rather than resolved against `.a`.
  T6 (above, and `PLAN.md`) fixed the sibling case — an at-rule with no
  selector of its own inheriting the enclosing rule's — but a nested
  qualified rule already has a selector, `_walk` just doesn't compose it with
  the parent's. Out of T6's scope; unfiled otherwise.

- **The cascade is implemented where it decides an answer, and nowhere else.**
  Phase 3 made `importance → layer → specificity → document order` real
  (invariant 21) at the two places a wrong answer produces a palette of colors
  the site never paints: `detect_ground` and `build_var_table`. **This is not a
  cascade engine and does not compute anyone's styles.** What is still not
  modelled:

  - **Only two properties are resolved this way** — the page background, and
    what a custom property holds. Every other declaration goes into the palette
    as written, because the palette wants every color a site declares, not the
    one that won on some element.
  - **`@import url(…) layer(x)` reserves `x`'s position** (`layer_order`,
    `PLAN.md` T8), but the imported sheet's *content* still isn't modelled —
    `@import` itself is still not followed, so nothing ever lands in that
    layer from this route; the reservation just stops a later real `@layer
    x {…}` elsewhere in the document from silently mis-ordering around it.
  - **Scoped custom properties (`@property`, and inheritance down the tree)**
    are not modelled. A property redefined on `.card` resolves globally here.
  - **An at-rule nested inside a style rule** still loses its declarations —
    see the limit above; it is a parse-shape gap, not a cascade one.

  **Why all four terms and not a cheaper subset**, which is the tempting
  mistake and was argued through before it was built: specificity alone is a
  mechanical `(ids, classes, elements)` count, and adding it *without* layers
  makes layered sites **worse** than document order, because an unlayered rule
  beats every layered one however specific it is — which is all of Tailwind v4.
  And `!important` cannot be a final tiebreak, because it *reverses* the layer
  term. A single page (tailwindcss.com) exercises all four. So it was all four
  or none, and "none" was the honest answer only while the core was
  stdlib-only.

  **`selector_weight` is not this and never was.** It is a usage heuristic that
  orders the palette, invariant 2's warning is about it, and phase 3 left it
  untouched. Treat its ordering as a hint.

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
- **A `calc()` inside a `color-mix()` percentage evaluates only literal
  arithmetic** (`T5`, landed 2026-07-26 — see invariant 22). `var()` inside the
  `calc()`, a unit other than `%`, percent×percent, and division by a
  percentage all still skip the whole mix rather than guessing, because none
  of them has a defined percentage-typed answer this tool can compute without
  either resolving a variable it isn't positioned to resolve or inventing a
  unit conversion. Not observed on the corpus beyond the shape T5 already
  fixed; the remaining gap is theoretical until a site exercises it.

- **A custom property whose winning definition is a value set on an element
  the `var()` is not consumed on resolves to that value anyway.** This is the
  gap the balanced parse of invariant 25 made visible. Its sibling gap —
  `initial` read as a plain value rather than guaranteed-invalid — is fixed;
  see invariant 26.

  ui.shadcn.com's 16 `.shimmer` declarations are the shape this limit still
  describes: `--shimmer-image` is defined three times — `initial` in
  Tailwind's `@property` guard, and `none` by the `.shimmer-none` and
  `.md\:shimmer-none` utilities — and since none of the three reaches the page
  element, `build_var_table` falls back to last-wins and takes `none` from a
  class the shimmering element does not carry. Invariant 26 alone does not fix
  this: it stops `initial` from winning, but `none` still does, from a rule
  that was never a candidate to begin with. That needs the **scoped custom
  properties are not modelled** limit below fixed first — resolving `.card`'s
  definition only for elements under `.card` — which is `PLAN.md`'s T9.

  **Not a regression, either way.** HEAD reported a color here only because
  the truncated call left an orphaned tail that resolved separately — the same
  accident invariant 25 fixed. No hex left any palette from either gap: all
  eight corpus sites kept identical hex sets, grounds and warnings, and the
  effect was confined to occurrence counts, which `selector_weight` already
  calls a hint.

- **Scoring is a heuristic** (`selector_weight`). Treat ordering as a hint.
- **Framework CSS cannot be reliably auto-detected** when it is inlined in the
  document, which is the common case for page builders. This is deliberately
  left to the user via `--list-sources` / `--only` / `--exclude` rather than
  guessed at. Note that excluding a sheet also removes its `var()` references,
  so a property defined in site CSS but consumed only by the framework flips
  `live` → `saved`. Accurate for the input; surprising if unexpected.

## Reference fixture

`palettes/fleshandbonedesign.com/` is the output for
`fleshandbonedesign.com/crass`, generated with `--exclude static-css --exclude
cargo.site --images`. Useful as a regression anchor: ground `#151515`,
`rgba(255,255,255,.75)` flattening to exactly `#c4c4c4` at 10.47:1, `#ffc600`
as `saved`, `#13330d` as `inert`, 20 tokens, one theme, no warnings. If a
change moves any of those, understand why before accepting it.

> **There is no committed copy, and there never has been** — `.gitignore`
> carries `palettes`, so the directory has never been tracked, and it is not on
> disk in a fresh clone. Earlier revisions of this section described a
> "committed copy" that is "stale"; that was wrong about *where* the fixture
> lives, though right that a checked-in one could not be trusted.
>
> **So the anchors listed above are the fixture** — they are the only durable
> form of it, and all of them were re-verified against a fresh run at commit
> `6507dda`: ground `#151515`, 20 tokens, one theme, no warnings, `#ffc600`
> `saved`, `#13330d` `inert`, and with `--images` the imagery measures
> **100.0% neutral** across 2 images and 19,919 pixels sampled (dominant
> `#3d3d3d` at 74.7%). Compare a change against a *freshly generated* run of
> the previous commit; there is nothing checked in to diff against.
>
> **The fixture is a weak anchor on its own, and it is worth knowing why.** It
> is a single-theme site with hand-written CSS, so the pre-`tinycss2` parser
> reproduces every anchor above exactly — measured, by running the tracked
> `palettekit.pyz`. It cannot detect a parser regression; the breadth check
> below is what does that.
>
> **Regenerating and committing it is still worth doing**, and it now needs two
> decisions rather than one: `palettes` would have to come out of `.gitignore`
> (or the fixture move elsewhere), and `fleshandbonedesign.com.har` is
> `.gitignore`d too, so **a fresh clone cannot regenerate it at all**. That is
> the same gap the "fixture corpus of small HTML files" entry in the Migration
> TODO addresses, and it makes that entry more urgent than its checkbox looks.

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

Current grounds, after phase 4 (**14 themes, 4 inferred**):

| site | grounds | inferred |
|---|---|---|
| getbootstrap.com | `#ffffff` / `#212529` | — |
| ui.shadcn.com | `#f5f5f5` / `#262626` | both |
| www.djangoproject.com | `#f8f8f8` / `#181d27` | — |
| news.ycombinator.com | `#ffffff` | yes |
| developer.mozilla.org | `#ffffff` / `#18191b` | — |
| tailwindcss.com | `#f0b100` / `#030712` | light |
| ground.news.har | `#eeefe9` / `#262626` | — |
| fleshandbonedesign.com.har | `#151515` | — |

MDN's second theme is phase 4's, and it is the only ground any phase moved
since phase 1. The site declares it entirely through `light-dark()`
(invariant 23): `html { background-color: var(--color-background-page) }`,
where that property holds `light-dark(#fff,#18191b)`. Both branches used to
land in one palette and the dark one had nowhere to be.

Django's dark theme is new — it was written `html[data-theme="dark"]`, and the
old string masking made every one of those selectors read `[data-theme=" "]`.
Its ground resolves by the same route its light one always did:
`body { background: var(--sidebar-bg) }`.

**The four inferred grounds are inferred because no page-level background is
readable at all — not because a readable one was ranked wrongly.** Neither the
cascade nor `color-mix()` moved any of them, and no remaining phase reaches
them. All three reasons were enumerated from the frozen bundles rather than
reasoned about, and are worth not re-deriving:

- **ui.shadcn.com has zero page-background candidates in either theme.** Its
  `<body>` carries `overscroll-none group/body antialiased` — no background
  utility — and it ships no `body`/`html`/`:root` background rule.
  ~~"Its only `<body>`/`<html>` backgrounds are `color-mix(in oklab, …)`, so
  phase 4 will fix it"~~ was written before phase 4 and was wrong; phase 4
  measured it and left it inferred.
- **tailwindcss.com's `<html>`** carries `dark:bg-gray-950` with no light
  counterpart, so there is no light page rule to read.
- **news.ycombinator.com paints with the presentational attribute
  `bgcolor="#f6f6ef"`** while its `body` rules set no background at all — that
  one is not CSS.

**Two things make this diff readable, and neither is the test suite.** Freeze
each site's fetched bundle to a file first, so a site that changed overnight
cannot masquerade as a regression. Then diff at the *declaration* level —
`(sheet_order, selector, prop, value, theme, at_rules)` as a multiset — not at
the palette level. The phase-1 swap passed all 65 tests and the reference
fixture on its first run while still mis-filing 124 of django's declarations;
the declaration diff is what caught it.

**Diff at the level the change operates on, and that is not always the
declaration.** Phase 2 changed no declaration at all — it changed one boolean,
`matches_page_element`, so the readable diff was that boolean: every distinct
`(selector, kind)` pair the two call sites ever hand it, old implementation
against new. That enumerates the blast radius before any palette is built. It
found 379 flipped declarations across four sites, of which 345 were `*` and
`:root *` and would have inverted Tailwind's and MDN's resets — and the palette
diff at the end was byte-identical, so a palette check alone would have shipped
it silently. Keep the old implementation alive in a scratch module for the
length of the change; it costs nothing and it is the only way to run this.

Phase 3's level was the **ordering key**: for every ground candidate and every
custom property, old winner against new, with the key's terms printed beside
them. Palettes came out byte-identical again, and the key diff is the only
thing that showed the twelve custom properties that moved — and that all twelve
were fixes. `git stash push palettekit/` is enough to run old against new
without a scratch copy of the module.

Phase 4's level was the **per-declaration color list** —
`(sheet_order, order, selector, prop) → [hexa]`, per theme. Not the palette,
which folds and merges; not the declaration, which the phase does not touch. It
is the only level that shows *removals*, and the removals were the finding: a
`color-mix()` that no longer parses used to leak its inner argument out as a
full-opacity color, and one of those leaks turned out to be a bright yellow no
site contains (invariant 24). The palettes changed on exactly the four sites
that use either function, which is the check that the blast radius was the
intended one.

**Predict the blast radius before writing the code, at the level the change
operates on.** Before phase 4 touched anything, every page-level background
candidate on all eight frozen bundles was enumerated per theme and marked for
whether either new function reached it. Exactly one did — MDN's — so "MDN
gains a dark theme and no other ground moves" was a falsifiable prediction
rather than a hope, and the two documented claims it contradicted got corrected
in `PLAN.md` before they could be rationalised afterwards.

**A test that passes before *and* after tests nothing about the change.** All
eight of phase 3's new tests were run against the stashed HEAD and required to
fail there; one of them passed, because the fixture's document order happened
to agree with the layer reversal it meant to check, and it was rewritten until
it disagreed. Do this — it is cheap, and a test written from a correct
implementation will otherwise quietly assert the thing that was already true.

**A number that doesn't match the record is a prompt to check your own
measurement before it is a prompt to explain the world.** Verifying T4
(invariant 26), a live re-fetch of tailwindcss.com gave occurrence counts that
didn't match the 137/29 and 130/22 this file records, and the first draft of
that verification explained the gap as the live site's content having moved on
in the time since. It had not — the site's source hadn't changed in over a
week, which the user checked and pointed out. The actual cause was
found in one more query: the verification had summed occurrences across every
violet- and teal-hued hex in the corpus (Tailwind ships some thirty shades per
hue) rather than reading the one dominant token the recorded numbers refer to;
read that single token and the fresh fetch reproduces 137/29 and 130/22
exactly, integer for integer. **"The measured world changed" and "my
methodology doesn't match the prior one" produce the same symptom — a number
that's off — and only one of them is checkable in seconds.** Rule out the
cheap explanation (reread what the original number actually counted, rerun the
comparison the same way) before writing down the expensive one, and don't
publish an explanation for a discrepancy that itself amounts to a guess.

## Migration TODO

**Moved. `PLAN.md`'s "Outstanding work" section is the authority** for
everything still to do — fourteen tasks, T1–T14, each with its rationale, its
prerequisites and the level its change should be *diffed* at.

It lives there rather than here because keeping two lists of the same work in
two files guarantees one of them goes stale, which is a failure this project
has already paid for more than once. Add new work there and link to it from
here if it needs saying twice.

What is settled, and stays recorded here because it describes the repo as it
is rather than work to do:

- [x] `pyproject.toml` — hatchling backend, version read from
      `palettekit/__init__.py`, console script, `images`/`images-fast`/`dev`
      extras, ruff config. Verified by building and installing the wheel.
- [x] `[project.urls]` and `authors` — filled in
      (`github.com/parkersprouse/palettekit`, Parker Sprouse).
- [x] `.gitignore` — present, and **narrower than earlier revisions of this
      list specified.** It carries `*.har` (with one exception, below),
      `.DS_Store`, `.remember`, `.venv`, `palettes` and `**/*cache*`. The
      last covers `__pycache__/` and `.ruff_cache/`; `dist/` and `out/` are
      **not** ignored, and neither is `*.pyz` — which is why the stale
      `palettekit.pyz` is tracked at all (`PLAN.md` T1).

      **`!parkersprouse.me.har` carves an exception into the `*.har` rule**,
      added 2026-07-27 alongside `example/` — the only HAR and the only
      generated-output directory this repo tracks. It's why a fresh clone can
      now regenerate the `example/` directory (verified byte-identical,
      `generated` dropped): the claim that a fresh clone can regenerate *no*
      fixture at all is no longer true for that one. It's still true for the
      reference fixture (`fleshandbonedesign.com.har`, still gitignored with
      no exception) and the four breadth-check bundles (`PLAN.md` T14).
- [x] **`LICENSE.md`** and the `[project.license]` / classifier entries in
      `pyproject.toml` — the owner chose the Hippocratic License 3.0 on
      2026-07-26.
