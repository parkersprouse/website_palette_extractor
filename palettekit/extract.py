"""Turning a pile of CSS into a ranked, named palette.

The ordering here is a heuristic and is meant to be argued with: it weights a
color by where it is used, not just how often it appears. A background on
`body` says more about a site than a border color on one hover state, even if
the hover rule is repeated more times.
"""
from __future__ import annotations

import re
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field

from .color import Color, contrast_ratio, delta_ok, hue_name, wcag_label
from .cssparse import (
    Stylesheet,
    is_inert_shadow,
    parse_inline_styles,
    parse_stylesheet,
    resolve_vars,
    selector_weight,
    split_selector_list,
    var_refs,
)
from .dom import (
    PageElement,
    element_signature,
    elements_matching_wrapped,
    full_tree,
    matches_page_element,
    page_elements,
    reach_elements,
    selector_matches,
    selector_reach,
    selector_specificity,
    untestable_reason,
    wrap_tree,
)
from .sources import Bundle

# Above this OKLab chroma a color is treated as having a real hue rather than
# being a tinted grey. Deliberately higher than Color.is_neutral: that answers
# "is this achromatic", this answers "would a person call this a color".
MUTED_CHROMA = 0.06

# T19: how many real matched elements to name per usage. `match_count` is the
# true total; this only bounds the sample kept for display, the same
# "bounded number of them" PLAN.md's own sketch of this task calls for.
# Kept small deliberately — measured against tailwindcss.com and
# ui.shadcn.com, each `examples` entry can carry up to 6 usages, and each
# sample string is itself bounded (`dom.element_signature`'s own `max_len`)
# but not free; this is the other half of keeping the payload growth this
# task adds proportionate rather than doubling the document.
MATCH_SAMPLES = 2

# Role ordering for display and for naming.
ROLE_ORDER = ["surface", "text", "line", "shadow", "graphic", "ui", "token",
              "other"]


@dataclass
class Usage:
    selector: str
    prop: str
    value: str
    source: str
    weight: float
    role: str
    third_party: bool
    inert: bool = False
    sheet_order: int = 0
    order: int = 0
    # The selector as it reads from inside its own theme, with any marker
    # removed. What the declaration is *matched* on; `selector` is what it is
    # scored on. See `_page_specificity` for why those differ.
    scope_selector: str = ""
    # Cascade terms carried over from the declaration, so `detect_ground` can
    # rank a usage without going back to the stylesheet.
    important: bool = False
    layer: str = ""
    theme_media: bool = False
    # Whether the declaration was written for this theme specifically — by
    # either mechanism, selector or media (`bool(d.theme)`) — rather than
    # belonging to every theme by being unscoped. Not a cascade term; used
    # only by `detect_ground`'s html/body pooling (T7) to tell a real
    # theme-specific claim on `<html>` apart from an unscoped `<body>` rule
    # that merely happens to also be present in this theme's build.
    theme_scoped: bool = False
    # T18: does `scope_selector` match a real element in the captured
    # document? `True`/`False` mean it was actually tested; `None` means it
    # could not be (no captured HTML, or `dom.selector_reach`'s own "no
    # basis" cases — see that function). `Entry.all_unmatched` only trusts
    # this when every usage in the entry got a determinate `False`; a `None`
    # anywhere in the mix leaves the entry `live`, same "refuse rather than
    # guess" contract as everywhere else this tool won't answer on no
    # evidence.
    matched: bool | None = None
    # T19: how many real elements `scope_selector` actually reached, and a
    # bounded sample of which ones. `None` mirrors `matched`'s own "no basis"
    # case rather than reading as zero — `match_count` is only ever an int
    # when `matched` is determinate (`True` or `False`), never when it's
    # `None`. `match_samples` is capped at build time (see `_build`), not
    # here, so `Usage` stays a plain record of what was already decided.
    match_count: int | None = None
    match_samples: list[str] = field(default_factory=list)
    # T24: why `matched` is `None`, when it is. `dom.untestable_reason`'s two
    # causes, plus a third this module alone knows about — no captured HTML
    # at all, which never reaches `dom.selector_reach` to begin with.
    # `None` here whenever `matched` is determinate (`True`/`False`); never
    # consulted otherwise. See `Entry.all_dynamic_only` for why the three
    # must stay distinguishable rather than folding into one flag.
    reach_reason: str | None = None


@dataclass
class Entry:
    color: Color
    usages: list[Usage] = field(default_factory=list)
    var_names: set[str] = field(default_factory=set)
    merged_hexes: set[str] = field(default_factory=set)

    # assigned later
    name: str = ""
    group: str = ""
    status: str = "live"
    role: str = "other"

    @property
    def score(self) -> float:
        return sum(u.weight for u in self.usages)

    @property
    def count(self) -> int:
        return len(self.usages)

    @property
    def roles(self) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for u in self.usages:
            out[u.role] += u.weight
        return dict(out)

    @property
    def primary_role(self) -> str:
        r = self.roles
        if not r:
            return "other"
        return max(r.items(), key=lambda kv: (kv[1], -ROLE_ORDER.index(kv[0])
                                              if kv[0] in ROLE_ORDER else 0))[0]

    @property
    def all_inert(self) -> bool:
        return bool(self.usages) and all(u.inert for u in self.usages)

    @property
    def all_unmatched(self) -> bool:
        """T18: every usage's selector was tested and matched nothing.

        `u.matched is False` rather than `not u.matched`, on purpose — a
        `None` (no basis: untestable selector, or no captured HTML at all)
        must not read as "unmatched" just because it is falsy. One `None`
        anywhere in the usages means this entry stays whatever `_status_for`
        would otherwise call it; only a unanimous, determinate `False`
        across every usage is confident enough to report.
        """
        return bool(self.usages) and all(u.matched is False
                                         for u in self.usages)

    @property
    def all_dynamic_only(self) -> bool:
        """T24: does this color's `live` status rest entirely on ground that
        can never be confirmed, by any capture however complete — not merely
        ground that hasn't been confirmed yet.

        Unanimous, the same pattern `all_unmatched` (invariant 27) already
        established: one ordinary matching usage, or even one merely
        `unmatched` one, alongside a `:hover`-only usage means this color is
        painted (or at least tested) on some non-dynamic basis, so the whole
        entry no longer rests entirely on interaction state.

        Checks `u.reach_reason == "dynamicState"` specifically, not "was
        `matched` `None`" — deliberately narrower, per T24's own filing.
        `matched is None` also covers an uncompilable selector (a library
        coverage gap, T21's own territory: some other engine might answer
        it, so it is undertested, not unknowable) and a bare `.css` input
        with no captured HTML at all (uninteresting here — the whole
        document is unconfirmed, singling out one color would be noise).
        Both leave `reach_reason` as something other than `"dynamicState"`,
        so they correctly fail this check rather than falsely qualifying.
        """
        return bool(self.usages) and all(u.reach_reason == "dynamicState"
                                         for u in self.usages)

    @property
    def only_third_party(self) -> bool:
        return bool(self.usages) and all(u.third_party for u in self.usages)


@dataclass
class Palette:
    page_url: str = ""
    ground: Color = field(default_factory=lambda: Color(255, 255, 255))
    ground_source: str = "default"
    entries: list[Entry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    image_report: dict | None = None

    # Themes. `theme_id` is named for the scope that produced the palette
    # ("base", "light", "dark"); `appearance` is what it actually looks like,
    # measured from the ground. The two disagree on a dark-by-default site
    # whose alternate theme is the light one, which is why both exist: the id
    # is how the palette is addressed, the appearance is how it is labelled.
    theme_id: str = "base"
    theme_scope: str = ""
    alternate: Palette | None = None

    @property
    def appearance(self) -> str:
        # Same threshold `_pick_report_theme` uses to decide which way to run
        # the report's own contrast ramp.
        return "dark" if self.ground.luminance() < 0.4 else "light"


def collect_sheets(bundle: Bundle, include_third_party: bool = True,
                   only: list[str] | None = None,
                   exclude: list[str] | None = None) -> list[Stylesheet]:
    """Parse every stylesheet, in the order the document actually applies them.

    Order matters: later rules win, so a palette that ignores it will happily
    report a framework's default background as the page background. The list is
    built by walking the HTML for <style> and <link rel=stylesheet> together,
    then matching each link against what was actually fetched.
    """
    sheets: list[Stylesheet] = []
    page_origin = bundle.page_origin
    css_by_url = {a.url: a for a in bundle.by_kind("css")}
    consumed: set[str] = set()
    n = 0

    def keep(source: str) -> bool:
        low = source.lower()
        if only and not any(t.lower() in low for t in only):
            return False
        return not (exclude and any(t.lower() in low for t in exclude))

    for asset in bundle.by_kind("html"):
        for label, payload, kind in _document_order(asset.text):
            if kind == "style":
                if not keep(label):
                    continue
                sheets.append(parse_stylesheet(
                    payload, source=label, origin=page_origin,
                    third_party=False, sheet_order=n))
                n += 1
            else:  # link
                match = _match_href(payload, asset.url, css_by_url)
                if match is None:
                    continue
                third = bool(page_origin and match.origin
                             and match.origin != page_origin)
                if third and not include_third_party:
                    consumed.add(match.url)
                    continue
                if not keep(match.url):
                    consumed.add(match.url)
                    continue
                sheets.append(parse_stylesheet(
                    match.text, source=match.url, origin=match.origin,
                    third_party=third, sheet_order=n))
                consumed.add(match.url)
                n += 1

    # Anything fetched but not linked in the markup — injected at runtime, or
    # a bare directory of CSS files. It applies, we just cannot place it.
    for asset in bundle.by_kind("css"):
        if asset.url in consumed:
            continue
        third = bool(page_origin and asset.origin
                     and asset.origin != page_origin)
        if third and not include_third_party:
            continue
        if not keep(asset.url):
            continue
        sheets.append(parse_stylesheet(
            asset.text, source=asset.url, origin=asset.origin,
            third_party=third, sheet_order=n))
        n += 1

    # Inline style attributes beat every stylesheet, so they go last.
    for asset in bundle.by_kind("html"):
        inline = parse_inline_styles(asset.text, source="[style attributes]",
                                     sheet_order=n)
        if inline.declarations and keep("[style attributes]"):
            sheets.append(inline)
            n += 1

    return sheets


_STYLE_OR_LINK = re.compile(
    r"<style([^>]*)>(.*?)</style>|<link\b([^>]*)>", re.S | re.I
)


def _document_order(html: str):
    """Yield (label, payload, kind) for style blocks and stylesheet links."""
    idx = 0
    for m in _STYLE_OR_LINK.finditer(html):
        if m.group(2) is not None:
            attrs, body = m.group(1), m.group(2)
            if not body.strip():
                continue
            ident = ""
            am = re.search(r"""\bid\s*=\s*(["'])(.*?)\1""", attrs, re.I)
            if am:
                ident = am.group(2)
            label = f"<style#{ident}>" if ident else f"<style[{idx}]>"
            idx += 1
            yield (label, body, "style")
        else:
            attrs = m.group(3) or ""
            if not re.search(r"""rel\s*=\s*(["']?)[^"'>]*stylesheet""",
                             attrs, re.I):
                continue
            hm = re.search(r"""\bhref\s*=\s*(["'])(.*?)\1""", attrs, re.I)
            if hm:
                yield (hm.group(2), hm.group(2), "link")


def _match_href(href: str, base_url: str, css_by_url: dict):
    """Find the fetched asset a <link href> refers to."""
    if href in css_by_url:
        return css_by_url[href]
    try:
        absolute = urllib.parse.urljoin(base_url, href)
    except ValueError:
        absolute = href
    if absolute in css_by_url:
        return css_by_url[absolute]
    # HARs sometimes differ in scheme or trailing query; fall back to path.
    tail = href.split("?")[0].rstrip("/").split("/")[-1]
    if tail:
        for url, asset in css_by_url.items():
            if url.split("?")[0].rstrip("/").endswith("/" + tail):
                return asset
    return None


# ------------------------------------------------------------------- cascade
#
# `importance → layer → specificity → document order`, which is the real thing
# rather than the approximation of it this used to carry. Two call sites use
# it and only two: `detect_ground`, to pick the color the page sits on, and
# `build_var_table`, to pick what a custom property resolves to. Everything
# else about ordering a palette is `selector_weight`, which is a *usage
# heuristic* and deliberately not this — invariant 2's warning is about that
# function, and the two do not conflict.


def layer_order(sheets: list[Stylesheet]) -> dict[str, int]:
    """Map every `@layer` name to its position in the document's layer order.

    Layers are global to the document, not to a sheet: a sheet that opens
    `@layer utilities { … }` is filling in the layer another sheet reserved, so
    the order is the order of *first mention* anywhere, walking sheets in
    document order.

    A sub-layer cascades inside its parent, which a flat first-mention list
    gets wrong: `@layer a; @layer b; @layer a.x` mentions `a.x` last, but it
    belongs between `a` and `b`. Sorting each name by the chain of its
    ancestors' positions puts it back where it goes.

    **`@import url(…) layer(x)` reserves `x`'s position (T8, `PLAN.md`), but
    the imported sheet itself is still not modelled**, because `@import` is
    not followed at all — `cssparse._walk` registers the name straight off
    the `layer(...)` `FunctionBlock` in the `@import`'s own prelude, the same
    way the `@layer a, b;` statement form reserves a position with no block
    yet to fill it. What's still missing is the *content*: the imported
    sheet is fetched separately if at all, and arrives with no memory of the
    layer it was imported into, so a site that layers exclusively through
    `@import` gets the position right but reads as contributing no
    declarations to it — the same answer this gave before layers existed,
    just no longer silently dropping the reservation too.
    """
    seen: list[str] = []
    for sheet in sorted(sheets, key=lambda s: s.sheet_order):
        for name in sheet.layers:
            if name not in seen:
                seen.append(name)
    at = {name: i for i, name in enumerate(seen)}

    def path(name: str) -> tuple[int, ...]:
        parts = name.split(".")
        return tuple(at.get(".".join(parts[:i + 1]), len(seen))
                     for i in range(len(parts)))

    return {name: i for i, name in enumerate(sorted(seen, key=path))}


def property_registrations(
    sheets: list[Stylesheet],
) -> dict[str, tuple[str | None, str | None]]:
    """Map every `@property`-registered custom property to (inherits, initial).

    T22 (`PLAN.md`). Global to the document like `layer_order`'s names — a
    sheet re-registering the same property simply overrides an earlier one,
    with no cascade of its own (the spec gives `@property` no precedence
    rules beyond "later wins"), so a plain dict merge in document order is
    exact rather than an approximation the way it would be for anything
    cascade-ranked.
    """
    regs: dict[str, tuple[str | None, str | None]] = {}
    for sheet in sorted(sheets, key=lambda s: s.sheet_order):
        regs.update(sheet.properties)
    return regs


def _layer_rank(layer: str, layers: dict[str, int], important: bool) -> int:
    """Where a declaration's layer puts it, as one sortable number.

    Unlayered normal declarations beat every layer, and later layers beat
    earlier ones. For `!important` declarations the spec **reverses** the whole
    ordering: an earlier layer wins, and an unlayered important declaration is
    the weakest important one there is. That reversal is the reason importance
    cannot be bolted on as a simple tiebreak — it changes what the next term
    means — and it is why this is all four terms or none.
    """
    n = len(layers)
    if important:
        return -(n + 1) if not layer else -layers.get(layer, n)
    return n if not layer else layers.get(layer, n)


def _cascade_key(d, specificity: tuple[int, int, int],
                 layers: dict[str, int]) -> tuple:
    """The full ordering key. Bigger wins.

    Takes a `Declaration` or a `Usage` — both carry the same five terms, and
    the two call sites hold one each.

    The theme term sits **between specificity and document order**, and that
    placement is the whole of what is left of invariant 2's theme addendum. A
    `prefers-color-scheme: dark` block writing `body { background: … }` has to
    beat a later unscoped `body` rule, because a browser applying the dark
    theme applies it — but it has to *lose* to an unscoped `.bg-x` that the
    body actually carries, because a browser does that too. Putting the term
    above specificity would win the first case and get the second backwards.

    Selector-scoped themes need no term at all: `html.dark` is `(0, 1, 2)`
    against `html`'s `(0, 0, 1)`, so specificity already says it. That half of
    the addendum is now a consequence rather than a rule.
    """
    return (
        1 if d.important else 0,
        _layer_rank(d.layer, layers, d.important),
        specificity,
        1 if d.theme_media else 0,
        d.sheet_order,
        d.order,
    )


def _page_element_tag(part: str) -> str | None:
    """Which element a `_PAGE_SEL` text match actually styles, or None.

    A selector reads right to left — `html body` is body's rule, scoped to a
    body that lives inside html — so the last token is the one being styled.
    `:root` is the same element as `<html>` in a document with no shadow root.
    Returns None for anything `_PAGE_SEL` itself would refuse, which callers
    fall back to `matches_page_element` for.
    """
    if not _PAGE_SEL.match(part):
        return None
    tokens = part.split()
    return "body" if tokens[-1].lower() == "body" else "html"


def _reaches(part: str, page: list[PageElement] | None, element: str) -> bool:
    """Does this selector-part reach *this specific* page element?"""
    tag = _page_element_tag(part)
    if tag is not None:
        return tag == element
    only = [el for el in (page or []) if el.tag == element]
    return matches_page_element(part, only)


def _page_specificity(selector: str, scope_selector: str,
                      page: list[PageElement] | None,
                      element: str | None = None
                      ) -> tuple[int, int, int] | None:
    """Specificity of this rule *as it applies to the page element*, or None.

    None means the rule does not reach `<html>` or `<body>` at all, and that is
    the cascade's own first step: only declarations from rules that match the
    element are ranked against each other. It is the reason invariant 19
    survives phase 3 rather than dissolving into specificity — `:root` and
    `[data-bs-theme=blue]` are *both* `(0, 1, 0)`, so specificity cannot
    separate them and never could. What separates them is that the document's
    `<html>` carries no `data-bs-theme=blue`, so Bootstrap's blue block is not
    a candidate for the page background in the first place.

    Two selector strings go in, and the split is deliberate. Matching runs on
    `scope_selector`, the selector as it reads from inside its own theme, since
    that is the form this tool's theme model recognises — `html.dark body` has
    to be seen as the dark theme's `body` rule. Specificity is read off the
    selector **as declared**, because that is what a browser counts: the marker
    is part of the selector and earns the theme its precedence. Keeping both is
    what makes a selector-scoped theme outrank what it overrides without any
    rule saying so.

    `split_selector_list` yields the two lists in step — `strip_theme_scope`
    emits one cleaned part per part it was given — so the parts pair up by
    position. If they ever did not, the matched form is scored instead, which
    understates the theme rather than inventing precedence for it.

    `element` narrows the match to one of `"html"`/`"body"` (T7): passing None
    keeps the old either-element behaviour, which is what `build_var_table`
    still wants — a custom property is not "the page's background", so there
    is no body-over-html preference to apply to it. `detect_ground` is the one
    caller that needs the split, into two pools it resolves separately.
    """
    matched = split_selector_list(scope_selector or selector)
    declared = split_selector_list(selector)
    if len(declared) != len(matched):
        declared = matched

    best = None
    for raw, part in zip(declared, matched, strict=False):
        if element is None:
            ok = _PAGE_SEL.match(part) or matches_page_element(part, page)
        else:
            ok = _reaches(part, page, element)
        if not ok:
            continue
        spec = selector_specificity(raw)
        if best is None or spec > best:
            best = spec
    return best


def _var_populations(sheets: list[Stylesheet], theme: str,
                     page: list[PageElement] | None,
                     layers: dict[str, int]
                     ) -> tuple[dict[str, tuple[tuple, str]], dict[str, list]]:
    """Split custom-property definitions into page-reaching and off-page.

    Factored out of `build_var_table` so `resolve_by_ancestry` (T9) can get
    at the off-page population's *candidate declarations*, which
    `build_var_table` itself collapses to last-wins and discards. Behaviour
    for `build_var_table`'s own callers is unchanged — this is the same
    split, same iteration order, same last-wins-by-overwrite for the off-page
    side (`off_page[prop]` is a list in *declaration order*, so `[-1].value`
    reproduces what used to be a live dict overwrite).

    See `build_var_table`'s own docstring for why the split exists at all
    (invariant 19) and why the page-reaching side alone is cascade-resolved.
    """
    rooted: dict[str, tuple[tuple, str]] = {}
    off_page: dict[str, list] = {}
    for pass_theme in ("", theme) if theme else ("",):
        for sheet in sheets:
            for d in sheet.declarations:
                if not d.is_custom_property or d.theme != pass_theme:
                    continue
                spec = _page_specificity(d.selector,
                                         d.themed_selector or d.selector, page)
                if spec is None:
                    off_page.setdefault(d.prop, []).append(d)
                    continue
                key = _cascade_key(d, spec, layers)
                current = rooted.get(d.prop)
                if current is None or key > current[0]:
                    rooted[d.prop] = (key, d.value)
    # A name can appear in both passes — off-page in the unscoped pass, then
    # page-reaching once the theme's own rule is considered. `rooted` wins the
    # merge either way (`build_var_table` below), but T9's ancestry walk must
    # not treat a property as off-page-only when some definition of it *does*
    # reach the page — that candidate set is a genuinely different question
    # (the cascade already answered it) and ancestry has no business
    # overriding a page-reaching answer.
    for name in rooted:
        off_page.pop(name, None)
    return rooted, off_page


def _substitute_registered_initials(
    table: dict[str, str],
    properties: dict[str, tuple[str | None, str | None]],
) -> dict[str, str]:
    """Replace a stored literal `initial` with its `@property` initial-value.

    T22 (`PLAN.md`), invariant 26's own extension. `initial` on an
    *unregistered* custom property is the guaranteed-invalid value
    `cssparse._resolve_var` already treats as absent — correct, because an
    unregistered property has no defined value to reset to. But
    `@property --x { inherits: false; initial-value: #fff }` gives `initial`
    on `--x` a concrete, spec-defined value: it is not guaranteed-invalid at
    all, so `var(--x, fallback)` must substitute `#fff`, not the fallback and
    not nothing. Rewriting the table here — once, before it ever reaches
    `resolve_vars` — means `_resolve_var`'s existing "stored is literally
    initial" branch never has to learn about registrations: by the time it
    runs, the table simply no longer says `initial` for a property that has
    a real one.
    """
    if not properties:
        return table
    out = table
    for name, value in table.items():
        if value.strip().lower() != "initial":
            continue
        reg = properties.get(name)
        if reg and reg[1] is not None and reg[1].strip():
            if out is table:
                out = dict(table)
            out[name] = reg[1]
    return out


def _merge_var_populations(
    rooted: dict[str, tuple[tuple, str]],
    off_page: dict[str, list],
    properties: dict[str, tuple[str | None, str | None]] | None = None,
) -> dict[str, str]:
    table = {**{name: decls[-1].value for name, decls in off_page.items()},
            **{k: v for k, (_key, v) in rooted.items()}}
    return _substitute_registered_initials(table, properties or {})


def build_var_table(sheets: list[Stylesheet], theme: str = "",
                    page: list[PageElement] | None = None,
                    layers: dict[str, int] | None = None,
                    properties: dict[str, tuple[str | None, str | None]] | None = None,
                    ) -> dict[str, str]:
    """Map custom property name to its value, as seen from within one theme.

    Two populations, and the split between them is the cascade's first step
    rather than a heuristic. A definition whose rule **reaches the page
    element** — `:root`, `html`, `body`, or a class the document actually
    carries — is a candidate for what the page computes, and those are resolved
    against each other by the full cascade. A definition that reaches no page
    element is not a candidate at all, and the two never compete.

    That is invariant 19, and phase 3 does not retire it: specificity cannot
    do this job, because `:root` and `[data-bs-theme=blue]` are both `(0, 1, 0)`
    and the blue block is written later. Bootstrap's own docs ship exactly that
    rule setting `--bs-body-bg: var(--bs-blue)`, and ranking the two would
    report the page background as Bootstrap blue. They are not ranked, because
    the document's `<html>` carries no `data-bs-theme=blue`. What phase 3
    changed here is only how the *page-reaching* set is resolved: by
    `importance → layer → specificity → order` instead of by last-wins.

    Off-page definitions stay on last-wins, deliberately. They are a fallback —
    a property consumed only by `.btn` is still worth resolving — and ranking
    declarations that match different elements by specificity would be
    comparing things the cascade never compares. (T9's ancestry walk, where
    wired in, overrides this last-wins fallback for one specific consuming
    declaration at a time — see `resolve_by_ancestry_kind` — never the table
    itself, which stays this shape for every other caller.)

    Theme scoping filters both populations: declarations scoped to any *other*
    theme are not visible here at all, and the passes run unscoped-first so
    that the off-page fallback still prefers this theme's own definitions.
    """
    layers = layers or {}
    rooted, off_page = _var_populations(sheets, theme, page, layers)
    return _merge_var_populations(rooted, off_page, properties)


def resolve_by_ancestry(candidates: list, consumer_elements: list,
                        layers: dict[str, int],
                        non_inheriting: bool = False) -> str | None:
    """The value real inheritance gives, for one property, one consumer.

    T9 (`PLAN.md`). `build_var_table`'s `scoped` population resolves an
    off-page custom property by last-wins across the whole document, which
    conflates two shapes that read identically in selector text: `.theme-a {
    --card: red }` meant to be read by an *ancestor's* descendants through
    inheritance, and `.shimmer-none { --shimmer-image: none }` meant to
    override a property on the *same* element a sibling utility sits on.
    Nothing in the selector distinguishes them — the answer lives in the real
    document tree, specifically in whether the class a candidate targets is
    an ancestor of, or identical to, the element consuming the `var()`. That
    tree is `full_tree`'s (`dom.py`), not `page_elements`'s.

    The walk starts at the consumer element itself (self counts as its own
    nearest ancestor) and moves upward. At each level it asks which
    candidates match *this specific element*, cascade-resolves among any
    that do — a level can have more than one candidate, the same as
    `build_var_table`'s rooted pool does for the page element — and stops at
    the first level with an answer, because a value set closer to the
    consumer always shadows one set further up; a real browser never looks
    past the nearest ancestor that sets the property. `candidates` must
    already be filtered to the right property name and theme by the caller,
    the same precondition `build_var_table`'s own loop enforces on itself.

    **A blanket selector (`*`) is not filtered out here the way
    `dom._is_blanket` filters it for page-level candidates.** At the
    consumer's own element — the first level this walk checks — a `*`
    candidate always matches, which would make it win outright over every
    real ancestor definition purely by walk order, the same mistake
    invariant 16 exists to prevent for the page element. Not yet decided
    whether the fix is the same one (test against a nondescript element) or
    something specific to inheritance, since a blanket rule *is* meaningfully
    different here — every element inherits from it, which is arguably
    correct rather than a false positive. Flagged rather than silently
    handled either way: no corpus site's `--card`-shaped case reaches this
    yet (Tailwind's own blanket-selector custom properties are non-color
    reset values, invariant 16's own finding), but a test should exist before
    this is trusted on real color tokens.

    **One consuming declaration can paint several real elements with
    genuinely different answers** — a `.bg-card` under one `.theme-neutral`
    wrapper and another under `.theme-blue`. This function does not pick one
    arbitrarily: it returns the value only if every consumer element agrees,
    and `None` if they disagree. A caller wanting the *per-element* answers
    instead of one collapsed value needs different plumbing than this
    function provides — see `PLAN.md` T9's own note on what remains before
    this is wired into `build_var_table`/`resolve_vars`'s single-table model,
    which assumes one resolved value per property per theme, not per element.
    """
    values = {v for v in
             _ancestry_winners(candidates, consumer_elements, layers,
                               non_inheriting)
             if v is not None}
    if len(values) == 1:
        return values.pop()
    return None


def _ancestry_winners(candidates: list, consumer_elements: list,
                      layers: dict[str, int],
                      non_inheriting: bool = False) -> list[str | None]:
    """One winner per consumer element — `None` where no ancestor matches.

    The walk itself, shared by `resolve_by_ancestry` (which collapses this to
    a single agreed value or refuses) and `resolve_by_ancestry_kind` (T9's
    pipeline wiring, which needs to tell "no candidate anywhere" apart from
    "consumers disagree" — both collapse to the same `None` above, but only
    one of them is safe to treat as a confirmed answer).

    **`non_inheriting` stops the walk at the consumer element itself** (T22,
    `PLAN.md`) — set when `@property` registers the property `inherits:
    false`. Real CSS inheritance never hands such a property down from an
    ancestor at all, so looking past self is answering a question the
    property's own registration says doesn't apply, and it is not merely
    theoretical: on `ui.shadcn.com.har`, `--tw-ring-color`/`--tw-ring-shadow`
    (both `inherits: false`) were resolving from an unrelated ancestor
    12-14 levels up — some other element's `.ring-*` utility leaking onto a
    descendant that carries no ring styling of its own — because the
    document-wide reset that would otherwise supply a same-element answer
    sits behind a selector list `cssselect2` cannot fully compile
    (`*,:before,:after,::backdrop` — `::backdrop` is an unsupported
    pseudo-element, and a single bad branch fails the whole list, a
    separate, undiagnosed gap; see `PLAN.md` T22's write-up). Restricting
    non-inheriting properties to self-only is the spec-correct fix
    regardless of that detail: it also happens to be what keeps a
    borrowed-from-nowhere ancestor value from ever being considered.
    """
    winners: list[str | None] = []
    for consumer_el in consumer_elements:
        winner = None
        levels = ((consumer_el,) if non_inheriting
                 else (consumer_el, *consumer_el.ancestors))
        for el in levels:
            best = None
            for d in candidates:
                spec = selector_matches(d.themed_selector or d.selector, el)
                if spec is None:
                    continue
                key = _cascade_key(d, spec, layers)
                if best is None or key > best[0]:
                    best = (key, d.value)
            if best is not None:
                winner = best[1]
                break
        winners.append(winner)
    return winners


def resolve_by_ancestry_kind(candidates: list, consumer_elements: list,
                             layers: dict[str, int],
                             non_inheriting: bool = False,
                             ) -> tuple[str, str | None]:
    """`resolve_by_ancestry`, but keeping the two outcomes it collapses to `None`
    apart — `("value", v)`, `("absent", None)`, or `("disagree", None)`.

    T9's pipeline wiring (`_build`) needs this distinction and
    `resolve_by_ancestry` does not expose it, deliberately: that function's
    existing contract and tests are untouched by this one's addition.

    **Only "value" and "absent" are safe to use as an override over
    last-wins.** "Absent" means every real consumer element was visited and
    none has an ancestor (or itself) setting the property at all — a
    confirmed answer, and last-wins is answering about the wrong element in
    that case, so it should lose. "Disagree" means two real elements
    genuinely resolve to two different values; today's single
    value-per-theme table has no way to hold both, so the honest move is to
    leave last-wins alone rather than pick one arbitrarily — the same
    "refuse rather than guess" contract `resolve_by_ancestry` already keeps.

    **A consumer element with no ancestor match is not itself treated as
    disagreement** when at least one other consumer element resolves to a
    real value — it is read as "no evidence from this element", not "this
    element votes for absence". `resolve_by_ancestry`'s own collapse already
    has this shape (`values` only ever collects non-`None` winners), so this
    keeps the two functions answering the same question the same way rather
    than only agreeing by coincidence on the cases both happen to test.
    Deliberate, not incidental: a value defined on one real ancestor is
    still real evidence even if a second consumer element this same
    declaration also paints happens to sit outside any matching ancestor.
    Pinned by `test_one_consumer_with_no_ancestor_match_does_not_read_as_disagreement`.
    """
    winners = _ancestry_winners(candidates, consumer_elements, layers,
                                non_inheriting)
    values = {v for v in winners if v is not None}
    if len(values) == 1:
        return "value", values.pop()
    if not values:
        return "absent", None
    return "disagree", None


def _page_color_scheme(sheets: list[Stylesheet], page: list[PageElement] | None,
                       layers: dict[str, int], table: dict[str, str]) -> str:
    """The cascade-resolved *unscoped* `color-scheme` value reaching the page, or "".

    T10 (`PLAN.md`). `light-dark()` resolves against the *used* `color-scheme`,
    not against whatever the OS prefers, and a page that never declares one
    renders the light branch regardless — see invariant 23's own overreach
    caveat. This reuses the exact page-reach-then-cascade machinery
    `build_var_table` uses for custom properties (invariant 19's
    `_page_specificity`/`_cascade_key`), applied to one ordinary property
    instead of the whole custom-property population.

    Unscoped-only (`d.theme == ""`) on purpose, and still is after T26: a
    `prefers-color-scheme`/OS-driven site (MDN, pawelgrzybek.com) states its
    confirmation this way, and it is genuinely one page-level value with one
    cascade winner. A *selector*-theme-scoped `color-scheme` declaration
    (`[data-theme="dark"] { color-scheme: dark }`) is a different shape —
    see `_theme_scoped_scheme_keywords` below, which T26 (`PLAN.md`) added
    to cover it rather than folding it in here.
    """
    best = None
    for sheet in sheets:
        for d in sheet.declarations:
            if d.prop != "color-scheme" or d.theme:
                continue
            spec = _page_specificity(d.selector, d.selector, page)
            if spec is None:
                continue
            key = _cascade_key(d, spec, layers)
            if best is None or key > best[0]:
                best = (key, d.value)
    return resolve_vars(best[1], table) if best else ""


def _theme_scoped_scheme_keywords(sheets: list[Stylesheet],
                                  table: dict[str, str]) -> set[str]:
    """`light`/`dark` keywords a selector-theme-scoped `color-scheme` states.

    T26 (`PLAN.md`, 2026-08-03). `_page_color_scheme` above only ever reads
    an *unscoped* `color-scheme` declaration through the cascade, because a
    static HAR capture freezes one `data-theme` state — `[data-theme="light"]
    { color-scheme: light }` structurally cannot DOM-match in the same
    capture that has `[data-theme="dark"]` on `<html>`. Gating on DOM reach
    the way the unscoped path does would make this confirmation permanently
    one-sided: whichever state the page happened to be captured in.

    So a theme-scoped `color-scheme` declaration is trusted at face value
    instead, the same way `theme_scope`/`_theme_plan` already trust
    `.dark`/`[data-bs-theme=dark]` to mean "this site has a dark theme"
    without requiring the class to be present in the captured markup
    (invariant 16's own DOM-reach requirement is about *page-background*
    candidates specifically, not about theme detection in general). A rule
    scoped to a theme by its own selector marker is a first-party statement
    about that theme, cascade or no cascade — there is nothing to rank it
    against, because nothing else can be scoped to the same theme by the
    same marker and disagree in a way ranking would resolve.

    Two designs were weighed at filing (see T26's own write-up): trust every
    theme-scoped declaration unconditionally, or DOM-match whichever scope
    the capture is actually in and treat only the *other* keyword's
    declaration as CSS-only evidence. Checked against every declaration in
    the corpus that carries `color-scheme` at all — `pseudo_selector_example
    .har`, `mdn.har`, `pawelgrzybek.com__light_dark_example.har`,
    `tailwindcss.com.har` — the two produce identical `scheme_keywords` on
    every one: every site that already confirms both keywords does so
    through the unscoped path above and this function adds nothing, and the
    one site this task was filed against (`pseudo_selector_example.har`)
    confirms both either way. No corpus evidence distinguishes them, so the
    simpler, symmetric design was taken rather than the one that would also
    need a DOM-reach carve-out in `_page_specificity` for one selector but
    not its sibling.
    """
    found: set[str] = set()
    for sheet in sheets:
        for d in sheet.declarations:
            if d.prop != "color-scheme" or not d.theme:
                continue
            found |= _scheme_keywords(resolve_vars(d.value, table))
    return found


def _scheme_keywords(value: str) -> set[str]:
    """`light`/`dark` tokens in a resolved `color-scheme` value, order-free.

    `normal | [ light | dark | <custom-ident> ]+ && only?` per spec — plain
    whitespace-separated keywords once `var()` is resolved, so a split is
    enough; `only` and any custom idents are simply not in the set this
    function looks for.
    """
    return set(value.strip().lower().split()) & {"light", "dark"}


def _scopes_present(sheets: list[Stylesheet], table: dict[str, str],
                    scheme_keywords: set[str]) -> set[str]:
    """Theme scopes that actually carry color.

    A `prefers-color-scheme: dark` block that only flips an image filter is not
    a second palette. Building one anyway would produce a copy of the base
    theme under a label promising something different.

    **`light-dark()` is the third theme mechanism** (phase 4), and unlike the
    other two it is not a scope over declarations — it is a scope over one
    value, written inline. A site using it and confirming both branches with
    `color-scheme: light dark` (or `dark light`) ships both themes, so a
    single `light-dark()` carrying color declares both, and the declaration
    itself stays unscoped so that it is read once per theme with a different
    branch each time. developer.mozilla.org is the case: it writes
    `html { background-color: var(--color-background-page) }` where the property
    holds `light-dark(#fff,#18191b)`, `html` also carries `color-scheme:light
    dark`, and without this it reads as one theme with both branches piled
    into it.

    **`scheme_keywords` is the gate T10 (`PLAN.md`) added.** `light-dark()`
    resolves against the *used* `color-scheme`, whose initial value is
    `normal` — light. A page that writes `light-dark()` and never confirms
    both keywords renders the light branch always (or the dark one alone, if
    it confirms only `dark` — see `extract()`'s `default_appearance`), and is
    not two-themed; registering both scopes anyway would build a second
    palette for a theme the page never shows. `pawelgrzybek.com`'s
    light/dark example is the corpus site that finally exercises the
    positive case — it declares `color-scheme:light dark` on `html`, so its
    two themes are confirmed, not just assumed the way MDN's always were.
    """
    found: set[str] = set()
    for sheet in sheets:
        for d in sheet.declarations:
            if found >= {"light", "dark"}:
                return found
            if not d.theme and "var(" not in d.value \
                    and "light-dark(" not in d.value.lower():
                continue
            # A `light-dark()` usually arrives through a custom property rather
            # than written in place, so the substitution has to happen before
            # the test — MDN's page rule reads `var(--color-background-page)`.
            resolved = resolve_vars(d.value, table)
            low = resolved.lower()
            if d.theme and d.theme not in found and _colors_of(resolved, d.theme):
                found.add(d.theme)
            if ("light-dark(" in low and {"light", "dark"} <= scheme_keywords
                    and (_colors_of(resolved, "light")
                         or _colors_of(resolved, "dark"))):
                found |= {"light", "dark"}
    return found


def _theme_plan(scopes: set[str]) -> list[tuple[str, str]]:
    """(theme id, scope) for each palette to build, default theme first.

    Unscoped declarations belong to every theme, so each palette is built from
    those plus one scope's worth of overrides. When both scopes are explicit
    neither set of unscoped rules is a theme on its own; when only one is, the
    unscoped declarations *are* the other theme — which is how a dark-by-default
    site with a `.light` override is handled.
    """
    if not scopes:
        return [("base", "")]
    if scopes == {"light", "dark"}:
        return [("light", "light"), ("dark", "dark")]
    other = "dark" if "dark" in scopes else "light"
    return [("base", ""), (other, other)]


# A bare channel triplet: `0 0% 3.9%`, `217.2 91.2% 59.8%`, `255 0 0`, with an
# optional `/ alpha`. Exactly three components — two would not be a color in
# any function, and allowing more invites false matches on ordinary lengths.
_NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)%?"
_TRIPLET = re.compile(rf"^{_NUM}(?:\s+{_NUM}){{2}}(?:\s*/\s*{_NUM})?$")


def _triplet_warning(sheets: list[Stylesheet], table: dict[str, str]) -> str:
    """Flag custom properties that hold channel triplets and are used raw.

    The shadcn/ui convention stores a color as bare channels — `--background:
    0 0% 3.9%` — to be assembled at the point of use as `hsl(var(--background))`.
    Wrapped like that it parses here and always has. Used directly, as
    `background-color: var(--background)`, it is not a color at all: the
    declaration is invalid and a browser computes it to `rgba(0,0,0,0)`, so the
    page paints nothing. Reading a color out of it would invent one the site
    never shows, which is the whole thing this tool exists not to do.

    So the value is skipped, as any unparseable value is — but silently
    skipping it leaves a site whose entire theme is written this way looking
    like an extraction failure. Naming it is the difference between "the tool
    is broken" and "these declarations paint nothing, here is why".

    The test is deliberately narrow: the consuming declaration must reference a
    custom property, must resolve to nothing but a triplet, and must yield no
    color. A property consumed only inside `hsl()` yields a color and is never
    reported, because nothing is wrong with it.
    """
    culprits: dict[str, set[str]] = {}
    for sheet in sheets:
        for d in sheet.declarations:
            if d.is_custom_property or d.role == "other" or "var(" not in d.value:
                continue
            resolved = resolve_vars(d.value, table).strip()
            if _colors_of(resolved) or not _TRIPLET.match(resolved):
                continue
            for name in var_refs(d.value):
                if _TRIPLET.match(table.get(name, "").strip()):
                    culprits.setdefault(name, set()).add(d.prop)
    if not culprits:
        return ""

    names = sorted(culprits)
    shown = ", ".join(names[:3])
    more = f" and {len(names) - 3} more" if len(names) > 3 else ""
    example = next(iter(culprits[names[0]]))
    return (
        f"{len(names)} custom propert"
        f"{'y holds' if len(names) == 1 else 'ies hold'} a bare channel triplet "
        f"({shown}{more}) and {'is' if len(names) == 1 else 'are'} used directly "
        f"in var() — for example `{example}: var({names[0]})`, which resolves to "
        f"`{table[names[0]].strip()}`. That is not a color: a browser discards "
        f"the declaration and paints nothing there. Triplets only become colors "
        f"inside a color function, as `hsl(var({names[0]}))`, and are read "
        f"normally when written that way. These colors are absent from the "
        f"palette because the page does not paint them."
    )


def _same_palette(a: Palette, b: Palette) -> bool:
    """True when a scope turned out not to change anything worth reporting."""
    return (a.ground.hexa == b.ground.hexa
            and {e.color.hexa for e in a.entries}
            == {e.color.hexa for e in b.entries})


def extract(bundle: Bundle, *, merge_threshold: float = 0.02,
            include_third_party: bool = True,
            third_party_weight: float = 0.25,
            min_score: float = 0.0,
            only: list[str] | None = None,
            exclude: list[str] | None = None,
            flat: bool = False,
            themes: bool = True) -> Palette:
    """Build the palette, or both palettes when the site ships two themes.

    Returns the default theme. A second one, when there is one, hangs off it as
    `.alternate` — the whole pipeline is run again for it, because a theme has
    its own ground and everything from alpha flattening to contrast ratios is
    measured against that.
    """
    sheets = collect_sheets(bundle, include_third_party=include_third_party,
                            only=only, exclude=exclude)

    all_var_refs: set[str] = set()
    for s in sheets:
        all_var_refs |= s.var_refs

    # The document's own <html>/<body>, so ground detection can tell a utility
    # class that paints the page from one that paints a card, and var()
    # resolution can tell a definition that reaches the page from one scoped to
    # a theme nobody selected. None when there is no readable HTML at all — a
    # bare .css input, say — in which case both fall back to selectors that
    # merely read like page rules.
    page = None
    tree = None
    for asset in bundle.by_kind("html"):
        page = page_elements(asset.text)
        # `full_tree` (T9) answers a different question than `page_elements`
        # — real ancestry below <html>/<body>, for `resolve_by_ancestry_kind`
        # — so it has to come from the *same* asset `page` did, not just the
        # first HTML asset seen. `None` when `page` is too (no readable
        # HTML), in which case `_build` falls back to last-wins for every
        # off-page property, same as before this existed.
        tree = full_tree(asset.text)
        if page:
            break

    # The document's `@layer` order, which is a property of the document rather
    # than of any one sheet — so it is resolved once, here, and handed to both
    # places that rank declarations.
    layers = layer_order(sheets)

    # T22 (`PLAN.md`): every `@property` registration in the document, so
    # `initial` on a registered property can resolve to its real
    # initial-value instead of being treated as absent (invariant 26's own
    # extension), and so T9's ancestry walk can stop at a non-inheriting
    # property's own element instead of borrowing a value from an unrelated
    # ancestor. Resolved once, like `layers`, and handed to every `_build`
    # call below.
    properties = property_registrations(sheets)

    # T10: which branch an unscoped build reads a `light-dark()` through, and
    # (via `_scopes_present`) whether a `light-dark()` site is confirmed
    # two-themed at all. Computed once, before `themes` is checked, because
    # `default_appearance` feeds every `_build` call below regardless —
    # `--no-themes` still has to pick a branch for a site that writes
    # `light-dark(): dark` and confirms only `color-scheme: dark`.
    #
    # T26 adds `_theme_scoped_scheme_keywords` alongside the original
    # unscoped-only `_page_color_scheme`: a `[data-theme="dark"]
    # { color-scheme: dark }` toggle confirms its own keyword by its own
    # selector marker, the same trust `theme_scope` already extends to
    # `.dark`/`[data-bs-theme=dark]`, rather than needing to DOM-match a
    # state a static capture cannot hold both sides of at once.
    table = build_var_table(sheets, page=page, layers=layers, properties=properties)
    scheme_kw = (_scheme_keywords(_page_color_scheme(sheets, page, layers, table))
                 | _theme_scoped_scheme_keywords(sheets, table))
    scopes = _scopes_present(sheets, table, scheme_kw) if themes else set()
    default_appearance = "dark" if scheme_kw == {"dark"} else "light"

    palettes = [
        _build(sheets, bundle.page_url, all_var_refs, theme_id, scope,
               merge_threshold=merge_threshold,
               third_party_weight=third_party_weight,
               min_score=min_score, flat=flat, page=page, layers=layers,
               tree=tree, default_appearance=default_appearance,
               properties=properties)
        for theme_id, scope in _theme_plan(scopes)
    ]

    if len(palettes) > 1 and _same_palette(palettes[0], palettes[1]):
        palettes = palettes[:1]
        palettes[0].theme_id, palettes[0].theme_scope = "base", ""

    _assign_names(palettes[0].entries, palettes[0].ground)
    if len(palettes) > 1:
        _align_names(palettes[0], palettes[1])
        _assign_names(palettes[1].entries, palettes[1].ground)
        palettes[0].alternate = palettes[1]

    pal = palettes[0]
    pal.warnings.extend(bundle.warnings)
    triplets = _triplet_warning(
        sheets, build_var_table(sheets, page=page, layers=layers,
                                properties=properties))
    if triplets:
        pal.warnings.append(triplets)

    # Every ratio in a palette is measured against its ground, so a ground that
    # was inferred rather than read makes all of them provisional. Worth saying
    # out loud: the numbers look just as authoritative either way. Sites that
    # paint the page from a wrapper element rather than html/body/:root land
    # here, and a theme whose ground was guessed can end up measured against
    # the other theme's background entirely.
    for p in [pal, pal.alternate]:
        if p and "{" not in p.ground_source:
            which = f"The {p.theme_id} theme's " if pal.alternate else "The "
            pal.warnings.append(
                f"{which}ground was inferred ({p.ground.hex}, {p.ground_source}) "
                f"because no html/body/:root rule sets a background this tool "
                f"can read. Contrast ratios for it are measured against that "
                f"guess. Common when the page background is painted by a "
                f"wrapper element."
            )
    if pal.alternate and pal.appearance == pal.alternate.appearance:
        # Both grounds landed on the same side of the light/dark line. The
        # palettes are still real and still different; only the labels would
        # mislead, so say so rather than inventing a distinction.
        pal.warnings.append(
            f"Both themes have a {pal.appearance} background "
            f"({pal.ground.hex} and {pal.alternate.ground.hex}), so they are "
            f"labelled by the rule that defines them rather than by appearance."
        )
    return pal


def _build(sheets: list[Stylesheet], page_url: str, all_var_refs: set[str],
           theme_id: str, scope: str, *, merge_threshold: float,
           third_party_weight: float, min_score: float,
           flat: bool, page: list[PageElement] | None = None,
           layers: dict[str, int] | None = None,
           tree: object | None = None,
           default_appearance: str = "light",
           properties: dict[str, tuple[str | None, str | None]] | None = None,
           ) -> Palette:
    """One theme's palette: everything scoped to it, plus everything unscoped."""
    layers = layers if layers is not None else layer_order(sheets)
    properties = (properties if properties is not None
                 else property_registrations(sheets))
    rooted, off_page = _var_populations(sheets, scope, page, layers)
    table = _merge_var_populations(rooted, off_page, properties)
    pal = Palette(page_url=page_url, theme_id=theme_id, theme_scope=scope)

    # T9: an off-page custom property resolves by real inheritance for the
    # specific declaration consuming it, where the document's real tree gives
    # a confident answer — see `resolve_by_ancestry_kind`. `wrapped_root` is
    # built once per theme rather than once per lookup: `elements_matching`
    # re-wraps the whole tree on every call, and PLAN.md's T9 blast-radius
    # measurement (2026-08-02) found that cost dominant (55s on
    # tailwindcss.com's ~500 distinct consumer selectors) next to parsing,
    # which is why this is hoisted here instead of called per-declaration.
    wrapped_root = wrap_tree(tree) if tree is not None else None
    consumer_cache: dict[str, list] = {}

    def consumers_of(selector: str) -> list:
        if selector not in consumer_cache:
            consumer_cache[selector] = (
                elements_matching_wrapped(selector, wrapped_root)
                if wrapped_root is not None else [])
        return consumer_cache[selector]

    # T18: does this usage's own selector reach a real element at all — the
    # same hoisted `wrapped_root` as `consumers_of`, memoized the same way.
    # `None` (no captured HTML) rather than `[]`-style False when there is no
    # tree, matching `dom.selector_reach`'s own "no basis" contract instead
    # of manufacturing a determinate answer this build has no evidence for.
    reach_cache: dict[str, bool | None] = {}

    def reach_of(selector: str) -> bool | None:
        if selector not in reach_cache:
            reach_cache[selector] = (
                selector_reach(selector, wrapped_root)
                if wrapped_root is not None else None)
        return reach_cache[selector]

    # T24: why `reach_of` came back `None`, for the one case worth naming
    # specifically (invariant 27/T18's "dynamic pseudo-class" shape). Only
    # ever consulted when `reach_of` is already `None` — see `reach` below —
    # so this stays a rare, memoized lookup rather than a per-declaration
    # cost. `dom.untestable_reason` only distinguishes "uncompilable" from
    # "dynamicState"; "no captured HTML at all" is this module's own third
    # cause and is read directly off `wrapped_root`, never handed to it.
    reason_cache: dict[str, str] = {}

    def reason_of(selector: str) -> str:
        if selector not in reason_cache:
            reason_cache[selector] = untestable_reason(selector)
        return reason_cache[selector]

    # T19: the real elements backing `matchCount`/`examples[].matches` for a
    # usage `reach_of` found `True` for. **Deliberately not `consumers_of`**
    # (T21, `PLAN.md`) despite the obvious-looking overlap — `consumers_of`
    # backs T9's real-inheritance walk and must stay on `_compile_usable`'s
    # pseudo-refusing filter (see that function's docstring for why sharing
    # it here produced a false-confirmed `absent` on `tailwindcss.com.har`).
    # This one is `reach_of`'s own base-compound-testing filter
    # (`dom._compile_reachable`), memoized the same way.
    match_cache: dict[str, list] = {}

    def match_elements_of(selector: str) -> list:
        if selector not in match_cache:
            match_cache[selector] = (
                reach_elements(selector, wrapped_root)
                if wrapped_root is not None else [])
        return match_cache[selector]

    # The bounded, formatted sample for `examples[].matches`, memoized by
    # selector text the same way `match_cache` is — a selector reused across
    # many declarations (a shared utility class, say) would otherwise re-run
    # `element_signature` on the same elements once per declaration.
    sample_cache: dict[str, list[str]] = {}

    def samples_of(selector: str) -> list[str]:
        if selector not in sample_cache:
            sample_cache[selector] = [element_signature(n) for n in
                                      match_elements_of(selector)[:MATCH_SAMPLES]]
        return sample_cache[selector]

    # Which branch a `light-dark()` resolves to. A themed build (`scope` set)
    # reads its own branch, same as always. An unscoped build — `--no-themes`,
    # or a themed run whose `light-dark()` usage was never confirmed
    # two-themed (T10, `PLAN.md`) — reads `default_appearance`, which
    # `extract()` computes from the page's own `color-scheme` and defaults to
    # light: what a browser does when the document says nothing about it.
    appearance = scope or default_appearance

    # A theme's own rules shadow the unscoped ones they were written to
    # override, matched on (selector as it reads inside the theme, property).
    # That pair is exactly what an author repeats to override something for a
    # theme, and without this the light `--bg: #fff` and the light `.card`
    # background both turn up in the dark palette as colors the dark theme
    # never paints. It is not general specificity — `border` shorthand against
    # a `border-color` override still slips through — but it removes the whole
    # class of duplicates that matter here.
    shadowed: set[tuple[str, str]] = set()
    if scope:
        for sheet in sheets:
            for d in sheet.declarations:
                if d.theme == scope:
                    shadowed.add((d.themed_selector, d.prop))

    buckets: dict[tuple, Entry] = {}
    n_decls = 0

    for sheet in sheets:
        for d in sheet.declarations:
            if d.theme and d.theme != scope:
                continue  # belongs to the other theme
            if not d.theme and (d.selector, d.prop) in shadowed:
                continue  # this theme overrides it
            if d.role == "other":
                # `color-scheme` (T10) is the one declaration this codebase
                # records that can never hold a color — it is read directly by
                # `_page_color_scheme`, not through this loop. Excluded here
                # rather than left to fall out of `_colors_of` returning
                # nothing, so it does not inflate `declarationsScanned`, which
                # the report and `stats` publish as "declarations scanned for
                # color".
                continue
            n_decls += 1
            decl_table = table
            # Only worth asking when this declaration actually references an
            # off-page-only property — the overwhelming majority reference
            # nothing, or reference a page-reaching one the cascade already
            # resolved, and `var_refs` tokenizes the value to check, which
            # isn't free to do on every declaration in the document.
            if off_page and "var(" in d.value:
                referenced = var_refs(d.value) & off_page.keys()
                if referenced:
                    consumer_elements = consumers_of(d.themed_selector or d.selector)
                    if consumer_elements:
                        overrides: dict[str, str] = {}
                        absent: set[str] = set()
                        for name in referenced:
                            reg = properties.get(name)
                            kind, val = resolve_by_ancestry_kind(
                                off_page[name], consumer_elements, layers,
                                non_inheriting=bool(reg and reg[0] == "false"))
                            if kind == "value":
                                # T22: an ancestry-confirmed literal `initial`
                                # is only "absent" if the property has no
                                # `@property` registration to give it a real
                                # value — same substitution
                                # `_substitute_registered_initials` applies
                                # to the base table, needed again here
                                # because this override is written fresh per
                                # declaration rather than flowing through it.
                                if (val.strip().lower() == "initial" and reg
                                        and reg[1] is not None and reg[1].strip()):
                                    val = reg[1]
                                overrides[name] = val
                            elif kind == "absent":
                                absent.add(name)
                            # "disagree" leaves last-wins alone.
                        if overrides or absent:
                            decl_table = {k: v for k, v in table.items()
                                         if k not in absent}
                            decl_table.update(overrides)
                    # No real consumer element found in the captured markup
                    # at all ("no basis", PLAN.md T9 2026-08-02) — last-wins
                    # is the only answer there is, so `decl_table` stays
                    # `table` unchanged rather than being treated as absent.
            value = resolve_vars(d.value, decl_table)
            colors = _colors_of(value, appearance)
            if not colors:
                continue

            # Weighted on the selector as it reads inside this theme, so a
            # themed page rule scores as the page rule it is rather than as
            # whatever class happens to carry the marker.
            sel = d.themed_selector
            w = selector_weight(sel, d.at_rules)
            if sheet.third_party:
                w *= third_party_weight
            if d.is_custom_property:
                # A token definition is not itself a use. It counts, but the
                # real signal is whether something references it.
                w *= 1.2 if d.prop in all_var_refs else 0.35

            inert = is_inert_shadow(d.prop, value)
            reach = reach_of(sel)
            # T19: how many real elements this usage's selector reaches, and
            # a bounded sample of which ones. `reach is False` already means
            # `selector_reach` ran `_compile_reachable` on this exact selector
            # against this exact root and found nothing, so
            # `match_elements_of` is guaranteed `[]` — asking it again would
            # repeat that query for every distinct selector in the document.
            # Only a confirmed `True` is worth a second, sample-bearing
            # lookup; `None` (no basis to test at all) leaves both
            # `None`/empty, same as `reach` itself.
            if reach is True:
                match_count, match_samples, reason = (
                    len(match_elements_of(sel)), samples_of(sel), None)
            elif reach is False:
                match_count, match_samples, reason = 0, [], None
            else:
                # T24: no captured HTML at all reads `reason_of` a selector
                # `dom.untestable_reason` never sees — this module's own
                # third cause, distinct from that function's two.
                match_count, match_samples = None, []
                reason = reason_of(sel) if wrapped_root is not None \
                    else "noCapturedHtml"

            for c in colors:
                if c.a < 0.02:
                    # Fully transparent. Flattening it would just produce a
                    # duplicate of the ground color.
                    continue
                # Keyed by role as well as value: one grey used for body text
                # and for card backgrounds is two tokens in any theme worth
                # having. Keying on value alone made that depend on whether the
                # two uses happened to be written the same way, which is not a
                # distinction anyone means to make.
                key = c.hexa if flat else (c.hexa, d.role)
                entry = buckets.get(key)
                if entry is None:
                    entry = Entry(color=c)
                    buckets[key] = entry
                entry.usages.append(
                    Usage(selector=d.selector, prop=d.prop, value=d.value,
                          source=d.source, weight=w, role=d.role,
                          third_party=sheet.third_party, inert=inert,
                          sheet_order=d.sheet_order, order=d.order,
                          scope_selector=sel, important=d.important,
                          layer=d.layer, theme_media=d.theme_media,
                          theme_scoped=bool(d.theme), matched=reach,
                          match_count=match_count,
                          match_samples=match_samples,
                          reach_reason=reason)
                )
                if d.is_custom_property:
                    entry.var_names.add(d.prop)

    entries = list(buckets.values())

    pal.ground, pal.ground_source = detect_ground(entries, page, layers)
    entries = _merge_near_duplicates(entries, merge_threshold, pal.ground)

    for e in entries:
        e.role = e.primary_role
        e.status = _status_for(e, all_var_refs)

    entries = [e for e in entries if e.score >= min_score]
    entries.sort(key=lambda e: -e.score)

    _assign_groups(entries, pal.ground)

    pal.entries = entries
    pal.stats = {
        "stylesheets": len(sheets),
        "declarationsScanned": n_decls,
        "distinctColors": len(buckets),
        "afterMerge": len(entries),
        "customProperties": len(table),
        "customPropertiesReferenced": len(
            [k for k in table if k in all_var_refs]
        ),
        "sources": _source_stats(sheets),
    }
    return pal


def _colors_of(value: str, appearance: str = "light") -> list[Color]:
    from .color import find_colors
    return find_colors(value, appearance)


def _source_stats(sheets: list[Stylesheet]) -> list[dict]:
    out = []
    for s in sheets:
        out.append({
            "source": s.source,
            "origin": s.origin,
            "thirdParty": s.third_party,
            "declarations": len(s.declarations),
        })
    return out


# A chain of page-level elements is still the page: `html body` is where a
# background belongs just as much as `body` is. Allowing the chain matters for
# themes, because `html.dark body` normalises to `html body` — anchoring on a
# single element would drop the dark theme's own ground rule on the floor and
# leave it inheriting the light one.
_PAGE_SEL = re.compile(r"^\s*(?:html|body|:root)(?:\s+(?:html|body|:root))*\s*$",
                       re.I)


def detect_ground(entries: list[Entry],
                  page: list[PageElement] | None = None,
                  layers: dict[str, int] | None = None) -> tuple[Color, str]:
    """Find the color the page actually sits on.

    Two steps, both the cascade's. **Which rules are candidates**: a selector
    qualifies if it *reads* like a page rule (`html`, `body`, `:root`) or if it
    actually selects this document's `<html>` or `<body>` — which is how a
    utility framework paints the page, with `class="bg-light-primary"` on the
    body rather than a `body {}` rule (invariant 16). **Which candidate wins,
    within a pool**: `importance → layer → specificity → document order`, via
    `_cascade_key` — see below for how the `<html>` and `<body>` pools
    themselves are then compared (T7).

    That second step used to be document order alone, which happened to be
    right on ground.news and was luck: `.bg-light-primary` beats `body` there
    because it is declared later, and it beats it in a browser because a class
    outranks an element. A site whose element-matched utility came *earlier*
    than a competing `body` rule was read wrongly, and that documented limit is
    what phase 3 lifts. Ordering is still the last term, and still decides
    every tie — which on the corpus is most of them.

    Matching runs on the selector as it reads inside its own theme, so
    `html.dark body` counts as the dark theme's page rule; scoring runs on the
    selector as declared, so the marker earns it the precedence it has in a
    browser. See `_page_specificity`.

    **Candidates matching `<html>` and ones matching `<body>` are resolved in
    separate pools** (T7), because the cascade does too — it resolves each
    element on its own. **Body's own winner is preferred over html's** —
    resolved independently, then compared, rather than ranked together —
    because that is what painting order does: `<body>`'s own box paints over
    the `<html>` canvas wherever it covers it, which in practice is the whole
    viewport, and that holds however important or specific html's rule is.

    **One exception, and it is not a cascade term either: an html rule written
    specifically for this theme still earns the precedence invariant 16 gives
    it over an unscoped body rule that merely happens to also be present in
    this theme's build.** Tailwind v4's `dark:bg-gray-950` on `<html>` is
    exactly this shape — dark-theme-scoped, competing against a `body {}` rule
    that was never written with a theme in mind and applies to every theme
    because it applies to none in particular. Preferring body unconditionally
    there would silently prefer a rule that says nothing about the theme over
    one that is the theme, which is the same mistake invariant 16 itself
    exists to prevent, just relocated to the other pool. So body wins unless
    html's candidate is theme-scoped (`Usage.theme_scoped`, by either
    mechanism — selector or media) **and body's is not**; found by a test
    fixture built to demonstrate exactly this collision
    (`test_tailwind_v4_shape_on_the_html_element`), not by the corpus — see
    below. Within a pool the normal `importance → layer → specificity → order`
    key still decides the winner unchanged.

    Not reachable on the corpus either way — every candidate on all four
    frozen bundles targets `<body>` except one `<html>`-only candidate
    (tailwindcss.com's dark theme) with no competing `<body>` candidate to
    prefer over or defer to — so this is insurance rather than an observed
    fix, like most of phase 3.
    """
    layers = layers or {}

    def _pool(element: str) -> list:
        candidates = []
        for e in entries:
            if not e.color.opaque:
                continue
            for u in e.usages:
                if u.role != "surface":
                    continue
                if u.prop not in ("background", "background-color"):
                    continue
                spec = _page_specificity(u.selector, u.scope_selector, page,
                                         element=element)
                if spec is None:
                    continue
                candidates.append((_cascade_key(u, spec, layers), e.color, u))
        return candidates

    # `max` keeps the first of equal keys, which matters because two colors
    # read out of one declaration tie on every term this key has — a
    # gradient's stops, say. It used to matter for `light-dark()` too, and
    # since phase 4 it does not: that resolves to the one color the theme
    # being built actually selects, which is how MDN's dark ground became
    # readable rather than being whichever branch was written first.
    body_win = max(_pool("body"), key=lambda t: t[0], default=None)
    html_win = max(_pool("html"), key=lambda t: t[0], default=None)

    winner = body_win or html_win
    if body_win and html_win:
        html_only_scoped = html_win[2].theme_scoped and not body_win[2].theme_scoped
        winner = html_win if html_only_scoped else body_win

    if winner:
        _key, color, u = winner
        return color, f"{u.selector} {{ {u.prop} }} in {u.source}"

    surf = [e for e in entries
            if e.color.opaque and e.primary_role == "surface"]
    if surf:
        top = max(surf, key=lambda e: e.score)
        return top.color, "highest-scoring surface color"

    return Color(255, 255, 255), "defaulted to white (no page background found)"


def _merge_near_duplicates(entries: list[Entry], threshold: float,
                           ground: Color) -> list[Entry]:
    """Fold visually identical colors together, keeping the strongest.

    Two decisions here matter more than they look:

    Comparison happens on the *rendered* color — each value flattened over the
    ground — because rgba(255,255,255,.02) and rgba(255,255,255,.03) are one
    color as far as anyone looking at the page is concerned, even though their
    declared values differ.

    Merging is confined to a single role. A grey used for body text and the
    same grey used for a card background render identically but are different
    tokens in any theme worth using, so they are kept apart.
    """
    if threshold <= 0:
        return entries

    for e in entries:
        e.role = e.primary_role

    def rendered(e: Entry) -> Color:
        return e.color if e.color.opaque else e.color.over(ground)

    # The ground must survive as its own token: it is the reference every other
    # color is measured against, and merging it into a near neighbour would
    # leave the palette describing a background that no token holds.
    def sort_key(e: Entry) -> tuple:
        is_ground = e.color.opaque and delta_ok(e.color, ground) < 0.005
        return (0 if is_ground else 1, -e.score)

    ordered = sorted(entries, key=sort_key)
    kept: list[Entry] = []

    def compatible(a: str, b: str) -> bool:
        # A custom property has no role of its own — it takes the role of
        # whatever consumes it — so it may merge into any of them.
        return a == b or "token" in (a, b)

    for e in ordered:
        target = None
        for k in kept:
            if not compatible(k.role, e.role):
                continue
            if delta_ok(rendered(k), rendered(e)) < threshold:
                target = k
                break
        if target is None:
            kept.append(e)
        else:
            target.usages.extend(e.usages)
            target.var_names |= e.var_names
            if e.color.hex != target.color.hex:
                target.merged_hexes.add(e.color.hex)
            target.merged_hexes |= e.merged_hexes

    for e in kept:
        e.role = e.primary_role
    return kept


def _status_for(entry: Entry, var_refs: set[str]) -> str:
    """live / saved / inert / unmatched.

    saved: only ever defined as a custom property nothing references. On
    design-tool-generated sites this is the designer's saved swatches, which
    are worth keeping but are not on the page.
    inert: every use is a zero-length shadow, which paints nothing.
    unmatched (T18): every usage's selector was tested against the real
    captured document and matched no element there — see `all_unmatched`.
    Checked last and only after `saved` has already had its say: `saved`
    answers "does any `var()` call in the CSS ever name this custom
    property" (a check over the stylesheets' own reference graph, no DOM
    involved), which is a different, more specific diagnosis than "does this
    declaration's selector reach a real element" — an already-`saved` entry
    stays `saved` rather than being relabelled `unmatched`, and an
    already-`inert` one stays `inert` for the same reason `all_inert` is
    checked first: a value that paints nothing is worth saying so about
    regardless of whether its selector would otherwise match.
    """
    if entry.all_inert:
        return "inert"
    non_token = [u for u in entry.usages if u.role != "token"]
    if not non_token and entry.var_names and not (entry.var_names & var_refs):
        return "saved"
    if entry.all_unmatched:
        return "unmatched"
    return "live"


def _assign_groups(entries: list[Entry], ground: Color) -> None:
    """Sort each color into the family it will be named and displayed under.

    Kept apart from naming so that two themes can be grouped, then paired up,
    then named — see `_align_names`.
    """
    # Grouping uses the rendered color, since that is what a reader sees, and a
    # higher chroma bar than `is_neutral`. Tinted greys — the slate and zinc
    # families every framework ships — sit around 0.03 and are greys doing a
    # grey's job; calling one "blue-2" because it is faintly cool is worse than
    # useless. Real brand colors sit far above this line.
    for e in entries:
        rendered = e.color if e.color.opaque else e.color.over(ground)
        if rendered.chroma < MUTED_CHROMA:
            e.group = {"surface": "surface", "text": "ink", "line": "line"}.get(
                e.role, "neutral"
            )
        else:
            e.group = "chroma"

    matches = [e for e in entries
               if e.color.opaque and delta_ok(e.color, ground) < 0.005]
    if matches:
        # The ground often doubles as ink on light blocks; the entry is the
        # same color either way, so label it for the job that defines the page.
        max(matches, key=lambda e: e.score).group = "ground"


def _align_names(base: Palette, alt: Palette) -> None:
    """Give one name to the token that plays the same part in each theme.

    Named independently the two palettes share nothing, and toggling the report
    swaps one list of names for an unrelated one — which makes the comparison
    the toggle exists to support impossible, and makes a `--c-ink-1` in the
    emitted CSS mean two different things in two blocks.

    Pairing is by rank within a group, measured against *that theme's own
    ground*. The highest-contrast ink in a light theme is the same token as the
    highest-contrast ink in a dark one even though the first is nearly black
    and the second nearly white; ranking by lightness would pair them
    backwards. Chroma pairs by hue first, since a brand color generally keeps
    its hue across themes and only shifts in lightness.

    Only the alternate is renamed. Anything left unpaired — a theme with more
    inks than its counterpart — keeps a name of its own from the naming pass
    that follows.
    """
    def rank(pal: Palette):
        def key(e: Entry) -> float:
            flat = e.color if e.color.opaque else e.color.over(pal.ground)
            return -contrast_ratio(flat, pal.ground)
        return key

    for group in ("ground", "surface", "ink", "line", "neutral"):
        # strict=False on purpose: the two themes rarely have the same number of
        # colors in a group, and stopping at the shorter one is exactly the
        # intent stated above — the surplus keeps its own name.
        pairs = zip(
            sorted((e for e in base.entries if e.group == group), key=rank(base)),
            sorted((e for e in alt.entries if e.group == group), key=rank(alt)),
            strict=False,
        )
        for be, ae in pairs:
            ae.name = be.name

    def by_hue(pal: Palette) -> dict[str, list[Entry]]:
        out: dict[str, list[Entry]] = defaultdict(list)
        for e in pal.entries:
            if e.group == "chroma":
                rendered = (e.color if e.color.opaque
                            else e.color.over(pal.ground))
                out[hue_name(rendered)].append(e)
        for members in out.values():
            members.sort(key=lambda e: -e.score)
        return out

    base_hues = by_hue(base)
    for hue, members in by_hue(alt).items():
        # Same reason: a hue present in both themes need not have the same
        # number of steps in each, and the extras are named independently.
        for be, ae in zip(base_hues.get(hue, []), members, strict=False):
            ae.name = be.name


def _assign_names(entries: list[Entry], ground: Color) -> None:
    """Generate stable, meaningful token names.

    Names describe what a color is and where it sits, because a generated name
    like `color-7` tells the next reader nothing. Entries that already carry a
    name — paired across themes by `_align_names` — are left alone, and the
    names they hold are reserved so nothing else takes them.
    """
    counters: dict[str, int] = defaultdict(int)
    used: set[str] = {e.name for e in entries if e.name}

    # Neutrals get ordered by lightness within their group so the ramp reads
    # in a sensible direction rather than by usage count.
    for group in ("ground", "surface", "ink", "line", "neutral", "chroma"):
        members = [e for e in entries if e.group == group and not e.name]
        if group == "chroma":
            members.sort(key=lambda e: -e.score)
            for e in members:
                base = hue_name(e.color if e.color.opaque
                                else e.color.over(ground))
                counters[base] += 1
                n = counters[base]
                name = base if n == 1 else f"{base}-{n}"
                while name in used:
                    n += 1
                    name = f"{base}-{n}"
                e.name = name
                used.add(name)
        else:
            members.sort(key=lambda e: -(e.color if e.color.opaque
                                         else e.color.over(ground)).oklab()[0])
            stem = {"surface": "surface", "ink": "ink", "line": "line",
                    "neutral": "grey", "ground": "ground"}[group]
            for i, e in enumerate(members, start=1):
                name = stem if len(members) == 1 and stem not in used \
                    else f"{stem}-{i}"
                while name in used:
                    i += 1
                    name = f"{stem}-{i}"
                e.name = name
                used.add(name)


def describe(entry: Entry, ground: Color) -> dict:
    """The record that ends up in the JSON."""
    c = entry.color
    flat = c.over(ground) if not c.opaque else c
    ratio = contrast_ratio(flat, ground)
    top = sorted(entry.usages, key=lambda u: -u.weight)[:6]

    rec = {
        "name": entry.name,
        "group": entry.group,
        "role": entry.role,
        "status": entry.status,
        "hex": flat.hex,
        "rgb": list(flat.rgb255),
        "css": {
            "hex": flat.hex,
            "rgb": flat.css_rgb(),
            "hsl": flat.css_hsl(),
            "oklch": flat.css_oklch(),
        },
        "neutral": flat.is_neutral,
        "score": round(entry.score, 2),
        "occurrences": entry.count,
        "contrastOnGround": round(ratio, 2),
        "wcagOnGround": wcag_label(ratio),
        "usedIn": sorted({u.prop for u in entry.usages}),
        "examples": [
            {
                "selector": u.selector, "property": u.prop, "source": u.source,
                # T19: how many real elements in the captured document this
                # usage's selector actually reached, not just its text.
                # `None` mirrors `Usage.matched`'s own "no basis to test"
                # case (no captured HTML, or an untestable selector) rather
                # than reading as zero. `matches` is a bounded sample of
                # which real elements they were — omitted, not an empty
                # list, when there is nothing real to show.
                "matchCount": u.match_count,
                **({"matches": u.match_samples} if u.match_samples else {}),
                # T24: why `matchCount` is `None`, when it is —
                # `"dynamicState"` (no resting state any capture could ever
                # test), `"uncompilable"` (a library coverage gap, T21's
                # territory), or `"noCapturedHtml"` (a bare `.css` input).
                # Additive and specific rather than leaving the reader to
                # guess at a bare `null`.
                **({"reason": u.reach_reason} if u.reach_reason else {}),
            }
            for u in top
        ],
    }
    if not c.opaque:
        rec["source"] = {
            "declaredAs": c.css_rgb(),
            "alpha": round(c.a, 4),
            "flattenedOver": ground.hex,
            "flattenedHex": flat.hex,
        }
    if entry.var_names:
        rec["customProperties"] = sorted(entry.var_names)
    if entry.merged_hexes:
        rec["mergedFrom"] = sorted(entry.merged_hexes)
    if entry.status == "live" and entry.all_dynamic_only:
        # T24: this color's `live` status rests entirely on a selector with
        # no resting state — every usage is `:hover`/`:focus`/etc-only. Not
        # a status change (invariant 27's own "unconfirmed is not absent"
        # reasoning still applies) — a transparency flag the report's
        # Caveats section and any JSON consumer can single this entry out
        # with, rather than a reader having to notice every example's
        # `reason` individually.
        #
        # `entry.status == "live"` is required, not implied by
        # `all_dynamic_only` alone: `_status_for`'s `saved`/`inert`
        # priority (invariant 27's own note) can still land on an entry
        # every one of whose usages is dynamic-state-only, e.g. a custom
        # property declared only inside a `:hover` rule and referenced
        # nowhere (`saved`). Without this gate that entry would carry
        # `dynamicOnly: true` while `renderCaveats()` names it as resting on
        # unconfirmable ground the reader has "live" reason to doubt — a
        # claim this flag has no business making about a color that was
        # never claimed live in the first place.
        rec["dynamicOnly"] = True
    return rec
