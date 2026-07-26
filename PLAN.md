# Migration plan: hand-rolled CSS reading → `tinycss2` + `cssselect2`

Status: **phases 1 and 2 landed 2026-07-26.** Phases 3–4 not started. Written
2026-07-26.

## Why

The owner set the priority order on 2026-07-26: **accuracy and breadth first,
slimness second** — a dependency is acceptable where it buys correctness. That
reverses the constraint under which the current design was chosen, and it
changes the answer to the question this plan exists to settle.

Five parsing bugs were found in a single session, all by running a spread of
real sites rather than by reading code:

| Bug | Cost | Root cause |
|---|---|---|
| Escaped quote in a selector masked past `{` | 178 of 181 themed rules on ground.news | hand-rolled string masking |
| `lab()` matched the color regex but had no parser | 251 declarations | incomplete CSS Color 4 |
| Comma split inside `:where(.dark,.dark *)` | every Tailwind v4 site's dark theme | hand-rolled selector split |
| `@charset`/`@import` glued onto the next selector | Bootstrap's entire `:root` block, 550 unresolved `var()` | brace walker ignored statement at-rules |
| `:root,[data-bs-theme=light]` judged wholly scoped | every Bootstrap 5.3 site's base tokens | selector list judged as a whole |

Four of the five are the same class of defect: **the tokenizer is an
approximation of the CSS grammar, and each site reveals a new corner of it.**
Fixing them one at a time is unbounded work. A spec-compliant tokenizer makes
that whole class go away rather than shrinking it.

The remaining accuracy gaps — cascade ordering, `color-mix()` — are then
tractable rather than blocked.

## What was verified before writing this

Not assumed. Probed directly (Python 3.14, clean venv):

- Both libraries are **pure Python**, no C extension. Only transitive dep is
  `webencodings` (BSD).
- `tinycss2.parse_stylesheet('@charset "UTF-8"; :root{--a:#112233}')` yields an
  `at-rule` and an intact `qualified-rule` with prelude `:root`. **The Bootstrap
  bug does not exist there.**
- `@layer base, utils;` and `@layer base { … }` are distinguishable
  (`rule.content is None` for the statement form), so layer order is derivable.
- `cssselect2.compile_selector_list` returns correct specificity, including the
  cases that matter here:

  | selector | specificity | note |
  |---|---|---|
  | `.dark\:bg-gray-950:where(.dark,.dark *)` | `(0, 1, 0)` | `:where()` correctly contributes 0 |
  | `.a:is(.b, .c)` | `(0, 2, 0)` | `:is()` takes the max of its arguments |
  | `.foo:not(.bar)` | `(0, 2, 0)` | so does `:not()` |
  | `:root` | `(0, 1, 0)` | |
  | `body` | `(0, 0, 1)` | |

- **A ~15-line stdlib `html.parser` subclass builds a tree `cssselect2` accepts.**
  This was the main risk and it is retired: no `lxml` (C extension) and no
  `html5lib` (slow, heavy) is required. Verified against deliberately messy
  markup — unclosed `<meta>`/`<br>`/`<p>`, uppercase `<DIV>`, unquoted attribute
  values — with `.dark\:bg-dark-primary` correctly matching `<body>` and
  `.bg-dark-primary` correctly not.

  > **It came in at ~55 lines, not 15** — the probe had no void-element list,
  > no end-tag matching, and no implied `</head>`, and all three turned out to
  > be load-bearing rather than polish. Worth carrying into phase 3's estimate:
  > the risky part of a shim like this is not the shape the probe demonstrates,
  > it is the list of exceptions the real corpus contains. Cost is fine —
  > 6 ms of a 170 ms run on developer.mozilla.org, 4 ms of 490 ms on the 11 MB
  > ground.news HAR, against ~0.1 ms for the two `re.search` calls it replaced.

### Python floor — settled

**Decided 2026-07-26: the floor is 3.10, and it is now verified rather than
nominal.** `requires-python = ">=3.10"`, ruff `target-version = "py310"`,
trove classifiers for 3.10–3.14. The suite passes on 3.10, 3.11, 3.12, 3.13 and
3.14, and 3.10 produces byte-identical JSON to 3.14 on the reference fixture.

This unblocks phase 1 with current releases and no pins:

| package | `requires-python` | note |
|---|---|---|
| `tinycss2` 1.5.1 | `>=3.10` | take this |
| `cssselect2` 0.9.0 | `>=3.10` | take this |
| `tinycss2` 1.3–1.4 | `>=3.8` | no longer needed |
| `cssselect2` 0.8.0 | `>=3.9` | no longer needed |

The old floor was 3.9 — never tested, and end-of-life since October 2025.

> Note for whoever schedules the next bump: **3.10 itself reaches end-of-life in
> October 2026.** Nothing in the codebase needs 3.11+, so this is a calendar
> decision rather than a technical one; raising to 3.11 costs nothing but is not
> yet motivated.

## Baseline to measure against

Record these now; "unchanged or better" is not checkable later without them.

**Inferred (guessed) grounds: 4 of 12 themes across the corpus.**

| site | grounds | inferred? |
|---|---|---|
| getbootstrap.com | `#ffffff` / `#212529` | no |
| ui.shadcn.com | `#f5f5f5` / `#262626` | **both** |
| www.djangoproject.com | `#f8f8f8` | no |
| news.ycombinator.com | `#ffffff` | **yes** |
| developer.mozilla.org | `#ffffff` | no |
| tailwindcss.com | `#f0b100` / `#030712` | **light only** |
| ground.news.har | `#eeefe9` / `#262626` | no |
| fleshandbonedesign.com.har | `#151515` | no |

Other counters: Bootstrap has **20** unresolved `var()` references remaining
(down from 550). `color-mix()` is skipped on **631** declarations on
tailwindcss.com and **211** on ui.shadcn.com. Tests: **65**. `ruff`: clean.

Reference fixture anchors that must not move: ground `#151515`,
`rgba(255,255,255,.75)` → `#c4c4c4` at 10.47:1, `#ffc600` `saved`, `#13330d`
`inert`, 20 tokens, 1 theme, no warnings.

> **When diffing JSON, drop the `generated` key first.** It holds a wall-clock
> timestamp, so two runs straddling a second boundary differ for no reason.
> This already cost one diagnostic pass.

## Scope

**Changes:** `cssparse.py` (most of it), `extract.py` (ground, var table,
weighting), `pyproject.toml`, CI matrix.

**Does not change:** `sources.py` and the `Bundle`/`Asset` layer, `color.py`,
`emit.py`, `images.py`, the CLI surface, and — critically — **the
`to_document()` JSON contract**. Keeping that fixed is what makes each phase
reviewable and the whole thing revertible.

Each phase is one commit, independently revertible, and leaves the tool working.

---

## Phase 1 — parser swap only — **DONE**

> **Outcome.** All acceptance criteria met. 66 tests (65 unchanged, none of
> their assertions edited, plus one new), `ruff` clean, reference fixture
> byte-identical to the previous commit, corpus grounds unchanged, module /
> console-script / zipapp JSON identical. Four departures from the plan as
> written, each deliberate:
>
> 1. **`split_selector_list` was kept.** The parser no longer needs it, but
>    `theme_scope`, `strip_theme_scope`, `selector_weight`, `detect_ground` and
>    `build_var_table` all still do. Deleting it now would mean pulling
>    `cssselect2` in early — phase 2's job. Same for `strip_comments`, which
>    survives only in `parse_inline_styles`, where it runs over HTML.
> 2. **`!important` moved out of `value`** onto `Declaration.important`. This
>    changed value strings on ~250 corpus declarations and dropped exactly one
>    — `--tw-backdrop-blur: !important`, whose value is empty once importance
>    is removed. It paints nothing, so dropping it is right.
> 3. **`var_refs` is now collected per declaration, not by regex over the
>    text.** Net effect on the corpus is one reference: `--tw`, which came from
>    `@supports not (hanging-punctuation:var(--tw))` — an at-rule prelude, and
>    a Tailwind feature probe never defined or painted.
> 4. **A latent bug had to be fixed for "unchanged or better" to hold.** See
>    below; it is now invariant 20.
>
> **What the swap uncovered.** Correct string handling meant selectors stopped
> reading `[data-theme=" "]`, which made django's `html[data-theme="dark"]`
> theme visible for the first time — and simultaneously made `theme_scope`
> match the marker inside `html:not([data-theme="light"])`, filing 124 dark
> declarations under *light*. A marker inside `:not()` is a negation; skipping
> those ranges fixes it. django went from 1 theme to 2 (`#f8f8f8` / `#181d27`),
> so the corpus is now **13 themes, 4 inferred**, against a baseline of 12 / 4.
>
> **Method note for phases 2–4.** The test suite and the reference fixture both
> passed on the first run *while django was mis-filed*. What caught it was a
> declaration-level multiset diff of old parser against new, over bundles
> frozen to disk so a site changing overnight could not be mistaken for a
> regression. Do that first, before the palette-level checks.

### As planned

Replace the brace walker with `tinycss2`, keeping the `Declaration` /
`Stylesheet` output shape byte-identical. **That shape is the seam**: nothing
downstream should need to know the parser changed.

1. Add `tinycss2` to `[project.dependencies]`.
2. Rewrite `parse_stylesheet` over `tinycss2.parse_stylesheet` →
   `parse_blocks_contents` for declarations. Populate `Declaration` exactly as
   now: `selector`, `prop`, `value`, `at_rules`, `order`, `sheet_order`,
   `theme`, `is_custom_property`.
3. Keep `at_rules` as the existing tuple of strings so `theme_scope`'s media
   path and `selector_weight`'s `@media print` / `@keyframes` handling keep
   working untouched.
4. Take `!important` from tinycss2 rather than string-matching, and store it on
   `Declaration` — unused until phase 3, but free to capture here.

**Delete:** `_mask_strings`, `strip_comments`, `_COMMENT`, `_DECL`, the
`parse_stylesheet` walker, `split_selector_list` (use
`tinycss2.parse_component_value_list` / `cssselect2`'s own splitting).

**Keep the tests.** Invariants 9, 17 and 18 become properties of the library
instead of hand-written code, but their tests stay — they now guard the
*integration*, which is exactly where a swap like this goes wrong.

**Acceptance:**
- All 65 tests pass with no edits to assertions.
- Reference fixture anchors unmoved.
- Corpus grounds unchanged or better; inferred count ≤ 4/12.
- Bootstrap's unresolved `var()` count ≤ 20.
- `ruff` clean; module/zipapp JSON identical (minus `generated`).

> The zipapp needs the dependency vendored into the staging dir now — update
> the build incantation in CLAUDE.md, or drop the zipapp target and say so.

---

## Phase 2 — real document, real selector matching — **DONE**

> **Outcome.** All acceptance criteria met. 69 tests (65 unchanged, plus four
> new; one deleted with its helper), `ruff` clean, reference fixture
> byte-identical to a fresh run of the previous commit, corpus grounds and
> palettes byte-identical across all eight inputs, module / console-script /
> zipapp JSON identical, 3.10 identical to 3.14. The shim landed in a new
> `dom.py`. Three departures from the plan as written:
>
> 1. **A fourth rule was needed: the blanket selector.** The plan anticipated
>    `:hover` and combinators. It did not anticipate that `*` and `:root *`
>    *genuinely select* `<html>`, so a real matcher says yes to them where the
>    regex said no. That is the single largest behaviour change in the phase and
>    it is a regression, not an improvement — see below. `dom._is_blanket`
>    refuses them, tested by matching against a nondescript element rather than
>    by pattern-matching selector text.
> 2. **`split_selector_list` was kept again**, and this time for a reason that
>    will not expire on its own: its five callers work on selectors that may not
>    compile, including ones `strip_theme_scope` itself can render invalid.
>    Retiring it needs phase 3's compiled-selector-per-rule, not `cssselect2`'s
>    presence. Noted at invariant 17.
> 3. **One implied end tag had to go into the shim.** `</head>` is optional and
>    routinely omitted, and `html.parser` closes nothing on its own, so `<body>`
>    was nesting inside `<head>` — `html > body` stopped matching and
>    `head .foo` started. `<head>`/`<body>`/`<frameset>` are children of
>    `<html>`, always; that is the only insertion rule, and it is exactly the
>    one the module's claim depends on.
>
> **What the change uncovered.** Promoting `*` to a page match would have let
> Tailwind v4's reset block — `* { --tw-gradient-from: #0000;
> --tw-ring-offset-color: #fff; --tw-shadow: 0 0 #0000 }` — outrank every
> utility that sets those properties to a real color, because invariant 19 lays
> page-scoped definitions over the rest. Measured: 11 named colors on
> ground.news collapsing to `#0000`/`#fff`, 26 on tailwindcss.com, and MDN's
> `light-dark()` polyfill (`:root *`) reduced to its dark branch, taking
> `--color-background-page` from `#ffffff`/`#18191b` to `#18191b` alone.
>
> **Method note.** Phase 1's lesson was "diff declarations, not palettes."
> Phase 2 changed no declaration — it changed one boolean — so the readable
> diff was that boolean, over every `(selector, kind)` pair its two call sites
> hand it, old implementation against new. 379 declarations flipped; 345 were
> the blanket selectors above. **The palette diff at the end was
> byte-identical**, so the palette check alone would have shipped the inversion
> silently. Generalised at the end of CLAUDE.md's breadth-check section: diff at
> the level the change operates on.
>
> **What phase 3 inherits.** Real specificity is now one
> `compile_selector_list(sel)[i].specificity` away, correct on `:where()`
> (contributes zero) and `:is()`/`:not()` (max of arguments) — the cases that
> defeat a hand-rolled count and the reason CLAUDE.md's "all four or none"
> argument concluded against trying.

### As planned

1. Add the stdlib `html.parser` → `ElementTree` shim (verified above) in
   `sources.py` or a new `dom.py`. It must keep returning **`None` when the
   document could not be read at all**, distinct from a document with no
   classes — invariant 16 depends on that distinction and
   `test_unreadable_document_is_not_an_empty_one` guards it.
2. Add `cssselect2`. Replace `matches_page_element` with a real matcher against
   `<html>`/`<body>`.
3. Lift the single-compound restriction. `matches_page_element` is currently
   narrow on purpose because a hand-rolled matcher cannot be trusted further; a
   real one can.

**Delete:** `_SIMPLE`, `_attr_matches`, `unescape_ident`, `PageElement`'s
hand-parsed attribute handling. — **all four deleted**, along with `_TAG_ATTR`
and `_IDENT_ESC`; `cssparse.py` went 772 → 615 lines.

**Tests that encode the old restriction and need conscious review** — each is
currently correct, and stays correct for a *different reason*:

- `.flex .bg-light-primary` → `False`. Still false, because the body is not a
  descendant of `.flex` — not because combinators are rejected wholesale.
- `.bg-light-primary:hover` → `False`. Decide deliberately: a real matcher can
  evaluate `:hover` structurally. Keep it false — a hover state is not the
  page's resting background — but make that an explicit rule, not a side effect.
  **Kept false, explicitly.** `cssselect2` flags exactly the dynamic-state
  pseudo-classes `never_matches` and `ElementWrapper.matches` drops them; the
  code skips them itself so the rule is stated rather than inherited.
- `page_elements`' escape handling tests move to the shim. **Done differently:**
  `unescape_ident` had a unit test, and with the helper gone the guard moved
  onto the behaviour — `.dark\:bg-dark-primary` and `.dark\3a bg-dark-primary`
  must both reach the class the body carries, asserted in
  `test_matches_only_what_selects_the_page_element`.

**Acceptance:** as phase 1, plus `TestPageElement` and `TestUtilityGround` pass
(with the two rewrites above documented in the commit message).

---

## Phase 3 — the actual cascade

The payoff, and the only phase that changes documented invariants.

Implement `importance → layer → specificity → document order` as the ordering
key in `detect_ground` and `build_var_table`.

1. Build the `@layer` order from the statement-form `@layer a, b;` declarations
   plus first-appearance of block forms. Unlayered rules sort **after** all
   layers (per spec).
2. Sort candidates on `(important, layer_index, specificity, sheet_order,
   order)`.
3. Collapse the approximations this replaces.

**Invariants that change — read before touching:**

- **Invariant 2** warns that "weighting picks the framework's default
  background." That warning is about `selector_weight`, the *usage heuristic* —
  not about CSS specificity. Real specificity is part of the cascade and does
  not conflict with it. **A future reader will hit invariant 2 and stall here
  unless this distinction is kept in front of them.**
- **Invariant 2's theme addendum** (`Usage.cascade_key`'s scoped bit) becomes
  redundant for selector-scoped themes — `html.dark` genuinely outranks `html`
  on specificity. It is still needed for `prefers-color-scheme` themes, which
  have no specificity difference at all. Keep it, narrowed to the media case.
- **Invariant 13** (theme shadowing on `(selector, prop)`) is a specificity
  approximation. Re-evaluate; it may survive as a narrower rule or retire.
- **Invariant 16** becomes "the matcher decides," and its candidate-set framing
  can be retired — along with the documented limit that it is not a specificity
  model.
- **Invariant 19** (page-scoped `var()` definitions outrank off-page ones)
  becomes a specificity consequence rather than a special case.

Retire each one **consciously and in writing**. A silently deleted invariant is
how the bug it prevented comes back.

**Acceptance:** corpus inferred count strictly better than 4/12, reference
fixture unmoved, and every retired invariant's test either still passes or is
removed with a note in CLAUDE.md saying which rule now covers it.

---

## Phase 4 — `color-mix()` and `light-dark()`

Independent of 1–3; can land at any point.

- `color-mix(in <space>, A p%, B q%)` — defined interpolation in a named space.
  `color.py` already has OKLab, Lab and sRGB conversions. Support at minimum
  `srgb`, `oklab`, `oklch`, `lab`, `lch`; return `None` for spaces not
  implemented, per the existing "parse or return None, never guess" convention.
- `light-dark(A, B)` — two values selected by the active theme, which this tool
  already models per palette. Nearly free and directly relevant.

**Acceptance:** the 631 + 211 skipped declarations resolve; corpus grounds
unchanged (these appear in component colors, not page backgrounds, so a moved
ground means something is wrong).

---

## Explicitly out of scope

**A headless browser** (Playwright + `getComputedStyle`) would be more accurate
than all of the above and is still the wrong trade:

- It cannot run against a HAR, which is the tool's best input format and the
  only one that works on sites refusing automated requests.
- `getComputedStyle` returns resolved values with **no provenance**. "Which
  selector declared this" is in the JSON contract and is most of the HTML
  report. Recovering it needs `CSS.getMatchedStylesForNode` over CDP — a much
  larger build.

Worth naming as the ceiling. Revisit only if phases 1–4 leave grounds
materially wrong on real sites.

## Checklist

- [x] Decide the Python floor — **3.10, verified across 3.10–3.14**
- [x] Phase 1 — `tinycss2` swap behind the `Declaration` seam
- [x] Update or retire the zipapp build for a vendored dependency —
      **updated**; `uv pip install --target` vendors `tinycss2` +
      `webencodings` into the staging dir, incantation in CLAUDE.md
- [x] Phase 2 — `html.parser` shim + `cssselect2` matching — **landed
      2026-07-26** as `dom.py`; grounds and palettes unchanged corpus-wide
- [ ] Phase 3 — full cascade; retire invariants 13/16/19 in writing
- [ ] Phase 4 — `color-mix()`, `light-dark()`
- [ ] Re-run the breadth check in CLAUDE.md after every phase
