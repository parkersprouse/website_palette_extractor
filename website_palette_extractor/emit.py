"""Writing the palette out in each format, including the interactive page."""
from __future__ import annotations

import base64
import datetime
import functools
import html as htmlmod
import importlib.resources
import json
import re

from .color import Color, contrast_ratio, parse_color
from .extract import Palette, describe

# The document's own schema stamp – moves on a separate schedule from
# `website_palette_extractor.__version__`, which tracks the tool rather than this one dict
# shape. Additive keys do not bump it; removing or re-typing a key does.
SCHEMA_VERSION = 1

GROUP_TITLES = {
    "ground": "Ground",
    "surface": "Surface",
    "ink": "Ink",
    "line": "Line",
    "neutral": "Neutral",
    "chroma": "Chroma",
}
GROUP_BLURBS = {
    "ground": "The color the page sits on. Everything else is measured against it.",
    "surface": "Backgrounds for blocks, cards, and controls.",
    "ink": "Text colors. Any with an alpha are shown flattened over the ground.",
    "line": "Borders, rules, and outlines.",
    "neutral": "Greys that did not resolve to a single clear role.",
    "chroma": "Everything with actual hue.",
}

# T20: one line per status, shown next to that status's own swatches rather
# than deferred to a single dense footer sentence. Order matches README's
# "Four statuses" section.
STATUS_TITLES = {
    "live": "Live",
    "saved": "Saved",
    "inert": "Inert",
    "unmatched": "Unmatched",
}
STATUS_BLURBS = {
    "live": "Actually painted on the page.",
    "saved": "A custom property nothing in the CSS references – often a "
             "design tool's saved swatches.",
    "inert": "A declaration that paints nothing, such as a shadow with "
             "every length at zero.",
    "unmatched": "This selector matched nothing in the page this tool "
                 "captured – could be unused CSS, or could be markup only "
                 "client-side JavaScript adds, which this tool cannot run.",
}


def _theme_document(pal: Palette) -> dict:
    """One theme's half of the document.

    `id` names the rule that produced the theme, `appearance` says what it
    looks like. They disagree on a dark-by-default site whose alternate is the
    light one, so both are carried: the id addresses the theme, the appearance
    labels it.
    """
    return {
        "id": pal.theme_id,
        "appearance": pal.appearance,
        "scope": pal.theme_scope,
        "ground": pal.ground.hex,
        "groundSource": pal.ground_source,
        "stats": pal.stats,
        "colors": [describe(e, pal.ground) for e in pal.entries],
    }


def to_document(pal: Palette) -> dict:
    """The dict the JSON file holds, and the report reads. Public API.

    `themes` is always present and always holds at least one entry. The
    top-level `ground`, `stats` and `colors` mirror the default theme – the
    first entry – so that everything reading this document before themes
    existed keeps working unchanged.

    `schemaVersion` is this document shape's own stamp, separate from
    `website_palette_extractor.__version__`. An additive key does not bump it; removing or
    re-typing a key does.
    """
    themes = [_theme_document(pal)]
    if pal.alternate:
        themes.append(_theme_document(pal.alternate))

    doc = {
        "name": _title_for(pal),
        "source": pal.page_url,
        "ground": pal.ground.hex,
        "groundSource": pal.ground_source,
        "generated": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "schemaVersion": SCHEMA_VERSION,
        "stats": pal.stats,
        "warnings": pal.warnings,
        "defaultTheme": pal.theme_id,
        "themes": themes,
        "colors": themes[0]["colors"],
    }
    if pal.image_report:
        doc["images"] = pal.image_report
    return doc


def _alt_theme(doc: dict) -> dict | None:
    """The non-default theme, if the site shipped one."""
    themes = doc.get("themes") or []
    return themes[1] if len(themes) > 1 else None


def _title_for(pal: Palette) -> str:
    url = pal.page_url or "palette"
    m = re.search(r"https?://([^/]+)(/[^?#]*)?", url)
    if not m:
        return url
    host = m.group(1).replace("www.", "")
    path = (m.group(2) or "").strip("/")
    return f"{host}{' / ' + path if path else ''}"


def slug(pal: Palette) -> str:
    """The base filename the emitted files share, derived from the page URL.

    Public because `__main__` names every output file with it, and reaching
    across modules for a leading-underscore name is the one thing an
    underscore is supposed to rule out. `to_document` is still the module's
    data contract; this is just the filename half of the same job.
    """
    s = re.sub(r"[^a-z0-9]+", "-", _title_for(pal).lower()).strip("-")
    return s or "palette"


# ------------------------------------------------------------------ text formats

def _natural(name: str) -> tuple:
    """Sort ink-2 before ink-10, and both before line-1."""
    m = re.match(r"^(.*?)(?:-(\d+))?$", name)
    stem, num = m.group(1), m.group(2)
    return (stem, int(num) if num else 0)


def _for_code(doc: dict, include_unused: bool) -> list[dict]:
    """Colors to put in a theme file.

    A stylesheet you paste into a project should contain what the site actually
    paints. Unreferenced design-tool swatches and no-op declarations stay in the
    JSON and the report, where they are labelled, rather than becoming tokens
    someone later mistakes for real ones.
    """
    if include_unused:
        return doc["colors"]
    return [c for c in doc["colors"] if c["status"] == "live"]


CODE_GROUPS = ["ground", "surface", "ink", "line", "neutral", "chroma"]


def _css_tokens(cols: list[dict], prefix: str, indent: str) -> list[str]:
    """The `--prefix-name: value;` lines for one theme, grouped and commented."""
    lines: list[str] = []
    by_group: dict[str, list[dict]] = {}
    for c in cols:
        by_group.setdefault(c["group"], []).append(c)

    for g in CODE_GROUPS:
        if g not in by_group:
            continue
        lines.append(f"{indent}/* {GROUP_TITLES.get(g, g)} */")
        for c in sorted(by_group[g], key=lambda c: _natural(c["name"])):
            note = "" if c["status"] == "live" else f"  /* {c['status']} */"
            lines.append(f"{indent}--{prefix}-{c['name']}: {c['hex']};{note}")
        lines.append("")

    alphas = sorted((c for c in cols if "source" in c),
                    key=lambda c: _natural(c["name"]))
    if alphas:
        lines.append(f"{indent}/* Declared with alpha – use over the ground "
                     "for real transparency */")
        for c in alphas:
            lines.append(
                f"{indent}--{prefix}-{c['name']}-a: {c['source']['declaredAs']};"
            )
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def emit_css(doc: dict, prefix: str, include_unused: bool = False) -> str:
    lines = [
        "/* " + doc["name"],
        " * " + (doc["source"] or ""),
        " * Extracted from the site's own stylesheets. Ground is "
        + doc["ground"] + ".",
        " * Generated by Website Palette Extractor – do not edit by hand.",
        " */",
        "",
        ":root {",
    ]
    lines += _css_tokens(_for_code(doc, include_unused), prefix, "  ")
    lines.append("}")

    alt = _alt_theme(doc)
    if alt:
        alt_cols = _for_code(alt, include_unused)
        look = alt["appearance"]
        lines += [
            "",
            f"/* {look.title()} theme – ground {alt['ground']}.",
            " * Token names match the block above, so a theme switch is only a",
            " * question of which block wins. Written twice because there is no",
            " * telling which mechanism the consuming project uses: the media",
            " * query follows the visitor's system setting, the attribute",
            " * selector follows an explicit toggle.",
            " */",
        ]
        # A media query is only meaningful when the two themes actually sit on
        # opposite sides of the light/dark line. When they do not, the toggle
        # is the only honest switch.
        if look != doc["themes"][0]["appearance"]:
            lines += [
                f"@media (prefers-color-scheme: {look}) {{",
                "  :root {",
                *_css_tokens(alt_cols, prefix, "    "),
                "  }",
                "}",
                "",
            ]
        lines += [
            f'[data-theme="{alt["id"]}"] {{',
            *_css_tokens(alt_cols, prefix, "  "),
            "}",
        ]

    lines.append("")
    return "\n".join(lines)


def emit_scss(doc: dict, prefix: str, include_unused: bool = False) -> str:
    out = [f"// {doc['name']}", f"// {doc['source']}",
           "// Generated by Website Palette Extractor – do not edit by hand.", ""]
    cols = _for_code(doc, include_unused)
    by_group: dict[str, list[dict]] = {}
    for c in cols:
        by_group.setdefault(c["group"], []).append(c)
    for g in ["ground", "surface", "ink", "line", "neutral", "chroma"]:
        if g not in by_group:
            continue
        out.append(f"// {GROUP_TITLES.get(g, g)}")
        for c in sorted(by_group[g], key=lambda c: _natural(c["name"])):
            out.append(f"${prefix}-{c['name']}: {c['hex']};")
        out.append("")
    out.append(f"${prefix}-palette: (")
    for c in sorted(cols, key=lambda c: _natural(c["name"])):
        out.append(f'  "{c["name"]}": {c["hex"]},')
    out.append(");")
    out.append("")
    return "\n".join(out)


def emit_ts(doc: dict, var_name: str, include_unused: bool = False) -> str:
    out = [f"// {doc['name']}", f"// {doc['source']}",
           "// Generated by Website Palette Extractor – do not edit by hand.", ""]
    cols = _for_code(doc, include_unused)
    out.append(f"export const {var_name} = {{")
    for c in sorted(cols, key=lambda c: _natural(c["name"])):
        out.append(f'  "{c["name"]}": "{c["hex"]}",')
    out.append("} as const;")
    out.append("")
    cap = var_name[0].upper() + var_name[1:]
    out.append(f"export type {cap}Color = keyof typeof {var_name};")
    alphas = sorted((c for c in cols if "source" in c),
                    key=lambda c: _natural(c["name"]))
    if alphas:
        out.append("")
        out.append("/** Colors as originally declared, with alpha intact. */")
        out.append(f"export const {var_name}Alpha = {{")
        for c in alphas:
            out.append(f'  "{c["name"]}": "{c["source"]["declaredAs"]}",')
        out.append("} as const;")
    out.append("")
    return "\n".join(out)


def emit_tailwind(doc: dict, include_unused: bool = False) -> str:
    colors = {c["name"]: c["hex"] for c in
              sorted(_for_code(doc, include_unused),
                     key=lambda c: _natural(c["name"]))}
    body = json.dumps(colors, indent=6)
    body = re.sub(r'^\{', "{", body)
    return (
        f"// {doc['name']}\n"
        f"// {doc['source']}\n"
        "// Generated by Website Palette Extractor – drop into tailwind.config.js\n\n"
        "module.exports = {\n"
        "  theme: {\n"
        "    extend: {\n"
        "      colors: " + body.replace("\n", "\n      ") + ",\n"
        "    },\n"
        "  },\n"
        "};\n"
    )


# ------------------------------------------------------------------ html report

def _pick_report_theme(doc: dict) -> dict:
    """Choose readable UI colors from the extracted palette itself.

    The report is rendered in the palette it documents, which is a nice touch
    right up until the palette has no readable pairing – a light site with no
    dark ink, say. So each choice is contrast-checked and falls back rather
    than shipping an unreadable page.
    """
    ground = parse_color(doc["ground"]) or Color(255, 255, 255)
    dark_bg = ground.luminance() < 0.4

    # Text for the report is chosen for legibility first. Earlier versions of
    # this picked whichever extracted color merely cleared the contrast bar,
    # which produced red body copy on one site and brown on another – faithful
    # to the palette, unpleasant to read. Neutrals are preferred, and when the
    # palette has no neutral that works, the ramp is derived from the ground
    # itself so the report is always readable.
    veil = Color(255, 255, 255) if dark_bg else Color(0, 0, 0)
    derived = {
        "strong": Color(veil.r, veil.g, veil.b, 0.95).over(ground),
        "body":   Color(veil.r, veil.g, veil.b, 0.78).over(ground),
        "muted":  Color(veil.r, veil.g, veil.b, 0.55).over(ground),
    }

    live_neutrals = [
        parse_color(c["hex"]) for c in doc["colors"]
        if c["neutral"] and c["status"] == "live"
    ]
    live_neutrals = [c for c in live_neutrals if c]

    taken: set[str] = set()

    def choose(role: str, floor: float) -> Color:
        target = derived[role]
        usable = [c for c in live_neutrals
                  if contrast_ratio(c, ground) >= floor
                  and c.hex not in taken]
        if not usable:
            # Nothing left that both reads and is distinct from what we already
            # used; the derived tone keeps the three levels visibly different.
            return target
        # Closest match to the derived target, so the report still reads in the
        # site's own greys where the site has suitable ones.
        pick = min(usable, key=lambda c: abs(
            contrast_ratio(c, ground) - contrast_ratio(target, ground)
        ))
        taken.add(pick.hex)
        return pick

    strong = choose("strong", 7.0)
    body = choose("body", 4.5)
    muted = choose("muted", 3.0)

    accent = None
    for c in sorted((c for c in doc["colors"] if not c["neutral"]),
                    key=lambda c: (c["status"] != "live", -c["score"])):
        col = parse_color(c["hex"])
        if col and contrast_ratio(col, ground) >= 3.0:
            accent = col
            break
    if accent is None:
        accent = strong

    line = Color(255, 255, 255, 0.18) if dark_bg else Color(0, 0, 0, 0.14)
    checker = "#2c2c2c" if dark_bg else "#d8d8d8"

    return {
        "ground": ground.hex,
        "strong": strong.hex,
        "body": body.hex,
        "muted": muted.hex,
        "accent": accent.hex,
        "line": line.css_rgb(),
        "checker": checker,
        "chipBorder": line.css_rgb(),
        "toastBg": strong.hex,
        "toastFg": ground.hex,
    }


_UI_VARS = ["ground", "strong", "body", "muted", "accent", "line", "checker",
            "toastBg", "toastFg"]


def _ui_var(name: str) -> str:
    return "--ui-" + re.sub(r"(?<!^)([A-Z])", r"-\1", name).lower()


def _ui_theme_css(themes: list[dict]) -> str:
    """The report's own reading colors, one set per theme.

    The report is rendered in the palette it documents, so a theme switch has
    to restyle the page itself and not just the swatches. Every value the page
    uses goes through these variables – including the toast, which used to be
    written straight into its rule and would otherwise have kept the first
    theme's colors after a toggle.

    The default theme is also written to bare `:root` so the page is styled
    before any script runs.
    """
    blocks: list[str] = []
    for i, t in enumerate(themes):
        ui = _pick_report_theme(t)
        decls = "\n".join(f"    {_ui_var(k)}: {ui[k]};" for k in _UI_VARS)
        if i == 0:
            blocks.append("  :root {\n" + decls + "\n  }")
        blocks.append(f'  :root[data-pk-theme="{t["id"]}"] {{\n{decls}\n  }}')
    return "\n".join(blocks)


# The interactive report's structural HTML/CSS/JS. Kept in its own file
# (report_template.html), not a triple-quoted string here, so it gets
# real editor/linter support instead of being an opaque blob to every tool
# that isn't Python-aware. This does not touch invariant 11 (the *emitted*
# report is standalone, no <link>/fetch()) -- only the template's *source*
# moved; emit_html() still returns a fully self-contained string with the
# placeholders substituted, same as before.
#
# importlib.resources, not a path relative to __file__: the latter breaks
# inside website_palette_extractor.pyz, where the package lives in a zip
# archive and there is no real filesystem path to open() -- the same class
# of build-machine-only failure build.py's own _verify() exists to catch
# for vendored dependencies (CLAUDE.md, "Rebuild the zipapp"). Verified
# directly against the .pyz on a clean 3.11 interpreter with none of this
# project's dependencies installed, not assumed from the stdlib docs.
_HTML = importlib.resources.files(__package__).joinpath(
    "report_template.html"
).read_text(encoding="utf-8")


@functools.cache
def _font_data_uri(relative_path: str) -> str:
    """Read a vendored font and return it as a `data:` URI.

    Same reasoning as `_HTML` above, and the same failure shape: a path
    relative to `__file__` works from a checkout and an installed wheel and
    breaks only inside website_palette_extractor.pyz. `importlib.resources`
    reads through the zip loader instead.

    Inlined rather than shipped as a sibling file next to the emitted
    report -- invariant 11 requires the report to open standalone from
    `file://`, and a `./assets/fonts/...` relative `url()` (the template's
    own first draft) is exactly the external reference that invariant
    forbids: separate the HTML from that sibling directory -- move it,
    email it, share just the one file -- and the fonts silently vanish.
    Only the two faces the report's own CSS can ever select are vendored at
    all (report_template.html's own comment, PLAN.md T29); the rest of each
    font family's weights were deleted rather than inlined unused, since a
    Nerd Font's per-weight file is several MB and this project already
    counts a report's own weight in its size budget (invariant 11's tests
    diff full HTML, not just structure).

    Called from inside `emit_html`, not eagerly at import time the way
    `_HTML` is -- `_HTML` is ~30KB and free to load unconditionally, but
    these two files are ~3MB raw between them, and `__main__.py` imports
    this module even for a `--formats json`-only run that never touches
    HTML at all. `functools.cache` keeps the "don't re-read and re-encode
    on a second `emit_html()` call" guarantee module-scope constants would
    have provided, without paying the cost on every import.
    """
    data = importlib.resources.files(__package__).joinpath(
        relative_path
    ).read_bytes()
    return f"data:font/ttf;base64,{base64.b64encode(data).decode('ascii')}"


def emit_html(doc: dict, pal: Palette) -> str:
    title = doc["name"]
    themes = doc["themes"]
    n_live = len([c for c in doc["colors"] if c["status"] == "live"])
    n_other = len(doc["colors"]) - n_live

    sub = (
        # T24: not "confirmed painted" -- a live color sourced entirely from
        # a `:hover`/`:focus`-only selector (Caveats section, below) is
        # never confirmed at all, the same overclaim invariant 27's own
        # subtitle fix already corrected for `unmatched` ("found in the
        # source but not painted" implied a confirmed non-match every
        # `unmatched` entry doesn't have). Dropped rather than hedged
        # inline, same precedent.
        f"{n_live} color{'s' if n_live != 1 else ''} painted on the page"
        + (f", plus {n_other} more found in the source" if n_other else "")
        + ". Read from the site's own stylesheets, not sampled from a "
          "screenshot. Click any swatch to copy it."
    )
    if len(themes) > 1:
        looks = " and ".join(t["appearance"] for t in themes)
        sub += (f" The site ships two themes ({looks}) – switch between them "
                "below; every value and ratio is re-read for the one shown.")
    if doc.get("source"):
        src = htmlmod.escape(doc["source"])
        sub += f' Source: <a href="{src}">{src}</a>.'

    payload = json.dumps(doc, ensure_ascii=False)
    # Keep the JSON from terminating the script element early.
    payload = payload.replace("</", "<\\/")

    # One pass, not a chain of `str.replace`. Chained replaces rescan the text
    # they have already substituted, so a placeholder filled in early can have
    # a *later* placeholder's name appear inside its own substituted content
    # and be rewritten again. That is not hypothetical: `__DATA__` is the
    # site's own JSON, and a site whose CSS contains the literal token
    # `__GROUP_TITLES__` (a class name is enough) had that token replaced
    # inside the data blob, producing invalid JSON and a report that renders
    # nothing – invariant 11's standalone guarantee broken by the site's own
    # content. `re.sub` with a callback visits each placeholder in the
    # *template* exactly once and never re-reads what it wrote.
    # Test: test_site_content_cannot_corrupt_the_report_payload.
    fills = {
        "__TITLE__": htmlmod.escape(title),
        "__TITLE_HTML__": htmlmod.escape(title),
        "__SUBTITLE__": sub,
        "__UI_THEMES__": _ui_theme_css(themes),
        "__DATA__": payload,
        "__GROUP_TITLES__": json.dumps(GROUP_TITLES),
        "__GROUP_BLURBS__": json.dumps(GROUP_BLURBS),
        "__STATUS_TITLES__": json.dumps(STATUS_TITLES),
        "__STATUS_BLURBS__": json.dumps(STATUS_BLURBS, ensure_ascii=False),
        "__FONT_INTER__": _font_data_uri("assets/fonts/inter/inter_variable.ttf"),
        "__FONT_MONO__": _font_data_uri(
            "assets/fonts/sauce_code_pro/sauce_code_pro_mono__regular.ttf"
        ),
    }
    # Longest first: `re` alternation is leftmost-first, not longest-match, so
    # an alternation listing `__TITLE__` before `__TITLE_HTML__` would match
    # the shorter one inside the longer and leave `_HTML` behind. The trailing
    # `__` happens to prevent that for this particular set, which is exactly
    # the kind of accident worth not relying on.
    pattern = "|".join(re.escape(k) for k in sorted(fills, key=len, reverse=True))
    # A replacement is returned verbatim by the callback, so backslashes and
    # `\g<...>` inside a color value or selector are never read as group refs.
    return re.sub(pattern, lambda m: fills[m.group(0)], _HTML)
