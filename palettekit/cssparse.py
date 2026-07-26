"""A small CSS reader, scoped to the job of finding colors.

This is deliberately not a general CSS parser. It needs to do three things
correctly: never read a color out of a comment or a string, keep track of which
selector and property each color came from, and follow var() chains. Everything
else about CSS it is happy to ignore.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

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


def theme_scope(selector: str, at_rules: tuple[str, ...]) -> str:
    """`light`, `dark`, or `""` for a declaration that belongs to no theme.

    The selector is consulted before the media query. A rule written `.dark .x`
    inside a `prefers-color-scheme: light` block is contradictory and
    vanishingly rare, and the explicit class is the stronger statement of the
    two.

    A selector *list* is judged as a whole, so `.dark .a, .b` is treated as
    dark-scoped even though `.b` is not. Splitting the list would be more
    accurate and is not worth the machinery: authors do not mix scoped and
    unscoped selectors in one rule.
    """
    m = (_THEME_IS.search(selector) or _THEME_CLASS.search(selector)
         or _THEME_ATTR.search(selector))
    if m:
        return m.group(1).lower()
    for at in at_rules:
        m = _THEME_MEDIA.search(at)
        if m:
            return m.group(1).lower()
    return ""


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
    """
    out = []
    for part in split_selector_list(selector):
        cleaned = _THEME_IS.sub("", part)
        cleaned = _THEME_ATTR.sub(" ", _THEME_CLASS.sub(" ", cleaned))
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


_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def strip_comments(css: str) -> str:
    return _COMMENT.sub(" ", css)


def _mask_strings(css: str) -> str:
    """Blank out string contents so `content: "#fff"` is not read as a color.

    Length is preserved so offsets stay valid for the caller.

    Outside a string a backslash begins an escape and the next character is
    literal — never a delimiter. Missing that case is not a small error: a
    Tailwind arbitrary-value class like

        .bg-\\[url\\(\\"https://…/hero.png\\"\\)\\] { background-image: … }

    carries an escaped quote *in the selector*. Reading it as the start of a
    string masks everything up to the next quote, which swallows the `{` and
    leaves the brace walker one level deep for the rest of the file. On the
    stylesheet that turned this up it cost 178 of 181 themed rules — silently,
    since the parse still succeeds and simply returns less.
    """
    out = list(css)
    i, n = 0, len(css)
    while i < n:
        ch = css[i]
        if ch == "\\":
            i += 2
            continue
        if ch in "\"'":
            quote = ch
            j = i + 1
            while j < n:
                if css[j] == "\\":
                    j += 2
                    continue
                if css[j] == quote:
                    break
                j += 1
            for k in range(i + 1, min(j, n)):
                out[k] = " "
            i = j + 1
            continue
        i += 1
    return "".join(out)


def parse_stylesheet(css: str, source: str, origin: str = "",
                     third_party: bool = False,
                     sheet_order: int = 0) -> Stylesheet:
    """Walk a stylesheet and collect every color-bearing declaration."""
    sheet = Stylesheet(source=source, origin=origin, third_party=third_party,
                       sheet_order=sheet_order)
    text = _mask_strings(strip_comments(css))

    for name in re.findall(r"var\(\s*(--[\w-]+)", text):
        sheet.var_refs.add(name)

    # Walk the brace structure, tracking the selector stack and at-rule context.
    stack: list[str] = []
    at_stack: list[str] = []
    buf = []
    i, n = 0, len(text)

    while i < n:
        ch = text[i]
        if ch == "{":
            prelude = "".join(buf).strip()
            buf = []
            if prelude.startswith("@"):
                at_stack.append(prelude)
                stack.append("")  # at-rule block: no selector of its own
            else:
                stack.append(prelude)
            i += 1
            continue
        if ch == "}":
            body = "".join(buf)
            buf = []
            sel = stack[-1] if stack else ""
            if sel:
                _collect(sheet, sel, body, source, tuple(at_stack))
            if stack:
                popped = stack.pop()
                if popped == "" and at_stack:
                    at_stack.pop()
            i += 1
            continue
        if ch == ";" and stack:
            # A declaration inside the current block, or an at-statement.
            decl = "".join(buf)
            buf = []
            sel = stack[-1]
            if sel:
                _collect(sheet, sel, decl, source, tuple(at_stack))
            i += 1
            continue
        buf.append(ch)
        i += 1

    return sheet


_DECL = re.compile(r"^\s*([\w-]+|--[\w-]+)\s*:\s*(.+?)\s*$", re.S)


def _collect(sheet: Stylesheet, selector: str, body: str, source: str,
             at_rules: tuple[str, ...]) -> None:
    # Nested blocks were handled by the walker; only flat declarations here.
    selector = " ".join(selector.split())
    # Resolved once per block rather than per declaration: the scope is a
    # property of the rule, and the regexes are not free.
    theme = theme_scope(selector, at_rules)
    for chunk in body.split(";"):
        m = _DECL.match(chunk)
        if not m:
            continue
        prop, value = m.group(1).strip().lower(), m.group(2).strip()
        if not value:
            continue
        keep = prop.startswith("--") or prop in PROPERTY_ROLE
        if not keep:
            continue
        sheet.declarations.append(
            Declaration(
                selector=selector,
                prop=prop,
                value=" ".join(value.split()),
                source=source,
                at_rules=at_rules,
                order=len(sheet.declarations),
                sheet_order=sheet.sheet_order,
                theme=theme,
            )
        )


_VAR_CALL = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*(.*?)\s*)?\)", re.S)


def resolve_vars(value: str, table: dict[str, str], depth: int = 0) -> str:
    """Substitute var() references using a name -> value table.

    Falls back to the declared default when a name is unknown, and gives up
    after a few levels so a circular definition cannot hang the run.
    """
    if depth > 8 or "var(" not in value:
        return value

    def sub(m: re.Match) -> str:
        name, default = m.group(1), m.group(2)
        if name in table:
            return resolve_vars(table[name], table, depth + 1)
        if default:
            return resolve_vars(default, table, depth + 1)
        return ""

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


def declaration_colors(decl: Declaration,
                       table: dict[str, str]) -> list[Color]:
    """Colors in a declaration, after var() substitution."""
    value = resolve_vars(decl.value, table)
    return find_colors(value)


def parse_inline_styles(html: str, source: str,
                        sheet_order: int = 0) -> Stylesheet:
    """Colors from `style="..."` attributes."""
    sheet = Stylesheet(source=source, sheet_order=sheet_order)
    masked = strip_comments(html)
    for m in re.finditer(r"""\bstyle\s*=\s*(["'])(.*?)\1""", masked, re.S | re.I):
        body = m.group(2)
        _collect(sheet, "[inline]", body, source, ())
        for name in re.findall(r"var\(\s*(--[\w-]+)", body):
            sheet.var_refs.add(name)
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


# ------------------------------------------------------------- the page element
#
# Ground detection has to know which rules actually land on the element the page
# is painted on, and a utility framework states that on the element rather than
# in the stylesheet. ground.news writes `<body class="… bg-light-primary
# dark:bg-dark-primary …">`, and those two utilities beat the `body {
# background-color: var(--background) }` rule in the site's own CSS on
# specificity — so the palette's ground is `#eeefe9`/`#262626`, not the
# `#ffffff`/`#0a0a0a` that `--background` resolves to.
#
# Nothing in the stylesheet distinguishes `.bg-light-primary` (on the body) from
# `.bg-dark-primary` (on some card); the class attribute is the only place that
# information exists. This is still reading CSS — it just reads which rules the
# document selects, rather than assuming only `html`/`body`/`:root` can.


@dataclass
class PageElement:
    """`<html>` or `<body>` as the document actually wrote it."""
    tag: str
    id: str = ""
    classes: frozenset = frozenset()
    attrs: dict = field(default_factory=dict)


_TAG_ATTR = re.compile(r"""([\w:-]+)\s*(?:=\s*(?:(["'])(.*?)\2|([^\s"'>]+)))?""",
                       re.S)
_IDENT_ESC = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\r\n]?|(.))", re.S)


def unescape_ident(name: str) -> str:
    """A CSS identifier as the HTML class attribute spells it.

    Selectors escape anything that would otherwise be syntax, so Tailwind's
    `dark:bg-x` class is *written* `.dark\\:bg-x` — and both escape forms turn
    up in the wild, `\\:` and the hex `\\3a `. Comparing without unescaping
    fails to match and silently falls back to a worse ground.
    """
    def sub(m: re.Match) -> str:
        hexits, ch = m.group(1), m.group(2)
        if hexits:
            cp = int(hexits, 16)
            # A null escape is a replacement character per CSS Syntax 3.
            return chr(cp) if cp else "�"
        return ch or ""
    return _IDENT_ESC.sub(sub, name)


def page_elements(html: str) -> list[PageElement] | None:
    """`<html>` and `<body>` as this document wrote them, or None.

    None means the tags could not be read at all — a truncated or non-HTML
    document. That is deliberately distinct from an element with no classes:
    the second says the body carries nothing, and the first says we do not
    know, and treating "unknown" as "nothing" would state a ground confidently
    on no evidence.
    """
    found = []
    for tag in ("html", "body"):
        m = re.search(rf"<{tag}\b([^>]*)>", html, re.I)
        if not m:
            continue
        el = PageElement(tag=tag)
        for am in _TAG_ATTR.finditer(m.group(1)):
            name = am.group(1).lower()
            value = am.group(3) if am.group(3) is not None else (am.group(4) or "")
            if name == "class":
                el.classes = frozenset(value.split())
            elif name == "id":
                el.id = value
            else:
                el.attrs[name] = value
        found.append(el)
    return found or None


# One simple selector at a time. A combinator — or anything else this does not
# know — simply fails to match at its position, which ends the walk and rejects
# the selector. That is the intended behaviour: `.foo .bar` is a rule about a
# descendant of the body, not about the body.
_SIMPLE = re.compile(r"""
      (?P<tag>^[A-Za-z][\w-]*)
    | \.(?P<cls>(?:[\w-]|\\[0-9a-fA-F]{1,6}[ \t]?|\\.)+)
    | \#(?P<id>(?:[\w-]|\\[0-9a-fA-F]{1,6}[ \t]?|\\.)+)
    | \[\s*(?P<attr>[\w:-]+)\s*
      (?:(?P<op>[~|^$*]?=)\s*(?P<val>"[^"]*"|'[^']*'|[^\]]*?)\s*)?\]
    | (?P<pseudo>::?[\w-]+(?:\([^)]*\))?)
""", re.X)


def matches_page_element(selector: str,
                         elements: list[PageElement] | None) -> bool:
    """Does this selector select `<html>` or `<body>` in this document?

    Narrow on purpose. It answers only for a single compound with no
    combinator, and rejects any pseudo-class other than `:root`, because a rule
    that applies on `:hover` is not the page's resting background. Anything
    less certain than "this definitely paints the page element" should return
    False and let the ordinary page-selector pattern have the last word.
    """
    if not elements:
        return False

    sel = selector.strip()
    if not sel:
        return False

    tag = ""
    ids: set = set()
    classes: set = set()
    attrs: list = []
    pos = 0
    while pos < len(sel):
        m = _SIMPLE.match(sel, pos)
        if not m:
            return False           # a combinator, or syntax we do not model
        if m.group("tag"):
            tag = m.group("tag").lower()
        elif m.group("cls"):
            classes.add(unescape_ident(m.group("cls")))
        elif m.group("id"):
            ids.add(unescape_ident(m.group("id")))
        elif m.group("attr"):
            val = (m.group("val") or "").strip("\"'")
            attrs.append((m.group("attr").lower(), m.group("op"), val))
        else:
            pseudo = m.group("pseudo").lower()
            if pseudo != ":root":
                return False       # conditional, or an element we cannot see
            tag = tag or "html"
        pos = m.end()

    if tag and tag not in ("html", "body"):
        return False

    for el in elements:
        if tag and tag != el.tag:
            continue
        if not classes <= el.classes:
            continue
        if ids and ids != {el.id}:
            continue
        if any(not _attr_matches(el, *a) for a in attrs):
            continue
        return True
    return False


def _attr_matches(el: PageElement, name: str, op: str | None, val: str) -> bool:
    have = el.id if name == "id" else el.attrs.get(name)
    if have is None:
        return False
    if op is None:
        return True
    if op == "=":
        return have == val
    if op == "~=":
        return val in have.split()
    if op == "|=":
        return have == val or have.startswith(val + "-")
    if op == "^=":
        return have.startswith(val)
    if op == "$=":
        return have.endswith(val)
    if op == "*=":
        return val in have
    return False


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
