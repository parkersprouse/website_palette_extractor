"""A CSS reader, scoped to the job of finding colors.

Tokenising is `tinycss2`'s job — it implements the CSS Syntax grammar, and this
module only decides which of the declarations it hands back are worth keeping,
which selector and at-rule context they carry, and which theme scopes them.

The split matters because the previous hand-rolled brace walker was an
*approximation* of the grammar, and every new site revealed a new corner of it:
an escaped quote in a Tailwind selector masked past the following `{`; a
statement `@charset` got glued onto the next rule's selector and cost Bootstrap
its whole `:root` block; a comma inside `:where()` split one selector into two
broken ones. Those looked like separate bugs and were one — see `PLAN.md` — and
the fix for a class rather than its instances is to stop approximating.

What is still this module's own is everything above the token stream: theme
scopes, selector weighting, `var()` resolution. Which rules land on the page
element moved to `dom.py`, where `cssselect2` answers it against a real tree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import tinycss2

from .color import Color, find_colors

# Properties whose values carry color, mapped to the role the color plays.
PROPERTY_ROLE = {
    "background": "surface",
    "background-color": "surface",
    "background-image": "surface",
    "color": "text",
    "-webkit-text-fill-color": "text",
    "text-decoration-color": "text",
    "-webkit-text-stroke-color": "text",
    "caret-color": "text",
    "border-color": "line",
    "border-top-color": "line",
    "border-right-color": "line",
    "border-bottom-color": "line",
    "border-left-color": "line",
    "border": "line",
    "border-top": "line",
    "border-right": "line",
    "border-bottom": "line",
    "border-left": "line",
    "outline": "line",
    "outline-color": "line",
    "column-rule-color": "line",
    "box-shadow": "shadow",
    "text-shadow": "shadow",
    "filter": "shadow",
    "-webkit-filter": "shadow",
    "backdrop-filter": "shadow",
    "fill": "graphic",
    "stroke": "graphic",
    "stop-color": "graphic",
    "flood-color": "graphic",
    "lighting-color": "graphic",
    "accent-color": "ui",
    "scrollbar-color": "ui",
    "text-emphasis-color": "text",
}


# ---------------------------------------------------------------- theme scopes
#
# A site that ships two themes says so in one of two ways: a
# `prefers-color-scheme` media query, or a class/attribute on a wrapper element
# that the site toggles. Both are *scopes over declarations*, which is why they
# are detected here rather than downstream: extract.py runs the whole pipeline
# once per scope, because each theme has its own ground and every contrast
# ratio and alpha flattening is measured against it.

_THEME_MEDIA = re.compile(r"prefers-color-scheme\s*:\s*(light|dark)", re.I)

# Only whole, known theme class names. `.dark-blue`, `.darken` and
# `.sidebar-dark` name components, not theme roots, and treating one as a theme
# would split an ordinary palette in half.
#
# A backslash ends the name no less than a letter does, which is why it is in
# the lookahead: Tailwind compiles `dark:bg-x` to the class *named*
# `dark:bg-x`, written `.dark\:bg-x`. That is a utility whose name happens to
# start with "dark", not a theme root, and reading it as one strips the marker
# out of the middle of a class name and leaves `\:bg-x` behind.
_THEME_CLASS = re.compile(
    r"\.(?:is-|has-|theme-|mode-|colou?r-mode-|colou?r-scheme-)?"
    r"(light|dark)"
    r"(?:-(?:mode|theme|scheme))?"
    r"(?![\w\\-])",
    re.I,
)

# The same marker wrapped in `:is()`/`:where()`, which is how Tailwind's `dark:`
# variant actually states the scope: `.dark\:bg-x:is(.dark *)`. It has to come
# off as a unit — removing just the `.dark` inside would leave `:is( *)` glued
# to the selector, which then matches nothing downstream.
_THEME_IS = re.compile(
    r":(?:is|where)\(\s*"
    r"\.(?:is-|has-|theme-|mode-|colou?r-mode-|colou?r-scheme-)?"
    r"(light|dark)"
    r"(?:-(?:mode|theme|scheme))?"
    r"(?![\w\\-])"
    r"[^)]*\)",
    re.I,
)

# [data-theme="dark"], [data-bs-theme=dark], [data-color-mode=dark], [theme=dark]
_THEME_ATTR = re.compile(
    r"\[\s*(?:data-)?[\w-]*(?:theme|scheme|mode|appearance)\s*"
    r"[~|^$*]?=\s*[\"']?(light|dark)[\"']?\s*[a-z]?\s*\]",
    re.I,
)

_WS = re.compile(r"\s+")
_REDUNDANT_HTML = re.compile(r"^html\s+(?=body\b)", re.I)

_NOT_OPEN = re.compile(r":not\(", re.I)


def _not_spans(selector: str) -> list[tuple[int, int]]:
    """Character ranges covered by a top-level `:not(...)`, brackets balanced.

    A theme marker inside a negation means the opposite of what it says, so
    every marker match has to be taken outside these ranges. django's docs are
    the case that proves it:

        @media (prefers-color-scheme: dark) {
          html:not([data-theme="light"]) { --body-bg: #0e1117; … }
        }

    Read the `[data-theme="light"]` as a scope and the dark theme's entire
    token block is filed under *light* — 124 declarations of it, including the
    ground. Skipping the negation lets the rule fall through to the media
    query, which says dark, which is what it is.

    **A `:not()` inside an `:is()`/`:where()` is not modelled.** Blanking the
    inner negation splits the outer function across the span boundary, so
    `strip_theme_scope('.x:is(.dark, :not(.light))')` leaves `:is( , …)` —
    the empty-functional-pseudo failure invariant 14 warns about. Left alone
    because it is unreachable on the corpus: of 1296 distinct themed selectors
    across the eight sites, including every Tailwind v4 shape, none nests a
    negation inside a marker's `:is()`. Fixing it properly means matching
    `_THEME_IS` with balanced parens rather than `[^)]*\\)`, which is worth
    doing when a real site needs it and not before.
    """
    spans: list[tuple[int, int]] = []
    for m in _NOT_OPEN.finditer(selector):
        if spans and m.start() < spans[-1][1]:
            continue                    # nested inside one we already took
        i, depth, quote = m.end() - 1, 0, ""
        while i < len(selector):
            ch = selector[i]
            if ch == "\\":
                i += 2
                continue
            if quote:
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    spans.append((m.start(), i + 1))
                    break
            i += 1
    return spans


def _negation_free(selector: str) -> str:
    """The selector with every `:not(...)` blanked out, length preserved."""
    spans = _not_spans(selector)
    if not spans:
        return selector
    out = list(selector)
    for a, b in spans:
        out[a:b] = " " * (b - a)
    return "".join(out)


def _outside_negations(selector: str, fn) -> str:
    """Apply `fn` to the parts of the selector that are not inside a `:not()`."""
    spans = _not_spans(selector)
    if not spans:
        return fn(selector)
    out, prev = [], 0
    for a, b in spans:
        out.append(fn(selector[prev:a]))
        out.append(selector[a:b])
        prev = b
    out.append(fn(selector[prev:]))
    return "".join(out)


def _strip_markers(text: str) -> str:
    cleaned = _THEME_IS.sub("", text)
    return _THEME_ATTR.sub(" ", _THEME_CLASS.sub(" ", cleaned))


def split_selector_list(selector: str) -> list[str]:
    """Split on the commas that separate selectors, not the ones inside them.

    `.a:is(.b, .c), .d` is two selectors, and a bare `split(",")` makes it
    three broken ones. Functional pseudo-classes made this load-bearing rather
    than pedantic: Tailwind v4 compiles its dark variant to
    `.dark\\:bg-x:where(.dark,.dark *)`, and splitting inside the `:where()`
    leaves `:where(, *)` — a selector that matches nothing, so the theme's
    rules stop being recognised as the theme's.

    Attribute values are quoted and can contain commas too, so quotes and
    brackets are tracked alongside parens.
    """
    parts, depth, quote, start = [], 0, "", 0
    i = 0
    while i < len(selector):
        ch = selector[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch == "\\":
            i += 2                      # an escape, never a delimiter
            continue
        elif ch in "\"'":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append(selector[start:i])
            start = i + 1
        i += 1
    parts.append(selector[start:])
    return [p.strip() for p in parts if p.strip()]


def selector_theme(selector: str) -> str:
    """The theme this selector puts itself in, from its own markers alone.

    A selector list is judged per selector, and one unscoped selector makes
    the whole rule unscoped. Bootstrap 5.3 opens with

        :root,[data-bs-theme=light] { --bs-border-color: #dee2e6; … }

    which defines the site's base tokens *and* its light-theme tokens in one
    rule. Reading the list as a whole tags every one of those as light-only,
    they vanish from the base var table, and several hundred `var()`
    references resolve to nothing.

    Selectors that disagree (`.dark .a, .light .b`) also come back unscoped:
    the rule cannot be attributed to one theme, and saying so beats picking
    whichever marker was written first.

    A marker inside `:not()` is not a scope — see `_not_spans`.
    """
    scopes = set()
    for part in split_selector_list(selector):
        part = _negation_free(part)
        m = (_THEME_IS.search(part) or _THEME_CLASS.search(part)
             or _THEME_ATTR.search(part))
        scopes.add(m.group(1).lower() if m else "")
    if len(scopes) == 1:
        found = scopes.pop()
        if found:
            return found
    return ""


def media_theme(at_rules: tuple[str, ...]) -> str:
    """The theme a `prefers-color-scheme` block puts its contents in."""
    for at in at_rules:
        m = _THEME_MEDIA.search(at)
        if m:
            return m.group(1).lower()
    return ""


def theme_scope(selector: str, at_rules: tuple[str, ...]) -> str:
    """`light`, `dark`, or `""` for a declaration that belongs to no theme.

    The selector is consulted before the media query. A rule written `.dark .x`
    inside a `prefers-color-scheme: light` block is contradictory and
    vanishingly rare, and the explicit class is the stronger statement of the
    two.

    Which of the two mechanisms answered is worth knowing downstream and is
    kept on `Declaration.theme_media`: a selector-scoped theme states its scope
    *in the selector*, so `html.dark` outranks `html` on real specificity and
    needs no help from the cascade. A media-scoped one has no specificity
    difference at all from what it overrides.
    """
    return selector_theme(selector) or media_theme(at_rules)


def strip_theme_scope(selector: str) -> str:
    """The selector as it reads from inside its own theme.

    `html.dark body` describes the dark theme's page background exactly as
    `html body` describes the light one's, so the marker has to come off before
    the selector is weighted or matched against the page-level pattern.
    Without this, `selector_weight` scores a themed page rule as an ordinary
    class and `detect_ground` never sees it at all — the dark theme then
    silently inherits the light ground and every ratio reported for it is
    wrong.

    A compound left empty by the removal becomes `:root`: `.dark { --bg: #000 }`
    is a root token override, and dropping it would leave no selector at all.

    `:not(...)` is left alone, for the same reason `theme_scope` does not read
    into it: `html:not([data-theme="light"])` is a rule *about* the negation,
    and stripping the marker out of it leaves `html:not()`, which is not a
    selector at all.
    """
    out = []
    for part in split_selector_list(selector):
        cleaned = _outside_negations(part, _strip_markers)
        cleaned = _WS.sub(" ", cleaned).strip()
        # `html body` and `body` select the same element, and the marker is
        # usually carried on `html`, so `html.dark body` has to come out as
        # plain `body` if it is to be recognised as the override of `body` that
        # it is. Only themed selectors pass through here, so this cannot
        # perturb an unthemed site.
        cleaned = _REDUNDANT_HTML.sub("", cleaned)
        out.append(cleaned or ":root")
    return ", ".join(out)


@dataclass
class Declaration:
    selector: str
    prop: str
    value: str
    source: str
    at_rules: tuple[str, ...] = ()
    order: int = 0          # position within its own stylesheet
    sheet_order: int = 0    # position of the stylesheet in the document
    theme: str = ""         # "light" / "dark" / "" for unscoped
    # The first term of the cascade, read from the token stream rather than
    # string-matched.
    important: bool = False
    # The second. The fully-qualified `@layer` name this declaration sits in —
    # `a.b` for a layer nested in a layer — or "" for an unlayered declaration,
    # which the spec ranks *above* every layer. The order the names themselves
    # cascade in is a property of the document rather than of one sheet, so it
    # is resolved in `extract.layer_order`.
    layer: str = ""
    # True when this declaration's theme came from a `prefers-color-scheme`
    # block rather than from a marker in its own selector. That distinction is
    # a cascade input: a selector-scoped theme outranks what it overrides on
    # specificity, and a media-scoped one is identical to it on every term.
    theme_media: bool = False

    @property
    def is_custom_property(self) -> bool:
        return self.prop.startswith("--")

    @property
    def role(self) -> str:
        if self.is_custom_property:
            return "token"
        return PROPERTY_ROLE.get(self.prop, "other")

    @property
    def themed_selector(self) -> str:
        """The selector with its theme marker removed, if it had one."""
        return strip_theme_scope(self.selector) if self.theme else self.selector


@dataclass
class Stylesheet:
    source: str
    origin: str = ""
    third_party: bool = False
    sheet_order: int = 0
    declarations: list[Declaration] = field(default_factory=list)
    var_refs: set[str] = field(default_factory=set)
    # `@layer` names in the order this sheet first mentions them, by either
    # form. Merged across sheets into one document-wide order by
    # `extract.layer_order` — layer names are global, and a sheet that mentions
    # `utilities` is talking about the same layer another sheet declared.
    layers: list[str] = field(default_factory=list)


_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def strip_comments(css: str) -> str:
    return _COMMENT.sub(" ", css)


_VAR_NAME = re.compile(r"var\(\s*(--[\w-]+)")


def _norm(text: str) -> str:
    """Collapse whitespace the way the old walker's `.strip()`/`split()` did."""
    return " ".join(text.split())


def parse_stylesheet(css: str, source: str, origin: str = "",
                     third_party: bool = False,
                     sheet_order: int = 0) -> Stylesheet:
    """Parse a stylesheet and collect every color-bearing declaration.

    `tinycss2` does the tokenising; `_walk` decides what to keep. Three things
    that used to be hand-written are now simply properties of the grammar:
    strings and comments cannot be mistaken for color (invariant 9), a comma
    inside `:where()` is not a selector separator (invariant 17), and a
    statement at-rule is consumed rather than glued to the next selector
    (invariant 18). Their tests stay — they now guard this integration, which
    is exactly where a swap like this goes wrong.
    """
    sheet = Stylesheet(source=source, origin=origin, third_party=third_party,
                       sheet_order=sheet_order)
    rules = tinycss2.parse_stylesheet(css, skip_comments=True,
                                      skip_whitespace=True)
    _walk(sheet, rules, source, at_rules=(), selector="", theme="",
          theme_media=False, layer="")
    return sheet


def _contents(node) -> list:
    return tinycss2.parse_blocks_contents(node.content, skip_comments=True,
                                          skip_whitespace=True)


def _qualify(parent: str, name: str) -> str:
    """`base` inside `@layer framework` is the layer `framework.base`."""
    return f"{parent}.{name}" if parent else name


def _register_layer(sheet: Stylesheet, name: str) -> None:
    """Note a layer's existence, and its ancestors' — order comes from this.

    Registering `a.b` registers `a` first even if nothing named it, because a
    sub-layer cascades *inside* its parent and the parent has to hold a
    position for that to mean anything.
    """
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        qualified = ".".join(parts[:i])
        if qualified not in sheet.layers:
            sheet.layers.append(qualified)


def _anonymous_layer(sheet: Stylesheet, parent: str) -> str:
    """A name for `@layer { … }`, which creates a new layer every time.

    Two anonymous blocks are two layers, never the same one re-opened, so the
    name has to be unique across the whole document — hence the sheet's
    position in it. The NUL keeps it from colliding with anything an author
    could write, and carries no dot, so `_register_layer` still splits the
    qualified name on parentage correctly.

    **The counter skips values, and that is not a bug.** It counts every
    registered name carrying a NUL, which includes a *named* layer nested in an
    anonymous one — `@layer { @layer x {} }` registers `\\x000-0.x`. Uniqueness
    only needs the count to rise between two calls, and it does: creating an
    anonymous layer always registers at least one new NUL-bearing name. Making
    it a true count of anonymous layers would be no more correct and one more
    thing to keep in step. No corpus site uses an anonymous layer at all, so
    `test_anonymous_layers_stay_distinct_when_nested` is the only thing holding
    this.
    """
    n = sum(1 for name in sheet.layers if "\x00" in name)
    return _qualify(parent, f"\x00{sheet.sheet_order}-{n}")


def _walk(sheet: Stylesheet, nodes: list, source: str,
          at_rules: tuple[str, ...], selector: str, theme: str,
          theme_media: bool, layer: str) -> None:
    """Record declarations, descending through nested rules and at-rule blocks.

    `selector` is the rule the current nodes sit inside, and `""` means there
    is none — the body of an `@font-face`, or of an `@media` nested directly in
    a rule. Declarations there are read for their `var()` references but not
    kept, which is what the brace walker did by pushing an empty selector for
    every at-rule block.

    `layer` is the enclosing `@layer`, which propagates through every other
    kind of at-rule: a rule inside `@layer base { @media … { … } }` is in
    `base` just as much as one written directly in it.
    """
    for node in nodes:
        if node.type == "declaration":
            # Every declaration contributes its references, whether or not the
            # property is one we keep. `var_refs` decides `live` vs `saved`
            # (invariant 10), and a property consumed only by `font-family` is
            # still a property something consumes.
            value = tinycss2.serialize(node.value)
            sheet.var_refs.update(_VAR_NAME.findall(value))
            if selector:
                _record(sheet, node, value, selector, source, at_rules, theme,
                        theme_media, layer)

        elif node.type == "qualified-rule":
            sel = _norm(tinycss2.serialize(node.prelude))
            # Once per rule rather than per declaration: the scope is a
            # property of the rule, and the regexes are not free.
            scoped = selector_theme(sel)
            media = "" if scoped else media_theme(at_rules)
            _walk(sheet, _contents(node), source, at_rules, sel,
                  scoped or media, bool(media), layer)

        elif node.type == "at-rule":
            keyword = node.lower_at_keyword
            prelude = _norm(tinycss2.serialize(node.prelude))
            if node.content is None:
                # A statement at-rule — `@charset`, `@import`, `@layer a, b;`.
                # It has no body and declares nothing; invariant 18 is now
                # simply this branch.
                if keyword == "layer":
                    # …but `@layer a, b;` declares the *order*, which is the
                    # whole point of writing it: it reserves positions before
                    # any of the blocks that fill them appear. Tailwind v4
                    # opens with one.
                    for name in prelude.split(","):
                        if name.strip():
                            _register_layer(sheet, _qualify(layer, name.strip()))
                continue
            inner = layer
            if keyword == "layer":
                inner = (_qualify(layer, prelude) if prelude
                         else _anonymous_layer(sheet, layer))
                _register_layer(sheet, inner)
            at = _norm(f"@{keyword} {prelude}")
            _walk(sheet, _contents(node), source, at_rules + (at,),
                  selector="", theme="", theme_media=False, layer=inner)


def _record(sheet: Stylesheet, node, value: str, selector: str, source: str,
            at_rules: tuple[str, ...], theme: str, theme_media: bool,
            layer: str) -> None:
    prop = node.lower_name
    if not (prop.startswith("--") or prop in PROPERTY_ROLE):
        return
    value = _norm(value)
    if not value:
        return
    sheet.declarations.append(
        Declaration(
            selector=selector,
            prop=prop,
            value=value,
            source=source,
            at_rules=at_rules,
            order=len(sheet.declarations),
            sheet_order=sheet.sheet_order,
            theme=theme,
            important=node.important,
            layer=layer,
            theme_media=theme_media,
        )
    )


_VAR_CALL = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*(.*?)\s*)?\)", re.S)


_GLUE_LEFT = "(,/ \t\n"
_GLUE_RIGHT = "),/; \t\n"


def resolve_vars(value: str, table: dict[str, str], depth: int = 0) -> str:
    """Substitute var() references using a name -> value table.

    Falls back to the declared default when a name is unknown, and gives up
    after a few levels so a circular definition cannot hang the run.

    **A substitution that would abut its neighbour is padded with a space**,
    because CSS substitutes *tokens* and this substitutes *text*. Tailwind v4
    minifies its opacity utilities to
    `color-mix(in oklab,var(--color-white)var(--tw-shadow-alpha),transparent)`;
    those are two component values with no separator needed, and pasting them
    together yields `#fff100%` — which the color scanner then read as the hex
    `#fff100`, a bright yellow appearing 18 times on ground.news and painted
    nowhere. A whole invented color, from two correct values and one missing
    space. The padded form reads as white at 100%, which is what the page
    paints.

    This is the same hazard `tinycss2`'s serializer guards with `/**/` — see
    CLAUDE.md's note on `:nth-child(3n/**/+1)` — arriving at the one place the
    library is not doing the writing.
    """
    if depth > 8 or "var(" not in value:
        return value

    def sub(m: re.Match) -> str:
        name, default = m.group(1), m.group(2)
        if name in table:
            out = resolve_vars(table[name], table, depth + 1)
        elif default:
            out = resolve_vars(default, table, depth + 1)
        else:
            return ""
        if not out:
            return out
        text = m.string
        before = text[m.start() - 1] if m.start() else ""
        after = text[m.end():m.end() + 1]
        if before and before not in _GLUE_LEFT and not out[0].isspace():
            out = " " + out
        if after and after not in _GLUE_RIGHT and not out[-1].isspace():
            out = out + " "
        return out

    prev = None
    out = value
    for _ in range(4):
        prev = out
        out = _VAR_CALL.sub(sub, out)
        if out == prev:
            break
    return out


_ZERO_LEN = re.compile(r"^0(?:[a-z%]+)?$", re.I)


def is_inert_shadow(prop: str, value: str) -> bool:
    """True for a shadow/drop-shadow whose every length is zero.

    Such a declaration is parsed and painted by the browser but is invisible,
    so the color in it is real in the source and absent from the render.
    """
    if prop not in ("box-shadow", "text-shadow", "filter", "-webkit-filter"):
        return False
    if prop in ("filter", "-webkit-filter"):
        m = re.search(r"drop-shadow\(([^)]*)\)", value, re.I)
        if not m:
            return False
        body = m.group(1)
    else:
        body = value
    # Strip colors, then look at what lengths remain.
    body = re.sub(
        r"\#[0-9a-fA-F]{3,8}|(?:rgba?|hsla?|oklch|oklab)\([^)]*\)", " ", body
    )
    lens = [t for t in re.split(r"[\s,]+", body.strip()) if t and t != "inset"]
    if not lens:
        return False
    return all(_ZERO_LEN.match(t) for t in lens)


def selector_weight(selector: str, at_rules: tuple[str, ...]) -> float:
    """How much a declaration should count toward the palette.

    Page-level selectors describe the site's ground truth; a hover state on one
    component does not. This is a heuristic, and it only ever affects ordering.
    """
    s = selector.lower().strip()
    w = 1.0

    parts = split_selector_list(s)
    base = parts[0] if parts else s

    if re.fullmatch(r"(html|body|:root)(\s*,\s*(html|body|:root))*", s):
        w = 6.0
    elif base in ("html", "body", ":root", "*"):
        w = 5.0
    elif re.match(r"^(h[1-6]|p|a|li|ul|ol|blockquote|figcaption|button|input|"
                  r"select|textarea|table|td|th|code|pre|hr|small|strong|em)\b",
                  base):
        w = 2.5
    elif base.startswith("."):
        w = 1.5
    elif base.startswith("#"):
        w = 1.2

    if re.search(r":(hover|focus|active|visited|checked|disabled)", s):
        w *= 0.4
    if "::" in s and "::part" not in s:
        w *= 0.8
    # A selector list applies in more places, so it counts for a little more.
    w *= 1.0 + min(len(parts) - 1, 6) * 0.05

    for at in at_rules:
        a = at.lower()
        if a.startswith("@media") and "print" in a:
            w *= 0.15
        elif a.startswith("@supports"):
            w *= 0.9
        elif a.startswith("@keyframes"):
            w *= 0.3
    return w


def declaration_colors(decl: Declaration, table: dict[str, str],
                       appearance: str = "light") -> list[Color]:
    """Colors in a declaration, after var() substitution."""
    value = resolve_vars(decl.value, table)
    return find_colors(value, appearance)


def parse_inline_styles(html: str, source: str,
                        sheet_order: int = 0) -> Stylesheet:
    """Colors from `style="..."` attributes."""
    sheet = Stylesheet(source=source, sheet_order=sheet_order)
    masked = strip_comments(html)
    for m in re.finditer(r"""\bstyle\s*=\s*(["'])(.*?)\1""", masked, re.S | re.I):
        # A style attribute is a declaration list, so it goes through the same
        # parser as everything else — `background:url(a;b)` has a semicolon in
        # it that is not a separator.
        decls = tinycss2.parse_blocks_contents(m.group(2), skip_comments=True,
                                               skip_whitespace=True)
        _walk(sheet, decls, source, at_rules=(), selector="[inline]", theme="",
              theme_media=False, layer="")
    return sheet


def extract_style_blocks(html: str) -> list[tuple[str, str]]:
    """Return (identifier, css) for every <style> element, in document order."""
    out = []
    for i, m in enumerate(
        re.finditer(r"<style([^>]*)>(.*?)</style>", html, re.S | re.I)
    ):
        attrs, body = m.group(1), m.group(2)
        if not body.strip():
            continue
        ident = ""
        am = re.search(r"""\bid\s*=\s*(["'])(.*?)\1""", attrs, re.I)
        if am:
            ident = am.group(2)
        label = f"<style#{ident}>" if ident else f"<style[{i}]>"
        out.append((label, body))
    return out


def extract_stylesheet_links(html: str) -> list[str]:
    """href values of <link rel=stylesheet>."""
    out = []
    for m in re.finditer(r"<link\b([^>]*)>", html, re.I):
        attrs = m.group(1)
        if not re.search(r"""rel\s*=\s*(["']?)[^"'>]*stylesheet""", attrs, re.I):
            continue
        hm = re.search(r"""\bhref\s*=\s*(["'])(.*?)\1""", attrs, re.I)
        if hm:
            out.append(hm.group(2))
    return out
