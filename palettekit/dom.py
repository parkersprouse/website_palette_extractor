"""The document's own `<html>` and `<body>`, and which selectors reach them.

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

The tree comes from stdlib `html.parser`, not `lxml` or `html5lib` — see
`_TreeBuilder` for why that is enough here.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from html.parser import HTMLParser

import cssselect2

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
