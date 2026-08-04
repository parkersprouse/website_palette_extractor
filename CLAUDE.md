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
  uv run --python "$v" --with tinycss2 --with cssselect2 --with html5lib \
    --no-project python -m unittest discover
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

The core takes **three** dependencies, all pure Python. **`tinycss2`** (one
transitive dep, `webencodings`) tokenises, and **`cssselect2`** (whose only dep
is `tinycss2`) parses selectors, matches them, and counts their specificity —
those two are by the same authors, and are phases 1 and 2 of `PLAN.md`.
**`html5lib`** (one transitive dep, `six`) arrived later, with T9: it builds a
conforming document tree *below* `<html>`/`<body>`, which `dom.py`'s own
~60-line `html.parser` shim deliberately does not, and which T9's real-ancestry
resolution needs. The shim was not replaced by it — see invariant 16 for why
both still exist.

Everything above all three — theme scopes, weighting, `var()`, what counts as a
theme, the cascade itself — is still ours. Pillow/numpy remain optional and
reached only through `images.py`, behind `--images`.

**Five top-level names have to reach the zipapp**, not three: the three above
plus `webencodings` and `six`. `six` vendors as a single `six.py` module rather
than a package directory, which `build.py`'s structural check has to allow for
explicitly — see below.

## Commands

```bash
python3 -m palettekit <target> -o out    # target: .har | URL | .html/.css path
python3 -m unittest discover             # 223 tests, all must pass (needs the deps)
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
`tinycss2`, `cssselect2`, `html5lib` and their transitive deps
(`webencodings`, `six`) into that staging dir via `uv pip install --target`
(or plain `pip` if `uv` isn't on `PATH`) — a zipapp carries
no dependency metadata, so without this the `.pyz` imports fine on a machine
that happens to have them installed and fails everywhere else — strips
`__pycache__`/`*.dist-info`/uv's `.lock` marker, and zips the result. It then
**structurally asserts** all six vendored top-level names
(`palettekit`, `tinycss2`, `cssselect2`, `html5lib`, `webencodings`, `six`)
are physically inside
the archive rather than smoke-testing by running it: running the built `.pyz`
on the same machine that built it would pass whether or not vendoring
happened, since site-packages is still on `sys.path` and a dev interpreter has
these installed regardless. That structural check is what actually catches a
skipped vendoring step — the failure mode the six-command version was silently
exposed to.

**The check accepts a package directory *or* a single module, and that is not
cosmetic.** It originally tested `name.startswith(f"{pkg}/")` only, which no
`six` could ever satisfy: `six` vendors as a top-level `six.py`, so it was
both absent from the required list and undetectable if it had been on it —
the archive could lose `six` entirely, pass `_verify`, import fine on the
build machine, and die on `import six` everywhere else. Exactly the failure
`_verify` replaced a smoke test to catch, reintroduced by the dependency
*shape* `html5lib` brought in. Verified by rebuilding the archive with
`six.py` removed and confirming `_verify` rejects it.

Reading `[project.dependencies]` out of `pyproject.toml` (via `tomllib`, free
at this project's floor) means the dependency list can't drift from the one
`pip install -e .` uses, the same discipline `PYTHON_FLOOR` applies to the
version guard below. The two *transitive* names (`webencodings`, `six`) are
the only ones added by hand, because neither is ever in `pyproject.toml`.

**Still a manual step, and still required**: run the built `.pyz` on an
interpreter that has *none* of the dependencies installed —

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
`palettekit/`, and **verify with an interpreter that has none of the three
dependencies installed** — on a development machine every interpreter has them
and a missing vendoring step is invisible to a smoke test, though not to
`build.py`'s own structural check.

### Regenerate `example/` too — it is the second tracked artifact

**`example/` is a committed *output* of this tool, and it goes stale the same
way `palettekit.pyz` does.** `README.md` points readers at it as sample
output, so a session that changed what the tool emits and left it alone ships
the previous version's output under the current version's name — the identical
failure the rule above exists for, on the artifact that had no rule.

```bash
python3 -m palettekit parkersprouse.me.har --images -o example
```

It drifted exactly as predicted, and was caught by regenerating rather than by
any check: committed 2026-08-02, it predated T18–T26 and still showed three
tokens as `live` that the current tool reports `unmatched` — so its `.css`,
`.scss`, `.ts` and `.tailwind.js` each shipped three tokens the tool now
correctly withholds (only `live` colors reach the code outputs), and its JSON
lacked `matchCount`/`matches`/`reason` entirely. Regenerated 2026-08-03.

**This is cheaper to check than to remember**: regenerate into a temp
directory and diff against the tracked copy with the `generated` key stripped
(it is a wall-clock timestamp — see the note above). Identical means nothing
to do.

Unlike the `.pyz`, this one *is* reproducible from a fresh clone —
`parkersprouse.me.har` is the single `.gitignore` exception — so there is no
reason for it to be wrong.

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
| `cssparse.py` | 1067 | `tinycss2` integration, `var()`, `selector_weight`, roles, theme scopes, `@layer` names, `color-scheme` pass-through (T10), `@supports` evaluation (T23), `@property` registrations (T22) |
| `dom.py` | 718 | `html.parser` → `ElementTree` shim, `cssselect2` matching of `<html>`/`<body>`, specificity, plus `full_tree`/`elements_matching`/`wrap_tree` (T9: real DOM below the page element), `selector_reach` (T18: does a selector match anything, real/none/untestable), `element_signature` (T19: a short label for one real matched element), `_compile_selector_parts` (T25: one bad selector-list branch costs only itself), and `untestable_reason` (T24: which of the two causes made `selector_reach` answer `None`) |
| `sources.py` | 292 | `load_har` / `load_url` / `load_paths` → `Bundle` |
| `extract.py` | 1921 | `extract()`, the cascade, per-theme `_build`, ground, merging, statuses, naming, `resolve_by_ancestry`/`resolve_by_ancestry_kind` (T9, non-inheriting-aware since T22), `Entry.all_unmatched` (T18), per-usage `match_count`/`match_samples` (T19), `_page_color_scheme`/`_scopes_present`'s confirmation gate (T10), `_theme_scoped_scheme_keywords` (T26), `property_registrations` (T22), `Entry.all_dynamic_only`/`Usage.reach_reason` (T24) |
| `emit.py` | 1086 | Emitters; `_HTML` is the report template (T20: status sub-headings, T24: always-present Caveats section) |
| `images.py` | 163 | Optional image quantisation, not part of the token set; `analyse` clamps k to the sample count (fewer opaque pixels than clusters used to raise) |
| `__main__.py` | 321 | CLI; `main()` guards `PYTHON_FLOOR` before anything else, then `_validate` rejects bad `--formats`/negative numerics before any work |

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
    definitions stay on last-wins as the shared table's own default**,
    deliberately — ranking declarations that match *different* elements by
    specificity is precisely the error above, and there is no single
    specificity ranking that could replace last-wins here.

    **T9 (`PLAN.md`, landed 2026-08-02) adds one exception, and it is not a
    ranking — it is real inheritance for one specific consuming declaration
    at a time**, not a change to the shared table. `resolve_by_ancestry_kind`
    walks the real document tree from a consuming declaration's own matched
    elements upward, and overrides last-wins only when it can *confirm* an
    answer for that consumer: a real ancestor sets the property (`"value"`),
    or every real consumer was checked and none has an ancestor that does
    (`"absent"`, which then falls through to the declaration's own written
    `var()` fallback, or nothing — the same route invariant 26's `initial`
    already takes). When the real tree can't confirm either — consumers
    disagree, or the consuming selector matches no element in the captured
    markup at all, the dominant real-world case per T9's own corpus
    measurement — last-wins is untouched. So "off-page definitions stay on
    last-wins" is still the honest default; it is no longer the only answer
    this tool can give.

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

    **"Ships both themes by definition" overreached, and T10 (`PLAN.md`,
    landed 2026-08-02) closed the gap.** `light-dark()` resolves against the
    *used* `color-scheme`, whose initial value is `normal` — light. A page
    that writes `light-dark()` and never declares `color-scheme: light dark`
    renders the light branch whatever the OS says, and calling that page
    two-themed is wrong.

    **`cssparse._record` now special-cases `color-scheme` through its
    filter** — not into `PROPERTY_ROLE` (it carries no color of its own, so
    `Declaration.role` falls through to `"other"`, which the main color-scan
    loop in `extract._build` and `_triplet_warning` already know to skip) but
    far enough to reach `sheet.declarations`, where `extract._page_color_scheme`
    resolves the winning value the same way `build_var_table` resolves a
    custom property — invariant 19's own `_page_specificity`/`_cascade_key`,
    applied to one ordinary property instead of the whole custom-property
    population, and unscoped-only for that one cascade path. ~~A
    `color-scheme` written *inside* a theme scope is a shape no corpus site
    has shown~~ — **one has, and it's fixed: T26 (`PLAN.md`, landed
    2026-08-03).** A `[data-theme="dark"] { color-scheme: dark }`-style
    toggle rule cannot DOM-match through `_page_color_scheme`'s cascade path
    for *both* keywords at once — a static capture freezes one `data-theme`
    state, so the sibling `[data-theme="light"]` rule structurally cannot
    also match in the same capture. `extract._theme_scoped_scheme_keywords`
    covers this the same way `theme_scope` already trusts `.dark`/
    `[data-bs-theme=dark]` to mean "this site has a dark theme" without
    requiring the marker to be present in the captured markup: every
    `color-scheme` declaration carrying a selector-theme scope
    (`Declaration.theme` truthy) is trusted for its own declared keyword
    unconditionally, unioned with `_page_color_scheme`'s unscoped-cascade
    result. Two designs were weighed at filing and turned out to produce
    identical results on every corpus site that carries `color-scheme` at
    all, so the simpler, symmetric one was taken rather than treated as an
    owner-arbitration question with nothing to arbitrate — see T26's own
    write-up in `PLAN.md` for the corpus comparison that decided it, and for
    the one unpredicted movement it found (`mdn.har`'s light theme relabels
    from `id:"base"` to `id:"light"`/`scope:"light"` — hex sets and grounds
    byte-identical, only the label changed, because MDN's own explicit
    toggle markup — present in its CSS, absent from this particular static
    capture's `<html>` — now registers a scope the generic themed-color path
    alone did not).

    `extract._scopes_present` gates its `light-dark()` →
    `{"light","dark"}` registration on `{"light","dark"} <= scheme_keywords`;
    unconfirmed, the colors still enter the palette, reading whichever single
    branch `extract._build`'s `default_appearance` selects — `"dark"` if the
    page confirms `dark` alone, `"light"` otherwise (absent, `normal`, or
    anything else — the same default as before T10, just no longer
    hardcoded).

    Checked against the corpus rather than assumed — MDN's CSS carries nine
    `color-scheme` declarations including `color-scheme:light dark`, so its
    two themes are real and the gate leaves it untouched (verified directly
    against a live fetch: still `#ffffff` / `#18191b`, both themes present).
    `mdn.har`, added the same day, is a frozen local capture of that same
    check — gitignored like the rest of this corpus, and reproduces the
    fetch exactly, so this no longer needs network access to reverify.
    **The counter-example this invariant said would be the fix's trigger
    turned up**:
    `pawelgrzybek.com`'s light/dark example
    (`pawelgrzybek.com__light_dark_example.har`, gitignored like every `.har`
    but `parkersprouse.me.har` — see T10's own write-up for why this stays a
    local, uncommitted corpus file rather than a second `.gitignore`
    exception) writes `light-dark()` twenty-four times and confirms both
    branches with `html { color-scheme:light dark }` — a positive control,
    not the negative case this invariant's gate exists for. That negative
    case (`light-dark()` present, `color-scheme` never confirming both) has
    no corpus site yet and is tested synthetically
    (`tests/test_color.py`'s `TestLightDarkNeedsColorScheme`) — each case
    required to fail against the pre-T10 implementation before being
    trusted, per this file's own "a test that passes before and after tests
    nothing" rule. The gate's own end-to-end effect was also verified
    directly on the real corpus file, not just inferred from the synthetic
    tests: stripping `color-scheme:light dark;` from a copy of the HAR
    collapses it from two themes to one; restoring the declaration restores
    both.

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
    is treated as absent, not substituted as text** (`resolve_vars`). On an
    *unregistered* custom property, `initial` **is** the guaranteed-invalid
    value — a browser resolving `var(name, fallback)` against it uses the
    fallback, it does not paste in the four letters `initial`.

    **Extended by T22 (`PLAN.md`, landed 2026-08-03): on a property
    `@property` registers with a real `initial-value`, `initial` is not
    guaranteed-invalid at all — it is a concrete, spec-defined value, and
    `var(name, fallback)` must substitute *that*, ignoring any author
    fallback, the same as it would for any other concretely-stored value.**
    `extract._substitute_registered_initials` rewrites the table once,
    before `resolve_vars` ever sees it, so this function's own "stored is
    literally `initial`" branch is unchanged and does not need to know
    registrations exist.

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

27. **`unmatched` requires every usage to be a confirmed non-match — one
    untestable usage anywhere in the entry leaves it `live`** (T18,
    `Entry.all_unmatched`, `dom.selector_reach`). `dom.selector_reach` answers
    three things, not two: `True` (matched a real element), `False` (compiled,
    was actually tested, matched nothing), `None` (could not be tested at
    all — uncompilable, or every branch is a dynamic state `cssselect2` marks
    `never_matches`). `all_unmatched` checks `u.matched is False`
    specifically, not `not u.matched`, so a `None` cannot silently read as a
    non-match.

    **A pseudo-element branch (`.card::after`) is not one of the untestable
    cases — since T21 (`PLAN.md`, landed 2026-08-02) it is tested against its
    *base compound*, and answers whatever `.card` itself answers.** Read
    T21's own note under invariant 27's amendment below before touching
    `dom._compile_reachable`/`dom.reach_elements` or `extract.consumers_of` —
    the two filters look interchangeable and are not, and sharing them
    reintroduces a real, corpus-found bug in T9's ancestry resolution rather
    than merely a missed edge case.

    This is not a hypothetical guard. `elements_matching_wrapped` — T9's own
    existing function — already collapses `None` and `False` to the same `[]`
    for a pseudo-element and a dynamic state alike, because none of its
    callers needed the distinction; reusing it for T18 would have flagged
    every `:hover`/`:focus`/`::after`/`::before` declaration on every site as
    content-not-on-the-page, including hand-written, fully-static ones.
    `dom.selector_reach` is the tri-state function built to keep `None` and
    `False` apart; `_compile_reachable` is its own filter, deliberately not
    shared with `elements_matching_wrapped`'s `_compile_usable` — see T21
    below for why.

    **The corpus investigation here is worth keeping because the first
    reading of it was wrong, and wrong in a specific, catchable way.**
    Measuring the naive "any usage zero-match" rule against
    `fleshandbonedesign.com.har` — the reference fixture, hand-written,
    trusted — found 7 of 14 `live` entries would flip, on selectors like
    `.quick-view-background`, `.menu-copy-2`, `h2`. The first theory was that
    these were classes JavaScript adds at runtime (a quick-view modal, a
    hover-triggered menu variant) — plausible, and wrong: `grep`ing the
    captured HTML for `quick-view` returned 28 hits, which looked like
    confirmation. Every one of those hits was inside an embedded `<style>`
    block's own CSS text, not a `class=` attribute — the grep matched the
    selector's own definition, not markup carrying it. A second check,
    restricted to `class="..."` attributes specifically, found zero real
    elements for `.quick-view*`, `.menu-copy-2`, `.menu-copy-3`,
    `.menu-copy-scroll`, `h2`, and several more — genuinely unused rules from
    a general-purpose theme stylesheet (Cargo's "crass" template ships
    variants this particular site never uses), not JS-gated content. The
    corrected finding argues *for* this invariant rather than against it: the
    signal is real, on the site it was most likely to be a false alarm.

    **`parkersprouse.me.har` is the cleanest positive case**: its only
    `unmatched` entries are `:where(dialog)` and `:where(fieldset)` — a
    normalize-style reset shipping rules for elements the page's static markup
    doesn't have yet, exactly the shape this status exists to name. Verified
    directly against the reference fixture's own documented anchors
    (ground `#151515`, 20 tokens, `#ffc600` `saved`, `#13330d` `inert`, no
    warnings) — all five held before and after; the `all_unmatched` check
    only ever narrows an entry that is *already* `live`, so `saved` and
    `inert` entries are never reconsidered (invariant priority: `inert` →
    `saved` → `unmatched` → `live`, `_status_for`).

    **A looser rule — flip whenever at least one usage is a confirmed
    non-match, ignoring `None` usages in the same entry — was measured and
    rejected.** Across `ground.news.har`/`tailwindcss.com.har`/
    `ui.shadcn.com.har` it flagged 8–13% more entries than the strict rule,
    and every additional case was an entry that also had a genuine `:hover`/
    `:focus`/`::placeholder` usage mixed in — exactly the ambiguous shape
    unanimity is meant to protect. The strict rule's own flips, read by hand
    across all five bundles, converged on cases this file already documents
    independently as correct: ui.shadcn.com's `.shimmer`/`.shimmer-none`
    (the "scoped custom properties are not modelled" limit below — a page
    this HAR never fetched) and `.theme-sketch` (a theme variant not selected
    on the captured page) both turn up here as `unmatched`, matching what was
    already known about them from other investigations.

    **A document-level "is this capture trustworthy" gate — flip nothing if
    the whole document's overall selector match rate is too low — was
    considered before measuring and abandoned after.** The premise was that a
    truncated HAR or client-hydrated shell (T9's own 2026-08-02 finding, off
    -page custom properties only) would show a visibly lower match rate than
    a trustworthy static capture. Measured, it does not discriminate:
    `fleshandbonedesign.com.har` — trusted, hand-written, complete — has a
    match rate of 0.29, statistically indistinguishable from
    `tailwindcss.com.har`'s 0.25–0.33. A generic theme stylesheet on a small
    site and a component library's full utility set on a docs site both
    produce "most selectors don't match this one page" for entirely different,
    equally legitimate reasons. There is no threshold that separates them, so
    none is used; the per-usage unanimity rule above is the check that
    actually holds up.

    **Performance:** reuses `_build`'s already-hoisted `wrapped_root` (T9) and
    memoizes by selector text (`reach_of`, mirroring `consumers_of`), same
    pattern, same reason. Measured on `tailwindcss.com.har`: existing baseline
    (T9 already wired in) 35s, with T18's per-declaration reach check added,
    ~47s — a real but proportional addition, not a new dominant cost, and a
    one-time per-extraction cost rather than a hot-path one.

    **The report's own reading colors move, because `_pick_report_theme`
    (`emit.py`) draws its neutral ramp from `live` entries only, and that
    pool shrank — invariant 11's own failure shape, so this was checked, not
    assumed.** Every corpus theme still clears its contrast floor with room
    to spare (lowest margin: 3.86:1 against a 3.0 floor, `tailwindcss.com`
    light). A before/after diff of the picked hex values on the three
    largest-shrink bundles shows only cosmetic drift — a different, equally
    real site grey chosen once its previous neighbour became `unmatched`,
    never a fall-back to the derived-from-ground synthetic tones. This is
    the mechanism `choose()`'s own derived-fallback comment describes
    working as intended, not a coincidence. Visually confirmed in a browser
    on `ground.news.har` (the largest shrink, 119→46 `live`), which caught a
    real bug in the process: `emit_html`'s report subtitle read "N found in
    the source but not painted" — true for `saved`/`inert`, false for
    `unmatched`, whose entire premise is that the tool *can't* confirm that.
    Fixed to "N more found in the source", dropping the overclaim rather than
    hedging it further inline.

    Tests: `TestSelectorReach` (`tests/test_dom.py`, the tri-state contract
    in isolation — a real match, a confirmed non-match, a dynamic state, a
    pseudo-element, an uncompilable selector, and a mixed list where one
    untestable branch does not make the whole list `None`), and
    `TestUnmatchedStatus` (`tests/test_extract.py`, end-to-end through
    `extract()` — a genuine non-match, a real match, one matching usage
    keeping a merged entry `live`, a hover-only usage staying `live` rather
    than guessing, `saved`/`inert` priority holding over `unmatched`, and a
    bare `.css` input with no captured HTML at all staying `live` rather than
    manufacturing a determinate answer from zero evidence).

    **T21 (`PLAN.md`, landed 2026-08-02): a pseudo-element branch is tested
    against its *base compound* instead of being refused.**
    `dom._compile_usable` used to drop every selector with
    `sel.pseudo_element is not None`, lumping `.card::after` in with
    `.card:hover`'s genuine unanswerability — but `cssselect2` happily
    evaluates `.test()` against a pseudo-element selector's base compound;
    `.pseudo_element` is only an annotation for the caller about a generated
    box `cssselect2` cannot itself represent as a tree node. Verified
    directly: `cssselect2.compile_selector_list(".card::after")[0].test(div)`
    is `True` for a real `<div class="card">`. Refusing the answer it already
    has made `unmatched`/`matchCount`/`matches` report `None` for a
    normalize-style reset's real `::before`/`::after` rules regardless of
    whether the base selector is on the page — the shape this task was filed
    against, and `parkersprouse.me.har`'s own reset stylesheet is the
    corpus's one live example of it.

    **`wrapped_root.query_all(*usable)` cannot be used to test it, which the
    filing's own sketch did not anticipate.** `cssselect2`'s `query_all`
    re-filters its arguments through `ElementWrapper._compile`, which drops
    `pseudo_element is not None` a *second* time, independently of and after
    any filtering the caller already did — verified directly, the identical
    compiled selector answers `True` from `.test(node)` and empty from
    `wrapped_root.query_all(sel)`. `dom.reach_elements`/`selector_reach`
    instead walk `wrapped_root.iter_subtree()` by hand and call
    `sel.test(element)` directly, which carries no such filter.

    **The filing's implementation predicted only `matched`/`matchCount`
    would move, and one declaration on `tailwindcss.com.har` also changed
    color — which is not a hex the palette lost, but the sign of a second,
    real bug the first draft of this task introduced rather than found.**
    T21's first draft shared one filter between `selector_reach`
    (T18/T19's reach question) and `extract.consumers_of` (T9's real
    -inheritance question, `resolve_by_ancestry_kind`), on the reasoning that
    both were "does this selector reach a real element." They are not the
    same question: T9 asks which element a declaration's *value* directly
    applies to — the element real CSS inheritance could originate from — and
    a pseudo-element's generated box is not that element; T9 was never meant
    to change. But `dom.selector_matches`, the *candidate* matcher
    `_ancestry_winners` uses to test a property's real setters against a
    consumer's ancestors, still refuses pseudo-elements unconditionally and
    was correctly left untouched — so once the shared filter let a
    pseudo-element consumer through, T9's ancestry walk ran, found no
    candidate `selector_matches` could see (because the real setters were
    *also* pseudo-element-scoped Tailwind utilities), and confirmed
    `"absent"` — a status `resolve_by_ancestry_kind`'s own contract treats as
    safe to override last-wins with, per invariant 19's T9 addendum. On
    `tailwindcss.com.har`, `.after\:inset-ring:after`'s
    `--tw-inset-ring-color` went from a wrong last-wins guess (`#00a6f4ff`,
    Tailwind's alphabetically-last `.inset-ring-*` utility, painted nowhere
    on the page) to no color at all — a **false confirmed absence**, worse
    than the guess it replaced, and not merely a missed edge case.

    Fixed by keeping the two questions on two filters:
    `dom._compile_usable`/`elements_matching_wrapped` (T9's, unchanged,
    still refuses pseudo-elements) and a new
    `dom._compile_reachable`/`dom.reach_elements` (T18/T19's, base-compound
    -aware). `extract._build` correspondingly gained a second memoized cache,
    `match_elements_of`, alongside the pre-existing `consumers_of` — the two
    must not be the same cache either, since `samples_of`/`matchCount` need
    the base-compound-aware answer and `consumers_of`'s off-page-var
    resolution must not see it. Guarded by
    `test_a_pseudo_element_consumer_does_not_trigger_ancestry_override`
    (`tests/test_extract.py`), built to fail against the shared-filter draft
    and pass against the split one — checked directly, per this file's own
    "a test that passes before and after tests nothing" discipline, rather
    than trusted by inspection.

    Verified on the corpus at the per-declaration `matched`/`matchCount`
    level (the diff convention T18/T19 set): across all seven frozen
    bundles, every moved key is `None` → a determinate value and nothing
    else — the union of keys before and after is identical, so no hex
    entered or left any palette. That was not true of the shared-filter
    draft, which is exactly why the split exists.

28. **A `@supports` leaf never confirms unsupported — only supported, or
    unknown** (`cssparse.supports_condition`, T23). `@media` and `@supports`
    used to be read identically: every block applies, `not (...)` included.
    That is backwards exactly when a `@supports not (...)` block is a
    fallback for browsers lacking a feature this tool already treats as real
    (invariants 22–23 exist because `color-mix()`/`light-dark()` are genuine
    evergreen-browser behaviour) — the fallback then wins last-wins over the
    real value on document order alone, with nothing in its selector saying
    it's conditional.

    `pawelgrzybek.com`'s light/dark example is the case that found this:
    `@supports not (color: light-dark(white,black)) { :root { --color
    -background: hsl(255 0% 100%); … } }` is a polyfill fallback, read at
    face value as just another unscoped `:root` declaration, later in
    document order, tied on specificity — so it silently overrode the real
    `light-dark()` value for **both** themes and reported the dark ground as
    `#ffffff`.

    **A full feature-query evaluator is not what this is, on purpose.**
    `@supports` covers arbitrary `property: value` pairs, and most
    properties' grammar is far richer than a single `<color>` —
    `background`'s a shorthand, `filter` takes functions `color.parse_color`
    was never built to read. Judging "unsupported" from a failed parse there
    would confidently flag real, universally-supported CSS as absent, which
    is a worse failure than the one being fixed: today's behaviour never
    drops a real declaration for `@supports` reasons, and a careless fix
    could start doing that silently, on any site.

    So a leaf declaration (`cssparse._supports_declaration`) returns `True`
    when it's a custom property (any non-empty value is syntactically valid
    on one) or a property in `_PURE_COLOR_PROPERTIES` — the subset of
    `PROPERTY_ROLE` whose grammar is *exactly* `<color>`, deliberately
    excluding shorthands and function-taking properties — whose value
    `parse_color` parses. **Everything else is `None`, never `False`** —
    including a pure-color property whose value fails to parse, because that
    could just as easily be a real CSS color function this tool hasn't
    implemented (`color(display-p3 …)`) as a genuinely unsupported one, and
    this tool has no way to tell those apart. `None` means "cannot tell,"
    and the caller treats it as supported — today's behaviour, unchanged.
    `False` can therefore only ever arise from negating an already-confirmed
    `True`, which is exactly `not (color: light-dark(...))`'s shape and
    nothing this project has evidence for beyond it.

    The `not`/`and`/`or`/parens grammar itself is evaluated for real, with
    three-valued (Kleene) logic so an unknown operand doesn't silently
    become `False`: `False and anything = False`, `True or anything = True`,
    otherwise `None`. `tinycss2` already groups a top-level `(...)` into one
    `ParenthesesBlock` with nesting resolved, so — same as invariants 24/25
    — no hand-rolled paren-depth counter was needed, only the walk over an
    already-structured token tree. A confirmed-`False` block is skipped
    outright, mirroring the statement-at-rule branch (invariant 18) rather
    than merely filtering its declarations afterward: no `_record`, no
    `var_refs` collection, because a block that doesn't apply in the browser
    this tool models doesn't reference anything in it either.

    Verified against all seven frozen bundles, not just synthetically: five
    are byte-identical (none carries a `@supports` condition on a pure-color
    property). `pawelgrzybek.com__light_dark_example.har` moves exactly as
    predicted — dark ground `#ffffff` → `#21262c`, and the "both themes have
    a light background" mislabelling warning disappears because the dark
    theme is now actually dark. `mdn.har` moves too, unpredicted at filing
    time: its stylesheet is compiled through a `light-dark()` PostCSS
    polyfill (`csstools`) emitting paired blocks — `@supports
    (color:light-dark(red,red))` with the real declarations, `@supports not
    (color:light-dark(tan,tan))` with `--csstools-light-dark-toggle-*`
    fallback machinery on a `:root *` blanket selector. Only the real block
    is read now; `declarationsScanned` drops by exactly the polyfill's 48
    declarations, and hex set, status counts, ground and theme count are all
    unchanged — the blanket-selector polyfill was only inflating occurrence
    counts, so what moved is ranking and `examples` provenance, which
    `selector_weight`'s own "treat ordering as a hint" caveat already covers.
    Tests: `TestSupports` (`tests/test_cssparse.py`).

## Status vocabulary

| Status | Means | Detected by |
|---|---|---|
| `live` | Actually painted | default |
| `saved` | Custom property nothing references — usually a design tool's saved swatches | `_status_for` vs `var_refs` |
| `inert` | Declaration that paints nothing, e.g. `drop-shadow(0 0 0 #13330d)` | `is_inert_shadow` |
| `unmatched` | Every usage's selector was tested against the real captured document and matched nothing there (T18) | `Entry.all_unmatched` vs `dom.selector_reach` |

**`dynamicOnly` (T24) is a flag, not a fifth status.** A color whose every
usage's selector is a dynamic pseudo-class (`:hover`, `:focus`, …) stays
`live` — invariant 27's own "unconfirmed is not the same as absent" reasoning
still applies, and no capture, however complete, could ever confirm or refute
an interaction state. `Entry.all_dynamic_only` sets an additive
`dynamicOnly: true` on that entry's JSON record instead, and the HTML
report's always-present Caveats section (`emit.py`'s `#caveats`, distinct
from the per-site `#warnings` box) names affected entries by theme. Narrower
than "every usage's `matched` is `None`" on purpose: an uncompilable selector
(T21's own territory — some other engine might answer it) and a bare `.css`
input with no captured HTML at all both also leave `matched` at `None`, and
conflating either with "structurally unknowable" would be dishonest.
`dom.untestable_reason` tells the two apart once `selector_reach` has already
answered `None`; `Usage.reach_reason` carries the answer (plus
`"noCapturedHtml"`, read directly off `wrapped_root is None` in
`extract._build` rather than handed to `untestable_reason`, which has no way
to know it) through to `Entry.all_dynamic_only`'s unanimity check.

**Verified against a purpose-built fixture, not only `ui.shadcn.com`'s
incidental `:hover` utilities.** `pseudo_selector_example.har` (owner-supplied,
2026-08-03) is a hand-written page whose `button` rule sets a resting color
and whose `button:hover`/`:focus`/`:active` each set a color found nowhere
else, with a real `<button>` in the captured markup — the detail that makes
this a genuine test of `dynamicOnly` rather than of `unmatched` (T18), since a
base compound matching nothing would explain the missing confirmation a
different way. All three interaction-only colors came back `dynamicOnly:
true`/`reason: "dynamicState"`/`matchCount: null`; the resting color came back
unflagged with `matchCount: 1`.

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
  - ~~`@property` registration itself is not read~~ — **read since T22
    (`PLAN.md`, landed 2026-08-03)**, in the two places it changes an
    answer: `inherits: false` stops T9's ancestry walk from crossing into an
    ancestor at all (`resolve_by_ancestry`/`resolve_by_ancestry_kind`'s
    `non_inheriting` flag — a value set on the consumer's own element still
    counts), and a registered `initial-value` gives the literal keyword
    `initial` a real substitution instead of invariant 26's "guaranteed
    -invalid, treat as absent" (`extract._substitute_registered_initials`).
    `syntax` itself is still not read — nothing here validates a stored
    value against its registered grammar, only `inherits`/`initial-value`
    are consulted. Found live on the corpus, not filed as a completeness
    gap: `ui.shadcn.com.har`'s `--tw-ring-color`/`--tw-ring-shadow` (both
    `inherits: false`) were resolving from an unrelated ancestor 12-14
    levels up before this landed. **Inheritance down the tree, for the
    off-page population, is now modelled where the real tree can confirm an
    answer** (T9, `PLAN.md`, landed 2026-08-02, invariant 19's own T9
    addendum) — a property redefined on `.card` resolves per real consuming
    element, not globally, when a consumer is in the captured markup and the
    real ancestors agree (and, since T22, when the property isn't
    registered non-inheriting). It still resolves globally (last-wins) when
    the tree can't confirm either direction: consumers disagree, or — the
    dominant real-world case per T9's own corpus measurement — the
    consuming selector matches no element in the captured markup at all (a
    Next.js app's client-hydrated content, or a truncated HAR capture; see
    T18's note on this same finding). "Not modelled" is no longer the
    accurate description; "modelled where the static capture can confirm
    it, last-wins elsewhere" is.
  - ~~A selector list with one unsupported branch loses every branch, not
    just the bad one~~ — **fixed, T25 (`PLAN.md`, landed 2026-08-03).**
    `cssselect2.compile_selector_list` fails the whole comma-separated list
    on the first unparseable part (Tailwind's own
    `*,:before,:after,::backdrop` reset selector, where `::backdrop` is
    unsupported, is the corpus case), so `selector_matches`,
    `dom._compile_usable`, and `dom._compile_reachable` — all three used to
    pass a whole list to it in one call — silently lost a perfectly good `*`
    or class branch sitting alongside the one bad pseudo-element or
    pseudo-class. `dom._compile_selector_parts` (`@lru_cache`d, the three
    call sites' new shared entry point) splits with `split_selector_list`
    first and compiles each branch on its own, unioning the survivors,
    exactly the shape sketched at filing time.

    **Deliberately not extended to `matches_page_element` or
    `selector_specificity`**, which share the identical
    try/except-the-whole-list shape. `matches_page_element` is unaffected
    either way for the one selector this bug is known to hit — `*` is
    already refused as blanket and `:before`/`:after` as pseudo-elements.
    `selector_specificity` is not so lucky: verified directly,
    `cssselect2.compile_selector_list(":before")[0].specificity` is
    `(0, 0, 1)`, not `(0, 0, 0)`, so fixing that call site would move an
    answer it feeds into `_cascade_key` (invariant 21) — an unmeasured
    blast radius across `detect_ground`/`build_var_table` this task did not
    sign up to predict. Left for its own task if a corpus case ever needs
    it.

    Verified on the corpus at the per-declaration `matched`/`matchCount`/
    ancestry-resolved-value level (T21/T22's own convention): four of seven
    bundles are byte-identical (no `::backdrop`-shaped selector list
    present). `ui.shadcn.com.har` is also byte-identical — T22's
    `non_inheriting` flag already stopped its `--tw-ring-color`/
    `--tw-ring-shadow` bug from this exact root cause, which is *not* what
    was predicted at filing time (the filing expected this bundle to move
    again "via the root cause"; it does not, because T22's fix already
    covers those two properties independently). `ground.news.har` moves
    only in `matchCount`/`matches` metadata on one example (`None` → a real
    count against every element in the document — the `*` branch reaching
    everywhere, exactly as predicted) with no hex, status, or occurrence
    change.

    `tailwindcss.com.har` is the real positive, and the mechanism was traced
    to a specific declaration rather than inferred from the palette diff —
    a keyed (hex, role) diff first, since positional list diffs misreport
    reordering as changed entries (this file's own recurring caution), then
    the actual `resolve_vars`/`resolve_by_ancestry_kind` inputs and outputs
    for one representative declaration, instrumented directly. Every Tailwind
    v4 `.shadow-{color}\/{opacity}` utility (and the matching
    `inset-shadow-`/`drop-shadow-`/`text-shadow-` families) writes
    `--tw-shadow-color:
    color-mix(in oklab, color-mix(in oklab, var(--color-{color}) {opacity}%,
    transparent) var(--tw-shadow-alpha), transparent)` — the utility's own
    opacity suffix is a literal percentage baked into the *inner* mix, and
    `--tw-shadow-alpha` (`@property`-registered `inherits: false`,
    `initial-value: 100%`) is a second, independent scaling factor that
    Tailwind's `@layer properties` reset sets back to `100%` — "no extra
    dimming" — on every element via exactly the broken
    `*,:before,:after,::backdrop` selector this task fixes. Pre-fix, that
    reset candidate never matched anything (whole list uncompilable), so
    T9's ancestry walk (`non_inheriting`-restricted to the consumer's own
    element, T22) found no same-element setter and confirmed `"absent"` —
    which discards even the legitimate off-page last-wins fallback
    (`30%`, from an unrelated `.shadow-xl\/30` utility elsewhere in the
    document) that `build_var_table` would otherwise have supplied. With
    `--tw-shadow-alpha` unresolved and no fallback written in the `var()`
    call, `resolve_vars` substituted empty text, `color-mix()`'s own
    missing-percentage default rule applied to the *outer* mix, and the
    result was alpha `0.25` — half of the inner mix's own `50%`, an
    accident of CSS's fallback grammar with no relationship to the class's
    own opacity suffix. Post-fix, the reset's `*` branch matches the
    consumer at its own element, `_ancestry_winners` returns the reset's
    literal declared value `100%` (not `initial` — the reset writes the
    number directly), `resolve_vars` substitutes it, and the outer mix
    collapses to the inner one unchanged (invariant 22's zero-alpha
    shortcut) — alpha `0.5`, exactly what a `\/50` utility promises and the
    page actually renders.

    The four hexes that disappear from `tailwindcss.com.har`'s palette
    entirely (`#e4a340` light; `#21274d`, `#33244d`, `#411e3b` dark) were
    checked individually rather than assumed: all four are `--tw-shadow
    -color`, all four carry `"alpha": 0.25` in their old `source`
    metadata — the artifact above, not a real rendered color, and its
    removal is the fix landing. `#b4b337`'s `live` → `unmatched` flip is a
    second-order effect of the same declaration moving: its one `live`
    usage (`matchCount: 1` against a real div, for `--tw-shadow-color` on
    `.shadow-sky-400\/50`) was this exact wrong-alpha artifact: fixed, that
    usage no longer flattens into this bucket, leaving only usages already
    confirmed non-matches — invariant 27's unanimity rule then fires
    correctly, which is a new way for this task to interact with T18/T19,
    not a bug in either. `afterMerge`/`distinctColors` move by exactly 1
    per theme once the wrong-alpha entries fold away and the corrected
    -alpha declarations rejoin buckets already tracked from other,
    unaffected declarations sharing the same rendered color;
    `declarationsScanned` and `customProperties` counts are unchanged, and
    JSON size does not grow. No ground moved on any bundle. Performance:
    `tailwindcss.com.har` end-to-end at ~19s, under invariant 27's recorded
    ~47s baseline — the new cache more than pays for the added per-branch
    compile. Tests:
    `test_an_unparseable_branch_does_not_void_a_good_one`,
    `test_an_unparseable_branch_does_not_void_a_matching_candidate`,
    `test_an_unparseable_branch_does_not_void_a_reachable_one`
    (`tests/test_dom.py`), each required to fail against the pre-fix
    implementation before being trusted.
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
  the `var()` is not consumed on resolves to that value anyway — fixed where
  the real document tree can confirm the right answer, T9 (`PLAN.md`, landed
  2026-08-02), invariant 19's own addendum.** This was the gap the balanced
  parse of invariant 25 made visible. Its sibling gap — `initial` read as a
  plain value rather than guaranteed-invalid — was fixed earlier; see
  invariant 26.

  **ui.shadcn.com's own 16 `.shimmer` declarations are the shape this limit
  used to describe, and T9's landing does *not* fix this specific bundle's
  example** — checked directly, not assumed, because it's the one case worth
  not getting wrong twice. `--shimmer-image` is defined three times:
  `initial` in Tailwind's `@property` guard, and `none` by the
  `.shimmer-none` and `.md\:shimmer-none` utilities. Invariant 26 already
  stops `initial` from winning. What's left needs the real element that
  consumes `--shimmer-image` to be in the captured tree at all — and on this
  frozen bundle it is not: the `.shimmer` element lives on
  `/docs/utils/shimmer`, a page this HAR never fetched (confirmed by
  searching the captured HTML directly — the string `shimmer` appears only
  inside a nav link's own JSON, never as a class). T9's ancestry walk asks
  "does any real ancestor of this consumer set the property," and with no
  real consumer in the tree at all there is nothing to ask — the "no basis"
  outcome, which correctly leaves last-wins (`none`) untouched rather than
  guessing. **The limit this example now demonstrates is capture
  completeness — the existing "No JavaScript is executed" entry above,
  compounded by which pages a HAR happens to fetch — not "scoped custom
  properties are not modelled."** That modelling gap is closed; this
  particular example was never reachable by closing it.

  **T18 (invariant 27, landed 2026-08-02) reaches this same `.shimmer`/
  `.shimmer-none` shape independently, from the other direction.** Where T9
  asks "is there a real consumer to resolve a value for" and finds none, T18
  asks the plainer question "does `.shimmer`'s own selector match any real
  element at all" — also none, so the entry lands `unmatched`. Two different
  investigations landing on the same declarations by different routes is
  corroboration, not redundancy: it was checked directly (not assumed) as
  part of T18's own corpus verification, and it is one of the cases invariant
  27 cites as the strict per-usage rule converging with what this file
  already knew independently.

  **Not a regression, either way, on the original phase-4 finding this entry
  describes.** HEAD reported a color here only because the truncated call
  left an orphaned tail that resolved separately — the same accident
  invariant 25 fixed. No hex left any palette from either gap: all eight
  corpus sites kept identical hex sets, grounds and warnings, and the
  effect was confined to occurrence counts, which `selector_weight` already
  calls a hint.

- **Scoring is a heuristic** (`selector_weight`). Treat ordering as a hint.
- **Framework CSS cannot be reliably auto-detected** when it is inlined in the
  document, which is the common case for page builders. This is deliberately
  left to the user via `--list-sources` / `--only` / `--exclude` rather than
  guessed at. Note that excluding a sheet also removes its `var()` references,
  so a property defined in site CSS but consumed only by the framework flips
  `live` → `saved`. Accurate for the input; surprising if unexpected.

- **`@supports` conditions are evaluated only for the one shape this project
  has evidence for — a full feature-query engine they are not** (T23,
  invariant 28, landed 2026-08-02). ~~`@supports` conditions are not
  evaluated~~ was true until T23 and would still describe most of the
  grammar afterward: a leaf declaration only ever confirms *supported*
  (a custom property, or a pure-`<color>` property whose value
  `color.parse_color` parses) or admits it doesn't know: `False` can only
  come from negating an already-confirmed `True`. Any `@supports` condition
  on a non-color property, or on a color property using a real CSS color
  function this tool hasn't implemented, still reads its block unconditionally
  — identical to every `@supports` block's behaviour before T23.

  Found while verifying T10 (`PLAN.md`) against
  `pawelgrzybek.com__light_dark_example.har`: the dark theme's reported
  ground was `#ffffff`, wrong — the page paints `hsl(210 15% 15%)` (roughly
  `#21262c`). The stylesheet writes

  ```css
  :root { --color-background: light-dark(hsl(255 0% 100%), hsl(210 15% 15%)); … }
  @supports not (color: light-dark(white,black)) {
    :root { --color-background: hsl(255 0% 100%); … }
  }
  ```

  — a fallback for browsers that can't parse `light-dark()` at all, meant to
  never apply in one that can. Read at face value it was just a second
  unscoped `:root` declaration for the same property, later in document
  order, tied on specificity — so `build_var_table`'s cascade (invariant 21)
  picked it over the real one, for **both** themes, since neither
  declaration is theme-scoped. T10's own gate (whether a `light-dark()` site
  is confirmed two-themed) was never affected by this — it's a wrong *value*
  inside an already-correctly-detected theme, a different question.

  T23 fixes exactly this shape and confirms it on the corpus: dark ground
  now `#21262c`, and `mdn.har`'s own `light-dark()` PostCSS polyfill — a
  second, previously-unknown real-world instance of the same pattern — is
  now read correctly too. See invariant 28 for the design and both results.
  A general `@supports` boolean-feature-query engine remains out of scope —
  most properties' grammar is far richer than `<color>`, and guessing
  "unsupported" past what this tool can actually parse would manufacture a
  worse failure (dropping real, universally-supported CSS) than the one this
  task fixed.

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
> the same gap `PLAN.md`'s T14 ("fixture corpus of small HTML files") named —
> and T14 closed 2026-08-03 without closing this specific gap, an owner
> decision that the one committed fixture `example/` already provides
> (`parkersprouse.me.har`, described above) is enough to stop tracking as
> open work. The gap itself, and the "still worth doing" above, are
> unchanged by that closure.

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

`mdn.har` (added 2026-08-02) is a frozen local capture of the
`developer.mozilla.org` row above and reproduces it exactly — offline
verification for a site that used to need a live fetch.
`pawelgrzybek.com__light_dark_example.har`, added the same day, isn't part of
this six-site breadth spread; it's T10's own corpus file (invariant 23), the
first site that both writes `light-dark()` and confirms it with
`color-scheme`.

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
everything still to do — T1–T27 as of 2026-08-03, each with its rationale, its
prerequisites and the level its change should be *diffed* at. Not updated
here each time a task is added; that section is the count that matters.

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
      no exception) and the four breadth-check bundles — `PLAN.md` T14 named
      this gap but **closed 2026-08-03 without closing it**, an owner
      decision that the one regenerable fixture above is satisfying enough
      to stop tracking as open work. The gap itself is unchanged.

      **Two more local, gitignored HARs joined the corpus 2026-08-02**:
      `mdn.har` (developer.mozilla.org, matching the breadth check's own live
      `#ffffff` / `#18191b` two-theme result — verified directly, so it now
      reproduces offline what used to need a live fetch) and
      `pawelgrzybek.com__light_dark_example.har` (the site that finally
      exercises `light-dark()` confirmed by `color-scheme`, T10's corpus
      file). Neither is a `.gitignore` exception — same untracked treatment
      as the four breadth-check bundles, and per T14's own closure that
      stays the state rather than a fix still pending.
- [x] **`LICENSE.md`** and the `[project.license]` / classifier entries in
      `pyproject.toml` — the owner chose the Hippocratic License 3.0 on
      2026-07-26.
