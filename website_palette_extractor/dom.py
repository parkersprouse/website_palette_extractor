"""The document's own elements, and which selectors reach them.

Ground detection has to know which rules actually land on the element the page
is painted on, and a utility framework states that on the element rather than
in the stylesheet. ground.news writes `<body class="… bg-light-primary
dark:bg-dark-primary …">`, and those two utilities beat the `body {
background-color: var(--background) }` rule in the site's own CSS — so the
palette's ground is `#eeefe9`/`#262626`, not the `#ffffff`/`#0a0a0a` that
`--background` resolves to.

Nothing in the stylesheet distinguishes `.bg-light-primary` (on the body) from
`.bg-dark-primary` (on some card); the class attribute is the only place that
information exists. This is still reading CSS — it just reads which rules the
document selects, rather than assuming only `html`/`body`/`:root` can.

**The matcher is `cssselect2`'s, over a real tree.** It used to be a regex over
one compound selector, deliberately narrow because a hand-rolled matcher cannot
be trusted past `.foo.bar[x=y]` — anything with a combinator, an `:is()` or an
unfamiliar pseudo-class simply failed to match and fell back to the
`html|body|:root` pattern. That restriction is phase 2's to lift (`PLAN.md`):
a spec matcher answers `.a:is(.b) > body`, `html:not([data-theme="light"])` and
`.dark\\:bg-x` alike, and answers them the way a browser does.

**Two trees, for two different questions.** `page_elements`' tree comes from
the stdlib `html.parser` shim below (`_TreeBuilder`) — enough for
`<html>`/`<body>` ancestry, which is the only structure that question can
ask about. `full_tree` (T9, `PLAN.md`) uses `html5lib` instead, because a
question about a real element several levels below the page element —
does this custom-property definition's selector match one of *its*
ancestors — needs a conforming tree builder's implied-tag and misnesting
handling to be right that far down, which `_TreeBuilder` deliberately isn't.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from html.parser import HTMLParser

import cssselect2
import html5lib

from .cssparse import split_selector_list

# `cssselect2.ElementWrapper.from_html_root` expects XHTML-namespaced tags,
# which is how a real HTML parser reports them.
_XHTML = "{http://www.w3.org/1999/xhtml}"

# Elements that never have an end tag. Pushing one onto the open-element stack
# would swallow everything after it as its children — `<meta>` in the head is
# enough to make `<body>` a descendant of `<head>`.
_VOID = frozenset({
    "area", "base", "basefont", "br", "col", "embed", "frame", "hr", "img",
    "input", "isindex", "keygen", "link", "meta", "param", "source", "track",
    "wbr",
})

# The direct children of `<html>`. Starting one closes whatever is open.
_SECTIONS = frozenset({"head", "body", "frameset"})


class _TreeBuilder(HTMLParser):
    """Real HTML in, `ElementTree` out — enough of one for selector matching.

    Deliberately not a conforming HTML5 tree builder. It does not insert
    implied tags, reparent misnested elements, or apply the in-body insertion
    modes, so a stray `</div>` or an unclosed `<p>` mid-document produces a
    tree that differs from the browser's *below* the page element.

    That does not reach an answer here, because the only elements ever tested
    are `<html>` and `<body>`, and the only structure a selector can ask about
    them is their ancestry — which is `<html>`, or nothing. Descendant
    combinators (`.flex .bg-light-primary`) and `:root` are decided from that
    chain alone. `html5lib` would be more faithful and buys nothing for this
    question; `lxml` is a C extension, which the pure-Python floor rules out.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: ET.Element | None = None
        self._open: list[ET.Element] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SECTIONS:
            # The one implied end tag this shim owes: `<head>` and `<body>` are
            # children of `<html>`, always. `</head>` is optional and routinely
            # omitted, and html.parser closes nothing on its own — so without
            # this the body nests *inside* the head, `html > body` stops
            # matching, and `head .foo` starts. Both are answers about the page
            # element's ancestry, which is the one thing this tree must get
            # right; everything below it may be as misnested as the source is.
            keep = 1 if self._open and self._open[0].tag == _XHTML + "html" else 0
            del self._open[keep:]

        el = ET.Element(_XHTML + tag,
                        {k: (v if v is not None else "") for k, v in attrs})
        if self._open:
            self._open[-1].append(el)
        elif self.root is None:
            self.root = el
        else:
            # Content after the root element closed. Keeping it under the root
            # is wrong in the abstract and irrelevant here; dropping it would
            # lose a `<body>` in a fragment that opened with something else.
            self.root.append(el)
        if tag not in _VOID:
            self._open.append(el)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        # `<div/>` in HTML is a start tag, but the author meant it to close.
        self.handle_starttag(tag, attrs)
        if tag not in _VOID and self._open:
            self._open.pop()

    def handle_endtag(self, tag: str) -> None:
        name = _XHTML + tag
        # Close the nearest matching open element, discarding anything left
        # open inside it. An end tag with no match at all is ignored, which is
        # what a browser does with a stray `</div>`.
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i].tag == name:
                del self._open[i:]
                return


@dataclass
class PageElement:
    """`<html>` or `<body>` as the document actually wrote it."""
    tag: str
    id: str = ""
    classes: frozenset = frozenset()
    attrs: dict = field(default_factory=dict)
    # The `cssselect2` view of the same element, carrying its position in the
    # tree. Everything a selector can ask beyond this element's own name and
    # attributes — ancestry, `:root`, sibling position — is answered from here.
    node: cssselect2.ElementWrapper | None = None


def page_elements(html: str) -> list[PageElement] | None:
    """`<html>` and `<body>` as this document wrote them, or None.

    None means the tags could not be read at all — a truncated or non-HTML
    document. That is deliberately distinct from an element with no classes:
    the second says the body carries nothing, and the first says we do not
    know, and treating "unknown" as "nothing" would state a ground confidently
    on no evidence.

    The first `<html>` and the first `<body>` win. A document with two of
    either is malformed, and a second one appearing in a HAR capture should not
    change the answer.
    """
    parser = _TreeBuilder()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # A parse error leaves whatever was built; an empty tree reads as
        # "could not tell", which is the honest answer.
        pass
    if parser.root is None:
        return None

    root = cssselect2.ElementWrapper.from_html_root(parser.root)
    found: dict[str, PageElement] = {}
    for node in root.iter_subtree():
        name = node.local_name
        if name in ("html", "body") and name not in found:
            found[name] = _describe(node)
            if len(found) == 2:
                break
    return [found[t] for t in ("html", "body") if t in found] or None


def full_tree(html: str) -> ET.Element | None:
    """The complete document tree, for questions `page_elements` can't answer.

    `_TreeBuilder` above is deliberately not a conforming tree builder below
    `<html>`/`<body>` — see its own docstring — because the only structure a
    selector could ask about the page element is its ancestry, which is
    `<html>` or nothing. A question about a real element deeper in the
    document (T9: does this custom-property definition's selector match an
    *ancestor* of the element consuming it?) needs a tree that gets misnested
    markup right below the page element too, not just at it.

    `html5lib`, not the stdlib shim: this is exactly the class of correctness
    `_TreeBuilder`'s docstring says buys nothing for `<html>`/`<body>`
    ancestry alone and was deferred for that reason (`PLAN.md` phase 2's own
    research: "`html5lib` would be more faithful and buys nothing for this
    question"). It buys something now that the question has moved past
    `<html>`/`<body>`. `namespaceHTMLElements=False` matches plain tag names
    (`div`, not `{http://www.w3.org/1999/xhtml}div`) the way `cssselect2`
    expects from `from_html_root` — verified directly, not assumed, against a
    selector reaching a nested element.

    Core install is pure Python: `six` and `webencodings` (the latter already
    a transitive dependency via `tinycss2`), so `PYTHON_FLOOR` and
    `build.py`'s vendoring model — which assumes no compiled wheels — are
    unaffected. `lxml`/`genshi`/`chardet` are optional extras this project
    does not install.

    Returns `None` on non-string input rather than raising — checked directly:
    `html5lib` is deliberately lenient about malformed *markup* (that is its
    whole design; there is no such thing as invalid HTML5 to it, empty string
    included, so `page_elements`' "unknown is not the same as absent"
    contract does not carry over the way it first looked like it would), and
    the only thing observed to make it raise is input that is not text at
    all.
    """
    try:
        return html5lib.parse(html, treebuilder="etree",
                              namespaceHTMLElements=False)
    except Exception:
        return None


def wrap_tree(root: ET.Element) -> cssselect2.ElementWrapper:
    """Wrap a `full_tree` root once, for callers that query it repeatedly.

    `ElementWrapper.from_html_root` walks and annotates the whole tree (parent
    pointers, id index) up front, so it is real work — cheap for the one-shot
    callers `elements_matching` serves directly, but wasteful when T9's
    ancestry walk (`extract.resolve_by_ancestry`) needs the same tree queried
    once per distinct consumer selector, which is hundreds of times on a
    real site. Measured directly (`PLAN.md` T9, 2026-08-02): re-wrapping per
    call was the dominant cost, not `html5lib`'s own parse — tailwindcss.com's
    479 distinct consumer selectors took 55s of wrapping against a parse cost
    too small to separate out. Callers that will look up more than one
    selector against the same tree should wrap once and pass the result to
    `elements_matching_wrapped` instead of calling `elements_matching`
    (which still wraps internally, for the common one-shot case) per lookup.
    """
    return cssselect2.ElementWrapper.from_html_root(root)


@lru_cache(maxsize=4096)
def _compile_selector_parts(selector: str) -> tuple:
    """Compile a selector list branch by branch, so one bad branch costs only itself.

    T25 (`PLAN.md`). `cssselect2.compile_selector_list` fails the *whole*
    list if any one branch is unparseable — it does not compile the good
    branches and skip the bad one:

    ```
    >>> cssselect2.compile_selector_list("*,:before,:after,::backdrop")
    cssselect2.parser.SelectorError: Expected a supported pseudo-element, got backdrop
    ```

    `::backdrop` is a real, valid CSS pseudo-element `cssselect2` simply
    doesn't implement. Tailwind v4's own `@layer properties` reset opens
    with exactly this selector on every corpus bundle that carries
    `@property` (`ground.news.har`, `tailwindcss.com.har`,
    `ui.shadcn.com.har`), so compiling the list as one unit lost the leading
    `*` branch too — the branch that should have answered every consumer's
    `@property`-registered `initial-value` at its own element, immediately.

    `split_selector_list` (invariant 17) already exists for exactly this
    shape — a selector list where one part is malformed — so each branch is
    split and compiled on its own; a branch that raises is dropped rather
    than voiding the whole list. Each of the three callers below filters the
    survivors differently afterward (pseudo-elements, `never_matches`), so
    this returns the raw compiled selectors rather than pre-filtering.

    Cached, the same reasoning as `selector_specificity`: `selector_matches`
    sits in T9's ancestry walk, called once per (consumer, ancestor,
    candidate) — compiling a selector list from scratch there was already
    wasteful before this added a split and per-branch compile on top of the
    single `compile_selector_list` call it replaces. `lru_cache` itself only
    requires hashable *arguments*; the tuple return is a separate
    precaution, because a cached *list* would be one mutable object handed
    to every caller sharing this cache entry. None of the three callers
    mutates what it gets back — and none may start to, including the
    compiled selector objects themselves, which are now shared across all
    three call sites rather than freshly compiled per caller.

    **Not used by `matches_page_element` or `selector_specificity`**, which
    have the identical try/except-the-whole-list shape and the identical
    bug, but were left out of T25's filing on purpose. For the one selector
    this bug is known to affect, `matches_page_element` is unaffected either
    way — `*` is already refused as blanket (`_is_blanket`) and `:before`/
    `:after` are refused as pseudo-elements, so the surviving branches
    change nothing it reports. `selector_specificity` is not so lucky and
    the claim "changes nothing" would be false there: verified directly,
    `cssselect2.compile_selector_list(":before")[0].specificity` is
    `(0, 0, 1)`, not `(0, 0, 0)`, so fixing that call site would move its
    answer for this selector — and `selector_specificity` feeds
    `_cascade_key` (invariant 21, `detect_ground`/`build_var_table`), an
    unmeasured blast radius this task did not sign up to predict. Left for
    its own task if a corpus case ever needs it.
    """
    compiled: list = []
    for part in split_selector_list(selector):
        try:
            compiled.extend(cssselect2.compile_selector_list(part))
        except Exception:
            continue
    return tuple(compiled)


def _compile_usable(selector: str) -> list | None:
    """The parts of a selector list a real element can be directly styled by.

    None covers everything `elements_matching_wrapped` treats as "no basis to
    answer": a selector `cssselect2` cannot compile, and a selector list
    where every branch is a pseudo-element or a dynamic state `cssselect2`
    marks `never_matches`. A pseudo-element is excluded here on purpose, not
    merely by inheritance from `cssselect2`'s own `query_all` filtering
    (which drops it independently — see `elements_matching_wrapped`'s
    docstring): this function backs T9's real-inheritance walk
    (`resolve_by_ancestry_kind`, `extract.consumers_of`), and a generated box
    is not an element real inheritance can originate from or be asked about —
    see `_compile_reachable` for the different, narrower question T18/T19
    need answered instead, and T21's own write-up (`PLAN.md`) for why the two
    must not share a filter despite looking like the same refusal.
    """
    compiled = _compile_selector_parts(selector)
    usable = [sel for sel in compiled
             if sel.pseudo_element is None and not sel.never_matches]
    return usable or None


def elements_matching_wrapped(
    selector: str, wrapped_root: cssselect2.ElementWrapper
) -> list[cssselect2.ElementWrapper]:
    """`elements_matching`'s query, against an already-`wrap_tree`'d root.

    Split out so a caller querying many selectors against one document (T9's
    ancestry walk) pays the wrapping cost once rather than once per selector.
    See `wrap_tree`'s own docstring for the measurement that made this worth
    splitting out.
    """
    usable = _compile_usable(selector)
    if usable is None:
        return []
    return list(wrapped_root.query_all(*usable))


def _compile_reachable(selector: str) -> list | None:
    """The parts of a selector list this project can test reach for (T18/T19).

    Like `_compile_usable`, except a pseudo-element branch (`.card::after`)
    stays usable rather than being dropped (T21, `PLAN.md`, landed
    2026-08-02): `cssselect2` still evaluates `.test()` against a
    pseudo-element selector's *base* compound, since `.pseudo_element` is
    only an annotation for the caller about a generated box `cssselect2`
    cannot itself represent as a tree node. Reach against `.card::after`'s
    base compound `.card` is exactly the question `selector_reach`/
    `reach_elements` answer — whether the class the rule is written for is on
    the page — and refusing it lumped a real, testable rule in with
    `:hover`'s genuine unanswerability.

    **Deliberately not shared with `_compile_usable`, despite the near-
    identical bodies.** T9's ancestry walk (`extract.consumers_of`, backed by
    `_compile_usable`) asks a different question — which real element a
    declaration's *value* directly applies to, the element real CSS
    inheritance could originate from — and a generated box is not that
    element. Sharing this filter with `elements_matching_wrapped` was T21's
    first draft and was wrong: `dom.selector_matches` (T9's own candidate
    matcher, used by `_ancestry_winners`) still refuses pseudo-elements
    unconditionally and was never meant to change, so a pseudo-element
    consumer would make T9 walk real ancestors for a property whose only
    real setters are *also* pseudo-element-scoped and therefore invisible to
    that walk — producing a confirmed `"absent"` (which overrides last-wins
    per `resolve_by_ancestry_kind`'s own contract) for a property that is
    genuinely set, just not through a selector `selector_matches` can see.
    Caught on `tailwindcss.com.har`: `.after\\:inset-ring:after`'s
    `--tw-inset-ring-color` resolved to a wrong last-wins guess (`#00a6f4ff`,
    Tailwind's alphabetically-last `.inset-ring-*` utility, painted nowhere
    on the page) before this split, and to nothing at all — a false
    `"absent"` — in the shared-filter draft, dropping a real, page-painted
    color. Splitting the filter restores the original last-wins answer for
    that declaration (still not exact, but not a fabricated non-answer
    either) and leaves it as a documented gap rather than a regression;
    fixing it for real needs `selector_matches` to test pseudo-element
    candidates against their base compound too, which is out of scope here
    since it changes what T9 confirms, not merely what T18/T19 report.
    """
    compiled = _compile_selector_parts(selector)
    usable = [sel for sel in compiled if not sel.never_matches]
    return usable or None


def reach_elements(selector: str,
                   wrapped_root: cssselect2.ElementWrapper
                   ) -> list[cssselect2.ElementWrapper]:
    """The real elements `selector_reach` tested this selector against (T19).

    Backs `matchCount`/`matches` for a usage `selector_reach` found `True`
    for — including a pseudo-element usage, whose base compound is what gets
    reported (T21, `PLAN.md`): the right unit, since a generated box isn't a
    separate node this tool could name even if it wanted to.

    **Not `wrapped_root.query_all(*usable)`.** `cssselect2`'s own `query_all`
    re-filters its arguments through `ElementWrapper._compile`, which drops
    any selector with `pseudo_element is not None` a *second* time —
    independently of, and after, `_compile_reachable`'s own filtering above.
    That means a pseudo-element branch this function deliberately keeps
    usable so it can be tested against its base compound would silently
    vanish again inside the very library call meant to test it; verified
    directly (`sel.test(node)` is `True`, `wrapped_root.query_all(sel)` is
    empty, for the identical compiled selector and node). `sel.test(element)`
    carries no such filter, so walking the subtree by hand and calling it
    directly is what actually reaches the base compound.
    """
    usable = _compile_reachable(selector)
    if usable is None:
        return []
    return [el for el in wrapped_root.iter_subtree()
           if any(sel.test(el) for sel in usable)]


def selector_reach(selector: str,
                   wrapped_root: cssselect2.ElementWrapper) -> bool | None:
    """Does this selector match at least one real element? `None` if untestable.

    T18 (`PLAN.md`): three answers, not two, and the caller has to keep them
    apart rather than treating "no basis" as a `False`. `True` and `False`
    both mean the selector compiled and was actually tested — the difference
    is only whether anything in the document matched. `None` means the
    question could not be asked at all: uncompilable, or every branch is a
    dynamic state `cssselect2` marks `never_matches` (see `_compile_reachable`,
    shared with `reach_elements`). A pseudo-element branch is tested against
    its *base compound* instead of being refused (T21, `PLAN.md`) —
    `.card::after` answers whatever `.card` itself answers. This is a
    deliberately different filter than `elements_matching_wrapped`'s — see
    `_compile_reachable`'s own docstring for why the two must not share one.

    Collapsing `None` into `False` is the specific mistake this function
    exists to prevent. `.old-class:hover` and a genuinely-dead `.old-class`
    both make `reach_elements` return `[]` — that function's empty-list
    contract does not distinguish "tested, matched nothing" from "could not
    test the resting-state question at all" (`:hover` has no resting state to
    test), because none of its existing callers needed that distinction.
    This one does: flagging every `:hover`/`:focus` declaration in a
    hand-written site as content-not-on-the-page would be wrong on exactly
    the sites this tool trusts most.

    Walks the subtree and calls `sel.test(element)` directly, the same way
    `reach_elements` does and for the same reason (T21, `PLAN.md`):
    `wrapped_root.query_all(*usable)` would silently re-drop any
    pseudo-element branch through `cssselect2`'s own internal filtering,
    independently of `_compile_reachable` above — see that function's
    docstring for the direct verification. `any(...)` over a generator
    expression short-circuits on the first match, so a selector that reaches
    something near the start of the document does not pay for walking the
    rest of it.
    """
    usable = _compile_reachable(selector)
    if usable is None:
        return None
    return any(sel.test(el) for el in wrapped_root.iter_subtree()
              for sel in usable)


def untestable_reason(selector: str) -> str:
    """Why `selector_reach` answered `None` for this selector (T24, `PLAN.md`).

    Only meaningful once `selector_reach` has already answered `None` — this
    recomputes `_compile_selector_parts` to tell apart the two causes that
    answer collapses into, on purpose (see its own docstring: keeping `None`
    a single tri-state value there, rather than a fourth outcome, is
    deliberate). `selector_reach` is `None` exactly when `_compile_reachable`
    finds no usable branch, which happens two structurally different ways:

    - `"uncompilable"` — nothing in the list compiled at all
      (`_compile_selector_parts` returns an empty tuple). A library/parser
      coverage gap, the same flavor as T21/T25: a different selector engine
      might answer this selector, so it is undertested, not permanently
      unknowable.
    - `"dynamicState"` — every branch that *did* compile is a dynamic
      pseudo-class `cssselect2` marks `never_matches` (`:hover`, `:focus`,
      `:target`, …). A pseudo-element branch would have stayed usable
      instead of being filtered out here (T21 — its base compound is real,
      testable evidence), so reaching this branch means every surviving
      selector genuinely has no resting state any capture could test: not
      undertested, structurally unanswerable.

    Callers must only invoke this after `selector_reach` returns `None` —
    it does not itself re-derive that determination.
    """
    compiled = _compile_selector_parts(selector)
    return "uncompilable" if not compiled else "dynamicState"


def element_signature(node: cssselect2.ElementWrapper, *, depth: int = 3,
                      max_len: int = 50) -> str:
    """A short, human-readable label for one real matched element (T19).

    Not a selector — a diagnostic for `examples`, naming *which* element among
    several a rule reached rather than restating the rule. `tag#id.class`,
    with up to `depth` immediate ancestors chained by `>` for the cases that
    matter most: a `.card` rule that lands on three different cards is only
    distinguishable by where each one sits, not by its own attributes, which
    are identical by construction. Bounded to the closest ancestors rather
    than the full path to `<html>` — the root end of a long chain is rarely
    what disambiguates a sibling from another; the immediate ones are.

    `max_len` is a hard cap on the whole string, not a per-part budget —
    class *count* is not a reliable proxy for length. Tailwind v4's own
    generated font classes on tailwindcss.com
    (`inter_6a166f28-module__775SPq__variable`, several per element) run
    past 200 characters on a single class, so capping "the first N classes"
    would still have let one pathological site blow up every `examples`
    payload. Measured directly, uncapped: `tailwindcss.com`'s JSON grew 38%
    (1.57MB → 2.17MB) and its report grew 46% — the report is not just the
    JSON's home, it embeds the identical `to_document()` output verbatim
    (invariant 11), so a payload regression here is a report regression too,
    on every site, not only pathological ones. This `max_len` plus
    `extract.MATCH_SAMPLES` capped at 2 (its own docstring) bring
    `tailwindcss.com` down to +19% JSON / +18% report and `ui.shadcn.com` to
    +17% JSON / +15% report — real growth for real new data, not the near-
    doubling the uncapped version produced.

    `node.ancestors` is already computed and cached during `wrap_tree`, so
    walking it here is free — no new tree traversal, matching `wrap_tree`'s
    own reasoning for why `resolve_by_ancestry_kind` and `selector_reach`
    share one wrapped root instead of re-wrapping per call.
    """
    def part(n: cssselect2.ElementWrapper) -> str:
        cls = "".join(f".{c}" for c in sorted(n.classes))
        idpart = f"#{n.id}" if n.id else ""
        return f"{n.local_name}{idpart}{cls}"

    chain = [*node.ancestors, node][-depth:]
    sig = " > ".join(part(n) for n in chain)
    if len(sig) > max_len:
        sig = sig[:max_len - 1] + "…"
    return sig


def elements_matching(selector: str,
                      root: ET.Element) -> list[cssselect2.ElementWrapper]:
    """Every real element in this tree that this selector matches.

    General-purpose, unlike `matches_page_element`: that function is deliberately
    narrow to "is this a statement about the page's resting appearance" and
    refuses pseudo-elements, dynamic states, and blanket selectors on purpose.
    This one answers a different, plainer question — where in the real
    document does this selector actually land — so it filters only what
    `cssselect2` itself cannot evaluate (a pseudo-element styles a generated
    box, not a real element; `never_matches` has no interaction state to test
    against), and leaves the rest, including `*`, to the caller's judgment.
    Reach — whether a pseudo-element rule's *base compound* is on the page —
    is a deliberately different question, answered by `reach_elements`
    instead (T21, `PLAN.md`); see `_compile_reachable`'s docstring for why
    this function does not answer it too.

    A selector `cssselect2` cannot compile returns no matches rather than
    raising, the same contract every other matcher in this module keeps —
    `strip_theme_scope` can hand callers something invalid, and real CSS
    carries pseudo-classes no library knows.

    Wraps the tree fresh on every call — fine for a one-shot lookup, wasteful
    for a caller checking many selectors against the same document. See
    `wrap_tree`/`elements_matching_wrapped` for that case.
    """
    return elements_matching_wrapped(selector, wrap_tree(root))


def selector_matches(selector: str,
                     element: cssselect2.ElementWrapper
                     ) -> tuple[int, int, int] | None:
    """This selector's specificity against one specific real element, or None.

    None means the selector does not match here at all — the same "no
    answer" contract `_page_specificity` (`extract.py`) keeps for
    `<html>`/`<body>`, generalised to any real element T9's ancestry walk
    visits. A selector list takes the highest specificity among the parts
    that actually match this element, mirroring `selector_specificity`'s own
    rule for a list scored as a whole — the two functions answer different
    questions (that one has no element to test against; this one does) and
    would otherwise silently disagree on a list where only one branch matches.
    """
    compiled = _compile_selector_parts(selector)
    best = None
    for sel in compiled:
        if sel.pseudo_element is not None or sel.never_matches:
            continue
        if sel.test(element) and (best is None or sel.specificity > best):
            best = sel.specificity
    return best


def _probe_element() -> cssselect2.ElementWrapper:
    """A nondescript element in a throwaway document.

    No classes, no attributes, no name any stylesheet targets, sitting inside a
    `<body>` inside a root — so a descendant combinator anchored on the page
    reaches it. Built element by element rather than parsed, because the only
    XML parser in reach is the stdlib one and nothing untrusted should ever
    meet it. (Real documents go through `html.parser`, which has no entity
    expansion to abuse.)
    """
    root = ET.Element(_XHTML + "html")
    body = ET.SubElement(root, _XHTML + "body")
    ET.SubElement(body, _XHTML + "div")
    wrapper = cssselect2.ElementWrapper.from_html_root(root)
    return next(n for n in wrapper.iter_subtree() if n.local_name == "div")


_ANY_ELEMENT = _probe_element()


def _is_blanket(sel) -> bool:
    """Does this selector land on everything, rather than on the page element?

    `*`, `:root *`, `body *` and `*, ::before, ::after` all *do* select
    `<html>` or `<body>`, so a real matcher says yes to them — and saying yes
    is wrong here. Two reasons, and they agree:

    A blanket rule makes no statement about the page element. Invariant 19
    lays page-scoped custom properties over the rest so that a definition
    reaching the page beats one scoped to a theme nobody selected; a rule
    reaching *every* element reaches the unselected theme too, so it earns
    nothing by the argument that rule exists for.

    And it inverts the cascade. The universal selector is the weakest thing in
    CSS — it loses to every class — so promoting it above class-scoped
    definitions gets the precedence backwards. Measured, on the corpus: this
    is how Tailwind v4 writes its reset (`* { --tw-gradient-from: #0000;
    --tw-ring-offset-color: #fff; … }`), and promoting it made that reset beat
    every utility that sets those properties to a real color — 11 named colors
    on ground.news collapsing to `#0000`/`#fff`, colors the site never paints.
    MDN's `light-dark()` polyfill fails the same way from `:root *`, taking
    `--color-background-page` from a light/dark pair to the dark branch alone.

    Testing it rather than pattern-matching the selector text keeps this in the
    same grammar as everything else here: a selector that also selects a
    nondescript `<div>` is not telling us about `<body>`.
    """
    return sel.test(_ANY_ELEMENT)


def _describe(node: cssselect2.ElementWrapper) -> PageElement:
    attrib = node.etree_element.attrib
    return PageElement(
        tag=node.local_name,
        id=node.id or "",
        classes=frozenset(node.classes),
        attrs={k: v for k, v in attrib.items() if k not in ("class", "id")},
        node=node,
    )


@lru_cache(maxsize=4096)
def selector_specificity(selector: str) -> tuple[int, int, int]:
    """`(ids, classes, elements)` for a selector, the way a browser counts it.

    `cssselect2` supplies this, which is the reason it is worth having at all
    for the cascade: a hand-rolled count gets exactly the cases wrong that
    modern CSS is written in. `:where()` contributes zero, so Tailwind v4's
    `.dark\\:bg-x:where(.dark,.dark *)` is one class and not two;
    `:is()`/`:not()`/`:has()` contribute the *maximum* of their arguments
    rather than the sum. Counting those by pattern is how a partial cascade
    ends up worse than plain document order.

    A selector list takes the highest of its members. That is not the cascade's
    own rule — the cascade scores whichever selector matched — so callers that
    know which one matched should ask about that one. `extract._page_specificity`
    does, per part.

    Uncompilable is `(0, 0, 0)`: the weakest thing there is, so a selector we
    cannot read never outranks one we can. Cached because `build_var_table`
    asks about the same handful of selectors once per custom property, and
    Bootstrap has thousands.
    """
    try:
        compiled = cssselect2.compile_selector_list(selector)
    except Exception:
        return (0, 0, 0)
    return max((sel.specificity for sel in compiled), default=(0, 0, 0))


def matches_page_element(selector: str,
                         elements: list[PageElement] | None) -> bool:
    """Does this selector select `<html>` or `<body>` in this document?

    Three kinds of selector are refused, and all three are rules rather than
    accidents of the library:

    A selector carrying a **pseudo-element** — `body::after` — styles a box the
    element generates, not the element. A background declared there does not
    paint the page.

    A selector standing on a **dynamic state** — `:hover`, `:focus`,
    `:focus-within`, `:target`, `:visited` — describes what the page looks like
    while something is happening to it, and the ground is what it looks like at
    rest. `cssselect2` marks exactly these `never_matches`, since it has no
    interaction state to evaluate them against; skipping them here says the
    same thing on purpose instead of inheriting it.

    A selector that lands on **everything** — `*`, `:root *` — genuinely does
    select the page element and still says nothing about it. See `_is_blanket`,
    which is the one place a real matcher needed reining in rather than letting
    loose.

    A selector `cssselect2` cannot compile is False rather than an error. That
    is required, not defensive: `strip_theme_scope` can hand this an `:is( ,
    …)` — the unmodelled nesting `cssparse._not_spans` documents — and CSS in
    the wild carries pseudo-classes no library knows (`:dir()` today). Either
    would raise. Failing to match is the same answer the narrow matcher gave
    for anything it did not understand, and it defers to `_PAGE_SEL`.
    """
    if not elements:
        return False
    try:
        compiled = cssselect2.compile_selector_list(selector)
    except Exception:
        return False

    for sel in compiled:
        if sel.pseudo_element is not None or sel.never_matches:
            continue
        if _is_blanket(sel):
            continue
        for el in elements:
            if el.node is not None and sel.test(el.node):
                return True
    return False
