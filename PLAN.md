# Migration plan: hand-rolled CSS reading → `tinycss2` + `cssselect2`

Status: **all four phases landed 2026-07-26.** Written 2026-07-26.

**The migration is done; the work it left behind is not.** See
[Outstanding work](#outstanding-work) below — ~~fourteen tasks, three of them
decisions the owner has since settled~~ **nineteen as of 2026-08-02** (T15–T19
were added after this line was written; not updated each time a task was
filed, since the count itself isn't load-bearing anywhere — the section
below is), six of them decisions the owner has settled outright (T1, T2, T3,
T9's direction, T11's won't-do, T14's closed-as-satisfied) — and it is the
authority for what is left.
`CLAUDE.md`'s Migration TODO points there rather than duplicating it.

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

## Potential future expansion

**Not planned. Restricted by the "No JavaScript is executed" premise this
tool is built on** (`CLAUDE.md`'s Known Limits, first entry) **— recorded
here only because T18/T19's own investigation (2026-08-02) gives it sharper
edges than "Explicitly out of scope" above had when that section was
written**, at the owner's request to keep it visible rather than only
implicitly ruled out.

That section already rejected replacing the CSS-parsing pipeline with a
headless browser's `getComputedStyle`, for two reasons that still hold: it
can't run against a HAR (this tool's best input, and the only one that works
on sites blocking automated requests), and `getComputedStyle` throws away
provenance — which selector declared a value — that the JSON contract and
most of the HTML report depend on.

**What's different here is narrower and later-stage: not replacing the
pipeline, only widening what document `dom.selector_reach`/
`elements_matching_wrapped` test against.** Render the page far enough (with
JS) to capture its post-hydration markup, then feed that markup into the
exact real-tree matching machinery T9 already built (`full_tree`/
`wrap_tree`/`elements_matching_wrapped`), unmodified. Provenance stays
intact — declarations are still read from stylesheets exactly as today, only
the DOM snapshot `selector_reach`/T9's ancestry walk test against would
change. A HAR could stay the primary input, with a rendered-DOM pass as an
optional supplement rather than a replacement — closer to `--images`'
opt-in shape (invariant/Convention: "a dependency in the core is now allowed
where it buys accuracy… but it should still earn its place against the
corpus") than to a rewrite.

**Concrete corpus motivation, not hypothetical.** ui.shadcn.com's
`.shimmer`/`.shimmer-none` shapes (CLAUDE.md's Known Limits, T9's own
write-up) resolve to "no basis" specifically because `.shimmer` lives on
`/docs/utils/shimmer`, a page this HAR never fetched — and even within a
fetched page, client-hydrated frameworks routinely inject markup a raw HAR
capture won't contain at all. T18's own corpus investigation independently
landed on the same declarations from a different angle (T18 asks "does
`.shimmer`'s selector match anything real"; T9 asks "is there a real
consumer to resolve a value for" — both unanswerable for the same reason).
This isn't a one-off: any client-rendered app has the same shape.

**Cost this would add, honestly, and it is not small.** A real browser
engine dependency (Playwright or similar) breaks the pure-Python floor
`build.py`'s vendoring model assumes — invariant 16 already rules out
`lxml` for exactly this reason (a C extension the zipapp's vendoring model
can't carry), and a browser binary is a much larger version of the same
problem, not a smaller one. `PYTHON_FLOOR`, `build.py`'s "vendor into a
`.pyz`" model, and the "runs anywhere with no compiled artifacts" promise
would all need to be renegotiated, not just extended. That is the trade this
section names without taking — filed here so the option is visible and
its cost is written down next to it, not so it gets picked up.

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
- [x] **T8** — `@import url(…) layer(x)` should register a layer.
      **Landed 2026-07-27** — reserves the position only, per the plan's own
      "consider doing only that." See T8's own write-up below
- [x] **T9** — model scoped custom properties (`@property`, inheritance) —
      investigated 2026-07-27, blocked on an owner decision. **Decided
      2026-08-02: build the real-DOM direction with `html5lib`. Landed
      2026-08-02.** `resolve_by_ancestry_kind` is wired into `_build` as an
      override on last-wins (real value or confirmed absence override;
      disagreement or no real consumer in the captured markup preserve).
      132 tests, `ruff` clean, 3.11–3.14 green, corpus-verified (full
      per-entry diff, not just hex sets — see this task's own entry below
      for why that distinction mattered here). See T9's own entry below for
      the full history; T18 and T19 (below) have since landed on top of
      this tree
- [x] **T10** — read `color-scheme` to confirm a `light-dark()` site is really
      two-themed — **the counter-example turned up (`pawelgrzybek.com`'s
      light/dark example), landed 2026-08-02.** `_page_color_scheme` reuses
      `build_var_table`'s own page-reach-then-cascade machinery for one
      ordinary property; `_scopes_present` now gates its `light-dark()` →
      `{"light","dark"}` registration on `color-scheme` confirming both
      keywords, and `extract._build` reads an unscoped build's branch from
      `default_appearance` (light, unless the page confirms `dark` alone)
      instead of a hardcoded `"light"`. 158 tests, `ruff` clean, 3.11–3.14
      green. See T10's own entry below
- [x] **T18** — flag declarations whose selector matches nothing in the real
      document — **filed 2026-08-02, landed 2026-08-02.** New status
      `unmatched`, gated on unanimity: every usage's selector must be a
      *confirmed* non-match (`dom.selector_reach` returns `False`, not
      `None`) or the entry stays `live`. 145 tests, `ruff` clean, 3.11–3.14
      green, corpus-verified against all five frozen bundles including a
      wrong first theory caught and corrected mid-investigation. See T18's
      own entry below and invariant 27 (`CLAUDE.md`) for the full history
- [x] **T19** — report actual matched elements in `examples`, not just
      selector text — **filed 2026-08-02, landed 2026-08-02.** `examples`
      entries gain `matchCount` (real elements reached, `None` mirroring
      `Usage.matched`'s own "no basis to test" case) and a bounded `matches`
      sample (`dom.element_signature`, tag/id/class plus a short ancestor
      chain, hard-capped in length — a bare `.card` needs the chain since two
      matches of the same selector are otherwise identical). Reuses T9/T18's
      hoisted `wrapped_root`/`consumers_of` rather than a new cache, and skips
      the second query entirely for the confirmed-non-match majority (T18's
      own corpus puts that at 70–75% of selectors). Measured, not assumed:
      46.0s → 46.7s on `tailwindcss.com.har` (noise-level), JSON/report growth
      capped to +15–19% after tuning down from an uncapped first cut that ran
      to +38–46%. Additive-only: JSON key-set diff across all five frozen
      bundles found no other key, hex set, status, or ground moved. Also
      surfaced in the HTML report's "Where each color came from" table
      (`emit.py`), the exact gap this task's own write-up named. 153 tests,
      `ruff` clean, 3.11–3.14 green, module/zipapp JSON identity reverified.
      See T19's own entry below for the full design and both measurements
- [x] **T20** — categorize the HTML report's palette by status, with
      per-status descriptions — **filed 2026-08-02, landed 2026-08-03.**
      Sub-grouped each hue/role section by status rather than adding an
      orthogonal filter axis, per the sketch's first option. See T20's own
      entry below for the outcome
- [x] **T21** — test a pseudo-element selector's base compound against the
      real element, instead of treating every pseudo-element as no-basis —
      **filed 2026-08-02, landed 2026-08-02.** Fixed T18/T19's reach
      question as predicted, and along the way found and fixed a second,
      unpredicted bug the first draft *introduced*: sharing the new filter
      with T9's consumer lookup produced a false confirmed `"absent"` on
      `tailwindcss.com.har`, dropping a real color rather than merely
      missing an edge case. Landed with the reach and consumer questions on
      two separate filters. See T21's own entry below for the full
      write-up and the regression test that guards the split
- [x] **T22** — read `@property` registrations (`syntax`/`inherits`/
      `initial-value`) — **filed 2026-08-02, landed 2026-08-03.**
      Not a hypothetical: `@property` appears in 3 of 5 frozen bundles
      (`ground.news.har`, `tailwindcss.com.har`, `ui.shadcn.com.har` — all
      Tailwind v4's own registrations). Fixed `ui.shadcn.com.har`'s
      `--tw-ring-color`/`--tw-ring-shadow` resolving from an unrelated
      ancestor 12-14 levels up. Along the way, found and filed T25 (the
      same-element default that should have preempted this was invisible
      because the reset's own selector list couldn't compile). See T22's
      own entry below
- [x] **T23** — evaluate `@supports` conditions instead of reading every
      conditional block as though it always applies — **filed 2026-08-02,
      landed 2026-08-02.** Fixed the `pawelgrzybek.com` dark ground exactly
      as predicted (`#ffffff` → `#21262c`) and, unpredicted, also corrected
      `mdn.har`'s `light-dark()` polyfill fallback. See T23's own entry
      below for the design (a leaf never returns confirmed-`False`, only
      `True`/unknown) and both corpus results
- [x] **T24** — a report "Caveats" section naming colors whose only evidence
      is a structurally unconfirmable selector (`:hover`, `:focus`,
      `:focus-visible`, …) — **filed 2026-08-02, requested by the owner
      after T18/T19/T21's own "untestable" investigation, landed
      2026-08-03.** Unlike T21/T22, this is the bucket nothing can ever
      close: a dynamic pseudo-class describes an interaction state, not
      markup, so no capture — however complete — resolves it. Landed as
      sketched: `dom.untestable_reason` tells "dynamicState" apart from
      "uncompilable" once `selector_reach` has already answered `None`;
      `Usage.reach_reason`/`Entry.all_dynamic_only` thread the unanimity
      check through `extract._build`; `describe()` adds an additive
      `examples[].reason` and an entry-level `dynamicOnly` flag; the report
      gains an always-present Caveats section naming affected entries.
      Corpus counts landed exactly on the filing's own prediction — 9
      (`ui.shadcn.com`, 3 light + 6 dark), 13 (`ground.news`), 7
      (`tailwindcss.com`), 0/0 on both hand-written sites — and all seven
      frozen bundles are byte-identical once the two additive keys are
      stripped. See T24's own entry below
- [x] **T25** — a comma-separated selector list loses every branch to one bad
      one — **filed 2026-08-03, found while diagnosing T22, landed
      2026-08-03.** `dom._compile_selector_parts` splits each list and
      compiles branches independently. `ui.shadcn.com.har` came back
      byte-identical — T22's `non_inheriting` flag already covers its two
      properties, contrary to this task's own filing-time prediction —
      while `tailwindcss.com.har` moved via a *different* `--tw-*` property
      hitting the same root cause. See T25's own entry below for the full
      corpus verification and why `matches_page_element`/
      `selector_specificity` stay out of scope

Repo and process:

- [x] **T11** — CI: 3.11–3.14, `ruff`, and package/zipapp/console-script JSON
      identity — **decided against 2026-08-01: won't do.** See T11's own
      entry below for the owner's reasoning
- [x] **T12** — `Makefile` or `build.py` for the zipapp incantation —
      **landed 2026-07-26** as `build.py`
- [x] **T13** — move `test_palettekit.py` into `tests/`, split by module —
      **landed 2026-07-27**. See T13's own write-up below
- [x] **T14** — fixture corpus of small committed HTML files per site
      archetype — **closed 2026-08-03, owner decision: satisfied by what's
      currently delivered.** The original ambitious scope (a small corpus
      spanning framework-heavy, page-builder, dark, light and CSS-variable
      -driven archetypes, plus committing the reference fixture and the four
      breadth-check bundles) was never built, and this closes without
      building it. What stands in its place: the `parkersprouse.me.har` +
      `example/` commit (2026-07-27) gives a fresh clone one real,
      regenerable, byte-identical-verified fixture — no longer the "commit
      nothing" state that made T14 urgent when filed. The reference fixture
      and the four breadth-check bundles remain gitignored and
      un-regenerable from a fresh clone; that gap is accepted rather than
      closed. See T14's own entry below for the full accounting
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
CSS nesting is making the shape it mishandles more common every year. ~~T14 is
the one that unblocks *checking* any of the others, since a fresh clone can
currently regenerate no fixture at all.~~ **Partly true as of 2026-08-01, and
closed rather than finished as of 2026-08-03**: the `parkersprouse.me.har` +
`example/` commit gave a fresh clone its first regenerable fixture, and with
T11 decided against, "unblocks checking the others" no longer pointed at a CI
job — it just meant the example was a real, verifiable anchor rather than an
unverifiable promise. The owner closed T14 there rather than building the
rest of its original scope (a small corpus spanning framework-heavy,
page-builder, dark, light and CSS-variable-driven archetypes, plus committing
the reference fixture and the breadth-check bundles) — see T14's own entry.
Everything else in this list is genuine but static.

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
| `CLAUDE.md` | the `for v in 3.10 …` matrix loop, and ~~the CI entry in T11~~ (T11 was decided against 2026-08-01 and never produced a CI entry to update) |
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
> `# TODO(migration): decide a license`, and CLAUDE.md is explicit that
> "nothing about publishing moves until a license is chosen." The package has
> never been published, so nobody is installed from PyPI on any version to
> break. A major bump would signal a compatibility break to consumers who do
> not exist yet; a minor bump records the change honestly without overstating
> its current blast radius. Revisit this reasoning if the package is published
> before the next floor bump — an EOL-driven floor raise on a *published*
> package is a different cost calculus. `schemaVersion` (T3) stays at `1`
> regardless, since it is that document's first stamp and moves on its own
> schedule — see T3.
>
> **The license question this reasoning rests on was itself resolved later
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

### T8 — `@import url(…) layer(x)` should register a layer (landed 2026-07-27)

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

**Landed as scoped: only the position is reserved, the second piece — actually
following the import — was not attempted.** `_walk`'s statement-at-rule branch
(`cssparse.py`) grew an `elif keyword == "import":` next to the existing
`@layer a, b;` handling, walking `node.prelude`'s tokens for a `function` node
named `layer` and reading its name from `.arguments` via `tinycss2.serialize`
— the same token-type search `_anonymous_layer` already does when looking for
`@layer {}`, not a regex over the serialized prelude. `_register_layer` then
reserves the name (and its ancestors, for a dotted sub-layer) exactly as the
`@layer a, b;` statement form does.

`layer_order`'s own docstring used to say the whole construct "is not
modelled" — that was accurate before this landed and is now half-true, so it
was corrected rather than left to mislead the next reader: the position is
modelled, the imported sheet's *content* still isn't, because `sources.py`
still doesn't follow `@import` (unchanged scope, per the plan's own "consider
doing only that").

No corpus site uses `@import ... layer(...)`, so this is insurance rather
than an observed fix — confirmed rather than assumed: all four frozen bundles
(`fleshandbonedesign.com`, `ground.news`, `tailwindcss.com`, `ui.shadcn.com`)
produce byte-identical `to_document` JSON before and after, diffed with
`generated` removed. Three new tests (`test_import_layer_reserves_a_position`,
`test_import_layer_name_is_found_by_token_not_regex`,
`test_import_without_layer_registers_nothing`), 110 → 113 tests, `ruff`
clean, 3.11–3.14 all pass.

### T9 — Model scoped custom properties — **DONE**, landed 2026-08-02

> **Investigated 2026-07-27, not implemented — blocked on an owner decision.**
> The scope this task assumed turns out not to exist at the fidelity the tool
> can currently reach. What follows is the finding, not a restatement of the
> caution already in this task's own opening paragraph below.

> **Decided 2026-08-02: build the real-DOM direction, with `html5lib`.**
> Between the two prerequisites this investigation surfaced (below), a real
> DOM below `<body>` was chosen over per-element computed-style resolution —
> the latter's own reasoning stands unchanged, it's still the cascade engine
> `CLAUDE.md` is explicit the tool is not, and its accuracy ceiling was judged
> not worth its scope against what T9 actually needs. `html5lib` over `lxml`:
> pure Python, so `PYTHON_FLOOR` and `build.py`'s vendoring model (which
> assumes no compiled wheels) stay unchanged — the same floor-vs-fidelity
> logic this file already applies to the `lxml` question elsewhere. The cost
> this defers isn't free: phase 2's own research called `html5lib` "slow,
> heavy" when the tool needed nothing past `<html>`/`<body>` matching: worth
> a real measurement once T9 is in shape to make one, not assumed away.
> Work started in a worktree the same day. Two follow-ups the same dependency
> unlocks, beyond what T9 itself needs to build, are filed separately rather
> than folded in here — **T18** (flag selectors matching nothing in the real
> document) and **T19** (report actual matched elements, not just selector
> text) below.

A property redefined on `.card` resolves globally here. `@property` and normal
inheritance down the tree are both unmodelled.

This is the largest open item and the one most likely to turn into a cascade
engine, which `CLAUDE.md` is explicit the tool is **not**. Scope it before
starting: the goal is a property resolving differently for the elements that
consume it, not computing anyone's styles.

It is also the second half of T4's trap — ui.shadcn.com's `--shimmer-image`
resolves to `none` from a utility the shimmering element does not carry.

**What was designed.** A same-element compatibility filter over
`build_var_table`'s existing off-page population (invariant 19): for a given
consuming declaration, keep an off-page custom-property definition as a
candidate only if that definition's own selector could plausibly land on the
*same* element the consumer's selector styles. Tested with `cssselect2` — the
same library `dom.matches_page_element` already uses — by compiling the
candidate's selector and testing it against a synthetic element built from the
consumer's own literal classes/id/tag (closed-world: exactly what is written,
nothing assumed beyond it), permissive about any ancestor combinator a
*candidate* itself writes (assumed satisfiable, since this tool has no real
DOM below `<body>` to confirm one either way — the same "unknown is not the
same as absent" reasoning `page_elements` already uses for its own `None`
case).

**Why it fails, and it is structural rather than a tuning problem.** Custom
properties are consumed overwhelmingly through *inheritance*, not by being
redefined on the exact element that reads them — that is the feature's whole
purpose, and a same-element filter answers a question inheritance was never
going to ask. ui.shadcn.com writes exactly that shape: `.theme-sketch`,
`.theme-neutral` and `.theme-blue` each redefine `--card` and dozens of
sibling tokens. Confirmed present in the fetched HTML, not JS-injected —
`<div data-slot="demo" class="theme-neutral relative flex w-full …">`, a
wrapper several levels below `<body>` — so this is a real authored pattern in
the frozen bundle, not a hypothetical. The actual consumers — `.bg-card`,
`.shadow-card`, `.ring-card`, `.dark\:bg-card:is(.dark *)` — carry none of
those three classes in their own selectors. A same-element filter tests
exactly what it claims to: none of the three theme classes reaches `.bg-card`'s
own subject compound, so all three are excluded and `--card` comes back
*absent* for every one of these consumers, not merely re-ranked. `background-
color: var(--card)` has no fallback text, so the declaration loses its color
outright — a strictly worse answer than today's arbitrary-but-present
last-wins value, on one of the site's most-used tokens.

This is not a corner case reachable only on this one site. Off-page
custom-property names with more than one competing definition were counted on
all four frozen bundles, by the same method `build_var_table` already uses to
find the off-page population, just grouped by name instead of collapsed to
last-wins (`#hex`/`lab(...)` pairs written under the *same* selector are
progressive-enhancement doubles for wide-gamut color, not contention, and are
excluded by counting distinct selectors rather than raw declarations):

| bundle | theme(s) | contested names |
|---|---|---:|
| fleshandbonedesign.com (the reference fixture — hand-written CSS, one theme) | base | 19 |
| ground.news | base / dark | 51 / 51 |
| tailwindcss.com | base / dark | 123 / 138 |
| ui.shadcn.com | base / dark | 127 / 127 |

Contention among off-page definitions is the norm on every corpus site,
including the smallest hand-written one — not a shape special to utility
frameworks or to this one site's theme picker. A same-element filter would
reach all of it.

**Why selector text cannot separate the two shapes.** A bare
`.theme-sketch { --card: … }` and a bare `.shimmer-none { --shimmer-image:
none }` are the identical grammatical shape: one class selector, no
combinator. One is meant to be read by an *ancestor's* descendants through
inheritance; the other is meant to override a property on the *same* element a
sibling utility class also sits on. Nothing in the selector text marks which
is meant — the distinction lives entirely in the real document tree,
specifically in whether the class a rule targets is an ancestor of, or
identical to, the element consuming the `var()`. `dom._TreeBuilder` deliberately
does not build that tree below `<html>`/`<body>` (invariant 16 says as much:
"the only elements ever tested are `<html>` and `<body>`"), so there is no
tree to ask the question of.

**The prerequisite this exposes, and it is the owner's call, not this task's
to make alone**: closing T9 needs either (a) a real DOM below `<body>` — an
`html5lib`-grade tree builder, a dependency question the same shape as the
`lxml` one this file already reserves for the owner explicitly (pure-Python
floor vs. fidelity) — or (b) per-element computed-style resolution, which is
the cascade engine `CLAUDE.md` is explicit the tool is not, and a far larger
commitment than either dependency question. Neither is "model scoped custom
properties" as a bounded diff; both are new capabilities this task cannot
absorb quietly.

**What stays true regardless of that decision.** Invariant 26 (`initial` as
guaranteed-invalid) is unaffected and still correct on its own terms — this
investigation found no fault in it. The `--shimmer-image` trap's other half —
`.shimmer-none`/`.md\:shimmer-none`'s `none` beating the fallback for elements
that were never toggled to `shimmer-none` at all — remains exactly the limit
`CLAUDE.md`'s "Known limits" section already describes it as, unchanged by
this investigation.

**Diff level, if this is picked up again once a real DOM is available:**
custom-property resolution table, old winner against new with the cascade
key's terms printed beside them — phase 3's level, which is the only one that
showed its twelve moves. Predict the blast radius on all four frozen bundles
*before* writing code, the same discipline phase 4 used — the contention
counts above are exactly that prediction, one design-generation early.

> **Progress, 2026-08-02 — the tree and the lookup primitive are landed and
> tested; wiring them into the actual pipeline is not, deliberately.**
> Started in a worktree (`worktree-t9-scoped-custom-properties`), ~~not yet
> merged to `main`~~ **merged the same day** (`f8dd55c`) — stale as of this
> task's later progress notes below, which cover the wiring itself and its
> own merge. Left here rather than deleted: it's an accurate snapshot of
> what existed at the moment it was written, not a claim about the task's
> current state.
>
> **Landed, in `dom.py`:** `full_tree(html)` — `html5lib.parse(...,
> treebuilder="etree", namespaceHTMLElements=False)`, verified directly to
> hand `cssselect2.ElementWrapper.from_html_root` a tree it accepts the same
> way `page_elements`' stdlib-shim tree does. `elements_matching(selector,
> root)` and `selector_matches(selector, element)` — general-purpose
> counterparts to `matches_page_element`/`selector_specificity` that answer
> the same two questions for *any* real element, not only `<html>`/`<body>`.
> Six new tests (`TestFullTree`), including one that reproduces this task's
> own motivating shape (a `.bg-card` element under `.theme-neutral` versus
> one outside it) and confirms the tree tells the two apart.
>
> **Landed, in `extract.py`:** `resolve_by_ancestry(candidates,
> consumer_elements, layers)` — the nearest-ancestor-or-self lookup this
> task's investigation found missing, cascade-resolving ties at whatever
> level it stops on rather than assuming one candidate per level. Five new
> tests (`TestResolveByAncestry`), run directly against this task's own
> `.theme-neutral`/`--card`/`.bg-card` shape: it returns `#f5f5f5` where a
> same-element filter returns nothing (`test_nearest_ancestor_wins_not_same_element`),
> gives two different real elements their own different real answers
> (`test_different_ancestors_give_different_real_answers`), and refuses to
> guess when one consuming declaration paints two elements under different
> ancestors that disagree (`test_disagreeing_consumers_collapse_to_none_not_a_guess`)
> rather than picking one arbitrarily.
>
> **Not landed, and this is the larger remaining piece** — as of this point
> in the day; resolved later the same day, see "Wired in" below.
> `build_var_table`/`resolve_vars` are built around one flat `dict[str, str]`
> table per theme, shared by every consuming declaration in the document —
> invariant 19's whole shape. `resolve_by_ancestry` breaks that model on
> purpose: its answer depends on *which* consumer is asking, so the single
> flat table can no longer be the return type for the `scoped` (off-page)
> population once ancestry-aware resolution is wired in. Wiring this in
> means either passing a consumer context through every `resolve_vars` call
> site (ground detection, `_scopes_present`, `_triplet_warning`, and the main
> per-declaration loop in `_build` all currently call it with a bare table),
> or restructuring how the `scoped` population is stored and looked up. Not
> designed yet — deliberately, rather than rushed to fit one sitting.
>
> **Also not decided:** what happens when a candidate's own selector is
> blanket (`*`) — see the caveat inside `resolve_by_ancestry`'s own
> docstring. And what a consuming declaration that paints multiple real
> elements with genuinely different ancestry-resolved values should do to
> the palette — today one declaration contributes one set of colors; real
> per-element resolution can produce more than one correct answer for the
> same declaration, which the palette's occurrence-counting model does not
> yet have a place for.
>
> **Verified so far:** all 124 tests pass (113 existing + 11 new, none of
> the existing ones edited), `ruff` clean, 3.11–3.14 all green. The new code
> is not yet reachable from any pipeline call, so it is a **provable no-op**
> on real output rather than an assumed one: `to_document()` on
> `parkersprouse.me.har --images` and on a frozen `ground.news.har`, diffed
> against a `git stash`-old run with `generated` dropped, both
> byte-identical. `palettekit.pyz` has **not** been rebuilt — deferred until
> there's a behavior change worth shipping in it, since a rebuild right now
> would just re-package a no-op.
>
> **What's next, in order:** design how the `scoped` population's return
> type changes to carry a per-consumer answer; predict the blast radius on
> all four frozen bundles per this task's own stated diff level, *before*
> wiring anything in; decide the blanket-selector and multi-element
> questions above; then wire it in and re-run the full verification
> discipline this file uses everywhere else — declaration-level diff first,
> palette-level second, corpus-wide, old against new.

> **Blast radius measured, 2026-08-02, same day — and the measurement is why
> wiring stops here rather than proceeding to a return-type redesign.** Per
> this task's own stated diff level: for every off-page custom property, per
> theme, on all four frozen bundles, last-wins (today) against
> `resolve_by_ancestry` (candidate), with which outcome produced the
> difference. Throwaway script, not committed.
>
> **First draft of this measurement had two defects, both caught before the
> numbers below were trusted, not after.** The consumer predicate was a bare
> substring test (`"var(--tw-shadow" in d.value`), which on Tailwind bundles
> matches `var(--tw-shadow-color)` and `var(--tw-shadow-alpha)` as if they
> consumed `--tw-shadow` itself — inflating disagreement and deflating "no
> basis" on exactly the two columns the conclusion rests on. Fixed with a
> boundary requirement (the name must be followed by `)`, `,`, or whitespace).
> And the `fleshandbonedesign.com` row was run with no excludes, silently
> pulling in third-party sheets and reporting two themes for a bundle
> `CLAUDE.md` documents as one — fixed by passing the same
> `exclude=["static-css", "cargo.site"]` the reference fixture itself is
> generated with. Numbers below are post-fix; the corrected predicate alone
> dropped tailwindcss.com's distinct consumer selectors from 1,895 to 479.
>
> | bundle | same | → real value | → confirmed absent | → real disagreement | → no basis (empty match) |
> |---|---:|---:|---:|---:|---:|
> | ground.news | 5 | 8 | 31 | 0 | 32 |
> | tailwindcss.com | 10 | 13 | 22 | 17 | 143 |
> | ui.shadcn.com | 5 | 8 | 18 | 9 | 120 |
> | fleshandbonedesign.com (excludes matched to the fixture) | 0 | 0 | 0 | 0 | 1 |
>
> **"No basis" dominates every bundle, and it is not a tuning gap: it is the
> consuming element not existing anywhere in the captured tree at all** —
> `elements_matching` on the consumer's own selector returns `[]` before
> ancestry is even asked. Confirmed by inspecting the actual captured HTML,
> not assumed from the count, and it is two distinct causes:
>
> - **`ground.news.har`'s captured body is truncated at exactly 1,048,576
>   bytes** — 2^20, a hard capture cap rather than a natural document end; it
>   cuts off mid-attribute (`class="…focus-visib`). Whole sections of the real
>   page are simply absent from `full_tree`, which has nothing to do with
>   JavaScript.
> - **`tailwindcss.com.har` and `ui.shadcn.com.har` are complete, uncapped
>   captures** (900,542 / 769,076 bytes, both ending cleanly at `</html>`) and
>   still mostly miss the consuming elements, because both are Next.js apps
>   whose real content is client-hydrated from JSON embedded in `<script>`
>   tags rather than written as literal markup — `full_tree` sees only the
>   server-rendered shell. This is `CLAUDE.md`'s existing "no JavaScript is
>   executed" limit, but it lands far harder on this question than on ground
>   detection: a `<body class="…">` is reliably present in a shell render,
>   while the deep utility-class elements T9's ancestry walk needs mostly are
>   not. Checked directly against this task's own motivating case:
>   `ui.shadcn.com`'s `.shimmer` element lives on `/docs/utils/shimmer`, a page
>   this HAR never fetched — the string `shimmer` appears in the captured
>   document only inside a nav link's JSON, never as a class. **T9 cannot
>   close its own motivating trap from this bundle** — not because ancestry
>   resolution is wrong, but because the element it would resolve for was
>   never captured in the first place.
>
> **This settles the design question the prior note left open, rather than
> leaving it for the return-type redesign to discover the hard way**:
> ancestry resolution has to be an *override on top of* last-wins, never a
> replacement, exactly the shape this task's own investigation already
> rejected the same-element filter for — "a strictly worse answer than
> today's arbitrary-but-present last-wins value." Left unguarded, "no basis"
> alone would turn 32–143 currently-present values `None` per bundle. Of the
> four outcomes, only two should ever override last-wins: a real different
> value (8–13 per bundle), or confirmed absence — every real consumer
> visited, no ancestor sets it anywhere (18–31 per bundle) — because
> last-wins there is answering about the wrong element and *should* lose.
> "Real disagreement" (0–17 per bundle) and "no basis" (1–143 per bundle)
> both have to fall through to today's behaviour unchanged: a single
> value-per-theme table has no way to express "two real elements are
> correctly different colors," and collapsing that to `None` is not an
> improvement over an arbitrary-but-present guess.
>
> **Perf, measured rather than assumed — but this measures `cssselect2`
> wrapper cost, not `html5lib` parse cost, and phase 2's deferred question
> about the latter is still open.** `elements_matching` re-wraps the whole
> tree with `cssselect2.ElementWrapper.from_html_root` on *every call*, even
> with per-selector memoization sitting outside it: tailwindcss.com (479
> distinct consumer selectors, post-fix) took 55s; ui.shadcn.com (199
> selectors) 6.3s; ground.news (105 selectors, truncated tree) 1.75s. That
> scales with selector count, not document size — ground.news parsed and ran
> full_tree end-to-end in the 1.75s total, so `html5lib`'s own parse cost is
> nowhere near the bottleneck here and this measurement does not speak to it
> either way. Wiring this into the real pipeline needs the wrapper hoisted
> once per document and reused across every selector, not rebuilt per lookup
> — a small signature change to `elements_matching` itself (accept a
> pre-wrapped root), on top of the landed and tested function.
>
> **Revised "what's next"**: the return type needs a fourth state, not the
> flat replacement the prior note assumed — override (real value or
> confirmed absent) versus preserve (disagreement or no basis) — and
> `elements_matching` needs the wrapper-reuse fix above regardless of how
> that design lands. Neither is done. This is a complete session's worth of
> progress on its own terms: a measurement that changed the plan rather than
> confirming it.

> **Wired in, 2026-08-02, same day — landed rather than left designed.** The
> owner's priority (accuracy first, whichever path gets there) settled the
> question the measurement above raised without resolving: worth doing
> despite a modest corpus payoff. Implemented per the revised design:
>
> - **`_var_populations`** (`extract.py`) factors `build_var_table`'s own
>   split into page-reaching (`rooted`) and off-page (`off_page`, now a
>   `dict[name, list[Declaration]]` instead of collapsed last-wins) —
>   `build_var_table` itself is a thin wrapper over it
>   (`_merge_var_populations`), verified **byte-identical** output, old vs
>   new, on all five bundles (`ground.news`, `tailwindcss.com`,
>   `ui.shadcn.com`, `fleshandbonedesign.com` with the fixture's own
>   excludes, `parkersprouse.me`) — every key, every value, not just a hash
>   (a first pass compared `hash(frozenset(...))` and disagreed on all five;
>   that was Python's per-process string-hash randomization, not a real
>   difference — caught by comparing actual sorted items instead of trusting
>   the hash).
> - **`resolve_by_ancestry_kind`** (`extract.py`), alongside the untouched
>   `resolve_by_ancestry`, sharing the walk via a new `_ancestry_winners`
>   helper: returns `("value", v)` / `("absent", None)` / `("disagree",
>   None)` — the three-way split the measurement showed was necessary, kept
>   out of the existing function so its own contract and five tests stay
>   exactly as landed. One deliberate, explicit decision the measurement
>   surfaced but didn't force: a consumer element with no ancestor match is
>   *not* read as voting for disagreement when another consumer element
>   resolves to a real value — `resolve_by_ancestry`'s own collapse already
>   has this shape, so `_kind` matches it rather than silently disagreeing
>   with the function it's meant to be a detailed version of. Pinned by
>   `test_one_consumer_with_no_ancestor_match_does_not_read_as_disagreement`.
> - **`dom.wrap_tree`/`elements_matching_wrapped`**: `elements_matching`
>   re-wrapped the whole tree on every call (the measurement's own perf
>   finding); split so `_build` wraps once per theme and reuses it across
>   every distinct consumer selector, memoized. `elements_matching` itself
>   is an unchanged one-line wrapper over the split — no existing call site
>   or test needed to change.
> - **`_build`'s per-declaration loop**: only when a declaration's value
>   references an off-page-only name (`var_refs(d.value) & off_page.keys()`
>   — tokenized, not a regex, the same discipline invariant 9 and the T5/T15
>   corollary already establish) does it look up that declaration's own real
>   consumer elements and ask `resolve_by_ancestry_kind`. `"value"` overrides
>   the per-declaration table entry; `"absent"` deletes it from a
>   per-declaration copy of the table (routing into `_resolve_var`'s
>   existing `stored is None` branch — the same path `initial`, invariant
>   26, already takes: the declaration's own written fallback applies, or
>   nothing does); `"disagree"` and an empty consumer-element list ("no
>   basis") leave the shared table untouched. Every other call site
>   (`_scopes_present`, `_triplet_warning`) still calls plain
>   `build_var_table` and is structurally untouched by this — `_triplet_warning`
>   in particular cannot be tripped by the "absent" deletion, since it never
>   sees `_build`'s per-declaration table at all.
>
> **Four new unit tests** (`TestResolveByAncestryKind`) pin the three-way
> split and the mixed-outcome decision. **Four new integration tests**
> (`TestAncestryWiredIntoBuild`) run `extract()` end-to-end: a real-ancestor
> override, a confirmed-absent case falling back to the declaration's own
> written fallback, the same case with no fallback yielding zero colors and
> no spurious warning, and a no-basis case proving last-wins survives
> unchanged. Each of the two behaviour-changing tests was confirmed to
> **fail against the pre-wiring implementation** (`git stash push --
> palettekit/dom.py palettekit/extract.py`, tests kept); the two
> regression/preservation tests pass unchanged before and after, which is
> the point of them. 132 tests total (124 + 8), `ruff` clean.
>
> **Corpus diff, first pass, was at the wrong level and understated the
> change — corrected before this was trusted, not after.** A hex-set
> comparison alone found only `tailwindcss.com` different and called the
> other four bundles unchanged. Invariant 25's own write-up already records
> why that is the wrong level for this class of fix: *"every hex set, ground
> and warning... identical before and after. What moved was occurrence
> counts, and through them the ranking that names tokens."* Re-run at the
> right level — full per-entry document diff (`name`, `occurrences`,
> `score`, `role`, `status`), old vs new (`git checkout 1cd2005 --
> palettekit/dom.py palettekit/extract.py`, run, restore, diff) — and the
> same pattern repeats here:
>
> - **`fleshandbonedesign.com` and `parkersprouse.me`: genuinely
>   byte-identical**, every field, both themes — no off-page contention
>   these bundles' declarations reach at all.
> - **`ground.news`: hex set unchanged, but 3–4 entries per theme shift
>   `occurrences`/`score` by single digits** (`#eeefe9` 181→176 occurrences
>   in the base theme, for example) — real reranking, small enough not to
>   move a name.
> - **`ui.shadcn.com`: hex set unchanged, but the dark theme has 11 entries
>   with a moved `name`** — `grey-2`↔`grey-4`, `surface-11`↔`surface-1`, and
>   several more swap pairwise. **These are exactly the tokens a consuming
>   project's CSS/SCSS/TS output would reference by name**, invariant 10's
>   own point about why `live` colors ship to code — so "hex set unchanged"
>   was true and also not the reassurance the first draft of this note
>   implied.
> - **`tailwindcss.com`: both a hex-set change and the largest name/rank
>   churn** — 2 hexes replaced by 3 in the dark theme
>   (`#201836`/`#28152b` → `#21274d`/`#33244d`/`#411e3b`), one new hex added
>   in the base theme (`#e4a340`), and 26–28 entries per theme with a moved
>   `name`, `occurrences`, or `score`.
>
> **The hex-level change is traced to a concrete, explicable shape rather
> than accepted on faith.** Tailwind emits declarations like
> `.shadow-pink-400\/50 { --tw-shadow-color: color-mix(in oklab,
> color-mix(in oklab, var(--color-pink-400) 50%, transparent)
> var(--tw-shadow-alpha), transparent) }`, where `--tw-shadow-alpha` is
> itself off-page (defined per-utility, not on the page element) — so the
> *definition* of `--tw-shadow-color` for one shadow utility was, before
> this, resolving its own opacity from **whichever `--tw-shadow-alpha` last
> won across the entire document**, not its own. Ancestry resolution finds
> the self-scoped definition (self counts as its own nearest ancestor,
> exactly as `resolve_by_ancestry`'s own docstring says) and each shadow
> utility now gets its own opacity instead of borrowing one from an
> unrelated utility declared later in the same stylesheet. A real fix, the
> same shape as invariant 26's `initial` correction and T5's `calc()`
> percentage evaluation.
>
> **The broader rerank on `ground.news`/`ui.shadcn.com`/`tailwindcss.com` is
> not separately traced per-entry** the way the hex change is — each
> individual occurrence-count shift is small and plausible (a handful of
> declarations moving from "shared last-wins value" to "own ancestry-correct
> value" changes which existing bucket each lands in), but this note does not
> prove each one is correct the way the shadow-alpha trace does. Grounds,
> warnings, and hex sets — the highest-stakes fields — are confirmed right;
> token *names* moving on a real site's output is the accuracy improvement
> this task exists for, not a regression, but say so plainly rather than
> letting "zero hex-set change" stand as "nothing changed."
>
> **Perf, measured on the same corpus rather than assumed acceptable**:
> `tailwindcss.com` (the one bundle with hundreds of distinct off-page
> consumer selectors) went from 1.6s to 35s for a full `extract()` run;
> `ui.shadcn.com` 1.2s → 5.1s; `ground.news` 0.5s → 1.5s;
> `fleshandbonedesign.com`/`parkersprouse.me` unchanged (no off-page
> contention at all). The wrapper-hoisting fix above already cut this from
> the measurement script's 224s/55s per-bundle wrap-per-selector cost; what
> remains is `cssselect2.query_all` itself scanning the tree once per
> distinct consumer selector, which is inherent to matching correctly
> rather than a bug. Not optimized further this session — the owner's
> stated priority is accuracy, and correctness was verified before cost was
> — but worth a line here if `tailwindcss.com`-shaped sites (hundreds of
> distinct utility selectors, most off-page) turn out to dominate real
> usage: query batching or an index keyed by class name are the likely
> next moves, not attempted here.
>
> `palettekit.pyz` **rebuilt** at the end of this session (`python3
> build.py`), per the standing process rule — this changed real pipeline
> behavior, not just documentation. Verified on a fresh 3.11 interpreter with
> neither dependency installed (`uv run --python 3.11 --no-project python
> palettekit.pyz fleshandbonedesign.com.har …`), and module/console-script/
> zipapp JSON confirmed identical.
>
> **Version matrix run this session, not skipped** — `dom.py` now imports
> `html5lib` at module scope for core pipeline code, not just an optional
> path, so the matrix command in `CLAUDE.md` was missing a dependency it
> would need on every version (`ImportError` as written; fixed to add
> `--with html5lib` in the same edit that caught this). All of 3.11–3.14
> green, 132 tests, after the fix.
>
> **Two places in `CLAUDE.md` restated this task's own prior claim and were
> now wrong, not just this file** — invariant 19's "off-page definitions stay
> on last-wins" and the Known-limits "scoped custom properties... not
> modelled" entry, plus the `--shimmer-image` limit write-up that pointed at
> the second as its own fix. All three updated in the same commit as the
> code, per this project's own "invariants restated at their call site stay
> in sync" rule — the `--shimmer-image` update also records, checked
> directly rather than assumed, that **this specific frozen bundle's example
> is still not fixed**: its `.shimmer` element lives on a page
> (`/docs/utils/shimmer`) this HAR never fetched, so it is a "no basis" case
> under T9's own three-way split, not a "confirmed absent" one — last-wins
> correctly stays untouched for it. Closing the modelling gap does not
> retroactively give a capture gap an answer it never had the markup for.

### T18 — Flag declarations whose selector matches nothing in the real document

**Filed 2026-08-02, alongside T9's `html5lib` decision. Landed 2026-08-02.**
New status `unmatched` (invariant 27, `CLAUDE.md`, which is the authority for
the full design history — this entry is the short version, corrected against
what was actually built rather than what was predicted here beforehand).

**The gap, as originally scoped, held up.** `extract._status_for` used to
distinguish `live` from `saved`/`inert` two ways only, and neither checked
whether an *ordinary* declaration's selector matches any real element at
all — `.old-promo-banner { color: #ff0000 }`, a leftover rule nothing in the
document carries anymore, reported `live`, indistinguishable from a color
the page actually paints. `dom.selector_reach` (new) plus
`Entry.all_unmatched` close that gap.

**Two predictions made in this entry before implementation turned out
wrong, and both were caught by measuring rather than trusting the
prediction.** Both are worth keeping visible rather than quietly fixed,
per this file's own standing discipline.

1. *"Whatever T18 builds needs a confirmed-absent-vs-no-basis split at the
   document level, the same shape as T9's."* Wrong shape. T9's own
   `resolve_by_ancestry_kind` never actually has a "confirmed this selector
   matches nothing" outcome to borrow — a consuming selector matching zero
   elements is *always* T9's "no basis" case, full stop. The real fix
   turned out to be per-*usage*, not per-document: `dom.selector_reach`
   returns `True`/`False`/`None` (matched / confirmed zero / untestable —
   pseudo-element, dynamic state, uncompilable), and `Entry.all_unmatched`
   requires **every** usage to be a confirmed `False` — one `None` anywhere
   in the entry leaves it `live`. A document-level "is this capture
   trustworthy" gate (flip nothing if the whole document's overall match
   rate is too low) was built and measured before being rejected: it does
   not discriminate. `fleshandbonedesign.com.har` — the trusted, hand-written
   reference fixture — has a match rate of 0.29, statistically
   indistinguishable from `tailwindcss.com.har`'s 0.25–0.33. There is no
   threshold that separates a small site's generic unused theme CSS from a
   docs site's unused utility classes; both produce "most selectors miss
   this one page" for legitimate, unrelated reasons.

2. *"[This will] flag most of a modern site's real, live CSS as dead,"*
   predicted from T9's blast-radius finding that off-page custom properties'
   consumer selectors matched nothing 120–143 times on the Next.js bundles.
   That finding was real but described a narrower population than T18
   actually touches (custom-property *consumers* only, vs. every
   color-bearing declaration), and checking T18's own broader population
   directly found something closer to the opposite: `tailwindcss.com.har`
   and `ui.shadcn.com.har` flip 21–29% of `live` entries, no worse than
   `ground.news.har`'s truncated capture, and no worse than the fully
   static, hand-written reference fixture — which the strict per-usage rule
   above flips 7 of 14 `live` entries on (**not** a Next.js-only problem).
   A first read of that number blamed client-side JS toggling; a `grep` for
   `quick-view` in the captured HTML returned 28 hits and looked like
   confirmation. Every hit was inside the site's own embedded `<style>` text
   — the selector's own definition — not a `class=` attribute. Restricting
   the check to real `class="..."` attributes found zero actual elements
   for every flipped case: genuinely unused rules from a general-purpose
   theme stylesheet (Cargo's "crass" template ships variants this site
   never uses), not JS-gated content. The corrected finding argues *for*
   this task rather than against it.

**What this does not fix.** Same limit as everywhere else in this file that
touches the DOM: only the static markup a HAR/URL fetch captured is visible.
A class added by JavaScript at runtime, or toggled by a runtime interaction
(`:hover`, a modal open state), reads `None` (no basis) rather than `False`
here, so it cannot make an entry `unmatched` by itself — but a *different*
usage on the same entry that genuinely is a confirmed non-match still can,
same as any other selector. `parkersprouse.me.har`'s `:where(dialog)` /
`:where(fieldset)` are the cleanest positive case in the corpus: a
normalize-style reset for elements the static markup doesn't have yet.

**Priority: `inert` → `saved` → `unmatched` → `live`** (`_status_for`). The
new check only ever narrows an entry that is already `live`; an
already-`saved` or already-`inert` entry is never reconsidered. Verified
directly against the reference fixture's own documented anchors — ground
`#151515`, 20 tokens, `#ffc600` `saved`, `#13330d` `inert`, no warnings — all
five held unchanged before and after.

**Diff level, as predicted:** per-declaration/per-entry status, old vs new,
on all five frozen bundles (`fleshandbonedesign.com.har`, `ground.news.har`,
`tailwindcss.com.har`, `ui.shadcn.com.har`, `parkersprouse.me.har`). Results:
fleshandbonedesign 7/14 `live` entries flip, ground.news 73–79/119–126,
tailwindcss.com 65–77/304–318, ui.shadcn.com 21–29/153–168,
parkersprouse.me 2–3/9 (base/dark themes, both directions of each range).
Ground, warnings, and total token counts unchanged on every bundle — this
task only narrows `status`, never what enters the palette or what the
ground resolves to. **The report's own reading colors are status-derived
and do move**, since `_pick_report_theme` (`emit.py`) draws its neutral
ramp from `live` entries only, and that pool shrank on every corpus site.
Checked rather than assumed, per invariant 11's own history of exactly this
failure shape: on `ground.news.har`/`tailwindcss.com.har`/`ui.shadcn.com.har`
every theme still clears its contrast floor with room to spare (lowest
margin 3.86:1 against a 3.0 floor), and a before/after diff of the picked
hex values shows only the expected cosmetic drift — a different, equally
real site grey chosen as its previous neighbor became `unmatched` and left
the candidate pool, never a fall-back to the derived-from-ground synthetic
tones. Visually confirmed in a browser on `ground.news.har` (the largest
pool shrink, 119→46), which also caught a real bug: `emit_html`'s report
subtitle read "N found in the source but not painted," which was true for
`saved`/`inert` but not for `unmatched` — fixed to "N more found in the
source" rather than asserting a confidence the status doesn't have.

**Performance, measured rather than assumed:** reused `_build`'s
already-hoisted `wrapped_root` (T9) and memoized by selector text
(`reach_of`, mirroring `consumers_of`) rather than building separate
machinery. `tailwindcss.com.har`: T9-only baseline 35s, with T18's
per-declaration reach check added, ~47s — real but proportional, not a new
dominant cost.

**Tests:** `TestSelectorReach` (`tests/test_dom.py`, 6 tests, the tri-state
contract in isolation) and `TestUnmatchedStatus` (`tests/test_extract.py`,
7 tests, end-to-end through `extract()`) — both written to fail against the
prior implementation before being trusted, per this file's own "a test that
passes before and after tests nothing" rule. 145 tests total (132 → 145),
`ruff` clean, 3.11–3.14 green, module/console-script/zipapp JSON identity
re-verified on the reference fixture.

**Schema note:** `status` gaining a fourth value does not bump
`schemaVersion` — same key, same type (string), which is what T3's own
compatibility promise actually says. Documented explicitly in `README.md`'s
schema section rather than left for a consumer to infer, since "new enum
value on an existing key" is a real third case T3's original two-case
promise (additive key / re-typed key) didn't name.

See **T20** below for the report-side categorization this status unlocks —
still not started, no longer blocked.

### T19 — Report actual matched elements in `examples`, not just selector text

**Filed 2026-08-02, alongside T9's `html5lib` decision. Landed 2026-08-02.**

**The gap, verified directly before starting.** `extract.py`'s per-entry JSON
builder set `examples` to `[{"selector": u.selector, "property": u.prop,
"source": u.source} for u in top]` — a sample of *selector text*, never
resolved against the document. Two rules matching different numbers of real
elements reported identically if they shared a selector: `.card { background:
… }` used by three sidebar cards and one header card looked the same as
`.card` used once, anywhere on the page.

**What landed.** `Usage` gains `match_count: int | None` and `match_samples:
list[str]`, computed once per declaration in `_build` alongside the existing
`reach_of(sel)` call (T18) rather than as a second pass. Three outcomes, not
two, mirroring `reach_of`'s own tri-state: `reach is None` (no captured HTML,
or an untestable selector) leaves both `None`/`[]`; `reach is False` — a
*confirmed* non-match, `selector_reach` already ran the query and found
nothing — sets `match_count = 0` **without** calling `consumers_of` again,
since that would repeat a query already known to return `[]`; only
`reach is True` calls `consumers_of(sel)` (T9's memoized wrapper around
`elements_matching_wrapped`) for the real count and a sample. `describe()`
emits these as `examples[].matchCount` (always present, nullable) and
`examples[].matches` (omitted, not an empty list, when there is nothing real
to show) — both **additive** JSON keys, no `schemaVersion` bump, per T3.

**`dom.element_signature(node, depth=3, max_len=50)`** is the new piece:
`tag#id.class` for the matched element plus up to `depth` immediate ancestors
chained by `>` (e.g. `div.container > div#hero.card.featured`), hard-capped
to `max_len` characters as a whole string rather than per class — see its own
docstring for why a per-class cap doesn't work on Tailwind v4's generated
font-variable classes. Not a selector — a diagnostic label distinguishing
*which* of several matches a given selector reached: two `.card` elements are
identical on their own tag/id/classes by construction, and only where they
sit tells them apart. Walks `node.ancestors`, already computed and cached by
`wrap_tree`, so this is free — no new tree traversal. `_build`'s own
`samples_of` memoizes the formatted sample by selector text, so a selector
repeated across many declarations (a shared utility class) formats its
sample once, not once per declaration.

**Reused rather than rebuilt, as this task's own earlier sketch called for:**
`consumers_of`, `_build`'s existing memoized wrapper around
`elements_matching_wrapped` against the one `wrapped_root` hoisted per theme
(T9). T19 widens its call site from the off-page-var-consumer subset T9 needs
to every declaration's own selector whose `reach_of` came back `True` — "the
same lookup at wider scope, not a different one" — rather than adding a
second cache or a second tree wrap. It does **not** fully eliminate the
double query this widening risked: `reach_of`/`selector_reach` and
`consumers_of`/`elements_matching_wrapped` still each run their own
`_compile_usable` + `query_all` independently for the selectors that do
match (there's no shared primitive returning both the tri-state answer and
the list from one query), so those get queried twice. The `reach is False`
short-circuit above matters because it skips this entirely for the
majority case — T18's own corpus note puts match rates at 0.25–0.33, so
70–75% of distinct selectors never pay the second query at all.

**Measured, not assumed, on both axes a change touching every declaration in
the document can move:**

- **Time.** `tailwindcss.com.har` end to end, T18-only baseline vs this task,
  `time.time()` around `extract.extract()`: 46.0s → 46.7s — noise-level, not
  the ~59s a naive "query every selector twice" would have cost. The
  `reach is False` short-circuit is why.
- **Payload.** `to_document()`'s output is inlined verbatim into the HTML
  report (invariant 11), so JSON growth is report growth. An uncapped first
  cut (`MATCH_SAMPLES=3`, no `max_len`) grew `tailwindcss.com`'s JSON 38%
  (1.57MB → 2.17MB) and its report 46% — driven by Tailwind's generated font
  classes running past 200 characters each. Capping `element_signature` at
  50 characters and `MATCH_SAMPLES` at 2 brought that to +19% JSON / +18%
  report on `tailwindcss.com` and +17% JSON / +15% report on
  `ui.shadcn.com` — real growth, proportionate to the real per-usage data
  this task adds to every entry, not the near-doubling the first cut
  produced. `dom.element_signature`'s own docstring carries these numbers
  next to the code they justify.

**Correctness verified separately from performance:** a JSON key-set diff
(old vs new, `_build` stashed) across all five frozen bundles
(`fleshandbonedesign.com`, `ground.news`, `tailwindcss.com`, `ui.shadcn.com`,
`parkersprouse.me`) found exactly two new keys (`matchCount`, `matches`) and
confirmed every hex set, status list, and ground was byte-identical to
before. A sample of `examples` entries read by hand on `tailwindcss.com`
showed the real signal this task exists for: `.border-gray-950\/5` reaching
53 real elements next to a `.prose hr:where(…)` usage in the same entry
confirmed at 0 (the entry stays `live` because another usage matches — T18's
own unanimity rule, unaffected by this task). `::part(...)` selectors
correctly report `matchCount: null` rather than a false zero, since
`cssselect2` marks them `never_matches` the same way `selector_reach` already
refuses to answer for `:hover`.

**Also surfaced in the HTML report**, not just the JSON — the "Where each
color came from" table (`emit.py`'s `renderProv`) now appends "(N matches)"
to each example row when `matchCount` is a number, verified rendering
correctly in a browser (`.old-promo-banner`-style selectors show "(0
matches)", a real selector with no captured HTML shows nothing). This was not
in the original sketch's stated diff level but is the exact gap this task's
own opening paragraph named for the report, not only the JSON, so leaving it
JSON-only would have half-finished the thing the gap analysis described.

**What this does not fix:** the same static-markup-only limit as T18 — a
`matchCount` of 0 means "not in the captured document", not "unused"; no
JavaScript runs. `MATCH_SAMPLES` and `max_len` bound the *sample* shown,
never the true `matchCount`.

Tests: `TestElementSignature` (`tests/test_dom.py` — tag/id/class formatting,
two same-selector matches staying distinguishable via the ancestor chain,
`depth` actually bounding it, and a class list long enough to trip `max_len`
actually getting truncated with the ellipsis) and `TestMatchDetail`
(`tests/test_extract.py` — two real matches counted and fully sampled, a
confirmed zero with no `matches` key, `None` on a bare `.css` input with no
captured HTML, and the sample landing at exactly `MATCH_SAMPLES` when the
real count is higher). All eight required to fail against the pre-T19 code
before being trusted, per this file's own "a test that passes before and
after tests nothing" rule — checked directly by stashing `palettekit/` and
rerunning them. The `max_len` test needed a sharper check than that alone:
stashing the whole feature makes it fail on an unrelated `ImportError`, which
doesn't prove the truncation *logic* is what the test catches — verified
separately by patching just the truncation lines out of a working
`element_signature` and confirming the test fails on the length assertion
specifically (105 chars vs the 50-char cap), not on import.

### T20 — Categorize the HTML report's palette by status, with descriptions

> **Outcome — landed 2026-08-03.** Took the first of the two sketched
> shapes: sub-group *within* each existing hue/role section by status,
> rather than an orthogonal filter axis. The filter-button shape doesn't
> give the per-status prose a location to live next to its colors, which is
> the whole point of "near where that status's colors actually are" — a
> second axis of buttons still leaves the description in a tooltip or a
> footnote.
>
> `render()` (`emit.py`) now sub-groups each `GROUP_ORDER` section's visible
> colors by `status`, in a fixed `STATUS_ORDER` (`live`, `saved`, `inert`,
> `unmatched` — README's own order), and inserts an `h3.status-heading` +
> `p.status-blurb` pair before each status's own `.grid`, sourced from new
> `emit.STATUS_TITLES`/`STATUS_BLURBS` dicts (mirroring `GROUP_TITLES`/
> `GROUP_BLURBS`) and injected the same way, via `__STATUS_TITLES__`/
> `__STATUS_BLURBS__` template placeholders.
>
> **Heading suppression has a real edge case, caught before landing rather
> than found live.** The first draft suppressed the subheadings whenever a
> section held only one status (`statusesPresent.length > 1`) — which hides
> the heading and description for a section that is entirely non-live, e.g.
> an all-`unmatched` `line` group: exactly the shape this task exists to
> explain. Fixed to suppress only when the section is purely `live`
> (`statusesPresent.length > 1 || statusesPresent[0] !== "live"`), so the
> default "rendered only" view — always live-only, since `visible()` already
> filters to it — renders exactly as before, byte-for-byte, and any section
> with even one non-live color always carries its explanation.
>
> **The footer's dense three-status sentence was cut, not left duplicated.**
> With the description sitting next to the colors it explains, repeating it
> a fourth time in a document-wide footnote was the exact anti-pattern this
> task was filed against. `renderFooter()` now only states the ground,
> where values come from, and points at the sections above; the `unmatched`
> blurb keeps invariant 27's "which this tool cannot run" hedge intact
> (`STATUS_BLURBS["unmatched"]`) since that's the one place it still lives.
>
> **Verified against `fleshandbonedesign.com.har`, not synthetically only.**
> It's the one frozen bundle whose `base` theme carries all four statuses at
> once (`live: 19, unmatched: 9, saved: 14, inert: 1`), split across three
> different hue/role groups (`surface`, `ink`/`line`, `chroma`) — so it
> exercises both the multi-status and mixed-group-membership cases in one
> report. Checked in a real browser tab, `file://`, both filter states:
> "rendered only" shows plain sections with no subheadings (unchanged from
> before this task); "everything found" shows each mixed section's LIVE /
> SAVED / INERT / UNMATCHED subheadings in that fixed order, each with its
> one-line description directly above its swatches. The reference fixture's
> own tests fixture (`tests/helpers.py FIXTURE`) independently carries all
> four statuses too, split across `surface`/`ink`/`line`/`chroma` — used for
> the new regression test rather than requiring network access.
>
> No data diff, as predicted — `to_document`'s output is unchanged; this is
> presentation only. New CSS uses existing `var(--ui-*)` tokens exclusively,
> so `test_report_theme_is_readable` needed no changes and still passes.
> 185 tests (184 + 1 new: `test_report_status_subheadings_appear_for_mixed_sections`,
> asserting the status markup and every status's blurb text land in the
> emitted HTML), `ruff` clean, 3.11–3.14 green, module/zipapp JSON identity
> reverified on `fleshandbonedesign.com.har` (`generated` excluded).

**Filed 2026-08-02, requested by the owner alongside T18's status-shape
decision. T18 has since landed** (`unmatched`, invariant 27) **— no longer
blocked.**

**The gap, verified directly in `emit.py`.** The report's swatch grid
(`render()`, `emit.py:747`) groups entries by hue/role (`GROUP_ORDER`:
ground/surface/ink/line/neutral/chroma — `emit.py:582`), each section with a
title and blurb (`GROUP_TITLES`/`GROUP_BLURBS`). Status plays no part in that
grouping. It surfaces three other ways, all secondary: a binary filter
toggle (`FILTERS`, `emit.py:700` — "rendered only" vs. "everything found"),
a small text tag on non-live swatches naming the status word (`swatch()`,
`emit.py:726-729`), and one prose sentence in the footer defining `saved`,
`inert`, and now `unmatched` for the whole document at once (`renderFooter()`,
`emit.py:867` — updated when T18 landed, still one dense sentence covering
three statuses at once). Nothing lets a reader scroll the palette and see,
section by section, *why* a given color isn't painted — they'd have to
toggle to "everything found", then read each small tag, then separately
recall which clause in the footer sentence defined it. There are now four
reasons a swatch might not be `live` (`saved`, `inert`, `unmatched`, each
meaning something different), and the tag+footer treatment does not scale to
explaining four independently-true reasons at a glance.

**Shape of the change, sketched rather than designed.** The request is
specifically to make status legible at scroll-through granularity, the same
way hue/role grouping already is — not necessarily to replace the
hue/role grouping, which answers a different, still-useful question ("what
family is this color in"). Two shapes worth weighing when this is picked up:
sub-group *within* each hue/role section by status (so "ink" shows its live
inks, then its saved inks, each under a small status-labelled subheading with
a one-line description — "rendered on the page" / "a custom property nothing
in the CSS references" / "paints nothing" / "this selector matches nothing in
the page this tool captured", the last one lifted from `renderFooter()`'s own
already-landed wording rather than redrafted); or add status as an orthogonal
second axis the existing filter toggle already gestures at, expanded from two
states (`live`/`all`) to one button per status that narrows the same grid
rather than replacing groups with statuses outright. Whichever shape, the
description text for each status should read like the per-status bullets in
`README.md`'s "Four statuses" section, not like the current footer's single
dense sentence — one short line per status, near where that status's colors
actually are, not deferred to a document-wide footnote.

**What this does not fix.** Report-only; it's a presentation change over
data `to_document` already emits (plus T18's new status field once that
lands). No new extraction, no schema change beyond whatever key T18 itself
adds — this task should not need its own `schemaVersion` bump.

**Diff level:** no data diff at all — `to_document`'s output is unchanged by
this task on its own. Verify by hand in a browser: load the report for a
site exercising all four statuses (a corpus bundle with real `saved`/`inert`
entries plus at least one T18-flagged declaration) and confirm every
category is identifiable while scrolling, with its description visible,
without opening dev tools or hovering a tooltip. Invariant 11 (report must
stay standalone, `file://`-openable) and the report-theme-readability test
apply to any new markup this adds, same as the rest of the report.

### T21 — Test a pseudo-element's base compound instead of refusing it outright

> **Outcome — landed 2026-08-02.** The reach question itself was fixed as
> filed. The blast-radius prediction below ("expect any pseudo-element
> usages on real, present selectors to move from `None` to a determinate
> answer and nothing else to move") was **falsified once, on the first
> implementation, and corrected before landing** — not merely unpredicted
> the way T23's `mdn.har` move was. Sharing `dom._compile_usable` between
> `selector_reach` (this task's own question) and `extract.consumers_of`
> (T9's real-inheritance question) let a pseudo-element consumer through to
> T9's ancestry walk, where `dom.selector_matches` — the *candidate* matcher
> T9 uses, correctly left untouched — still refuses pseudo-elements. On
> `tailwindcss.com.har` this produced a **false confirmed absence** for
> `.after\:inset-ring:after`'s `--tw-inset-ring-color`: a real, page-painted
> color dropped entirely, replacing a wrong-but-present last-wins guess with
> nothing, which is a worse answer than either the pre-T21 guess or the
> correct one. Fixed by keeping the reach question
> (`dom._compile_reachable`/`dom.reach_elements`, base-compound-aware) and
> T9's consumer question (`dom._compile_usable`/`elements_matching_wrapped`,
> unchanged, still pseudo-refusing) on two separate filters and two separate
> `extract._build` caches. See CLAUDE.md invariant 27's own T21 addendum for
> the full write-up, the corpus numbers, and the regression test
> (`test_a_pseudo_element_consumer_does_not_trigger_ancestry_override`) built
> to fail against the shared-filter draft before being trusted. With the
> split, the corpus verification below holds exactly as originally
> predicted: `None` → determinate and nothing else, on all seven frozen
> bundles, key-set identical before and after.

**Filed 2026-08-02**, found while explaining to the owner why T18/T19 report
`None`/"no basis" for some selectors — three different mechanisms produce
that answer, and this is the one that turned out not to need to.

**The gap, verified directly, not assumed.** `dom._compile_usable` (shared by
`selector_reach` and `elements_matching_wrapped`, T18/T19's own shared
filter) drops every selector branch with `sel.pseudo_element is not None`
unconditionally, lumping `.card::after` in with genuinely untestable cases
like `.card:hover`. But `cssselect2`'s compiled selector still evaluates
`.test(element)` against the *base* compound when a pseudo-element is
present — checked directly against a real tree:

```python
sel = cssselect2.compile_selector_list(".card::after")[0]
sel.pseudo_element  # "after"
sel.test(div_with_class_card)  # True
```

The library isn't refusing to answer here; the code is discarding an answer
it already has. `:hover` is `never_matches=True` — cssselect2 itself says
"this can never be true of static HTML," a real refusal. A pseudo-element
selector is a different thing: cssselect2 happily tests its base compound,
and only marks `.pseudo_element` as an annotation for the *caller* to decide
what to do with a generated box it can't itself represent as a DOM node.

**Why it matters beyond correctness-in-principle.** T18's `unmatched` status
and T19's `matchCount`/`matches` both sit on top of `_compile_usable`. A
normalize-style reset stylesheet with real `::before`/`::after` rules for
classes the page actually carries — the same shape
`parkersprouse.me.har`'s own `:where(dialog)`/`:where(fieldset)` entries are,
per invariant 27's own write-up — currently reports `matched: None` /
`matchCount: None` for any pseudo-element rule, regardless of whether the
base selector is genuinely on the page. `None` should mean "no basis to
test," and here there plainly is one.

**Shape of the change, sketched rather than designed:** have
`_compile_usable` (or a variant of it used by `selector_reach`/
`elements_matching_wrapped` specifically) keep a pseudo-element branch as
usable, testing its base compound rather than dropping it. `matched`/
`matchCount`/`matches` for a `.card::after` rule would then reflect whatever
real elements `.card` reaches — the right unit to report, since a generated
box isn't a separate node this tool could name even if it wanted to.

**What needs deciding, not just coding:** whether every pseudo-element
should be treated identically for reach purposes, or only ones that render
unconditionally (`::selection`, `::marker`, `::placeholder`) versus ones
gated on a separate `content` declaration (`::before`/`::after`, which paint
nothing without it). Leaning toward "identical" — this task asks "is the
base selector on the page," not "does this rule paint," and the second
question is explicitly out of scope for `unmatched` already (invariant 27:
`unmatched` is about DOM presence, not paint — that boundary is `inert`'s
job, for a different reason). Confirm that reading holds before
implementing rather than assuming it.

**Diff level:** same convention as T18/T19 — per-declaration `matched`/
`matchCount` diff, old vs new, across all five frozen bundles. Expect any
pseudo-element usages on real, present selectors to move from `None` to a
determinate answer and nothing else to move; `parkersprouse.me.har`'s own
reset stylesheet is the most likely site to actually exercise this.

### T22 — Read `@property` registrations (`syntax`/`inherits`/`initial-value`)

> **Outcome — landed 2026-08-03.** The "likely correct-but-inert" prediction
> below was wrong, and wrong in the informative direction: the `inherits`
> half — flagged in the filing as "hasn't been checked" — turned up a live,
> corpus-confirmed bug, not merely a completeness gap. On `ui.shadcn.com.har`,
> `--tw-ring-color`/`--tw-ring-shadow` (both registered `inherits: false`)
> were resolving through T9's ancestry walk from an unrelated ancestor
> **12–14 levels up the real DOM tree** — some other element's `.ring-*`
> utility leaking onto a descendant that carries no ring styling of its own.
> Measured directly by instrumenting `_ancestry_winners` before writing any
> fix: across all seven frozen bundles, every winning candidate resolved at
> ancestor level 0 (self) *except* these two properties on this one bundle.
> Root cause underneath it: the document-wide reset that would otherwise
> supply a same-element "initial" answer sits behind
> `*,:before,:after,::backdrop { --tw-ring-color: initial; … }`, and
> `::backdrop` is a pseudo-element `cssselect2` doesn't support —
> `compile_selector_list` raises on the *whole* comma-separated list when any
> one branch is unparseable, so the `*` branch (which would otherwise have
> matched at level 0 and stopped the walk immediately) is invisible to
> `selector_matches` too. That compile-failure detail is a separate,
> undiagnosed gap (see the new note below) — not fixed here, and not needed
> to be: restricting `inherits: false` properties to self-only lookup is the
> spec-correct fix on its own terms, and it happens to also be exactly what
> keeps this borrowed-from-nowhere ancestor value from ever being considered,
> regardless of why the level-0 default failed to answer first.
>
> **Implemented both halves the filing sketched.** `cssparse._walk` now
> registers `@property` blocks onto `Stylesheet.properties` (name →
> `(inherits, initial_value)`), kept off `sheet.declarations`/`var_refs`
> entirely (T22 is a deliberate `continue`, the same shape as the statement
> at-rule branch, invariant 18) rather than relying on the incidental "no
> selector, so `_record` drops it" behavior that made `@property` blocks
> inert before this existed. `extract.property_registrations` merges them
> across sheets in document order (last-registration-wins, matching the
> spec — `@property` carries no cascade of its own). Two consumers:
>
> - **Invariant 26's extension.** `extract._substitute_registered_initials`
>   rewrites a table entry that is literally `initial` to the property's
>   registered `initial-value`, once, before the table ever reaches
>   `resolve_vars` — `cssparse._resolve_var` needed no changes, since by the
>   time it runs the table simply no longer says `initial` for a property
>   that has a real one. The same substitution is applied a second time to
>   a T9 ancestry override's own `("value", "initial")` result, since that
>   path writes a fresh `initial` into `decl_table` independently of the
>   base table. Per-spec, this is not "use the registered value as a
>   fallback" — `initial` on a *registered* property is not
>   guaranteed-invalid at all, so `var(--x, fallback)` must ignore the
>   fallback and substitute the registered value directly, matching what
>   `_resolve_var` already does for any other concretely-stored value.
> - **T9's ancestry walk gains `non_inheriting`** (`resolve_by_ancestry`/
>   `resolve_by_ancestry_kind`/`_ancestry_winners`, default `False` so every
>   existing call and test is untouched). `_build`'s own call site sets it
>   from `properties.get(name)[0] == "false"`. When true, the walk checks
>   only the consumer element itself, never `.ancestors` — a value set on
>   the very same element still counts (self is not "past self"), only a
>   *real ancestor's* definition is excluded, matching what `inherits:
>   false` actually means.
>
> **Verified against the actual corpus, not just synthetically**, same
> convention as T18/T19/T21/T23: JSON (`generated` dropped) diffed old vs
> new across all seven frozen bundles. Five bundles carry no `@property` at
> all and were untouched by construction; `tailwindcss.com.har`,
> `ground.news.har`, `mdn.har`, `parkersprouse.me.har` and
> `pawelgrzybek.com__light_dark_example.har` are **byte-identical**. Only
> `ui.shadcn.com.har` moves, and narrowly: exactly one occurrence removed
> from each theme's merged neutral-grey bucket (light `#e5e5e5`: 157→156;
> dark `#3c3c3c`: 128→127) — the stray ring-color/ring-shadow value that used
> to leak in from the wrong ancestor. No hex added or removed, no ground
> moved, no token count changed, no status changed; only the two occurrence
> counts and their downstream `score` (invariant 2's own "treat ordering as
> a hint" territory). Exactly the shape a fix for a rare, specific
> mis-attribution should produce — a small, precise subtraction, not a
> palette reshuffle.
>
> 9 new tests (4 `TestPropertyRegistration` in `test_cssparse.py`; 3
> `TestNonInheritingAncestry` plus 2 new cases in
> `TestAncestryWiredIntoBuild`, `test_extract.py`). **8 of the 9 confirmed to
> fail against pre-task code** (checked against `8bbcbbe`, the commit before
> this landed, not merely reasoned about): the 3
> `TestPropertyRegistration` cases that read `sheet.properties` fail with a
> bare `AttributeError` (the field didn't exist yet); the 3
> `TestNonInheritingAncestry` cases fail with `TypeError` from the
> not-yet-existing `non_inheriting` parameter; the 2 end-to-end
> `TestAncestryWiredIntoBuild` cases fail with a genuine `KeyError` (the
> expected color simply isn't in the palette). **The 9th,
> `test_a_property_rule_contributes_no_declaration_or_var_ref`, passes
> against both** — checked, not assumed, after an initial write-up wrongly
> implied it had been verified alongside the other 8. Pre-task, an
> `@property` block's declarations already produced no
> `sheet.declarations`/`var_refs` entries, but incidentally: `_walk`
> recursed into the block with `selector=""`, and `_record` silently drops
> any declaration when `selector` is falsy — the same fallback invariant 18
> exploits for a statement at-rule's body. This task's own `continue`
> branch makes that explicit rather than relying on it, but the *observable*
> outcome doesn't move, so the test can't discriminate the fix. Kept anyway,
> deliberately, as a regression lock on the explicit behavior rather than a
> proof of it — not the same thing as an untested claim, but worth being
> honest about which one it is. 181 tests total, `ruff` clean, 3.11–3.14
> green.
>
> **A new, related gap surfaced and was deliberately not fixed here**:
> `cssselect2.compile_selector_list` fails the *entire* selector list when
> any one comma-separated branch is unparseable (`::backdrop` above), rather
> than compiling the parseable branches and skipping the bad one. This is
> not specific to `@property` or to T9 — `selector_matches`,
> `_compile_usable`, and `_compile_reachable` (`dom.py`) all pass a whole
> selector list to `compile_selector_list` in one call, so any one of them
> can silently lose every branch of a list over a single unsupported
> pseudo-element or pseudo-class anywhere in it. Fixing it would mean
> compiling each `split_selector_list` part independently and unioning the
> survivors — plausible, but a change to three matching call sites at once
> deserves its own blast-radius measurement rather than riding in on this
> task's diff. Unfiled as its own T-number pending that measurement; noted
> here so it isn't rediscovered from scratch.

**Filed 2026-08-02**, found the same way as T21 — explaining what "not
modelled" means for `@property` (already named in CLAUDE.md's Known Limits)
turned into checking whether any corpus site actually uses it, which nobody
had done.

**Not a hypothetical — checked directly.** `@property` appears in three of
the five frozen bundles: `ground.news.har` (135 occurrences),
`tailwindcss.com.har` (123), `ui.shadcn.com.har` (101);
`fleshandbonedesign.com.har` and `parkersprouse.me.har` have none. Sampled
one from `tailwindcss.com.har`:

```css
@property --tw-content{syntax:"*";inherits:false;initial-value:""}
```

All three sites' usage is Tailwind v4 registering its own internal custom
properties this way — the same mechanism invariant 26's `initial` handling
already has to work around (`--tw-gradient-via-stops: initial` inside a
`@layer properties` guard), from the other side: `@property` is where a
browser gets the *real* fallback value invariant 26 currently has to treat
as merely "absent."

**What this would add, in two places already built to receive it:**

- **Invariant 26's `initial` handling.** A stored value of the literal
  keyword `initial` on a custom property currently falls through to "absent"
  — `var()`'s own fallback, or nothing. With `@property` read, a registered
  property's `initial-value` is not "absent," it's a specific value a
  browser substitutes. Whether this changes anything measurable depends on
  whether any registered `initial-value` in the corpus is color-bearing —
  `--tw-content`'s own is an empty string, not a color, so this exact
  occurrence is likely a no-op.
- **T9's ancestry walk** (`resolve_by_ancestry_kind`). Real inheritance is
  the *default* for an unregistered custom property, which is what T9 built
  for. A property registered with `inherits: false` doesn't inherit at all,
  and walking real ancestors for one would be answering a question that
  doesn't apply to it. Whether any corpus property T9 currently resolves by
  ancestry is also registered non-inheriting hasn't been checked.

**This task starts with a measurement, not a parser change** — the same
"predict the blast radius before writing the code" discipline the rest of
this file uses. Before implementing: for every `@property` in the corpus,
record its `initial-value` and `inherits` flag, and check whether either one
touches a property this tool already resolves to a color, an ancestry
answer, or an `initial`-keyword fallback. If nothing color-bearing turns up
— plausible, given the one sample found is an empty string — this may be
correct-but-inert the same way T5's `calc()` evaluator's untouched branches
are, worth doing for completeness rather than for a corpus payoff.

**Diff level:** per-declaration color list, old vs new, on the three bundles
that carry `@property` at all. `fleshandbonedesign.com.har` and
`parkersprouse.me.har` should be byte-identical by construction — neither
has anything for this to read.

### T23 — Evaluate `@supports` conditions instead of reading every block as though it always applies

> **Outcome — landed 2026-08-02.** Both effects predicted at filing time were
> confirmed, plus one that wasn't: `mdn.har` also moves, for a reason that
> only turned up once a real `@supports (color: light-dark(...))` guard was
> evaluated for real.

Filed while verifying T10 against `pawelgrzybek.com`'s light/dark example:
`_walk` read every `@supports` block's contents unconditionally, `not (...)`
included, so a fallback block written for browsers that can't parse
`light-dark()` was being read by this tool too — and its plain light-only
value then won last-wins over the real `light-dark()` declaration for *both*
themes, because neither is theme-scoped and specificity ties (invariant 21).

**Full feature-query evaluation was explicitly out of scope, and still is.**
`@supports`'s grammar covers arbitrary `property: value` pairs, most of
which this tool has no grounds to judge — `background`'s a shorthand,
`filter` takes functions `color.py`'s parser was never meant to read, and
guessing "unsupported" from a failed parse would confidently flag real,
universally-supported CSS as absent. That is a worse failure than the one
being fixed: today's behaviour (read every block) never drops a real
declaration for `@supports` reasons; a careless fix could start doing that
silently, on any site.

**The shape that stays inside those limits: evaluate the boolean grammar for
real, and make a leaf declaration return `True` or `None`, never a confirmed
`False`.** `False` can only ever come from negating an already-confirmed
`True` — which is exactly `@supports not (color: light-dark(white,black))`'s
shape, and nothing else this project has evidence for.

- **The `not`/`and`/`or`/parens structure is real, hand-rolled boolean logic
  over three-valued (Kleene) results** (`_eval_supports_condition`,
  `_combine_supports`) — `None` (unknown) propagates through `and`/`or`
  exactly the way an unknown operand should: `False and unknown = False`
  regardless of the unknown side, `True or unknown = True`, and otherwise the
  result is `None`. This is real, verified logic, not a heuristic — the
  corollary's "hand-roll only what the library can't do" applies here
  because no library evaluates CSS conditionals at all.
- **`tinycss2` already groups a top-level `(...)` into one `ParenthesesBlock`
  token with nesting handled**, so — same as invariants 24/25's `resolve_vars`/
  `var()`-fallback rewrites — this needed no hand-rolled paren-depth counter.
  Walking `node.prelude`'s tokens directly and recursing into a block's
  `.content` is the whole traversal.
- **The one leaf that returns a confirmed answer**
  (`_supports_declaration`) is deliberately narrow: a custom property
  (`--x: ...`) is always `True` (CSS spec: any non-empty token stream is a
  syntactically valid custom-property value), and a property in
  `_PURE_COLOR_PROPERTIES` — the subset of `PROPERTY_ROLE` whose grammar is
  *exactly* `<color>` and nothing else (`color`, `background-color`,
  `border-color`, `fill`, …; explicitly **not** `background`, `border`,
  `box-shadow`, `filter`, `backdrop-filter` — shorthands and function-taking
  properties `parse_color` was never built to read) — is `True` when
  `color.parse_color` parses its value. Everything else, including a pure
  -color property whose value *fails* to parse (a real CSS color function
  this tool simply hasn't implemented, e.g. `color(display-p3 ...)`), is
  `None` — unknown, not unsupported. This is the same reasoning as invariant
  22's `calc()` evaluator: refuse to guess past the grammar this tool
  actually models, rather than special-case the one corpus shape.
- **A confirmed-`False` `@supports` block is skipped outright** — no
  `_record`, no `var_refs` collection — mirroring the statement-at-rule
  branch (invariant 18) rather than merely filtering declarations after
  walking them, because a real non-supporting-condition fallback block is
  inert to the browser this tool models, references and all. Anything `True`
  or `None` walks exactly as before this task existed.

**Verified against the actual corpus, not just synthetically.** All seven
frozen bundles were regenerated before/after (`generated` dropped):
`fleshandbonedesign.com.har`, `ground.news.har`, `parkersprouse.me.har`,
`tailwindcss.com.har` and `ui.shadcn.com.har` are byte-identical — none
carries an `@supports` condition on a pure-color property. Two move:

- **`pawelgrzybek.com__light_dark_example.har`** — the site this task was
  filed against. Dark theme's ground moves `#ffffff` → `#21262c`, exactly
  the value CLAUDE.md's known-limit entry predicted, and the "both themes
  have a light background" mislabelling warning disappears because the dark
  theme is now actually dark.
- **`mdn.har`** — not predicted at filing time, found only once real
  evaluation was in place. MDN's global stylesheet is compiled through a
  `light-dark()` PostCSS polyfill (`csstools`) that emits *two* blocks per
  token: `@supports (color:light-dark(red,red)) { /* the real declarations
  */ }` and `@supports not (color:light-dark(tan,tan)) { /* --csstools
  -light-dark-toggle-* fallback machinery, on a `:root *` blanket selector
  */ }`. Before this task both were read; now only the real one is.
  `declarationsScanned` drops 817 → 769 (exactly the 48 polyfill
  declarations across the stylesheet), and reordering follows from that:
  the blanket-selector polyfill was inflating `--color-*` custom-property
  occurrence counts, which is why the palette's own hex set, status counts
  (39 live / 9 unmatched / 3 saved, both before and after), ground and theme
  count are all **unchanged** — only occurrence-derived ranking and
  `examples` provenance moved, which `selector_weight`'s own "treat ordering
  as a hint" caveat already covers.

**Performance:** `tailwindcss.com.har`, the slowest bundle in the corpus,
timed identically before and after (46.4s / 46.6s, real-time — noise-level,
no `@supports` on this bundle to even exercise the new code path).

166 tests (11 new, `TestSupports` in `test_cssparse.py`), `ruff` clean,
3.11–3.14 green. The new tests were confirmed meaningful, not vacuous,
against pre-task code: the integration test asserting a confirmed-false
block's declarations never reach `sheet.declarations`/`sheet.var_refs` fails
on stashed `cssparse.py` (both the real and fallback `--bg` values are
recorded there), the same "test that passes before and after tests nothing"
discipline every other invariant in this file follows.

**What is still not covered, by design, same as before this task**:
any `@supports` condition on a non-pure-color property, or on a pure-color
property whose value uses a CSS color function this tool doesn't implement,
stays `None` and the block is read — identical to this tool's behaviour
before T23 existed. `selector(...)`/`font-tech(...)` feature functions are
likewise `None`. This is a narrowing of the general problem to the one shape
with corpus evidence, not a general `@supports` evaluator, and the
"materially larger problem" framing at filing time still describes the
general case accurately.

**Diff level:** JSON (`generated` dropped) across all seven frozen bundles.

### T24 — A "Caveats" section for structurally unconfirmable colors

> **Outcome — landed 2026-08-03.** Landed close to the sketch below, with
> the "leaning toward" calls resolved rather than left open.
>
> `dom.untestable_reason(selector)` is the sibling function to
> `selector_reach` the sketch called for — an enum-shaped `str`, not a
> fourth value squeezed into `bool | None`. It only distinguishes
> `"dynamicState"` from `"uncompilable"`, exactly the two causes the filing
> named as this module's own; it is only ever called once `selector_reach`
> has already answered `None`, and does not re-derive that determination
> itself. "No captured HTML at all" — the third cause the filing's own
> classification (reason 1) set aside as uninteresting — is read directly
> off `wrapped_root is None` in `extract._build`, never handed to
> `dom.untestable_reason`, which has no way to know it.
>
> **Threading matched the sketch exactly**: `Usage.reach_reason` (`None`
> whenever `matched` is determinate), and `Entry.all_dynamic_only` checking
> `u.reach_reason == "dynamicState"` unanimously — not "was `matched`
> `None`", which would have re-admitted reasons 1 and 2 the filing's own
> "dishonest" line rejected.
>
> **JSON went with the `examples[].reason` extension the sketch leaned
> toward**, plus an entry-level `dynamicOnly: True` flag (only present when
> true) rather than making the report recompute unanimity from raw
> examples — a JSON consumer gets the same shortcut. Both are additive; no
> `schemaVersion` bump.
>
> **Report placement matched the sketch**: an always-present `#caveats`
> section, generic copy regardless of whether the current theme has any
> affected entries, placed near the footer rather than inside "Where each
> color came from". Per-theme rather than one-time like `#warnings` —
> `dynamicOnly` is a per-color flag, so `renderCaveats()` reruns inside
> `render()` on every theme/filter/format switch, the same lifecycle
> `renderFooter()` already has.
>
> **Corpus counts landed on exactly the filing's own prediction**: 9
> (`ui.shadcn.com` — 3 light + 6 dark, verified per-theme), 13
> (`ground.news`), 7 (`tailwindcss.com`), 0 on both hand-written sites. All
> seven frozen bundles are byte-identical once `dynamicOnly` and
> `examples[].reason` are stripped — no ground, status, hex, or ranking
> moved, confirming this is purely additive as designed. Browser-verified
> on `ui.shadcn.com` (both themes, via the toggle) and `parkersprouse.me`
> (zero-count case, generic copy only, no list).
>
> **Two corrections found in review, before landing, neither reachable by
> the corpus counts above.** `describe()`'s first draft set `dynamicOnly`
> from `entry.all_dynamic_only` alone, with no status gate — but
> `_status_for`'s `saved`/`inert` priority (invariant 27's own note) can
> still land on an entry every one of whose usages is dynamic-state-only, a
> custom property declared only inside a `:hover` rule and referenced
> nowhere being the concrete shape. `all_unmatched` avoids this because
> `_status_for` only ever consults it *after* ruling out `saved`/`inert` —
> position does the gating there; `all_dynamic_only` had no equivalent
> position, being read straight into `describe()`. Not present on any of
> the seven frozen bundles (checked directly, not assumed — every flagged
> entry across all three non-zero bundles came back `live`), so the corpus
> diff could not have caught it; fixed by gating on `entry.status == "live"`
> at the one call site, and it is now the exact discriminator
> `test_a_saved_entry_is_not_flagged_dynamic_only` tests, required to fail
> against the ungated version before being trusted (it does — a `saved`
> entry carried `dynamicOnly: true`). Second, the report's own subtitle read
> "N colors **confirmed painted** on the page", which is invariant 27's own
> previously-fixed overclaim recurring in a new spot: a live entry sourced
> entirely from a dynamic-state selector is exactly what this task says is
> *not* confirmed. Dropped "confirmed" rather than hedging it inline, the
> same precedent invariant 27's own subtitle fix set for `unmatched`.
>
> One correction found while writing the tests: `:is( , .x)` — the
> selector `test_a_selector_that_will_not_compile_is_none_not_false`
> (invariant 27/T18) uses as its "won't compile" example — does not
> actually fail to compile. Verified directly against `cssselect2`: an
> empty branch inside `:is()` compiles to a selector `cssselect2` itself
> marks `never_matches`, not a `SelectorError`. That test's own name
> predates this task and is still accurate for `selector_reach` (`None`
> either way), but it would have been the wrong fixture for
> `untestable_reason`'s "uncompilable" branch specifically — `::backdrop`
> (T25's own example, a real pseudo-element `cssselect2` doesn't implement)
> is what genuinely raises, and is what the new tests use instead.
>
> Tests: `TestUntestableReason` (`tests/test_dom.py`) and `TestDynamicOnly`
> (`tests/test_extract.py`), the latter end-to-end through `extract()` —
> a hover-only color flagged, one resting usage clearing the flag, a plain
> matching color never flagged, an uncompilable selector and a
> no-captured-HTML input both correctly *not* flagged despite also being
> `matched is None`, and a `saved` entry (the status-gate correction above)
> also correctly not flagged despite `all_dynamic_only` being structurally
> true for it. All required to fail against the pre-fix
> implementation before being trusted (`git stash push palettekit/`,
> the T25/T22 discipline), which they did — four of six errored on a
> missing `reason`/`dynamicOnly` key entirely.

**Filed 2026-08-02**, requested by the owner after the same conversation
that filed T21/T22 — explaining the three different shapes of "untestable"
(a dynamic pseudo-class, a JS-hydration gap, a pseudo-element the code
discards unnecessarily) surfaced one this project hadn't named anywhere:
**a `:hover`/`:focus`-style rule is not merely unverified today, it can
never be verified by any capture, however complete.** T21 is a real gap
(the library already answers; the code discards it). T22 is a real gap (the
CSS is right there, unread). The "Potential future expansion" section above
is a deliberate non-goal that more engineering — a browser engine — could
still close. This is none of those: no markup capture, however complete,
resolves an interaction state, because the state doesn't exist until a user
is actually interacting. That is a different *kind* of gap from everything
else filed in this document, and today it produces zero signal — a `live`
entry sourced entirely from `.foo:hover` reads identically to one painted at
rest.

**Measured on the real corpus before writing anything, not assumed.** Using
`dom`'s own classification (a selector is `dynamic-only` when every branch
`cssselect2` reports `never_matches` and none carries a pseudo-element —
kept deliberately distinct from "uncompilable," below) against every
`Usage` on a real `extract()` run:

| Bundle | Entries entirely `dynamic-only`-sourced |
|---|---:|
| `ui.shadcn.com.har` | 9 |
| `ground.news.har` | 13 |
| `tailwindcss.com.har` | 7 |
| `fleshandbonedesign.com.har` | 0 |
| `parkersprouse.me.har` | 0 |

Sample: ui.shadcn.com's `#e7000b` is reported plain `live` with its only
usage being `.hover\:bg-destructive\/80:hover` — a red the reader has no way
to know is a *maybe*, not a *definitely*. The zero counts on both
hand-written sites aren't a coincidence worth ignoring: utility-class
frameworks generate a `:hover`/`:focus` variant for nearly every color
utility they ship, so this is structurally a framework-heavy-site problem
more than a general one — worth knowing before assuming every site needs
the caveat rendered.

**Deliberately narrower than "everything `matched is None`."** `Usage.matched
= None` today conflates three causes this task must *not* treat alike:

1. No captured HTML at all (a bare `.css` input) — uninteresting here; there
   is nothing this section could single out, the whole document is
   unconfirmed.
2. An uncompilable selector — `cssselect2` doesn't recognise it (a
   vendor-prefixed pseudo-class) or `_is_blanket`-shaped constructs like
   `*,:before,:after,::backdrop`. This is a **library/parser coverage**
   question, the same flavor of gap as T21, not a structural impossibility —
   a different selector engine might answer it. Corpus-common (106–187
   occurrences per major bundle, measured alongside the table above) but out
   of scope for this task specifically.
3. A selector every one of whose branches is a dynamic pseudo-class
   (`cssselect2`'s own `never_matches`) — the one this task is about.

Lumping (2) into "permanently unknowable" would be dishonest — T21's own
finding is that some of what looks untestable today is actually just
undertested. This task's classification has to keep that line intact, not
blur it for the sake of one simpler caveat.

**Shape of the change, sketched rather than designed.**

- **Data.** `dom.py` needs a function distinguishing "dynamic-only" from
  "uncompilable" from plain "no basis" — `_compile_usable`'s current `None`
  return doesn't carry a reason. Likely a sibling to `selector_reach`
  returning an enum/reason rather than reusing its boolean-ish tri-state,
  since a fourth outcome squeezed into a `bool | None` return is exactly the
  kind of collapsing invariant 27's own history (T18's own corpus
  investigation) warns against.
- **Threading.** `Usage` likely gains a marker for its own selector's
  classification (mirroring `match_count`/`match_samples`'s T19 precedent
  rather than inventing a new shape); `Entry` gains an `all_dynamic_only`-
  style unanimity check, the exact same pattern `all_unmatched` (invariant
  27) already established: *every* usage has to be dynamic-only for the
  color's `live` status to be entirely resting on unconfirmable ground — one
  ordinary matching usage alongside a `:hover` one means the color is
  genuinely painted regardless, and no caveat is warranted for that entry.
- **JSON.** Leaning toward extending T19's existing `examples[]` shape
  rather than a parallel mechanism — `matchCount: null` already means "no
  basis"; a `reason` field (`"dynamicState" | "uncompilable" |
  "noCapturedHtml"`) turns that null into a specific, additive answer
  instead of adding a whole new key namespace. Worth deciding against the
  alternative (a dedicated entry-level flag) once this is picked up, not
  now.
- **Report.** A new, **always-present** section — unlike the per-site
  `warnings` box (`emit.py`'s `#warnings`, only rendered when
  `doc.warnings.length`), this should explain the *category* generically
  even on a site that doesn't trigger it, the same way `renderFooter()`'s
  static status vocabulary already explains `saved`/`inert`/`unmatched`
  regardless of which ones a given palette actually has. Then, when the
  current site does have `all_dynamic_only` entries, name them specifically
  — mirroring `unmatched`'s own precedent of naming affected entries rather
  than only gesturing at a global disclaimer. Placement: near the footer/
  `#warnings` area, not inside the "Where each color came from" `<details>`
  (T19's table already shows per-example match counts; a reader scanning
  live swatches for outright guarantees is a different use case than a
  reader auditing provenance).

**What this does not fix.** No status or ranking changes — a dynamic-only
entry stays `live`, correctly, per invariant 27's own "unconfirmed is not
the same as absent" reasoning; this task is purely a transparency addition
on top of an already-correct classification. Additive JSON only, no
`schemaVersion` bump, same promise as T18/T19.

**Diff level:** additive JSON key-set diff across all five frozen bundles,
confirming the per-bundle `all_dynamic_only` entry counts land on exactly
9/13/7/0/0 (the table above) — a number this task can be checked against
before it's trusted, the same way T19's own corpus numbers were pinned
before landing. Browser verification of the new section on a bundle with a
non-zero count (`ui.shadcn.com`) and one with zero (`parkersprouse.me`), to
confirm the generic explanation still renders when nothing site-specific
does.

### T25 — A comma-separated selector list loses every branch to one bad one

> **Outcome — landed 2026-08-03.** Fixed as sketched: `split_selector_list`
> each list, `compile_selector_list` each branch on its own inside a
> `try`/`except`, union the survivors (`dom._compile_selector_parts`,
> `@lru_cache`d and shared by all three named call sites). One prediction in
> the filing did not hold: `ui.shadcn.com.har`'s `--tw-ring-color`/
> `--tw-ring-shadow` were expected to "move again, this time via the root
> cause" and instead came back **byte-identical** — T22's `non_inheriting`
> flag already stops the ancestry walk for those two specific properties
> independently of this bug, so the compile fix has nothing left to change
> there. `ground.news.har` moves only in reach metadata (`matchCount`/
> `matches` on one example, `None` → a real count against the whole
> document) with no color change. Four of seven bundles — everything
> without the `::backdrop`-shaped reset selector — are byte-identical.
>
> `tailwindcss.com.har` is the real movement, and the mechanism was traced
> to one declaration rather than inferred from the palette diff, after an
> initial write-up of this outcome got the causal story wrong by reading a
> *positional* list diff instead of the keyed one — caught before landing,
> not after. Every `.shadow-{color}\/{opacity}` utility (and its
> `inset-shadow-`/`drop-shadow-`/`text-shadow-` siblings) bakes its own
> opacity suffix into an inner `color-mix()` and separately multiplies by
> `var(--tw-shadow-alpha)`, an `@property`-registered (`inherits: false`,
> `initial-value: 100%`) scaling factor the reset sets back to `100%` on
> every element via the same broken `*,:before,:after,::backdrop` selector.
> Pre-fix, that same-element default was invisible, so T9's ancestry walk
> confirmed `"absent"` — discarding even the legitimate off-page last-wins
> fallback `build_var_table` would otherwise have supplied — and the
> unresolved `var()` with no written fallback left `color-mix()`'s own
> missing-percentage default rule to produce alpha `0.25`, an accident of
> CSS fallback grammar unrelated to the utility's actual opacity suffix.
> Post-fix it resolves to the reset's literal `100%`, and the outer mix
> collapses to the inner one unchanged (invariant 22's zero-alpha
> shortcut) — alpha `0.5`, exactly what a `\/50` utility promises. The four
> hexes that disappear from the palette (`#e4a340` light; `#21274d`,
> `#33244d`, `#411e3b` dark) were checked individually: all four are
> `--tw-shadow-color` at the wrong-alpha `0.25`, not a real rendered color.
> `matches_page_element` and `selector_specificity` were deliberately left
> unfixed, per the filing's own scope, but the filing's assumption that
> neither call site's answer would move for the known selector was only
> half right: `selector_specificity` *would* move (`:before`'s specificity
> is `(0, 0, 1)`, not `(0, 0, 0)` — checked directly, not assumed, before
> writing that down) and feeds `_cascade_key` unmeasured, so it stays out
> of scope for its own task rather than on the strength of a false
> "changes nothing" claim. Full write-up, corpus numbers, and the three
> regression tests (each checked to fail against the pre-fix
> implementation) are in CLAUDE.md's "Known limits" section under this
> task's own former entry there.

**Filed 2026-08-03**, found while diagnosing T22's `--tw-ring-color`/
`--tw-ring-shadow` bug — the false-confirmed-ancestor value was only
possible because the same-element default that should have preempted it
was invisible, and the reason it was invisible is this task.

**The gap, verified directly.** `cssselect2.compile_selector_list` parses a
whole comma-separated selector list in one call and raises if *any* branch
is unparseable — it does not compile the good branches and skip the bad
one:

```python
>>> cssselect2.compile_selector_list("*,:before,:after,::backdrop")
cssselect2.parser.SelectorError: Expected a supported pseudo-element, got backdrop
```

`::backdrop` is a real, valid CSS pseudo-element `cssselect2` simply
doesn't implement. Three call sites in `dom.py` — `selector_matches`,
`_compile_usable`, `_compile_reachable` — each pass a whole selector-list
string to `compile_selector_list` in one call and catch the exception by
returning "no answer" (`None`, or `[]` downstream) for the *entire* list,
including branches like the leading `*` that would compile fine on their
own. This is exactly `split_selector_list`'s own reason for existing
(invariant 17) — a selector list where one part is malformed — except none
of these three call sites uses it before compiling.

**Why it matters beyond this one selector.** Tailwind v4's own
`@layer properties` reset opens with
`*,:before,:after,::backdrop { … : initial; … }` on every corpus bundle
that carries `@property` (`ground.news.har`, `tailwindcss.com.har`,
`ui.shadcn.com.har` — T22's own measurement). On `ui.shadcn.com.har` this
selector's failure to compile is *why* `--tw-ring-color`/`--tw-ring-shadow`
resolved from an unrelated ancestor 12–14 levels up instead of stopping at
the consumer's own element: the `*` branch that should have answered
"initial" there, immediately, was never considered at all. T22's own fix
(a `non_inheriting` flag that keeps the ancestry walk from crossing into an
ancestor for a non-inheriting property) happens to prevent this *specific*
symptom without touching the underlying compile failure — so the same class
of bug remains possible anywhere a selector list mixes a good branch with
one `cssselect2` can't parse, on any of the three call sites above, for any
property.

**Not filed as urgent — no second corpus instance found yet.** The only
confirmed occurrence is the one T22 diagnosed. Whether it's common depends
on how often real stylesheets pair a broad selector (`*`, a class) with an
unsupported pseudo-element or pseudo-class in the same comma list;
Tailwind's own reset is the one shape known to do it, and it's now handled
correctly for the one property pair the corpus exercises, via T22's
unrelated fix.

**Shape of the change, sketched rather than designed.** All three call
sites already have `split_selector_list` available (`cssparse.py`) for
exactly this shape. The fix is mechanical in outline — split the selector
list first, `compile_selector_list` (or a single-selector compile) each
part independently inside a `try`/`except`, and union the survivors — but
touches three matching call sites at once, each with its own contract
(`selector_matches` returns a specificity; `_compile_usable`/
`_compile_reachable` return compiled-selector lists with different
pseudo-element filtering, per T21's own hard-won distinction between the
two). A change here risks re-merging exactly the filter T21 had to split
apart, so it needs the same "predict the blast radius before writing the
code" discipline as every other selector-matching change in this file, not
a quick patch.

**Diff level:** same convention as T21/T22 — per-declaration `matched`/
`matchCount`/ancestry-resolved-value diff, old vs new, across all seven
frozen bundles. Expect `ui.shadcn.com.har`'s `--tw-ring-color`/
`--tw-ring-shadow` entries to move again (this time via the root cause
rather than T22's workaround) and predict everything else stays put before
trusting a byte-identical palette diff — the same shape T22 itself just
demonstrated.

### T10 — Read `color-scheme` to confirm a `light-dark()` site is two-themed

> **Outcome — landed 2026-08-02.** The counter-example this task was waiting
> on turned up: `pawelgrzybek.com`'s light/dark example, captured as
> `pawelgrzybek.com__light_dark_example.har` (gitignored, same as every other
> `.har` but `parkersprouse.me.har` — not a second `.gitignore` exception,
> that stays an owner call per T14). It writes `light-dark()` twenty-four
> times and confirms both branches with `html { color-scheme:light dark }`,
> so it is the positive control this task needed, not the negative one — see
> below for how the gate was actually verified.

Invariant 23 says a site writing `light-dark()` ships both themes "by
definition", and flags its own overreach: `light-dark()` resolves against the
**used** `color-scheme`, whose initial value is `normal` — light. A page that
writes `light-dark()` and never declares `color-scheme: light dark` renders the
light branch whatever the OS says, and calling it two-themed is wrong.

~~The tool cannot currently tell: `color-scheme` is neither a custom property
nor in `PROPERTY_ROLE`, so `_record` drops it and it never reaches a
`Declaration`.~~ **No longer true.** `cssparse._record` now special-cases
`color-scheme` through its filter — not into `PROPERTY_ROLE` (it carries no
color, so `Declaration.role` falls through to `"other"`, which the main
color-scan loop in `extract._build` and `_triplet_warning` already knew to
skip) but far enough to reach `sheet.declarations`, where the same cascade
machinery every page-reaching declaration gets can rank it.

**Two published stats diverge here, and only one should.** `stats.sources[].
declarations` (`len(sheet.declarations)`) is a raw count of everything
`_record` kept, and now honestly includes `color-scheme` — moved on the
corpus (`tailwindcss.com.har`, +9 in both themes and the top-level mirror;
its reset layer writes `color-scheme` a handful of times, unscoped). `stats.
declarationsScanned` (`extract._build`'s own `n_decls`) is meant to answer
"how many declarations were examined for color", so `_build`'s main loop
skips `d.role == "other"` before incrementing it — verified: `tailwindcss.
com.har`'s `declarationsScanned` is unchanged, and the full corpus diff
below (all five frozen bundles) shows exactly that one field moving,
nowhere else.

`extract._page_color_scheme` resolves the winning `color-scheme` value the
same way `build_var_table` resolves a custom property (invariant 19's
`_page_specificity` + `_cascade_key`), for one ordinary property instead of
the whole custom-property population, and deliberately unscoped-only — a
`color-scheme` written *inside* a theme scope is a shape no corpus site has
shown and is left for a future counter-example, the same way the rest of
this task was. `extract._scheme_keywords` reads the resolved value's
whitespace-separated keywords (`only`/custom idents ignored, order-free).

`extract._scopes_present` gates its `light-dark()` → `{"light","dark"}`
registration on `{"light","dark"} <= scheme_keywords`. When it isn't
confirmed, `light-dark()` colors still enter the palette — through
`extract._build`'s `appearance = scope or default_appearance` — reading
whichever single branch the page's own `color-scheme` actually selects:
`"dark"` if it resolves to `dark` alone, `"light"` for `normal`, absence, or
anything else. `default_appearance` is computed once in `extract()`,
unconditionally (even under `--no-themes`, which never calls
`_scopes_present` at all but still has to pick a branch), and threaded into
every `_build` call.

**Verified the gate is actually exercised, not just passing by accident,**
by stripping `color-scheme:light dark;` from a copy of the pawelgrzybek HAR
and re-running: two themes collapse to one. Restored, it's two again. The
positive corpus file alone couldn't have shown that — it only proves the
gate doesn't *break* a real two-themed site, which is a different claim.

**MDN is the site this gate could have broken, and it was checked directly
rather than inferred from its declaration count.** A live fetch of
`https://developer.mozilla.org` after the gate landed still comes back
`two themes: base (light, ground #ffffff), dark (dark, ground #18191b)` —
the exact grounds the breadth-check table already recorded, unmoved.
`mdn.har`, added the same day, is a frozen local capture of that same fetch
and reproduces it exactly, so this no longer needs network access to
reverify — see the corpus note above T10's diff level and `CLAUDE.md`'s
`.gitignore` write-up.

**Diffed at the JSON level (`generated` dropped) against all five frozen
bundles**, old implementation against new: four are byte-identical
(`fleshandbonedesign.com.har`, `ground.news.har`, `parkersprouse.me.har`,
`ui.shadcn.com.har` — none carries a `color-scheme` declaration at all).
`tailwindcss.com.har` moves in exactly the one field the stats note above
predicts (`sources[].declarations`, +9, both themes and the top-level
mirror) and nowhere else — no ground, no token, no `declarationsScanned`.
Module, console script and zipapp were also checked against each other on
the pawelgrzybek bundle and are identical.

**The negative branch this task exists for has no corpus site**, so its
tests (`tests/test_color.py`, `TestLightDarkNeedsColorScheme`) are synthetic
— a minimal `light-dark()` page with `color-scheme` absent, `normal`, `dark`
alone, `light dark`, and `dark light` (order shouldn't matter). Each was
run against the pre-T10 implementation (`git stash` on `cssparse.py`/
`extract.py` only, tests kept) and required to fail there before being
trusted, per this file's own "a test that passes before and after tests
nothing" rule — the three negative cases did (old code always registered
both scopes for any `light-dark()` regardless of `color-scheme`), and the
two positive cases (already two-themed) passed both before and after, as
they should.

`TestLightDark`'s own fixture (`tests/test_color.py`) now declares
`color-scheme: light dark` too — without T10 it didn't need to, but leaving
it out post-T10 would have made that fixture accidentally exercise the
*unconfirmed* path while asserting the *confirmed* one's outcome, which is
exactly the kind of test that passes for the wrong reason.

**A real bug surfaced while verifying the positive corpus file, and it is
not this task's to fix.** The dark theme's reported ground on
`pawelgrzybek.com__light_dark_example.har` is `#ffffff` — wrong; the page
paints `hsl(210 15% 15%)`, roughly `#21262c`, which does show up ranked in
the dark palette just not chosen as ground. Reproduced identically on
stashed pre-T10 code, so it predates this task. Cause, traced by hand: the
stylesheet's `@supports not (color: light-dark(white,black)) { :root {
--color-background: hsl(255 0% 100%); … } }` fallback block — meant only for
browsers that can't parse `light-dark()` — sits *after* the real `:root`
block in document order. This tool does not evaluate `@supports` conditions
(no corpus site needed it to before now), so the fallback's plain light-only
value reaches `build_var_table` as just another unscoped `:root`
declaration and wins last-wins over the `light-dark()` one, for **both**
themes, because neither is theme-scoped and specificity ties. Filed as a new
known limit in `CLAUDE.md` rather than fixed here — `@supports` evaluation
is a different, larger problem (parsing and evaluating a boolean feature
query) than anything this task's diff level covers.

**Diff level:** theme count and ids per site.

---

## Repo and process

Moved here from `CLAUDE.md`'s Migration TODO, which now points at this section.

### T11 — CI — decided against 2026-08-01, won't do

**Decided: this project does not get a CI pipeline.** It's a solo,
unpublished tool, and a GitHub Actions workflow is a maintenance surface
(matrix definitions, action-version pin drift, a second place secrets and
permissions could go wrong) that buys back a check already cheap to run by
hand. The owner made this call explicitly, recorded here as `[x]` rather
than left `[ ]`, so a future session doesn't re-open it as an oversight.

**What this does not undo.** The JSON-identity check T11 would have automated
is still real and still worth running — it's what would have caught T1's
stale artifact — it just stays a manual step, same as the
neither-dependency-installed interpreter check already is:

```bash
python3 build.py
# then diff to_document() output (generated dropped) between
# python3 -m palettekit, the installed `palettekit` script, and
# python3 palettekit.pyz
```

`CLAUDE.md`'s "Rebuild the zipapp before a work session is finished" section
carries this as the standing manual replacement for what would have been
T11's CI job.

**What was planned, before the decision, kept for context rather than
deleted:** run the suite on 3.11–3.14 (per T2), `ruff check`, and assert
that the package, the zipapp and the installed console script produce
identical JSON for the same input. `python3 build.py` (T12) calls
`zipapp.create_archive`, which embeds each entry's mtime, so the comparison
was always going to be JSON output, never archive bytes — that part of the
design stands regardless of whether it runs in CI or by hand.

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

### T13 — Move `test_palettekit.py` into `tests/` and split by module — landed 2026-07-27

1,595 lines and fourteen `TestCase` classes in one file by the time this
landed (it grew from the 1,272 this task was filed against). Mechanical, and
worth doing before the suite grew further.

**Split one file per `palettekit/` module**, mirroring the layout table at
the top of `CLAUDE.md`:

| File | Classes moved in |
|---|---|
| `tests/test_color.py` | `TestParsing`, `TestColorMaths`, `TestColorMix`, `TestLightDark` |
| `tests/test_cssparse.py` | `TestCss`, `TestThemeScopes` |
| `tests/test_dom.py` | `TestPageElement` |
| `tests/test_extract.py` | `TestMerging`, `TestUtilityGround`, `TestCascade`, `TestThemes`, `TestChannelTriplets` |
| `tests/test_emit.py` | `TestEndToEnd` |
| `tests/test_sources.py` | `TestBadInput` |
| `tests/test_packaging.py` | `TestPackaging` |

No `images.py` file, since nothing tests it yet.

**Not a 1:1 mapping for every class, and that's a judgment call rather than
an oversight.** A few classes exercise more than one module through the full
`sources.load_any → extract.extract → emit.to_document` pipeline
(`write_fixture`), so the split went by which module's *behavior* each class
is actually asserting, not which module its first import happens to touch.
`TestCascade` calls `parse_stylesheet`/`layer_order` directly for some
methods but is fundamentally testing `extract.detect_ground`'s cascade key
(invariant 21) via `ground_of`, so it went to `test_extract.py`, not
`test_cssparse.py`. `TestChannelTriplets` similarly went to `test_extract.py`
because three of its five methods assert on `pal.warnings`
(`extract._triplet_warning`), even though two of them call `find_colors`/
`resolve_vars` directly. `TestEndToEnd` went to `test_emit.py` rather than
`test_extract.py` because its assertions are dominated by document-shape
checks (`schemaVersion`, JSON round-trip, standalone HTML, report-theme
contrast) — `emit.py`'s own contract — even though it builds its fixture
through `extract.extract`.

**Shared fixtures moved to `tests/helpers.py`**: `write_fixture` and the
four HTML constants (`FIXTURE`, `UTILITY_GROUND`, `MEDIA_THEMES`,
`CLASS_THEMES`) that more than one of the split files needs. `tests/` is a
real package (`tests/__init__.py`), so each file imports what it needs with
`from .helpers import ...` rather than a `sys.path` hack.

**Verified the count didn't drift, not just that everything still passes**:
`grep -oh "    def test_[a-zA-Z0-9_]*"` against the old file and the new
ones, sorted and diffed, came back identical — all 113 methods, none
renamed, none dropped, before deleting the original. Names alone don't prove
bodies survived a hand-retyped move, so followed up with a structural diff —
`ast.unparse` on every `ClassDef` in the old file against the same class
wherever it landed in the new package, which normalises formatting so
re-wrapping a line doesn't read as a change. Exactly two classes differ, both
deliberate:

- `TestEndToEnd.test_html_report_is_standalone_and_valid` lost a vacuous
  `self.assertNotIn("__", ... if False else "")` and the local `import re`
  shadowing the module-level one above it. The assertion always checked
  membership in the literal empty string, so it could never fail regardless
  of `html`'s content — dead weight from some earlier debugging pass, not a
  behavior this move needs to preserve.
- `TestPackaging.test_pyproject_floor_matches_python_floor`'s
  `Path(__file__).parent` became `.parent.parent` — forced by `tests/` sitting
  one directory below the repo root now, not a discretionary edit. Breaks
  silently (wrong path, `FileNotFoundError` before it gets there) if a later
  reorganisation adds another directory level and this doesn't get updated
  alongside it.

Every other class's source is byte-for-byte identical to what
`test_palettekit.py` held at `HEAD` before this task.

**Both existing entry points still work, deliberately, per the
`[tool.pytest.ini_options]` comment this task had to update rather than
break**: `python3 -m unittest discover` (`tests/__init__.py` makes discovery
find the package without an explicit `-t`) and `pytest` (`testpaths` in
`pyproject.toml` moved from `["."]` to `["tests"]`). Both were run and both
reported 113 passed. The stdlib path matters on its own: it's what keeps the
suite runnable with no install beyond the two runtime dependencies, per
`README.md`'s Tests section — reverified across the full floor matrix,
3.11 through 3.14, via `uv run --no-project` with only `tinycss2`/
`cssselect2` supplied.

**Two other places quietly hardcoded the old single-file name and needed
updating alongside it**: `pyproject.toml`'s `[tool.ruff.lint.per-file-ignores]`
(`"test_palettekit.py"` → `"tests/*.py"`, the long color-literal/selector
`E501` exemption) and `[tool.hatch.build.targets.sdist]`'s `include` list
(`"/test_palettekit.py"` → `"/tests"`). Confirmed with `pyproject-build
--sdist` (not `python -m build` — a repo-root `build.py` shadows the
installed `build` package under `-m` because `-m` prepends the cwd to
`sys.path`, a pre-existing quirk this task didn't introduce and isn't in
scope to fix) that the sdist tarball now ships the whole `tests/` package
rather than one file.

`README.md`'s Tests section and `CLAUDE.md`'s Commands block and floor-matrix
loop were updated to the new invocation and the current test count (101 →
113, grown across T5 through T15 since the count in `CLAUDE.md` was last
touched).

### T14 — Fixture corpus of small HTML files per site archetype

> **Outcome — closed 2026-08-03, owner decision: satisfied by what's
> currently delivered, not by finishing the scope below.** Nothing new was
> built for this closure; it accepts the state this entry already
> describes as of 2026-08-02 as good enough to stop tracking as open work.
>
> What that state is, plainly: one committed, regenerable, byte-identical
> -verified fixture (`parkersprouse.me.har` + `example/`, landed
> 2026-07-27) — a real anchor in place of the "a fresh clone can regenerate
> nothing" gap that made this task urgent when filed. Two more corpus HARs
> (`mdn.har`, `pawelgrzybek.com__light_dark_example.har`) exist locally and
> are exercised by name throughout `CLAUDE.md` (T10, T23), but neither is
> committed — same gitignored, non-regenerable-from-a-fresh-clone status as
> the reference fixture and the four breadth-check bundles.
>
> **What this closure does not claim**: the small per-archetype corpus
> (framework-heavy, page-builder, dark, light, CSS-variable-driven) this
> task's title names was never built, and the parser-regression weakness
> this entry's own second paragraph describes — the reference fixture is
> single-theme, hand-written CSS, and the pre-`tinycss2` parser reproduces
> every one of its anchors exactly, so it cannot by itself catch a parser
> regression — is still real and still uncovered by anything a fresh clone
> can run offline. The breadth check (`CLAUDE.md`'s own section) remains
> the thing that actually catches that class of bug, and it still needs
> either network access or one of the gitignored local HARs.
>
> File a fresh task rather than reopening this one if that gap becomes the
> thing blocking a specific piece of work, rather than a standing "should
> do this eventually" line with nothing left waiting on it.

Framework-heavy, page-builder, dark, light, CSS-variable-driven.

~~Still urgent~~ **— closed rather than urgent, per the Outcome above.** No
longer true that it's the item that unblocks checking every other one — T11
(the CI job that would have used a regenerable fixture) is decided against,
so there was no other task left waiting on this by the time it closed.
`.gitignore` carries both `*.har` and `palettes`, so ~~a fresh clone can
regenerate nothing~~ **as of 2026-08-01, that's no longer quite right**:
not the reference fixture, not the breadth check, ~~not the `example/`
directory `README.md` promises~~ **— that one's done.** `12a6ac5` ("Added
example output and updated README") committed `parkersprouse.me.har` (via a
`!parkersprouse.me.har` exception carved into `.gitignore`'s `*.har` rule)
alongside the `example/` directory it produces. Regenerated from the
committed HAR and diffed against the committed JSON with `generated`
dropped: **byte-identical.** The reference fixture
(`fleshandbonedesign.com.har`) and the four breadth-check bundles
(`ground.news`, `tailwindcss.com`, `ui.shadcn.com`, plus
fleshandbonedesign.com again) are still gitignored with no exception, so a
fresh clone still can't regenerate either of those. Small committed fixtures
remain the fix that doesn't mean committing an 11 MB HAR for those two.

It also addresses a weakness found this session: the reference fixture is a
single-theme, hand-written-CSS site, and the **pre-`tinycss2` parser reproduces
all six of its anchors exactly**. It cannot detect a parser regression. The
breadth check can, and the breadth check needs network and frozen bundles —
committed fixtures are what make that offline and reviewable. `parkersprouse.me`
doesn't substitute for this: it's one more real site, not the small
per-archetype set this task asks for, and it's a single theme like the
reference fixture already is.

**Two more local, gitignored HARs joined 2026-08-02, T10's own corpus:**
`mdn.har` (a frozen capture of the `developer.mozilla.org` breadth-check row,
reproducing its live `#ffffff` / `#18191b` two-theme result exactly — see
T10's own entry) and `pawelgrzybek.com__light_dark_example.har` (the site
that finally exercises `light-dark()` confirmed by `color-scheme`). Neither
gets a `.gitignore` exception, same untracked treatment as the rest of this
corpus — and, per the Outcome above, that stays the state rather than a gap
this task will still come back and fix.

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
