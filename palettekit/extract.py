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
)
from .sources import Bundle

# Above this OKLab chroma a color is treated as having a real hue rather than
# being a tinted grey. Deliberately higher than Color.is_neutral: that answers
# "is this achromatic", this answers "would a person call this a color".
MUTED_CHROMA = 0.06

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

    @property
    def cascade_key(self) -> tuple[int, int]:
        return (self.sheet_order, self.order)


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


def build_var_table(sheets: list[Stylesheet]) -> dict[str, str]:
    """Map custom property name to its value.

    Later declarations win, which approximates the cascade well enough for
    resolving a value to a color. It does not model specificity or scoping.
    """
    table: dict[str, str] = {}
    for sheet in sheets:
        for d in sheet.declarations:
            if d.is_custom_property:
                table[d.prop] = d.value
    return table


def extract(bundle: Bundle, *, merge_threshold: float = 0.02,
            include_third_party: bool = True,
            third_party_weight: float = 0.25,
            min_score: float = 0.0,
            only: list[str] | None = None,
            exclude: list[str] | None = None,
            flat: bool = False) -> Palette:
    sheets = collect_sheets(bundle, include_third_party=include_third_party,
                            only=only, exclude=exclude)
    table = build_var_table(sheets)

    all_var_refs: set[str] = set()
    for s in sheets:
        all_var_refs |= s.var_refs

    pal = Palette(page_url=bundle.page_url)
    pal.warnings.extend(bundle.warnings)

    buckets: dict[tuple, Entry] = {}
    n_decls = 0

    for sheet in sheets:
        for d in sheet.declarations:
            n_decls += 1
            value = resolve_vars(d.value, table)
            colors = _colors_of(value)
            if not colors:
                continue

            w = selector_weight(d.selector, d.at_rules)
            if sheet.third_party:
                w *= third_party_weight
            if d.is_custom_property:
                # A token definition is not itself a use. It counts, but the
                # real signal is whether something references it.
                w *= 1.2 if d.prop in all_var_refs else 0.35

            inert = is_inert_shadow(d.prop, value)

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
                          sheet_order=d.sheet_order, order=d.order)
                )
                if d.is_custom_property:
                    entry.var_names.add(d.prop)

    entries = list(buckets.values())

    pal.ground, pal.ground_source = detect_ground(entries)
    entries = _merge_near_duplicates(entries, merge_threshold, pal.ground)

    for e in entries:
        e.role = e.primary_role
        e.status = _status_for(e, all_var_refs)

    entries = [e for e in entries if e.score >= min_score]
    entries.sort(key=lambda e: -e.score)

    _assign_names(entries, pal.ground)

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


def _colors_of(value: str) -> list[Color]:
    from .color import find_colors
    return find_colors(value)


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


_PAGE_SEL = re.compile(r"^\s*(html|body|:root)\s*$", re.I)


def detect_ground(entries: list[Entry]) -> tuple[Color, str]:
    """Find the color the page actually sits on.

    This resolves like the cascade does: among page-level background rules,
    the last one declared wins. Weighting instead of ordering gets this wrong
    on any site that loads a framework stylesheet before its own, which is
    most of them.
    """
    candidates = []
    for e in entries:
        if not e.color.opaque:
            continue
        for u in e.usages:
            if u.role != "surface":
                continue
            if u.prop not in ("background", "background-color"):
                continue
            if any(a.lower().startswith("@media") and "print" in a.lower()
                   for a in ()):
                continue
            parts = [p.strip() for p in u.selector.split(",")]
            if not any(_PAGE_SEL.match(p) for p in parts):
                continue
            candidates.append((u.cascade_key, e.color, u))

    if candidates:
        _key, color, u = max(candidates, key=lambda t: t[0])
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
    """live / saved / inert.

    saved: only ever defined as a custom property nothing references. On
    design-tool-generated sites this is the designer's saved swatches, which
    are worth keeping but are not on the page.
    inert: every use is a zero-length shadow, which paints nothing.
    """
    if entry.all_inert:
        return "inert"
    non_token = [u for u in entry.usages if u.role != "token"]
    if not non_token and entry.var_names and not (entry.var_names & var_refs):
        return "saved"
    return "live"


def _assign_names(entries: list[Entry], ground: Color) -> None:
    """Generate stable, meaningful token names.

    Names describe what a color is and where it sits, because a generated name
    like `color-7` tells the next reader nothing.
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
        g = max(matches, key=lambda e: e.score)
        g.group = "ground"
        g.name = "ground"

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
            {"selector": u.selector, "property": u.prop, "source": u.source}
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
    return rec
