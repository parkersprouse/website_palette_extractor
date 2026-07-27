# Migration plan: hand-rolled CSS reading → `tinycss2` + `cssselect2`

Status: **all four phases landed 2026-07-26.** Written 2026-07-26.

**The migration is done; the work it left behind is not.** See
[Outstanding work](#outstanding-work) below — fourteen tasks, three of them
decisions the owner has since settled, and it is the authority for what is
left. `CLAUDE.md`'s Migration TODO points there rather than duplicating it.

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
> decision rather than a technical one; ~~raising to 3.11 costs nothing but is
> not yet motivated.~~
>
> **Superseded 2026-07-26: the owner decided to raise the floor to 3.11.** The
> calendar motivated it — October 2026 is roughly three months out. The section
> above describes the 3.10 floor **as currently shipped**; it stays as written
> until the bump lands, at which point every claim in it moves. See
> **T2** in [Outstanding work](#outstanding-work) for the seven edits.
>
> **T2 landed 2026-07-26.** Every claim above now reads 3.11, not 3.10: floor
> is `>=3.11`, ruff `target-version = "py311"`, trove classifiers 3.11–3.14,
> suite re-verified on 3.11/3.12/3.13/3.14 (95 tests, all pass), and JSON is
> byte-identical between 3.11 and 3.14 on the reference fixture. Left the
> section above as written rather than rewritten in place — same reasoning as
> phase 3's invariant corrections: a struck-through prediction next to what
> actually happened is more useful to the next reader than a silently updated
> past.

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

## Phase 3 — the actual cascade — **DONE**

> **Outcome.** 77 tests (69 unchanged, none of their assertions edited, plus a
> new `TestCascade` of eight), `ruff` clean, reference fixture anchors unmoved,
> **all eight corpus palettes byte-identical** to a fresh run of the previous
> commit, module / console-script / zipapp JSON identical, 3.10–3.14 all pass.
> Cost 4–7% (`getbootstrap.com` 364 → 390 ms), held down by an `lru_cache` on
> `selector_specificity`.
>
> **This phase's invariant list was wrong on three of four, and the errors all
> ran the same way: they predicted a rule would dissolve into specificity when
> specificity cannot express it.** Corrected below in place. The generalisable
> lesson is that *specificity is not the cascade* — it is one term of four, and
> it only ever runs after the matching step has chosen the candidates.
>
> **One acceptance criterion was not met and is not reachable from this phase.**
> "Corpus inferred count strictly better than 4/12" assumed the cascade would
> recover a ground somewhere. It cannot: all four inferred grounds are inferred
> because **no page-level background color is readable at all**, not because the
> readable ones were ranked wrongly.
>
> | inferred ground | why | reachable by |
> |---|---|---|
> | ui.shadcn.com, both themes | ~~the only `<body>`/`<html>` backgrounds are `color-mix(in oklab, …)`~~ **wrong — see below** | ~~phase 4~~ nothing |
> | news.ycombinator.com | painted by the presentational attribute `bgcolor="#f6f6ef"`; its `body` rules set no background at all | nothing — it is not CSS |
> | tailwindcss.com, light | `<html>` carries `dark:bg-gray-950` and no light counterpart; there is no light page-background rule to read | nothing |
>
> **Corrected while implementing phase 4**, by enumerating every page-level
> background candidate per theme rather than reasoning about it: ui.shadcn.com
> has **zero** in either theme. Its `<body>` carries `overscroll-none
> group/body antialiased` and no background utility, and it ships no
> `body`/`html`/`:root` background rule at all. It is the same category as the
> two rows below it — nothing to rank, not something ranked wrongly. Phase 4
> left it inferred, and no phase reaches it.
>
> Written down rather than quietly dropped, because the number is the headline
> measure in the baseline section and someone will check it. **The honest
> summary of phase 3 is that it changed no answer on the corpus and changed 12
> custom-property resolutions, every one of them a fix** — see below. It is
> insurance against a class of error the corpus does not currently contain,
> which is a real result but not the one this line promised.
>
> **What moved, and why each is a fix.** The readable diff was the ordering
> key, dumped at both call sites over frozen bundles, old against new. Ground
> winners: **zero changed**; candidate rank order: **zero changed**. Twelve
> custom properties resolved differently, in three groups, none of them a color
> — which is why the palettes are byte-identical:
>
> | site | what moved | term responsible |
> |---|---|---|
> | getbootstrap.com | 5 `--docsearch-*`: `html[data-theme=dark]` `(0,1,1)` now beats the later `[data-bs-theme=dark]` `(0,1,0)` | specificity |
> | ui.shadcn.com | 3 `--font-*`: an **unlayered** class on `<html>` now beats `@layer theme`'s `:root`. The old winner was the self-referential `var(--font-sans)`, which resolved to nothing | layer |
> | developer.mozilla.org | `--sticky-header-height`: `:root{…!important}` now beats a later normal `:root` | importance |
>
> **Departures from the plan as written**, beyond the invariant corrections:
>
> 1. **`!important` reverses the layer order**, which the plan did not mention.
>    Among important declarations the earlier layer wins and an unlayered
>    important declaration is the weakest of them. Implemented, because it is
>    the reason importance cannot be a simple tiebreak — it changes what the
>    next term *means*. Nothing on the corpus exercises it; `TestCascade`
>    does.
> 2. **`split_selector_list` was kept a third time.** Phase 2 predicted it
>    would go when "phase 3 gives every selector a compiled form it can rely
>    on." It does not: `_page_specificity` needs to pair the *matched* form of
>    a selector list with the *declared* form part by part, and both may be
>    uncompilable. Its five callers are unchanged. It is not going away; the
>    note at invariant 17 should stop promising that it will.
> 3. **Candidates matching `<html>` and `<body>` are still ranked in one pool**,
>    which the cascade never does. Deliberately deferred: instrumenting every
>    ground candidate with the element it reaches showed **no corpus site has
>    page-level background candidates on both elements**, so grouping would
>    sort the same pools in the same order. Recorded at `detect_ground` with
>    the shape of the fix, rather than written blind.
> 4. **`@import url(…) layer(x)` is not modelled**, because `@import` is not
>    followed. Named at `layer_order` rather than pretended.

### As planned

Implement `importance → layer → specificity → document order` as the ordering
key in `detect_ground` and `build_var_table`.

1. Build the `@layer` order from the statement-form `@layer a, b;` declarations
   plus first-appearance of block forms. Unlayered rules sort **after** all
   layers (per spec).
2. Sort candidates on `(important, layer_index, specificity, sheet_order,
   order)`.
3. Collapse the approximations this replaces.

**Invariants that change — corrected after the fact. Three of the four
predictions below were wrong; the strikethrough is the prediction and the text
under it is what actually happened.**

- **Invariant 2** warns that "weighting picks the framework's default
  background." That warning is about `selector_weight`, the *usage heuristic* —
  not about CSS specificity. Real specificity is part of the cascade and does
  not conflict with it. **A future reader will hit invariant 2 and stall here
  unless this distinction is kept in front of them.** — **Correct as written.**
  `selector_weight` is untouched by this phase.
- **Invariant 2's theme addendum** (the scoped bit) becomes redundant for
  selector-scoped themes — `html.dark` genuinely outranks `html` on
  specificity. It is still needed for `prefers-color-scheme` themes, which have
  no specificity difference at all. Keep it, narrowed to the media case. —
  **Correct as written**, and now `Usage.theme_media`. The one thing the plan
  did not say is *where the term goes*: **between specificity and document
  order**, never above specificity. A media-dark `body` must beat a later
  unscoped `body` and must lose to an unscoped `.bg-x` the body carries,
  because a browser does both.
- ~~**Invariant 13** (theme shadowing on `(selector, prop)`) is a specificity
  approximation. Re-evaluate; it may survive as a narrower rule or retire.~~ —
  **Wrong: it is not a specificity approximation at all.** Invariant 13 decides
  **which colors enter the palette**, and the cascade decides **which value a
  property resolves to**. Those are different questions and specificity cannot
  answer the first: no ranking removes a color from a bucket. Kept verbatim,
  its test untouched and still passing.
- ~~**Invariant 16** becomes "the matcher decides," and its candidate-set
  framing can be retired — along with the documented limit that it is not a
  specificity model.~~ — **Half wrong.** The candidate-set framing *stays*, and
  `_is_blanket` is why: a real matcher over-matches, and `*` genuinely selects
  `<html>`. What phase 3 retires is only the **documented limit beneath it** —
  "a site whose element-matched utility came earlier than a competing `body`
  rule would still be read wrongly." That is now false, and
  `test_specificity_beats_a_later_rule_of_lower_specificity` is the case.
- ~~**Invariant 19** (page-scoped `var()` definitions outrank off-page ones)
  becomes a specificity consequence rather than a special case.~~ — **Wrong,
  and the most costly of the three to have believed.** `:root` and
  `[data-bs-theme=blue]` are **both `(0, 1, 0)`**, so specificity cannot
  separate them and the blue block is written later. Invariant 19 is a
  **matching** rule, not a specificity one: the cascade only ranks declarations
  from rules that match the element, and the document's `<html>` carries no
  `data-bs-theme=blue`. It survives verbatim. What changed is only how the
  page-reaching set is resolved among itself — full cascade instead of
  last-wins. Off-page definitions stay on last-wins, since ranking rules that
  match *different* elements by specificity is precisely the error above.

Retire each one **consciously and in writing**. A silently deleted invariant is
how the bug it prevented comes back.

**Acceptance:** ~~corpus inferred count strictly better than 4/12~~ (not
reachable — see the outcome table above), reference fixture unmoved, and every
retired invariant's test either still passes or is removed with a note in
CLAUDE.md saying which rule now covers it. **Met, with that one exception
stated.**

---

## Phase 4 — `color-mix()` and `light-dark()` — **DONE**

> **Outcome.** 93 tests (78 unchanged, none of their assertions edited, plus
> `TestColorMix` of nine, `TestLightDark` of five, and one in `TestCss`), all
> fifteen run against the stashed `palettekit/` and required to fail there.
> `ruff` clean, **reference fixture byte-identical** to a fresh run of the
> previous commit, 3.10 identical to 3.14, module / console-script / zipapp
> JSON identical. 895 `color-mix()` declarations and 70 `light-dark()` ones now
> resolve; six still do not, and they are named below. Cost is 5–10% on the two
> heaviest sites (tailwindcss.com 1219 → 1340 ms, ui.shadcn.com 925 → 968 ms)
> and nothing measurable elsewhere.
>
> **The headline is the theme, not the mix.** `color-mix()` moved a great many
> colors and no ground, exactly as the rewritten criterion above predicted.
> `light-dark()` moved developer.mozilla.org from **one theme to two**,
> `#ffffff` / `#18191b`, both read from `html { background-color }` rather than
> inferred. The corpus is now **14 themes, 4 inferred** against phase 3's 13/4.
>
> Palette-level blast radius was exactly the four sites that use either
> function; getbootstrap.com, www.djangoproject.com, news.ycombinator.com and
> fleshandbonedesign.com.har are byte-identical.
>
> **Departures from the plan as written:**
>
> 1. **`light-dark()` had to become a theme *mechanism*, not just a value.**
>    The plan called it "two values selected by the active theme, which this
>    tool already models per palette" — true, and not sufficient. MDN ships no
>    `prefers-color-scheme` block and no theme class worth the name; the
>    function *is* the whole declaration of its dark theme. Resolving branches
>    without registering scopes would have picked light everywhere and
>    **deleted** every dark color the tool used to report. `_scopes_present`
>    now reads it as declaring both. Invariant 23.
> 2. **A phantom color had to be fixed for "unchanged or better" to hold** —
>    the same shape phase 1 hit with invariant 20, and found the same way.
>    `resolve_vars` substitutes *text* where CSS substitutes *tokens*, so
>    Tailwind v4's minified
>    `color-mix(in oklab,var(--color-white)var(--tw-shadow-alpha),transparent)`
>    resolved to `#fff100%` and the scanner read the hex `#fff100` — a bright
>    yellow, 18 occurrences on ground.news, painted nowhere. Phase 4 removed it
>    (the mix no longer parses) and would have reported *nothing* in its place;
>    padding substitutions at token boundaries reports white at 100%, which is
>    what the page paints. Invariant 24.
> 3. **The zero-alpha short circuit is accuracy, not speed.** `color-mix(in
>    oklab, X p%, transparent)` is ~90% of the corpus and the premultiplied
>    algebra collapses there exactly to "X at alpha × p". Round-tripping
>    through OKLab instead lands ±1 off on some channels, and buckets are keyed
>    on the quantised hex — the drift would invent palette entries out of
>    rounding. Invariant 22.
> 4. **Powerless-hue thresholds are per-space and are noise floors.** A true
>    grey converts to a chroma of ~1e-5 in CIE Lab and ~4e-8 in OKLab, all
>    rounding; the nearest genuinely tinted grey sits at 0.56 and 1.5e-3. One
>    shared epsilon cannot serve both, because Lab chroma runs to ~150 and
>    OKLab chroma to ~0.4. Found by a test, not by reading.
> 5. **`calc()` percentages are refused, and that is the whole remaining gap** —
>    six declarations, all `.shimmer-color-*` on ui.shadcn.com writing
>    `color-mix(in oklch, <color> calc(60 * 1%), transparent)`. Evaluating them
>    needs a `calc()` evaluator, which is a different piece of work; guessing
>    50% would print a color the page does not paint.
>
> **What the diff showed that a palette check would not.** Per-declaration
> color lists, per theme, over frozen bundles. Beyond the phantom above it
> found the intended removals — `color-mix(in oklab,var(--color-gray-950),white
> 90%)` used to contribute `#030712` *and* `#ffffff`, neither of which is on the
> page, and now contributes the one color that is, `#e1e2e4`. The palettes
> would have shown a plausible net change either way.
>
> **One pre-existing defect found and deliberately not fixed.** `resolve_vars`
> matches `var()` with a non-greedy regex, so a fallback containing parens —
> `var(--shimmer-image, linear-gradient(…))` on ui.shadcn.com — is cut at the
> first `)` and the rest of the value is left as garbage. It produced garbage
> before this phase and after it, on three declarations of one site. It is a
> `var()` bug, not a `color-mix()` one, and folding it in would bury it.
>
> **Fixed since, and it was three declarations of one site only where the
> garbage was visible.** `_var_call` now counts parentheses with
> `color.balanced_end` (invariant 25). Predicted from the frozen bundles before
> any code was written: 102 distinct affected calls on **five** sites, not one
> — so "only ui.shadcn.com moves" was falsified in advance rather than
> discovered afterwards. The per-declaration color diff then found the real
> shape of it: 204 declarations whose *discarded* fallback had been resolving a
> second time as an orphaned tail, counting every color in it twice. Every hex
> set, ground and warning on all eight sites is identical; occurrence counts and
> the token names ranked from them are what moved.
>
> That landed as `6507dda` and added two tests, so **the suite is 95, not the
> 93 this outcome block records** — 93 was the count at phase 4 itself and is
> left as written. 95 is the number `CLAUDE.md` and `README.md` should agree
> with, and the number a fresh run produces.

### As planned

Independent of 1–3; can land at any point.

- `color-mix(in <space>, A p%, B q%)` — defined interpolation in a named space.
  `color.py` already has OKLab, Lab and sRGB conversions. Support at minimum
  `srgb`, `oklab`, `oklch`, `lab`, `lch`; return `None` for spaces not
  implemented, per the existing "parse or return None, never guess" convention.
  — **Done, and eleven spaces rather than five**: `srgb`, `srgb-linear`, `hsl`,
  `hwb`, `lab`, `lch`, `oklab`, `oklch`, `xyz`, `xyz-d50`, `xyz-d65`. The extra
  six cost almost nothing once the Lab inverse matrices were in — those were
  needed for `lab`/`lch` regardless, and `xyz` is the intermediate they pass
  through. The corpus uses only `oklab` (905 declarations) and `oklch` (14).
- `light-dark(A, B)` — two values selected by the active theme, which this tool
  already models per palette. Nearly free and directly relevant. — **Done, and
  it is a theme mechanism**, not only a value: see departure 1 above.

**Acceptance — rewritten before implementing, because as first written it was
wrong in both directions.** It said "corpus grounds unchanged … a moved ground
means something is wrong". Measured against frozen bundles, the opposite holds:

- **`color-mix()` reaches no page background on any corpus site.** Enumerating
  every page-level `background`/`background-color` candidate per theme, across
  all eight inputs, exactly one is touched by either function — and it is a
  `light-dark()`. So "grounds unchanged" is right for `color-mix()` and is not
  a check of anything, since nothing was at risk.
- **`light-dark()` must move a ground, and that is the phase's headline.**
  developer.mozilla.org writes `html { background-color:
  var(--color-background-page) }` where that property resolves to
  `light-dark(#fff,#18191b)`. Today both branches land in one palette and the
  site reads as one theme. Reading the branch the theme selects is what makes
  its dark ground readable at all.
- ~~"two of the four inferred grounds are waiting on this phase"~~ — **false,
  and stated in three places.** ui.shadcn.com has **zero** page-level
  background candidates in either theme: its `<body>` carries no background
  utility and it ships no `body`/`html`/`:root` background rule. It is the
  same category as tailwindcss.com's light ground and news.ycombinator.com's
  `bgcolor` attribute — nothing to rank, not something ranked wrongly. Phase 4
  moves the inferred count not at all. Corrected at its three sites.

So: **the reference fixture is the hard check** — `fleshandbonedesign.com.har`
contains neither function, so every anchor must be byte-identical.
developer.mozilla.org gains a light/dark pair, `#ffffff` / `#18191b`. **No
other ground moves.** Palette *contents* change on the three `color-mix()`
sites and on MDN, which is the point, and the readable diff is the one below.

**Diff at the per-declaration color list** — `(sheet_order, order, selector,
prop) → [hexa]`, per theme, old against new over frozen bundles. Not the
palette, which folds and merges, and not the declaration, which does not change
at all this phase. It is the only level that shows the *removals*: a
`color-mix()` this tool cannot evaluate now yields nothing, where today its
inner argument leaks out as a full-opacity color the page never paints.

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

- [x] Decide the Python floor — **3.10, verified across 3.10–3.14**.
      Superseded: the owner raised it to **3.11** on 2026-07-26; shipping that
      is **T2**, now landed
- [x] Phase 1 — `tinycss2` swap behind the `Declaration` seam
- [x] Update or retire the zipapp build for a vendored dependency —
      **updated**; `uv pip install --target` vendors `tinycss2` +
      `webencodings` into the staging dir, incantation in CLAUDE.md
- [x] Phase 2 — `html.parser` shim + `cssselect2` matching — **landed
      2026-07-26** as `dom.py`; grounds and palettes unchanged corpus-wide
- [x] Phase 3 — full cascade — **landed 2026-07-26**. Invariants 13, 16 and 19
      were re-read and **kept**: the prediction that they would dissolve into
      specificity was wrong in all three cases, corrected in writing above.
      Palettes byte-identical corpus-wide; 12 custom properties resolve better
- [x] Phase 4 — `color-mix()`, `light-dark()` — **landed 2026-07-26**. Moved
      one ground and it was `light-dark()`'s, not `color-mix()`'s:
      developer.mozilla.org goes from one theme to two. The inferred count is
      unchanged at 4, and the ~~"two of the four are waiting on this
      phase"~~ claim was wrong — corrected in the acceptance section above
- [x] Re-run the breadth check in CLAUDE.md after every phase

### Outstanding — see [Outstanding work](#outstanding-work) for each

Decided by the owner 2026-07-26, ready to build:

- [x] **T1** — rebuild the zipapp (vendored deps + a `sys.version_info` guard),
      and make rebuilding it part of finishing a session — **landed
      2026-07-26**. `palettekit.PYTHON_FLOOR` guards `main()` before anything
      else; `python3 build.py` (T12) rebuilds and vendors; verified against an
      interpreter with neither dependency installed
- [x] **T2** — raise the Python floor to 3.11 — **landed 2026-07-26**. All
      seven edits made; suite re-verified on 3.11–3.14 (95 tests) and JSON
      byte-identical to 3.14 on the reference fixture. `__version__` bumped to
      `1.1.0` — see the note at T2 below for why a minor bump and not a major
      one
- [x] **T3** — `to_document` as a *versioned* public API — **landed
      2026-07-26**. Added top-level `schemaVersion: 1`; compatibility promise
      written in `README.md`'s Output section; shape asserted by a new test

Accuracy gaps left by phases 1–4:

- [x] **T4** — read `initial` as guaranteed-invalid, take the fallback —
      **landed 2026-07-26**. `resolve_vars` now checks the stored value against
      the literal keyword before substituting it. Verified against a frozen
      `tailwindcss.com` bundle, old code against new: the dark theme's
      `violet` token (`#ad46ff`) goes 29 → 137 occurrences and its `teal`
      token (`#00d5be`) goes 22 → 130 — an **exact match** to the numbers
      recorded when this task was written, reproduced on a fresh fetch. (An
      earlier draft of this entry claimed the live site's content had drifted
      to explain a mismatch; that mismatch was a self-inflicted measurement
      error — summing occurrences across every violet-ish hex in the corpus
      rather than reading the one dominant token — not a real discrepancy.
      Corrected after being challenged on it.) No ground moved, no token count
      changed. `ground.news.har` and `fleshandbonedesign.com.har` are
      byte-identical before and after (minus `generated`) — the shimmer trap
      T4 warns about is ui.shadcn.com's, not on either local fixture. That
      trap (T9's half) is untouched by this change, as predicted
- [x] **T5** — evaluate `calc()` in a `color-mix()` percentage — **landed
      2026-07-26**. Tokenized with `tinycss2` (not a hand-rolled scanner — see
      the corollary this prompted, below); a small recursive-descent evaluator
      (`color.eval_calc_percentage`) handles literal `+ - * /` arithmetic over
      the resulting numbers and percentages;
      anything outside that — `var()`, mixed units, percent×percent, division
      by a percentage — returns `None`, same as an unreadable mix always has.
      Verified against a frozen `ui.shadcn.com` bundle, old code against new,
      at the per-declaration color list: exactly six declarations move, all
      `.shimmer-color-blue-500\/60 { --shimmer-color }`, three per theme — the
      whole predicted blast radius and nothing else. Ground, warnings and
      every other token are byte-identical; one new token (`#7caefb`) appears
      in both themes. 98 → 100 tests, `ruff` clean, 3.11–3.14 verified
- [x] **T6** — an at-rule nested in a style rule loses its declarations —
      **the one that grows on its own** as CSS nesting spreads. **Landed
      2026-07-27.** See T6's own write-up below
- [x] **T7** — resolve `<html>` and `<body>` in separate pools, body
      preferred. **Landed 2026-07-27.** See T7's own write-up below
- [ ] **T8** — `@import url(…) layer(x)` should register a layer — parse
      `layer(x)` from `node.prelude`'s `tinycss2` tokens (a `FunctionBlock`
      named `layer`), not a regex over the serialized prelude — see the
      T5/T15 corollary and T8's own note below
- [ ] **T9** — model scoped custom properties (`@property`, inheritance)
- [ ] **T10** — read `color-scheme` to confirm a `light-dark()` site is really
      two-themed — **waiting on a counter-example; do not do this yet**

Repo and process:

- [ ] **T11** — CI: 3.11–3.14, `ruff`, and package/zipapp/console-script JSON
      identity
- [x] **T12** — `Makefile` or `build.py` for the zipapp incantation —
      **landed 2026-07-26** as `build.py`
- [ ] **T13** — move `test_palettekit.py` into `tests/`, split by module
- [ ] **T14** — fixture corpus of small committed HTML files — **unblocks
      checking every other task**; a fresh clone can currently regenerate
      nothing
- [x] **T15** — audit hand-rolled scanning/parsing across the whole codebase
      against the T5 corollary (defer to a library already in the dependency
      set for anything it does correctly; hand-roll only what it can't do).
      **Landed 2026-07-27; see the full write-up below.** Done:
      `color.py`'s `_split_top`/`_split_component` now tokenize with
      `tinycss2` instead of hand-rolled depth-counting — same risk profile as
      T5, verified byte-identical on the frozen `ui.shadcn.com` bundle.
      **A second, real bug turned up finishing the audit's second half**
      (`cssparse.py`/`extract.py`, not `color.py`): `_VAR_NAME` was defined
      twice at `cssparse.py` module scope, so the second definition silently
      shadowed the first, and the `var_refs` collection that decides `live`
      vs `saved` (invariant 10) was running the *wrong* pattern — one with no
      `var(` anchor at all, so it read any `--name`-shaped text anywhere in a
      value as a reference. Confirmed on the live corpus, not just a
      synthetic case: ground.news ships Tailwind arbitrary-value utilities
      like `.bg-\[--color-bg\]{background-color:--color-bg}`, a bare dashed
      identifier used directly as a value (invalid CSS, paints nothing) —
      the old pattern misread that literal text as a reference to
      `--color-bg`. Replaced with a token walk (`_var_ref_names`) that only
      recognizes an actual `FunctionBlock` named `var`, recursing into every
      function/block's contents so a `var()` nested in another `var()`'s own
      fallback still counts. `extract.py` carried its own duplicate of the
      correct pattern for the same job in `_triplet_warning`; both now share
      `cssparse.var_refs`. 101 → 103 tests, `ruff` clean. Diffed at the
      aggregate `var_refs`-set level per phase 4's methodology: byte-identical
      `to_document` output on `fleshandbonedesign.com.har` and on frozen
      `ui.shadcn.com`/`tailwindcss.com` bundles; ground.news is the only
      corpus site that moves, `customPropertiesReferenced` 159 → 158 for the
      light theme, exactly the predicted shape.
      Reviewed and left alone: `_whole_value_spans`/`balanced_end` — already
      delegates the hard part to a shared, quote/escape-aware utility, and
      switching to tokens would trade a working solution for the fragility of
      reconstructing string offsets from a token list, with no accuracy gain.
      `cssparse.py`'s theme/selector regexes (`_THEME_MEDIA`, `_THEME_CLASS`,
      `_THEME_IS`, `_THEME_ATTR`, `_REDUNDANT_HTML`, `_NOT_OPEN`) and
      `extract.py`'s `_PAGE_SEL` — invariant 17 already covers these: every
      caller runs over raw preludes that may not compile, or over
      `strip_theme_scope` output that can itself be invalid, so a
      `cssselect2`-compiled form isn't available to switch to. The anchored
      validators (`_HEX`, `_FUNC`, `_PERCENT`, `_CALC_CALL`, `_TRIPLET`,
      `_ZERO_LEN`, `_WS`) match a whole, already-delimited string rather than
      scanning one, so there is no tokenization being re-derived.
      `is_inert_shadow`'s regexes work the same way, on an already-isolated
      `drop-shadow()`/shadow value. The HTML-scanning regexes
      (`_STYLE_OR_LINK`/`_document_order`, `extract_style_blocks`,
      `extract_stylesheet_links`, `parse_inline_styles`'s attribute regex) are
      a different domain entirely — neither `tinycss2` nor `cssselect2` parses
      HTML, and `dom.py`'s `html.parser` shim is deliberately narrow (only
      `<html>`/`<body>` ancestry); reusing it for general markup extraction is
      a `dom.py`/`lxml`-sized question of its own, not a mechanical swap, and
      stays unfiled. **Two findings still need the owner's explicit sign-off
      before anyone touches them, each roughly the size of the `dom.py`/`lxml`
      question — filed as T16 and T17 rather than left as unfiled findings.**
      Not touched: `dom.py`'s `html.parser` tree shim versus `lxml` — see its
      own note below, unchanged from the original scope of this task
- [x] **T16** — rewrite `resolve_vars`'s `var()` substitution on `tinycss2`
      tokens instead of text, replacing the `_GLUE_LEFT`/`_GLUE_RIGHT`
      glue-padding heuristic with `tinycss2.serialize()`'s own adjacency
      rules — **landed 2026-07-27**; see T16's own write-up below for the
      `/**/`-vs-comment-blind-scanner hazard it found and the measured
      corpus/perf blast radius
- [x] **T17** — rewrite `COLOR_TOKEN` on `tinycss2` tokens (a `FunctionBlock`'s
      `.lower_name` identifying `rgb()`/`hsl()`/`oklch()`/etc. instead of a
      name regex plus a hand-bounded nesting allowance) to fill its known
      nesting gap — **landed 2026-07-27**; see T17's own write-up below for
      the corpus diff, which found two real bugs the nesting gap itself
      never appears to cause
- [x] **License** — `LICENSE.md` + the `[project.license]` and classifier
      entries — **landed 2026-07-26**. Owner chose the Hippocratic License
      3.0; see "License" under Outstanding work below

---

# Outstanding work

**This section is the authority for what is left to do.** `CLAUDE.md`'s
Migration TODO points here rather than repeating it — two lists of the same
work is exactly the drift this session was spent finding, and one of them will
always be the stale one.

Nothing below is a phase. Phases 1–4 were one migration with a shared
acceptance bar; these are independent, and any of them can land alone.

**Ordering, if you want one.** T4 was worth the most by a wide margin — it was
the only open item that moved colors and token names on a real site today, and
it landed 2026-07-26. T6 is the one that gets worse on its own, because native
CSS nesting is making the shape it mishandles more common every year. T14 is
the one that unblocks *checking* any of the others, since a fresh clone can
currently regenerate no fixture at all. Everything else is genuine but static.

Each task carries the level its change should be **diffed** at. That is this
project's most expensive lesson — phase 1 passed the whole suite and the
reference fixture while mis-filing 124 declarations, phase 2 was byte-identical
at the palette level while inverting 345, and phase 4's only real finding was a
*removal*. A test that passes before and after tests nothing about the change.

---

## Decided by the owner, 2026-07-26

These three were open questions until the owner settled them. Recorded as
decided; the work is described, not re-argued.

### T1 — Rebuild the zipapp, and make rebuilding it part of finishing a session

> **Outcome — landed 2026-07-26.** Both faults fixed and diffed at the level
> this section names:
>
> - **Fault 1 (stale walker)** — `build.py` (T12) rebuilds from current source.
>   Module / console-script / zipapp JSON is identical on `ground.news.har`
>   (the two-theme site) and on `fleshandbonedesign.com.har --images` (the
>   reference fixture: ground `#151515`, 20 tokens, one theme, no warnings —
>   all unmoved), each diffed with `generated` dropped.
> - **Fault 2 (crashes under an old interpreter)** — `palettekit.PYTHON_FLOOR =
>   (3, 11)` in `__init__.py` is the one place the floor lives; `main()`
>   checks it before `build_parser()` runs, so a version guard fires at
>   start-up rather than the failure surfacing four calls deep in
>   `_align_names`. Confirmed both directions: `uv run --python 3.10
>   --no-project python palettekit.pyz ground.news.har …` now prints `error:
>   palettekit requires Python 3.11+ (running 3.10.20).` and exits 1 — no
>   `TypeError`; `uv run --python 3.11 --no-project python palettekit.pyz
>   fleshandbonedesign.com.har …` (neither dependency installed) runs clean and
>   reproduces the fixture anchors.
> - **Fault 3 (falsified identity check)** — no longer falsified; see above.
>
> **"Read the floor from one place" turned out to mean two places, not one**,
> and the plan as written only named the first: `PYTHON_FLOOR` on its own can
> still drift from `pyproject.toml`'s `requires-python` if one is bumped and
> not the other. Closed with a test rather than a comment —
> `test_pyproject_floor_matches_python_floor` reads `requires-python` via
> `tomllib` (stdlib at this floor) and asserts it against `PYTHON_FLOOR`, so a
> mismatch fails the suite instead of waiting to be noticed. 96 → 97 tests.
>
> **The guard sits inside `main()`, not at module scope above the imports.**
> The plan didn't specify where; module scope would put an `if` block ahead of
> `import argparse` / `from . import emit, extract, …`, which is exactly what
> ruff's `E402` (import-not-at-top) exists to flag, and `ruff check .` is
> required to stay clean. It doesn't cost anything: the actual failure is
> `zip(strict=)` at runtime, not at import — `extract.py` and friends still
> import cleanly on 3.9 because of `from __future__ import annotations` — so a
> guard at the top of `main()`, before any real work starts, catches it with
> no `noqa` needed.
>
> **Diffed at the level this section named**: built artifact's JSON against
> `python3 -m palettekit`, module vs. console-script vs. zipapp, on every
> corpus input available locally. Not diffed at the byte level —
> `zipapp.create_archive` embeds mtimes, so two builds of identical source are
> never byte-identical, and that was never the claim; the claim is
> **output** identity, which held.

**Decided: rebuild it, and make it process rather than a thing to remember.**

The tracked `palettekit.pyz` is the **pre-phase-1 program** — no `dom.py`, no
`tinycss2`, `color.py` at 528 lines against today's 1004. It has three faults
and they were measured, not inferred:

1. It **runs**, using the old hand-rolled walker with all five parsing bugs the
   migration existed to remove. On `fleshandbonedesign.com.har` it reproduces
   every reference anchor exactly, so the fixture cannot detect it.
2. It **crashes on a real site** — `ground.news.har` exits 1 with `TypeError:
   zip() takes no keyword arguments`, because a zipapp carries no
   `requires-python` and it ran under a 3.9 interpreter.
3. It **falsifies `CLAUDE.md`'s three-way identity check** ("all three must
   produce identical JSON") against the committed artifact.

**Do:**

- Rebuild with the incantation in `CLAUDE.md`, **vendoring `tinycss2`,
  `cssselect2` and `webencodings`** into the staging dir. Test the result with
  an interpreter that has none of them installed — on a development machine
  every interpreter does, and the bug is invisible.
- Add a **`sys.version_info` guard** at `__main__` with a readable message.
  **Read the floor from one place** rather than hard-coding `(3, 10)` — T2
  raises it to 3.11, and a guard that silently keeps testing the old floor is
  the same failure mode as the stale artifact it is meant to prevent.
  Rebuilding does not fix fault 2. Worth knowing exactly why: all eight modules
  carry `from __future__ import annotations`, so the PEP-604 annotations are
  strings and the package **imports cleanly on 3.9** — the only 3.10-only
  runtime construct is `zip(strict=)`, four call sites in `extract.py`. So an
  unguarded zipapp does not fail at startup; it fails deep in `_align_names`,
  on two-theme sites only, looking exactly like a bug in the tool.
- **T12 is the real prerequisite.** "Rebuild after each session" is
  unenforceable as a human step — the artifact is four phases stale precisely
  because someone was meant to remember. Land the `Makefile`/`build.py` first,
  then the process instruction is one command and CI can assert it.
- Once it is automated, add the rebuild to `CLAUDE.md`'s Commands block and to
  the end-of-session routine, and have CI assert module / console-script /
  zipapp JSON identity so a stale artifact fails the build instead of shipping.

> **One tradeoff the decision did not have to weigh, stated once.** A rebuilt
> `.pyz` tracked in git is a ~144 KB binary churning on every session, and it
> is the reason `*.pyz` belongs in `.gitignore` in most projects. The
> alternative is to untrack it, build it in CI, and attach it to releases —
> which gets the freshness guarantee without the churn. The decision was to
> rebuild, so T1 is written to rebuild; if the churn becomes annoying, this is
> the escape hatch and it does not need re-litigating from scratch.

**Diff level:** the built artifact's JSON against `python3 -m palettekit`, on
every corpus input. Identity is the whole acceptance criterion.

### T2 — Raise the Python floor to 3.11

**Decided: 3.11.** 3.10 reaches end-of-life in **October 2026**, roughly three
months out, and the matrix should not keep certifying a dead version.

**Name the cost honestly, since the code does not force it.** Nothing in the
codebase needs 3.11 — the only 3.10-only construct is `zip(strict=)`. So this
narrows compatibility for no technical gain, and it is a **breaking change for
anyone installed on 3.10**. That is a reasonable trade against an EOL date and
a smaller test matrix; it is not a free one.

**Seven edits, four files** — enumerated so nobody re-derives them:

| file | edit |
|---|---|
| `pyproject.toml` | `requires-python = ">=3.11"` |
| `pyproject.toml` | drop the `Programming Language :: Python :: 3.10` classifier |
| `pyproject.toml` | the verified-floor comment at the top (lines 10–11) |
| `pyproject.toml` | `[tool.ruff] target-version = "py311"` |
| `CLAUDE.md` | the `**Python 3.10+, verified**` paragraph |
| `CLAUDE.md` | the `for v in 3.10 …` matrix loop, and the CI entry in T11 |
| `README.md` | "Python 3.10+ (tested on 3.10 through 3.14)" |

**Sub-decision left open: bump `__version__` from `1.0.0`.** Narrowing the
supported interpreter range is the kind of change a version number exists to
signal, and `palettekit/__init__.py` is the single source of truth
(`[tool.hatch.version]`). Pair it with T3's schema marker if both land
together.

**Diff level:** none — this changes no behaviour. Re-run the matrix over
3.11–3.14 and confirm byte-identical JSON to 3.14 on the reference fixture,
which is what the old floor's claim rested on.

> **Landed 2026-07-26.** All seven edits made as listed. Matrix re-run on
> 3.11/3.12/3.13/3.14: 95 tests pass on each, `ruff` clean under
> `target-version = "py311"` (no new `UP` findings — the codebase already used
> nothing older), and JSON is byte-identical between 3.11 and 3.14 on the
> reference fixture (`#151515`, 20 tokens, 1 theme, no warnings, `generated`
> dropped before comparing).
>
> **The version-bump sub-decision: `1.0.0` → `1.1.0`, not `2.0.0`.** The
> "breaking change for anyone installed on 3.10" cost named above is honest but
> currently theoretical — `pyproject.toml` still carries
> `# TODO(migration): decide a licence`, and CLAUDE.md is explicit that
> "nothing about publishing moves until a licence is chosen." The package has
> never been published, so nobody is installed from PyPI on any version to
> break. A major bump would signal a compatibility break to consumers who do
> not exist yet; a minor bump records the change honestly without overstating
> its current blast radius. Revisit this reasoning if the package is published
> before the next floor bump — an EOL-driven floor raise on a *published*
> package is a different cost calculus. `schemaVersion` (T3) stays at `1`
> regardless, since it is that document's first stamp and moves on its own
> schedule — see T3.
>
> **The licence question this reasoning rests on was itself resolved later
> the same day** — the owner chose the Hippocratic License 3.0; see
> "License" under Outstanding work. That does not retroactively change the
> minor-vs-major call above, which was correct for the state of the repo at
> the time T2 landed.

### T3 — Make `to_document`'s dict a versioned public API

**Decided: make it public.** There is no good reason to keep it private, and
checking that turned up something worth stating plainly:

**The "public" half is already done.** `emit.to_document` has no underscore, is
the worked example in `palettekit/__init__.py`'s module docstring, is called by
`__main__`, and is asserted by roughly a dozen tests. `CLAUDE.md` already calls
it "the public data contract". Nothing needs opening.

**The word doing the work in the original TODO was *versioned*, and that part
is real.** A consumer holding this dict has no way to detect a breaking change:
there is no marker in the document, and `generated` is a timestamp rather than
a schema stamp. Today's compatibility story is an informal promise in prose —
that `themes` is always present, and that top-level `ground`/`stats`/`colors`
mirror `themes[0]` so pre-themes readers keep working.

**Do:**

- Add a **`schemaVersion`** key to the document (an integer is enough) and
  emit it from `to_document`. It is the one thing that makes the rest
  checkable.

  **Say in the same breath that it is not the package version.**
  `palettekit/__init__.py` already carries `__version__ = "1.0.0"`, and a
  consumer seeing both will ask which one governs the dict. They move on
  separate schedules: the package version tracks the tool, the schema version
  tracks this one document shape. Worth stating now, because T2's
  version-bump sub-decision and this key would otherwise collide the first
  time either is touched.
- Write the compatibility promise down where a consumer will find it — the
  README's Output section, not only `CLAUDE.md` — including the mirroring rule
  above, which is already load-bearing for anyone who integrated before themes.
- State what a bump means: additive keys do not bump, removing or re-typing a
  key does.
- Assert the shape in a test, so a stray key rename fails loudly rather than
  silently breaking a downstream reader.

**Diff level:** the document's **key set**, per theme, against HEAD — not the
values. The only intended change is one added key.

> **Landed 2026-07-26.** `emit.SCHEMA_VERSION = 1` and a `schemaVersion` key on
> `to_document`'s output, top level only — not per theme, which is what "per
> theme" in the diff level above means to *check*, not a place to add the key.
> A new test asserts the exact key set on a palette with no `--images` report
> (`images` is conditional on `pal.image_report`, so an unconditional
> assertEqual needs that case) and was confirmed to fail before the key
> existed. Key-set diff against a fresh run of the pre-T3 commit on the
> reference fixture: exactly `{schemaVersion}` added, nothing removed, no
> value changed at any key including per-theme ones. Suite is 96 tests.
> Compatibility promise written in `README.md`'s Output section and echoed at
> `emit.to_document`'s docstring and in `CLAUDE.md`'s data-flow section.

---

## Accuracy gaps left by phases 1–4

All seven are documented under "Known limits" in `CLAUDE.md`, each with its
diagnosis and fix already worked out. They are transcribed here as tasks
because a "known limit" reads as a decision not to act, and these are not that
— they are work that was deliberately kept out of a phase whose blast radius
was being measured.

### T4 — Read `initial` as the guaranteed-invalid value and take the fallback — landed 2026-07-26

**Was the highest-value open item.** Tailwind v4 guards every registered property
with `@layer properties { *, ::before, ::after, ::backdrop {
--tw-gradient-via-stops: initial; … } }`, for browsers with no `@property`. On
a custom property `initial` **is** the guaranteed-invalid value, so a browser
resolving `var(--tw-gradient-via-stops, <the stops>)` uses the fallback.
`resolve_vars` substitutes the literal token `initial` instead and finds no
color in it.

Cost at the time this task was written: **108 declarations on
tailwindcss.com's dark theme**; `violet` drops from 137 occurrences to 29 and
`teal` from 130 to 22. That is ranking, and ranking is what names tokens — so
this moves names, not just counts.

Kept out of the invariant-25 change deliberately, so a real behaviour change
would not ride inside one whose blast radius was being measured. That reason
has expired.

**Landed.** Fixed at the one call site that reads a name out of the var
table (`resolve_vars`'s `one_pass`, `palettekit/cssparse.py`): a stored value
that is the literal keyword `initial` (trimmed, case-folded) is treated as
absent, so the call falls through to the declared fallback exactly as a
browser resolving a guaranteed-invalid custom property does. `initial` is
matched only as an exact stored value — a name whose value merely *contains*
the word (`initial-value`) is untouched, and no other CSS-wide keyword
(`unset`, `revert`) is touched, since those are not guaranteed-invalid on a
custom property and modelling them is inheritance — T9's job, not this one.

Verified against a **frozen** `tailwindcss.com` bundle (fetched once, same
pickle fed to old and new code, so the diff cannot be site drift): the
dark-theme token at `#ad46ff` (named plain `violet` — the dominant shade in
that hue) goes **29 → 137** occurrences, and `#00d5be` (plain `teal`) goes
**22 → 130** — an exact match, integer for integer, to the numbers recorded
above when this task was written. (A first pass at this verification summed
occurrences across *every* violet- and teal-hued hex in the corpus — Tailwind
ships ~30 shades per hue — rather than reading the one dominant token PLAN.md
tracks, producing a different-looking but wrong pair of numbers that briefly
got blamed on the live site having changed. It had not; the aggregation was
the bug. Corrected after being challenged on the "site drift" claim.) No
ground moved (`#f0b100` / `#030712` unchanged), and total token count was
unchanged in both themes (305, 317) — usages were restored on existing
entries, no new hues invented. `ground.news.har` and
`fleshandbonedesign.com.har` are byte-identical before and after (minus
`generated`): neither uses this guard pattern, confirming the blast radius is
confined to sites that do.

A new unit test, `test_initial_custom_property_falls_back`, requires it to
fail against HEAD before the fix (checked directly, per this file's own
testing discipline) and covers the keyword-vs-substring and
case/whitespace edges. 97 → 98 tests, `ruff` clean.

**Trap:** ui.shadcn.com's 16 `.shimmer` declarations look like the same bug and
are not — `--shimmer-image` is `initial` in the guard *and* `none` from two
utilities the shimmering element never carries. Fixing `initial` alone still
leaves `none` winning by last-wins. That half is T9, and the two should be
measured separately or neither result is interpretable.

**Diff level:** per-declaration color list, `(sheet_order, order, selector,
prop) → [hexa]`, per theme. Expect **additions** — this restores colors that
currently resolve to nothing — which is the opposite direction from phase 4 and
worth predicting before running.

### T5 — Evaluate `calc()` in a `color-mix()` percentage — landed 2026-07-26

Six declarations corpus-wide, all `.shimmer-color-*` on ui.shadcn.com writing
`color-mix(in oklch, <color> calc(60 * 1%), transparent)`. The mix used to be
skipped whole (invariant 22), which was correct at the time — defaulting to
50% would have printed a color the page does not paint.

**Landed.** `color.py` gained a small recursive-descent `calc()` evaluator
(`_calc_expr` / `_calc_term` / `_calc_factor`, entry point
`eval_calc_percentage`) restricted to `+ - * /` and parens over bare numbers
and percentages, typed the way CSS itself types them: like units add,
`<number> * <percentage>` gives a percentage, `<percentage> * <percentage>`
and division by a percentage do not. `_mix_component` calls it when a
component's percentage is a `calc(...)` call spanning the rest of the
component text; anything outside the subset — `var()` inside the `calc()`,
another unit, trailing junk after the call, an unbalanced expression — returns
`None` and the whole mix stays unreadable, exactly as it was before this task
for everything not in scope.

**Tokenizing went through one revision.** The first cut hand-rolled a regex
tokenizer (`_calc_tokenize`) over the `calc()` body's raw text — the exact
"parsing refuses to guess" module reaching for its own string scanner instead
of the `tinycss2` dependency already sitting one file away. Challenged on it:
`tinycss2.parse_component_value_list()` already tokenizes CSS numeric syntax
correctly (percentages, a dimension's unit split cleanly off, scientific
notation, a leading sign folded into the number) and groups nested parens
into a `ParenthesesBlock` and nested functions into a `FunctionBlock` — the
regex re-derived a worse version of exactly that, and silently failed to
tokenize `calc(1e2% / 2)` (valid CSS) because the regex had no scientific-
notation branch. Replaced `_calc_tokenize` with `_calc_tokens`, which calls
`tinycss2` directly and hands the recursive-descent evaluator real token
objects instead of raw strings; the evaluator itself — the arithmetic and
type-checking, which no CSS tokenizer performs — is unchanged. Re-verified
byte-identical against the same frozen `ui.shadcn.com` bundle (below), and
`calc(1e2% / 2)` now evaluates where it previously returned `None`. This
prompted a standing corollary to the accuracy-first priority note at the top
of this file: defer to a library already in the dependency set for anything
it does correctly, codebase-wide, not only in the parser — see `CLAUDE.md`.

Verified against a **frozen** `ui.shadcn.com` bundle (fetched once, same
pickle fed to old and new code via `git stash push palettekit/color.py`, so
the diff cannot be site drift), at the per-declaration color list — the level
this task specified before writing any code: **exactly six declarations
move**, three per theme, all `.shimmer-color-blue-500\/60 { --shimmer-color }`
— the whole predicted blast radius, integer for integer. Ground
(`#f5f5f5` / `#262626`, both inferred) and every warning are unchanged; the
only palette-level change is one new token, `#7caefb` (`blue-15`/`blue-16`
depending on theme, merged from `#3080ff` at the mix's own alpha), appearing
in both themes.

Two new tests: `test_a_literal_calc_percentage_in_a_mix_is_evaluated` (the
corpus shape and a few other operators, each checked against the same mix
written as a plain percentage rather than merely asserting *some* color came
back) and `test_calc_outside_the_supported_subset_yields_nothing` (mixed
units, percent×percent, division by a percentage, and two malformed shapes).
`test_a_mix_that_cannot_be_evaluated_yields_nothing`'s old `calc(2 * 30%)`
example was replaced with `calc(50% - var(--x))`, since the former is now
evaluable and would no longer illustrate the invariant it sits under. Both new
tests were run against the pre-fix code first and confirmed to fail/pass as
expected (the "evaluated" test errors with `NoneType has no attribute hexa`;
the "outside the subset" test already passes, since everything currently
returns `None`). 98 → 100 tests, `ruff` clean, 3.11–3.14 verified.

### T6 — An at-rule nested inside a style rule loses its declarations

`.a { color: red; @media (min-width:1px) { color: blue } }` yielded the `red`
and not the `blue`. `_walk` descended into an at-rule with no selector, and
declarations with no selector are read for `var()` references only. The brace
walker did the same thing for the same reason, so this predates `tinycss2`.

**Landed 2026-07-27.** The selector half of the fix was as small as predicted:
in `_walk`'s at-rule branch, when `selector` is already set (the at-rule is
nested inside a style rule rather than sitting at the top of the sheet), the
enclosing `selector` now carries straight through into the at-rule's contents
instead of being reset. A **top-level** at-rule — `@media { .b { color: green
} }` with no enclosing rule — still resets to `selector=""`, which is
unchanged and still correct: a qualified rule found inside it computes its own
selector regardless of what's passed down.

**The theme half was not as small, and the first draft got it wrong.** The
obvious move — carry `theme`/`theme_media` through unchanged alongside
`selector` — passed the first test and is a real regression, not a harmless
simplification: `.a { color: red; @media (prefers-color-scheme: dark) { color:
blue } }` has an *unscoped* enclosing rule, so carrying its `theme` through
verbatim records the nested `blue` as `theme == ""`. `_theme_plan`/
`_scopes_present` (`extract.py`) read `Declaration.theme` directly, and an
empty theme means "belongs to every theme" — so the fix's first draft would
have invented a color the light theme never paints, the mirror image of the
bug it was fixing (dropping a declaration versus contaminating one), and
exactly what invariant 13 exists to prevent from the other direction. Caught
by `advisor()` before landing, not by the corpus, which is silent on this: no
frozen bundle nests a themed media query inside a style rule. The corrected
version mirrors the qualified-rule branch's own `scoped or media` precedence a
few lines above it: a selector-derived theme on the enclosing rule wins
outright (`.dark .a { @media (prefers-color-scheme: light) {...} }` stays
`dark`), and only an *unscoped* enclosing rule lets the nested media query
supply a theme.

**This is the one that grows on its own.** Native CSS nesting makes the shape
more common every year, and the corpus was frozen in 2026 — a nested
`prefers-color-scheme` block is, if anything, the more likely real-world shape
than the plain `min-width` one this task opened with.

**Diffed at the declaration multiset**, `(sheet_order, selector, prop, value,
theme, at_rules)`, per this task's own prediction — this adds declarations
that do not currently exist, so it is the one level that shows it. Checked
against all four locally-frozen bundles (`fleshandbonedesign.com.har`,
`ground.news.har`, `tailwindcss.com.har`, `ui.shadcn.com.har`): **byte-identical
on every one**, both before and after the theme correction — none of them
happens to nest an at-rule directly inside a style rule today, confirming this
task's own framing that the bug is currently latent and growing, not something
the frozen corpus already hits. The reference fixture's anchors (ground
`#151515`, 20 tokens, one theme, no warnings) reproduce exactly, and the
rebuilt zipapp was verified on a bare Python 3.11 interpreter with neither
dependency installed.

Two new tests, both in `TestCss`, both required to fail before being trusted:
`test_an_at_rule_nested_in_a_style_rule_keeps_the_enclosing_selector` failed
against HEAD (`git stash push -- palettekit/cssparse.py`), dropping the nested
`blue` declaration exactly as described above.
`test_a_nested_media_theme_is_still_found_as_a_scope` failed against the
*first-draft* fix specifically — it passed the first test while still
recording the nested dark declaration as `theme == ""` — which is what makes
it the test that actually discriminates the theme half of this task rather
than regression coverage for the selector half. 106 → 108 tests, `ruff` clean,
3.11–3.14 byte-identical.

### T7 — Resolve `<html>` and `<body>` in separate pools (landed 2026-07-27)

`detect_ground` ranked candidates matching either element in **one pool**,
which the cascade never does: it resolves each element separately, and the
visible page color is the body's background where it has one.

Deliberately deferred in phase 3, and measured rather than assumed —
instrumenting every candidate with the element it reaches showed **no corpus
site has page-level backgrounds on both**, so grouping would sort the same
pools in the same order. Confirmed again before landing: all four frozen
bundles produce byte-identical JSON before and after this task.

**The trap this task named was real, and caught something the task's own
framing did not anticipate.** Two fixtures were built to fail against HEAD
first, per the plan:

- `test_html_and_body_grounds_resolve_in_separate_pools` — an unscoped `body`
  and an unscoped `html`, tied on every cascade term, differing only in that
  `html` is declared later. One shared pool falls through to document order
  and picks `html` (`#ffffff`); separate pools correctly pick `body`
  (`#eeefe9`), because painting order — not declaration order — decides which
  element's background is visible.
- `test_body_ground_wins_even_when_html_outranks_it_on_every_term` — `html`'s
  background is `!important` and id-specific, `body`'s is neither. Body still
  wins, because the two elements are never in cascade competition with each
  other in the first place; `<body>`'s box simply paints over the `<html>`
  canvas regardless of what won on either side.

**The first implementation — literally "prefer body whenever it has an
answer," the plan's own words with no qualification — passed both new tests
and broke a pre-existing one:** `TestUtilityGround.test_tailwind_v4_shape_on_the_html_element`.
That fixture's dark theme has an unscoped `body { background-color: #ffffff }`
*and* a dark-theme-scoped `.dark\:bg-gray-950:where(.dark,.dark *)` on
`<html>` — exactly the two-candidates-on-both-elements shape the corpus check
says doesn't occur, arrived at from a different direction: a synthetic fixture
built to test something else (Tailwind v4's comma-in-`:where()` shape,
invariant 17) that happened to also give body a candidate. Unconditional body
preference reported `#ffffff`, silently discarding the dark theme's real
ground (`#030712`, verified against the live site) in favor of a rule that
says nothing about the dark theme at all — invariant 16's own mistake, found
again in the other pool.

**The fix needed one more distinction than "which element," and it already
existed in the data**: whether the winning declaration was written for *this
theme specifically* — `Usage.theme_scoped`, added for this task,
`bool(Declaration.theme)` carried through — as opposed to being unscoped and
merely present in every theme's build by construction. `detect_ground` now
prefers body's pool winner **unless** html's winner is theme-scoped and
body's is not; within a pool the ordinary cascade key is unchanged. That
keeps the Tailwind test's `#030712` (html is genuinely theme-scoped there) and
both new tests' body-preference (neither candidate is theme-scoped in
either) simultaneously — verified by running all three together, not just
each in isolation.

**Diff level:** ground winner and candidate rank per theme. All four frozen
bundles byte-identical before and after — **no corpus change at all**, exactly
as predicted — but the plan's literal text above ("prefer the body's answer",
no caveat) was wrong on its own terms, caught only because a pre-existing test
was run against the new implementation before trusting it, not because the
corpus check ever would have. `CLAUDE.md` invariant 21 now carries the
corrected, qualified version — read that, not the unqualified sentence two
paragraphs up this file, if the two ever seem to disagree. 108 → 110 tests,
`ruff` clean, 3.11–3.14 byte-identical, reference fixture anchors reproduce
exactly, module/console-script/zipapp JSON identity verified, `.pyz` rebuilt
and confirmed on a bare Python 3.11 interpreter with neither dependency
installed.

### T8 — `@import url(…) layer(x)` should register a layer

`layer_order` does not see it, because `@import` is not followed at all. Named
rather than pretended in phase 3.

**Two pieces of work, and the second is the larger one:** parsing the
`layer(x)` form out of the prelude is easy; actually *following* an `@import`
means fetching another stylesheet, which is a `sources.py` concern and touches
the `Bundle` layer that all four phases deliberately left alone.

The layer position can be reserved without following the import — that is
strictly better than today and much cheaper. Consider doing only that.

**Per the T5/T15 corollary: "easy" means reading `node.prelude`'s `tinycss2`
tokens, not a regex over the serialized string.** `_walk` already receives
`node.prelude` as a token list before anything downstream serializes it (see
the `@layer a, b;` branch, which serializes only to get a flat comma-separated
identifier list — safe there because a layer name can't itself contain a comma
or paren). `@import`'s prelude is `<url> [ layer(<name>) | layer ]? …`, so the
`layer(...)` piece is a `FunctionBlock` sitting in that same token list —
`.lower_name == "layer"` finds it directly, the same way `_calc_tokens` (T5)
and `_split_component`/`_split_top` (T15) find `calc()`/percentages/commas by
token type rather than by pattern-matching text. Reach for
`re.search(r"layer\(...\)", prelude)` here and it's the same mistake T5's
first draft made, just relocated.

**Diff level:** the layer order list per document, then the cascade key at both
call sites.

### T9 — Model scoped custom properties

A property redefined on `.card` resolves globally here. `@property` and normal
inheritance down the tree are both unmodelled.

This is the largest open item and the one most likely to turn into a cascade
engine, which `CLAUDE.md` is explicit the tool is **not**. Scope it before
starting: the goal is a property resolving differently for the elements that
consume it, not computing anyone's styles.

It is also the second half of T4's trap — ui.shadcn.com's `--shimmer-image`
resolves to `none` from a utility the shimmering element does not carry.

**Diff level:** custom-property resolution table, old winner against new with
the cascade key's terms printed beside them — phase 3's level, which is the
only one that showed its twelve moves.

### T10 — Read `color-scheme` to confirm a `light-dark()` site is two-themed

Invariant 23 says a site writing `light-dark()` ships both themes "by
definition", and flags its own overreach: `light-dark()` resolves against the
**used** `color-scheme`, whose initial value is `normal` — light. A page that
writes `light-dark()` and never declares `color-scheme: light dark` renders the
light branch whatever the OS says, and calling it two-themed is wrong.

The tool cannot currently tell: `color-scheme` is neither a custom property nor
in `PROPERTY_ROLE`, so `_record` drops it and it never reaches a `Declaration`.

**No corpus site needs this.** Checked rather than assumed — MDN carries nine
`color-scheme` declarations including `color-scheme:light dark`, so its two
themes are real, and it is the only corpus site using the function. So this is
**waiting on a counter-example**, and is the one task here that should probably
not be done until one turns up.

**Diff level:** theme count and ids per site.

---

## Repo and process

Moved here from `CLAUDE.md`'s Migration TODO, which now points at this section.

### T11 — CI

Run the suite on **3.11–3.14** (per T2), `ruff check`, and assert that the
package, the zipapp and the installed console script produce identical JSON for
the same input — that last is the cheapest real regression check the project
has, and it is the one that would have caught T1's stale artifact.

**Compare JSON output, not archive bytes.** `python3 build.py` (T12) calls
`zipapp.create_archive`, which embeds each entry's mtime; two builds of
identical source are never byte-identical, and that's fine — it was never the
freshness guarantee. Whatever CI job implements this should run `python3
build.py` then diff `to_document()` output (with `generated` dropped) between
`python3 -m palettekit`, the installed `palettekit` script, and `python3
palettekit.pyz`, the same way T1 was verified locally in the absence of this
task.

### T12 — `Makefile` or `build.py` for the zipapp

> **Outcome — landed 2026-07-26** as `build.py` (root of the repo). Stages,
> vendors (`uv pip install --target`, falling back to `sys.executable -m pip`
> when `uv` isn't on `PATH` — a uv-managed venv's own interpreter has no `pip`
> module, so the fallback direction can't be assumed away), strips build
> metadata, and zips — one command, `python3 build.py`, replacing the six-step
> incantation this section describes.
>
> **Departure from "smoke-test the result":** verification is a structural
> assert that `palettekit`, `tinycss2`, `cssselect2` and `webencodings` are
> physically present in the archive (`zipfile.ZipFile(...).namelist()`),
> not a subprocess run of the built `.pyz`. Running it on the machine that
> built it proves nothing — site-packages is still on `sys.path`, and every
> dev interpreter has these installed anyway, which is exactly the blind spot
> the six-command version had. The interpreter-with-neither-dependency check
> CLAUDE.md calls for stays a separate, manual step (`uv run --python 3.11
> --no-project python palettekit.pyz …`) — it needs an environment `build.py`
> doesn't control, so it isn't something the script can assert on its own.
>
> **`[project.dependencies]` is read out of `pyproject.toml` via `tomllib`**
> rather than copied into `build.py` as a literal list — the same "one place"
> discipline `PYTHON_FLOOR` uses (T1), so the vendored set can't quietly
> diverge from what `pip install -e .` installs.
>
> **Diff level:** the archive's own contents (structural assert above), plus
> T1's JSON-identity check, which is what actually exercises a rebuild.

The staging-dir incantation in `CLAUDE.md` is six commands with a vendoring
step that is silently skippable on a development machine. **Prerequisite for
T1's process half** — automate it and "rebuild each session" becomes one
command that CI can verify.

### T13 — Move `test_palettekit.py` into `tests/` and split by module

1,272 lines and fourteen `TestCase` classes in one file. Mechanical, and worth
doing before the suite grows further.

### T14 — Fixture corpus of small HTML files per site archetype

Framework-heavy, page-builder, dark, light, CSS-variable-driven.

**More urgent than it looks, and it is the item that unblocks checking every
other one.** `.gitignore` carries both `*.har` and `palettes`, so **a fresh
clone can regenerate nothing**: not the reference fixture, not the breadth
check, not the `example/` directory `README.md` promises. All of it is
reachable only on the owner's machine. Small committed fixtures are the only
fix that does not mean committing an 11 MB HAR.

It also addresses a weakness found this session: the reference fixture is a
single-theme, hand-written-CSS site, and the **pre-`tinycss2` parser reproduces
all six of its anchors exactly**. It cannot detect a parser regression. The
breadth check can, and the breadth check needs network and frozen bundles —
committed fixtures are what make that offline and reviewable.

### T15 — Audit hand-rolled scanning against the T5 corollary — landed 2026-07-27

Raised while reviewing T5: the first cut of the `calc()` evaluator hand-rolled
a regex tokenizer even though `tinycss2` — already a dependency — tokenizes
CSS numeric syntax correctly and was one file away. Fixed in T5 itself, and it
raised the obvious next question: **what else in the codebase re-derives by
hand what a library already does?** The owner's answer was explicit and
general — accuracy and comprehensiveness beat slimness/portability everywhere
in the codebase, not only in the parser — recorded as a corollary to the
priority-order note at the top of `CLAUDE.md`.

**Landed:** `color.py`'s `_split_top` (splits a `color-mix()`/`light-dark()`
body on top-level commas) and `_split_component` (splits `<color>
<percentage>?`) both hand-counted parens/brackets/quotes/escapes character by
character. `tinycss2.parse_component_value_list` already groups all of that —
parens and brackets into `ParenthesesBlock`, function calls into
`FunctionBlock`, quoted strings with their own escape handling — into single
tokens, so a top-level comma is just a `LiteralToken` in the flat list, and
`tinycss2.serialize()` reconstructs each part losslessly. `_split_component`
gained one new concept it didn't need before: a `calc()` call is
percentage-typed the same way a literal `50%` is, so `_is_percentage_like`
checks for either a `PercentageToken` or a `FunctionBlock` named `calc`, at
either edge of the component (a percentage may be written first).

Verified against the frozen `ui.shadcn.com` bundle from T5: the full
`to_document` output (minus `generated`) is **byte-identical** to the T5
commit's baseline, and all 100 pre-existing tests — including
`test_a_minified_mix_has_no_space_before_the_percentage`, the test that exists
specifically because a whitespace `split()` cannot find the boundary in
`var(--ring)50%` — pass unchanged. One new test,
`test_a_component_percentage_may_be_written_first`, covers a spec-legal shape
(`<percentage> <color>`) that was never actually exercised before — nothing on
the corpus writes it, which is exactly why it went untested until this
refactor's leading-percentage branch made it worth checking directly. 100 →
101 tests, `ruff` clean, 3.11–3.14 verified.

**Reviewed and left alone:** `_whole_value_spans` (finds top-level
`color-mix()`/`light-dark()` call spans) and `balanced_end` (the shared
paren-counter it and `cssparse._var_call` both use). These already delegate
the hard part — quote/escape-aware bracket matching — to a single, general,
well-tested utility rather than re-deriving CSS tokenization from scratch, and
`_whole_value_spans` needs its answer as **character offsets into the
original value string**, which tokens don't carry directly; reconstructing
them from serialized token lengths would trade a working, simple scanner for
a new and less obvious source of drift, for no accuracy gain. Not everything
that scans a string by hand is the mistake T5 found — only the part that
re-derives something a library already gets right *and* fails on real input,
which this does not.

**The rest of the audit, finishing the "whole codebase" scope the task title
promises, turned up one more landed fix and a set of fast verdicts:**

**Landed:** `cssparse.py` defined `_VAR_NAME` twice at module scope —
`r"var\(\s*(--[\w-]+)"` (intended for `var_refs` collection) and, later in the
file, `r"\s*(--[\w-]+)\s*"` (intended only for `_var_call`'s already-positioned
`.match()`). The second silently shadowed the first, so `_walk`'s
`sheet.var_refs.update(_VAR_NAME.findall(value))` — the collection invariant
10 relies on to decide `live` vs `saved` — was actually running the unanchored
pattern, which reads any `--name`-shaped text anywhere in a value as a
reference, `var(` or not.

This is exactly the corollary's two-prong test, not a style complaint: it
re-derives what a `FunctionBlock` token already gives unambiguously, *and* it
fails on real input. Confirmed on the corpus rather than a synthetic case —
ground.news ships Tailwind arbitrary-value utilities that put a bare custom
property name directly in the value position:

```css
.bg-\[--color-bg\]{background-color:--color-bg}
.border-\[--color-border\]{border-color:--color-border}
```

Neither is a `var()` call — Tailwind's `[--name]` arbitrary-value syntax means
"use this exact text as the value," and a bare dashed-ident isn't a valid
`background-color`, so the declaration paints nothing. The shadowed pattern
still matched the literal text `--color-bg`/`--color-border` inside it and
counted both as referenced. A third name,
`--radix-dropdown-menu-content-transform-origin`, moved the same way via
`.origin-\[--radix-dropdown-menu-content-transform-origin\]`.

Fixed with `_var_ref_names`, a recursive token walk: only a `FunctionBlock`
whose `.lower_name` is `var` contributes a name, taken from the first
non-whitespace token in `.arguments`; every function/block's contents are
still recursed into regardless, so a `var()` nested inside another `var()`'s
own fallback — `var(--a, var(--b, red))` — still yields both names, matching
what the old regex's unrestricted `.findall` happened to catch by accident.
`extract.py` carried an exact duplicate of the correctly-anchored pattern for
the same job in `_triplet_warning`; both call sites now share one function,
`cssparse.var_refs`.

**Diffed at the aggregate `var_refs`-set level, phase 4's shape.** Per-sheet
`var_refs` sets are identical old-to-new on every stylesheet and inline-style
source in `ground.news.har` and `fleshandbonedesign.com.har` **except** the
one file above; `to_document` output (minus `generated`) is **byte-identical**
on `fleshandbonedesign.com.har` and on frozen `ui.shadcn.com` and
`tailwindcss.com` bundles (fetched live and pickled once, then run old code
against new against the same frozen `Bundle` — the T4 lesson about not
re-fetching between runs, applied here since no committed fixture exists for
either site per T14). ground.news is the only site that moves: the aggregate
`var_refs` set shrinks by 3 (228 → 225: `--color-bg`, `--color-border`,
`--radix-dropdown-menu-content-transform-origin`), but
`customPropertiesReferenced` only drops by one, 159 → 158 for the light theme
— that stat is `len([k for k in table if k in all_var_refs])`, an intersection
with the theme's *defined* custom-property table, and `--color-bg` and the
`--radix-…` name are referenced-but-never-defined on this site, so only
`--color-border` was ever a key in `table` to begin with. That one token's
score shifts (83.94 → 79.48, ~5%) because `_build`'s `w *= 1.2 if d.prop in
all_var_refs else 0.35` (`extract.py`) no longer boosts *the one declaration*
that defines `--color-border` — the boost is per-declaration, not applied to
the token as a whole, which is why a 3.4× swing on one input only moves the
merged score a few percent. The exact shape T15's corollary predicts either
way: a library doing the job more correctly moves occurrence-derived numbers,
not hex sets. No color, ground, or hex entered or left any palette. Two new
tests
(`test_var_refs_do_not_read_string_content`,
`test_var_refs_recurse_into_a_fallback`) cover the invariant-9-shaped case
(a string literal is not a reference) directly, since the corpus shape that
actually tripped it — a bare value, not a string — is ground.news-specific and
not worth hard-coding into a unit test. 101 → 103 tests, `ruff` clean.

**Fast verdicts, the rest of the file-by-file pass:**

- `cssparse.py`'s theme/selector regexes (`_THEME_MEDIA`, `_THEME_CLASS`,
  `_THEME_IS`, `_THEME_ATTR`, `_REDUNDANT_HTML`, `_NOT_OPEN`) and
  `extract.py`'s `_PAGE_SEL`/`selector_weight` regexes — invariant 17 already
  settled this and says not to re-derive the prediction a third time: every
  caller runs over raw preludes that may not compile, or over
  `strip_theme_scope` output that can itself be invalid (`:is( , …)`), so
  there is no guaranteed-valid `cssselect2`-compiled form to switch to.
- The anchored validators — `_HEX`, `_FUNC`, `_PERCENT`, `_CALC_CALL`,
  `_TRIPLET`, `_ZERO_LEN`, `_WS` — match a whole, already-delimited string
  (`^...$`) rather than scanning one for a match anywhere in it. They are
  validators, not scanners, and re-derive no tokenization.
- `is_inert_shadow`'s regexes (strip color literals out of a `drop-shadow()`
  body, check what's left is all zero-length) work the same way
  `_whole_value_spans` does: on an already-isolated single value, needing the
  leftover text rather than a token list. Same verdict, same reasoning.
- The HTML-scanning regexes — `extract.py`'s `_STYLE_OR_LINK`/
  `_document_order`, and `cssparse.py`'s `extract_style_blocks`,
  `extract_stylesheet_links`, and `parse_inline_styles`'s attribute regex —
  are a different domain than the rest of this task entirely. Neither
  `tinycss2` nor `cssselect2` parses HTML; the closest thing in the
  dependency set is `dom.py`'s own `html.parser` tree shim, and that shim is
  deliberately narrow, built to answer one question (does `<html>`/`<body>`
  match a selector) and documented as not modelling general structure.
  Extending it to general markup extraction — ident recognition, tag/attr
  scanning in document order — is a project roughly the size of the
  `dom.py`/`lxml` question below, not a mechanical swap, and is noted here
  rather than filed. (In passing: `cssparse.extract_style_blocks` has no
  remaining caller — `extract.py` grew its own `_document_order` and uses
  that instead. Dead code, not a corollary finding; left alone rather than
  pulled into this task's diff.)

**Two findings are flagged, not landed, and need the owner's sign-off before
anyone acts on them — each is roughly the size of the `dom.py`/`lxml`
question below, not a mechanical swap like T5's:**

**Owner-authorized 2026-07-26 as tracked work — filed as T16 and T17 below
rather than left as unfiled findings, neither started yet:**

1. **T16 — `resolve_vars`'s `_GLUE_LEFT`/`_GLUE_RIGHT` glue-padding**
   (invariant 24). See T16's own write-up below for the full case and the
   re-verification it needs before landing.
2. **T17 — `COLOR_TOKEN`**, the regex that finds every
   hex/`rgb()`/`hsl()`/`oklch()`/`oklab()`/`color()`/`lab()`/`lch()`/
   named-color literal in a declaration value. See T17's own write-up below.

**Not touched:** `dom.py`'s `html.parser` tree shim versus `lxml` — out of
scope for this task from the start; see the note below.

`dom.py`'s tree shim is a C-extension question, not a mechanical one.
`lxml` is a C extension; `build.py`'s vendoring
(`pip install --target`, structurally asserted per T1) assumes pure-Python
packages with no platform-specific wheels, and swapping it in would need that
model re-examined, not just a code change. Needs the owner's explicit
sign-off the same way the original `tinycss2`/`cssselect2` migration did.
**Kept as a note for now, per the owner (2026-07-26) — not filed as a task.**

### T16 — Rewrite `resolve_vars`'s `var()` substitution on tokens, not text — landed 2026-07-27

`resolve_vars` substitutes *text*: it finds a `var(` call in a plain string
(`_var_call`, delimited by `color.balanced_end`), decides its replacement, and
splices the replacement string back into the surrounding text. CSS substitutes
*tokens* — a browser never has to guess whether two adjacent values need a
separator — so this function carries its own guess: `_GLUE_LEFT`/
`_GLUE_RIGHT`, a hand-derived set of characters a substitution is or isn't
allowed to abut without a padding space. That heuristic exists because of
invariant 24: Tailwind v4 minifies to
`color-mix(in oklab,var(--color-white)var(--tw-shadow-alpha),transparent)`,
two component values with no separator, and pasting the substitutions together
without padding invented a bright yellow (`#fff100%` read as the hex
`#fff100`) that painted nowhere on the page.

**The proposed fix:** tokenize `value` with `tinycss2.parse_component_value_list`
once, walk the resulting list for `FunctionBlock` tokens named `var`, and
substitute each one with the *tokens* of its resolved value (itself obtained
by recursively resolving that value's own `var()` calls) rather than a spliced
string. Re-serializing the whole list with `tinycss2.serialize()` at the end
would let the library's own adjacency-aware serializer decide spacing — the
same mechanism that already inserts `/**/` to stop `:nth-child(3n+1)` from
re-merging into `:nth-child(3n)` — instead of the hand-derived
`_GLUE_LEFT`/`_GLUE_RIGHT` character-class check. This is the exact class of
thing the T5 corollary targets: a library already in the dependency set
solving a problem (token adjacency) that is currently solved by hand, worse.

**Why this is not a mechanical swap, and needs the same weight as `dom.py`:**

- **Hot path.** `resolve_vars` runs on every declaration in every stylesheet,
  up to four passes deep (`depth` in the current signature). A rewrite that
  tokenizes and re-serializes on each pass, rather than scanning a string once,
  needs at least a rough benchmark against the corpus — phase 3's cascade work
  already cost a measured 4–7%, and this sits on a hotter path than that did.
- **Three invariants are pinned to the current text-substitution shape.**
  Invariant 24 (glue-padding itself), invariant 25 (`balanced_end` delimiting a
  fallback that may contain parentheses of its own — a `FunctionBlock`'s
  `.arguments` already gives this structurally, but the *discard-fallback*
  behavior when the name resolves must be preserved exactly), and invariant 26
  (`initial` read as guaranteed-invalid, not a literal stored value — must
  keep comparing the *value*, not incidentally break on how it's tokenized).
  A rewrite has to reproduce specific, already-corpus-verified behavior for
  each, not just "still resolve `var()` correctly" in the abstract.
- **Re-verification must be the same shape phases 3 and 4 used**, not a unit
  test: freeze the corpus bundles used before (`tailwindcss.com`,
  `ui.shadcn.com`, `ground.news.har`, `fleshandbonedesign.com.har`), diff old
  code against new at the per-declaration resolved-value level (not the
  palette, which folds and merges and would hide a subtle glue regression the
  same way invariant 25's bug hid behind unchanged hex sets), and predict the
  blast radius before writing code — the corollary's whole point is a
  library doing something *more correctly*, so occurrence counts and possibly
  a token or two are expected to move, and "nothing moved at all" would be as
  suspicious here as it was reassuring for T4.

**Diff level:** resolved-value string, per declaration, per theme — the same
`(sheet_order, order, selector, prop) → value` shape phase 4 used, since this
is squarely var()-resolution territory and the palette folds too much to show
a spacing regression.

**Landed.** `_var_call`, `_VAR_NAME`, and `_GLUE_LEFT`/`_GLUE_RIGHT` are gone.
`resolve_vars` now tokenizes `value` once with
`tinycss2.parse_component_value_list`, walks it (`_substitute_vars`) for
`FunctionBlock` nodes named `var`, and replaces each one in place with the
*tokens* of its resolved value — read off the `var()` call's own already-parsed
`.arguments` (`_var_name_and_fallback`) rather than re-derived by counting
parens — before re-serializing the whole list with `tinycss2.serialize()` at
the end. `_var_ref_names` (T15) already walked a token tree this same shape
for a different purpose and was the template.

**A real hazard turned up in exactly the place the proposal above predicted —
token adjacency — but not the one predicted.** `tinycss2.serialize()`
disambiguates an unsafe adjacency by inserting `/**/`, which is what the
proposal wanted in place of `_GLUE_LEFT`/`_GLUE_RIGHT`. It is correct CSS and
`tinycss2` itself reads it back losslessly — but this codebase's own
downstream color scanners (`color._split_component`, `_split_top`,
`COLOR_TOKEN`) are regex-based and do not treat a `comment` token as
insignificant the way they treat whitespace. Left alone,
`color-mix(in oklab,var(--white)var(--alpha),transparent)` resolves to
`#fff/**/100%`, and `_split_component` reads the color half as `#fff/**/` —
which `parse_color` cannot parse — silently *losing* the color rather than
reading it correctly. Caught before it shipped by running
`test_var_substitution_does_not_glue_two_tokens_into_one` against a version of
the new code with the fix below removed, per the "a test that passes before
and after tests nothing" discipline: it failed, `[] != ['#ffffffff']`, proving
the test discriminates and the fix is load-bearing.

**The fix is `tinycss2.serialize(resolved).replace("/**/", " ")`, and it is
safe as a blind string replace, not merely convenient.** No declaration value
this project ever holds can contain a real CSS comment in the first place —
`tinycss2.parse_stylesheet`/`parse_blocks_contents` are both called with
`skip_comments=True` everywhere in `cssparse.py` — so the only `/**/` that can
ever appear in `value` or in any table-stored value is one this exact
replacement already turned into a space one recursion level down. Inductive
over recursion depth, not merely true for the corpus.

**The retry loop is gone, measured rather than assumed.** The text-based
version called `one_pass` up to four times because a text splice cannot tell
its own output from the text sitting next to it. The token-based version
fully resolves each `var()`'s replacement before splicing it in
(`_resolve_var`'s own recursive call), so nothing spliced ever needs finding
again. Before deleting the loop, the old implementation was instrumented to
count how often a *second* substitution round ever changed anything, run
against all four frozen corpus bundles (`tailwindcss.com`, `ui.shadcn.com`,
`ground.news.har`, `fleshandbonedesign.com.har`): **zero** declarations,
corpus-wide, ever needed a second round. Every retry was pure
convergence-checking overhead.

**One other structural difference from the old text scan, predicted before
running the diff rather than explained after:** a `var(` sitting inside a
`url(...)` or a quoted string is a single leaf token here (`URLToken`/
`StringToken`), so it is correctly invisible to the walk — a browser would
never treat it as a custom-property reference either, and the old substring
scan could not tell the two cases apart. Grepped for first: zero declarations
in the four frozen bundles mix `var(` and `url(` in the same value, so the
prediction was "no movement from this," and the corpus diff confirmed it.

**Corpus diff, at the level this section specifies:** 19,802 `(theme, sheet,
order, selector, prop)` keys total across the four bundles; the candidate set
itself is unchanged (same keys, old and new, on every site). 371 of them
differ as strings, **all four sites' full palette JSON (minus `generated`) is
byte-identical old vs new**, and `find_colors()` run over every differing pair
returns identical results on every one — the 371 are whitespace-only, in the
direction `_GLUE_LEFT`/`_GLUE_RIGHT`'s conservative padding predicts: the old
code padded a real separator character with its *own* extra space (`3px
#dadbd6` → `3px  #dadbd6`, double space) and padded some boundaries
(`dimension` before `hash`, `*` on either side in `calc()`) that CSS does not
require a separator for at all. `fleshandbonedesign.com.har` — the reference
fixture's source — has zero differences; ground `#151515`, 20 tokens, one
theme, no warnings, reproduced exactly with `--images`.

**Benchmark, as this section's own "hot path" note required.** In-process,
best-of-5 over all four bundles: old 2.709s, new 3.098s — **+14.4%**, worse
than phase 3's measured 4–7% as predicted, because this sits on a hotter path.
Profiling found the first version cost +18.9%: `_resolve_var`'s stored-value
branch was tokenizing `stored`, substituting, re-serializing to a string via a
call to `resolve_vars` itself, and then **re-tokenizing that string a second
time** to get splice-ready tokens back — a wasted round trip discovered by
`cProfile`, not anticipated in the original design. Fixed by tokenizing
`stored` once and walking it directly (`_resolve_var`, the `"var(" not in
stored` fast path added alongside it), which recovered about a third of the
regression. A further lever exists — the same profiling run found 77,776
tokenize calls covering only 2,238 distinct strings, so a cache scoped to one
`table`'s lifetime would remove most of the remaining duplication — but
sharing parsed token *nodes* across call sites is only safe because nothing
mutates a node after it has been spliced in once; scoping that cache correctly
(a table can outlive any single `resolve_vars` call, and `id(table)` reuse
after garbage collection is a real hazard in a long-running process such as
the test suite) is a second, separable piece of work, not exercised or landed
here. Left as a known lever rather than taken, matching the priority order at
the top of `CLAUDE.md`: accuracy first, and a disclosed, corpus-verified 14%
on a path that was never the dominant cost in a single-site run is the
honest trade against retiring a hand-rolled heuristic and closing two real
gaps (the `/**/` hazard above, and `url()`/string leakage) rather than a
regression to silently engineer away with cross-call caching risk.

**The malformed-`var()` and circular-chain edge cases were checked directly,
not just left to corpus silence** (neither shape occurs in the four frozen
bundles): `resolve_vars('var(10px, var(--a))', {'--a': '#123'})` still
resolves the nested `var(--a)` while leaving the malformed outer call
untouched (`'var(10px, #123)'`), and a three-property circular chain
(`--a`→`--b`→`--c`→`--a`) terminates and returns the same partial text old
code did (`'var(--a)'`/`'var(--c)'` depending on entry point) rather than
hanging. Both match the old implementation byte-for-byte, confirmed by
running the same three calls against the stashed pre-T16 `cssparse.py`.

**One dead regex found in passing:** `_VAR_NAME = re.compile(r"\s*(--[\w-]+)\s*")`
was `_var_call`'s own anchor pattern — the second, shadowing `_VAR_NAME` T15
had already tracked down and fixed the aliasing bug for, still left defined at
module scope. With `_var_call` gone, nothing referenced it; removed rather than
left orphaned.

**Verification:** 103 tests pass (unchanged count — T16 touched no test file),
`ruff` clean, 3.11–3.14 matrix green, module/console-script/zipapp JSON
parity confirmed, `palettekit.pyz` rebuilt via `build.py` and verified on
`uv run --python 3.11 --no-project` with neither dependency installed.

### T17 — Rewrite `COLOR_TOKEN` on `tinycss2` tokens — landed 2026-07-27

`COLOR_TOKEN` is the regex that finds every hex, `rgb()`/`rgba()`/`hsl()`/
`hsla()`/`oklch()`/`oklab()`/`color()`/`lab()`/`lch()`, and named-color literal
in a declaration value — the base token scan every property's value goes
through in `find_colors`, once `color-mix()`/`light-dark()` spans are already
carved out (invariant 22, T5). It is the single largest piece of hand-rolled
domain logic left in `color.py`.

**The known gap:** the function-call branch,
`(?:rgba?|hsla?|oklch|oklab|color|lab|lch)\s*\([^()]*(?:\([^()]*\)[^()]*)*\)`,
tolerates exactly one level of nested parentheses. `rgb(calc(1 + 2) 0 0)`
matches; `rgb(min(calc(1 + 2), 3) 0 0)` — a second level of nesting — does
not, and the regex fails closed (finds nothing) rather than reading a wrong
color, which is the safe direction for this codebase to fail in but is still
a real gap. A `FunctionBlock`'s `.lower_name` identifies these functions
directly regardless of how deeply their arguments nest, since `tinycss2`
already resolved that nesting when it tokenized.

**The proposed fix:** tokenize the value once (this can likely share a single
tokenization pass with `_whole_value_spans`, which currently re-scans the same
string separately to find `color-mix()`/`light-dark()` spans — worth
resolving as part of this task rather than tokenizing the same value twice),
walk the flat token list for `HashToken` (hex), `IdentToken` matching `NAMED`,
and `FunctionBlock` tokens whose `.lower_name` is one of the known color
functions, and hand each one's own tokens to the existing per-space parsers
rather than a captured regex group.

**Why this is not a mechanical swap:** this single function is exercised by
essentially every invariant in the file that depends on "a color was found in
this declaration" — 9 (strings/comments must not be misread as color, which a
token-based scan gets for free since `StringToken`/`CommentToken` are already
distinct types, rather than the regex's implicit reliance on not matching
inside them), 22–23 (`color-mix()`/`light-dark()` span exclusion, which this
scan runs alongside), and 24–26 indirectly (anything `resolve_vars` produces
flows through this scanner next). A rewrite is a real behavior change to the
most heavily-relied-on function in the file, not a refactor with an identical
observable result — closing the nesting gap **will** find colors the current
regex reports nothing for, on any corpus site that has one, so "no diff at
all" is not the success criterion the way it was for T5 and T15's landed half.

**Diff level:** per-declaration color list (phase 4's level) across the full
frozen corpus, predicting the blast radius before writing code — specifically,
search the corpus first for any second-level-nesting shape this would newly
catch, so the prediction is falsifiable rather than "probably nothing changes."

**Landed.** `COLOR_TOKEN`, `_whole_value_spans`, and `_WHOLE_VALUE_FUNCS` are
gone. `find_colors` now tokenizes `value` once with
`tinycss2.parse_component_value_list(value, skip_comments=True)` and walks it
recursively (`_collect_colors`): a `HashToken` or an `IdentToken` matching
`NAMED` is read directly; a `FunctionBlock` whose `.lower_name` is
`color-mix`/`light-dark` is evaluated as a unit exactly as before and not
recursed into; a `FunctionBlock` naming one of the known color functions is
handed whole to `parse_color` via `tinycss2.serialize`; anything else — a
gradient, a shadow, an unrecognised function, a bare `( … )` grouping — is
recursed into, because a color can appear anywhere inside those. This also
folds `_whole_value_spans`'s separate re-scan into the same walk, which the
proposed fix flagged as worth doing rather than tokenizing the value twice.

**The predicted finding did not occur, and a different, real one did — caught
by the corpus diff rather than by the prediction.** The write-up above
predicted "closing the nesting gap **will** find colors the current regex
reports nothing for, on any corpus site that has one." It does not, on this
corpus: `_num`/`_hue` (the channel-value parsers `rgb()`/`hsl()`/`oklch()`/etc.
call into) only understand a literal number or percentage, never `calc()` or
`min()`/`max()`, so a color function nested two levels deep still resolves to
no color once correctly delimited — the boundary was never the only thing
standing between the old code and a real answer. Confirmed directly:
`find_colors("rgb(min(calc(1 + 2), 3) 0 0)")` is `[]` both before and after,
and a color declared *after* an unreadably-nested one is unaffected either way
(`test_a_color_function_nested_two_levels_deep_finds_nothing`). No corpus site
exercises a shape that would flip this — the four frozen bundles produced zero
diffs of this kind.

**What the corpus diff found instead: 58 declarations, all removals, all one
of two shapes neither the original write-up named.** Diffed at the
per-declaration resolved-value level (`resolve_vars` output, per theme, old
`find_colors` against new) across all four frozen bundles. Both shapes are
`background-image: url(...)`, and both land on `tailwindcss.com.har` and
`ground.news.har` — the DocSearch CSS below is bundled directly into
`tailwindcss.com`'s own Next.js build
(`https://tailwindcss.com/_next/static/chunks/0de0_fu7khccy.css`,
first-party, not a third-party sheet):

1. **A quoted `url()` read its own SVG markup as color** — 52 of the 58 (40 on
   `tailwindcss.com.har`'s DocSearch-icon CSS, 2 on
   `fleshandbonedesign.com.har`'s checkbox glyph). All are
   `background-image: url("data:image/svg+xml,...")` where the embedded SVG
   carries `stroke='black'`/`fill='white'` attributes. The old flat-text regex
   scanned straight through the quote marks; the new walk never opens a
   `url()`'s argument beyond checking it isn't one of the recursed-into cases,
   and the argument itself is a lone `StringToken`, which no branch of
   `_collect_colors` visits. This is invariant 9's own mistake
   (`content: "#fff"` is not a color) one `url()` layer deeper than that
   invariant's test reaches — `content` happens to be filtered out by
   `PROPERTY_ROLE` before it ever reaches `find_colors`, so that test never
   exercised a case where the string survives to the scanner; `background-image`
   is legitimately color-bearing (gradients), so its quoted `url()` argument
   does reach `find_colors`, and did not get the same protection until now.
2. **A bare `url()` read a filename as a named color** — 6 of the 58, all
   `ground.news.har`'s `url(https://…/bg-black.png)`, each paired in the same
   `background-image` value with an unrelated second `url(...)`
   (`about_page_newspaper_watermark.png` or `background-img.png`) that
   contributes nothing either way. `\bblack\b` matched the word inside the
   filename the same way it matches a real `black` keyword elsewhere in a
   value; every one of the six old results is a single `#000000`, confirmed by
   re-reading the six records directly rather than the mechanism first
   guessed at (no `color: black` shares any of these six declarations — that
   guess was wrong and is not repeated here). A bare `url(...)` is tokenized
   as its own `URLToken` type, distinct from the `FunctionBlock` a quoted
   `url("...")` produces, and neither is ever opened by the walk.

Every one of the 58 diffs is a pure removal — `new` is `[]` in all of them,
confirmed by grep rather than eyeballed — and no diff appears on any
declaration shape other than these two. Regression tests:
`test_a_quoted_url_does_not_read_its_own_markup_as_color`,
`test_a_bare_url_does_not_read_its_filename_as_a_named_color`. Both were
checked against the pre-T17 implementation and fail there, per the "a test
that passes before and after tests nothing" discipline; the nesting-gap safety
test does not discriminate against the old code and says so in its own
docstring, kept as forward regression coverage rather than proof of a
behavior change.

**The removals are not confined to occurrence counts — invariant 25's own
precedent, checked directly rather than assumed away.** A per-declaration diff
undercounts what a change like this actually does, because `Entry.score`
feeds `_assign_names`'s natural-sort ranking (invariant 25's own write-up
makes exactly this point about a different removal). So the real check is the
full palette JSON, old build against new, `generated` dropped — same recipe as
phase 2/3/4's own verification:

```bash
git stash push palettekit/ && for h in ground.news tailwindcss.com \
  ui.shadcn.com fleshandbonedesign.com; do
    python3 -m palettekit "$h.har" -o "out-old/$h"
  done && git stash pop
# then the same into out-new/, and diff hex sets, grounds, warnings, names,
# occurrences, and scores per theme
```

`ui.shadcn.com` is untouched entirely on every field this script compares
(`ground`, `groundSource`, hex set, names, occurrences, scores, statuses,
warnings) — 0 of the 58 removals came from it. That is not the same claim as
"full JSON byte-identical": `stats`, `usedIn`, `examples`, and `source` were
not diffed field-by-field, though a direct dict-equality check on this one
bundle's two JSON files (`generated` dropped) does come back `True`, so the
stronger claim happens to hold here too — just not because the summary script
above proves it in general. `ground.news.har` and `fleshandbonedesign.com.har`
move `occurrences`/`score` on two or three entries per theme each, by exactly
the amount the removed declarations contributed, and **no token is renamed**
on either — their score gaps between neighbours are wide enough that a few
fewer occurrences doesn't cross a rank boundary. Grounds, warnings, and hex
sets are unchanged on all four bundles.

**`tailwindcss.com.har` is the exception, and it is a consolidation, not just
a rename.** The base theme's entry count drops from 305 to 303 — two fewer
entries, not merely reshuffled names — and tracing it down to one hex shows
why. `#785800` is not a literal color anywhere in the stylesheet: it is
Tailwind's `black/50` utility, `rgb(0 0 0 / 0.502)`, flattened over this
theme's yellow ground (`#f0b100`). In the old build it landed as **three**
separate entries, kept apart by invariant 7's `(hexa, role)` bucketing —
`yellow-14` (role `surface`, 7 occurrences: `--tw-ring-color`,
`--tw-text-shadow-color`, `.bg-black/50`, and two hits on
`.DocSearch-MagnifierLabel`'s `background-image`), `yellow-16` (role `text`,
8 occurrences: `.text-black/50` and kin), `yellow-23` (role `line`, 4
occurrences: `.border-black/50`, `.divide-black/50`) — 19 occurrences total.
The new build folds all three into one: `yellow-7`, role `text`, 17
occurrences.

Two of those 19 were themselves spurious, and directly traceable: the
`.DocSearch-MagnifierLabel` declaration is `background-image:
url("data:image/svg+xml,...")`, and its embedded SVG spells out
`stroke='rgba(0, 0, 0, 0.5)'` twice (once on a `<path>`, once on a `<circle>`)
— confirmed against the per-declaration diff, `old = ['#00000080',
'#00000080'] -> new = []` at `theme=base sheet=0 order=4455`. Flattened over
the same yellow ground, `rgba(0, 0, 0, 0.5)` renders to the identical
`#785800` as the real `black/50` utility — a coincidental collision between a
fake reading and a real one, not a new color the removal invents. That alone
drops the old `surface` entry from 7 to 5 and the cluster total from 19 to 17,
matching the new count exactly.

The 3-to-1 entry consolidation is a second, larger effect riding on top of
that count change, and it is invariant 6 doing exactly what it is specified to
do. `_merge_near_duplicates` walks entries in descending global score order,
and its `compatible()` check treats a `token`-role entry — a custom property,
which "has no role of its own" per its own comment — as mergeable into
*anything*, while `surface`/`text`/`line` are never mergeable into each other
directly. Old's `--tw-ring-color`/`--tw-text-shadow-color` usages (role
`token`) merged into the `surface` entry specifically — visible in its
`customProperties` field — leaving `text` and `line` as separate,
already-`kept` anchors by the time each was reached. The only anchor role
that admits all three of `surface`/`text`/`line` into one entry is `token`
itself: `k.role` is fixed once before the merge loop runs and not recomputed
until after it ends, `surface` and `text` are never compatible with each
other directly, and `compatible()` makes `token` the one role compatible with
everything — so an entry ending up with usages from all three roles is only
possible if a `token`-role entry was the kept anchor each of them was compared
against. That the new build's ordering puts the `token` bucket in that
position is a direct consequence of removing 58 spurious declarations
elsewhere and shifting the global score ranking of dozens of nearby entries
(the occurrence drops on `grey-1`/`grey-58` etc. above are part of the same
shift) — plausible and consistent with everything measured, though the loop
itself was not instrumented to watch the swap happen. This is existing,
correct invariant-6/-7 behavior responding to a correct input change, not a
new mechanism T17 introduces — the same shape invariant 25's own write-up
describes for a different removal, and the reason that write-up is the right
precedent to check against here.

Net effect: hex set unchanged, the same rendered color that used to be three
entries is now one, `yellow-7` through roughly `yellow-50` each pointing
at a different hex than before (`yellow-7` was `#fdc700`, is now `#785800`;
`yellow-10` was `#fff085`, is now `#ffd230`; and so on down the cluster) as
everything below the consolidation point shifts up two ranks. Not a bug — the
new occurrence counts and the merged entry are both correct, per the findings
above — but a real consumer-visible effect worth recording rather than
glossing over: anyone pinning a specific `--c-yellow-7` value across a rebuild
of this exact site sees it change. `grey`/`surface` groups on this same
bundle, and every group on the other three bundles, keep their names — this
is specific to `tailwindcss.com`'s unusually large single-hue cluster
colliding with a `token`-role merge target, not a general renaming risk from
this change.

**A rough timing check, since this replaces one compiled-regex `finditer`
with a full tokenize-and-walk on every declaration, including the majority
that hold no color at all** (T16 sat on a hotter path — up to four
`resolve_vars` passes per declaration — and got a measured number; this one
deserved a check rather than an assumed "same shape"). Over
`tailwindcss.com.har`'s 5,191 declarations, old vs new `find_colors`, 20
warmed-up passes: new measured **~52–59ms/pass** across separate runs, old
**~82ms/pass** — new is faster, not slower, and the spread doesn't change that
conclusion. Plausible cause, not confirmed further: the old scanner ran two
separate regex passes per declaration (`_whole_value_spans`'s span search,
then `COLOR_TOKEN`'s own finditer, the latter carrying a ~140-way named-color
alternation tried at every position), where the new code tokenizes once and
dispatches on `dict`/`frozenset` membership.

**Full corpus re-verification, same shape as T5's and T16's:** 106/106 tests
pass (103 plus the three new ones), `ruff check .` clean, the reference
fixture's every anchor unmoved (`fleshandbonedesign.com.har --images`: ground
`#151515`, 20 tokens, one theme, no warnings, `#ffc600` saved, `#13330d`
inert, `#c4c4c4` at 10.47:1), the Python 3.11/3.12/3.13/3.14 matrix all green,
and module/console-script/zipapp JSON identical across all four bundles with
the interpreter held constant. One unrelated wrinkle surfaced while checking
that last one: `ground.news.har`'s `score` field differs in its last decimal
place between a 3.11 and a 3.14 interpreter (`51.7` vs `51.71`, and similarly
on three other entries) — confirmed present identically in the pre-T17 code
built the same way, so it is a pre-existing floating-point rounding difference
between interpreter versions unconnected to this task, not a T17 regression;
`color.py` has no part in computing `score` at all. `palettekit.pyz` rebuilt
(after also deleting `_WHOLE_VALUE_FUNCS`, a leftover unused frozenset caught
on review — the dispatch in `_collect_colors` compares `.lower_name` to the
two literal strings directly and never read it) and verified on a bare 3.11
interpreter with neither dependency installed.

### License

**`LICENSE.md` + the `[project.license]` and classifier entries — landed
2026-07-26.** The owner chose the Hippocratic License 3.0.
`pyproject.toml`'s `[project]` table sets `license = "Hippocratic License
3.0"` and `license-file = "LICEN[CS]E.*"`, the `TODO(migration)` comments are
gone, and the sdist's `include` list ships `/LICENSE.md`. Nothing else was
waiting on this, and nothing else changed as a result of it.
