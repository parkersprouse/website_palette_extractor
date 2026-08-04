"""Writing the palette out in each format, including the interactive page."""
from __future__ import annotations

import datetime
import html as htmlmod
import json
import re

from .color import Color, contrast_ratio, parse_color
from .extract import Palette, describe

# The document's own schema stamp — moves on a separate schedule from
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
    "saved": "A custom property nothing in the CSS references — often a "
             "design tool's saved swatches.",
    "inert": "A declaration that paints nothing, such as a shadow with "
             "every length at zero.",
    "unmatched": "This selector matched nothing in the page this tool "
                 "captured — could be unused CSS, or could be markup only "
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
    top-level `ground`, `stats` and `colors` mirror the default theme — the
    first entry — so that everything reading this document before themes
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
        lines.append(f"{indent}/* Declared with alpha — use over the ground "
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
        " * Generated by Website Palette Extractor — do not edit by hand.",
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
            f"/* {look.title()} theme — ground {alt['ground']}.",
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
           "// Generated by Website Palette Extractor — do not edit by hand.", ""]
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
           "// Generated by Website Palette Extractor — do not edit by hand.", ""]
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
        "// Generated by Website Palette Extractor — drop into tailwind.config.js\n\n"
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
    right up until the palette has no readable pairing — a light site with no
    dark ink, say. So each choice is contrast-checked and falls back rather
    than shipping an unreadable page.
    """
    ground = parse_color(doc["ground"]) or Color(255, 255, 255)
    dark_bg = ground.luminance() < 0.4

    # Text for the report is chosen for legibility first. Earlier versions of
    # this picked whichever extracted color merely cleared the contrast bar,
    # which produced red body copy on one site and brown on another — faithful
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
    uses goes through these variables — including the toast, which used to be
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


_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · palette</title>
<style>
  *, *::before, *::after { box-sizing: border-box; }
__UI_THEMES__
  body {
    margin: 0; padding: 2rem 1.5rem 5rem;
    background: var(--ui-ground); color: var(--ui-body);
    font-family: "Helvetica Neue", Helvetica, Arial, system-ui, sans-serif;
    font-size: 15px; line-height: 1.45;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1060px; margin: 0 auto; }
  a { color: var(--ui-strong); }
  code, .mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }

  header { border-bottom: 1px solid var(--ui-line); padding-bottom: 1.4rem;
           margin-bottom: 2rem; }
  h1 { margin: 0 0 .35rem; font-size: clamp(1.7rem, 5vw, 2.9rem);
       font-weight: 700; letter-spacing: -.03em; color: var(--ui-strong); }
  h1 .dot { color: var(--ui-accent); }
  .sub { margin: 0; max-width: 68ch; color: var(--ui-body); }

  .stats { display: flex; flex-wrap: wrap; gap: 1.4rem; margin-top: 1rem;
           font-size: .8rem; color: var(--ui-muted); }
  .stats b { color: var(--ui-strong); font-weight: 700; }

  .controls { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center;
              margin-bottom: 2rem; }
  .controls label { font-size: .8rem; color: var(--ui-muted); margin-right: .2rem; }
  .seg { display: inline-flex; border: 1px solid var(--ui-line); }
  .seg button {
    appearance: none; background: none; border: 0; cursor: pointer;
    font: inherit; font-size: .78rem; padding: .34rem .7rem;
    color: var(--ui-muted); border-right: 1px solid var(--ui-line);
  }
  .seg button:last-child { border-right: 0; }
  .seg button[aria-pressed="true"] { background: var(--ui-strong);
                                     color: var(--ui-ground); font-weight: 700; }
  .seg button:focus-visible { outline: 2px solid var(--ui-accent);
                              outline-offset: -2px; }
  .seg.cap button { text-transform: capitalize; }
  [hidden] { display: none !important; }

  section { margin-bottom: 2.6rem; }
  h2 { font-size: .72rem; font-weight: 700; letter-spacing: .14em;
       text-transform: uppercase; color: var(--ui-muted); margin: 0 0 .2rem; }
  .blurb { margin: 0 0 1rem; font-size: .86rem; color: var(--ui-muted);
           max-width: 62ch; }

  h3.status-heading { font-size: .66rem; font-weight: 700; letter-spacing: .1em;
       text-transform: uppercase; color: var(--ui-muted); margin: 1.2rem 0 .15rem; }
  h3.status-heading:first-of-type { margin-top: .3rem; }
  .status-blurb { margin: 0 0 .6rem; font-size: .78rem; color: var(--ui-muted);
                  max-width: 60ch; }

  .grid { display: grid; gap: 10px;
          grid-template-columns: repeat(auto-fill, minmax(198px, 1fr)); }

  .sw { appearance: none; border: 1px solid var(--ui-line); background: none;
        padding: 0; text-align: left; font: inherit; color: inherit;
        cursor: pointer; display: flex; flex-direction: column; position: relative; }
  .sw:focus-visible { outline: 2px solid var(--ui-accent); outline-offset: 2px; }
  .sw:hover { border-color: var(--ui-strong); }

  .chip { height: 80px; border-bottom: 1px solid var(--ui-line);
          position: relative; }
  .chip.alpha {
    background-image:
      linear-gradient(45deg, var(--ui-checker) 25%, transparent 25%,
                      transparent 75%, var(--ui-checker) 75%),
      linear-gradient(45deg, var(--ui-checker) 25%, transparent 25%,
                      transparent 75%, var(--ui-checker) 75%);
    background-size: 12px 12px; background-position: 0 0, 6px 6px;
  }
  .chip .fill { position: absolute; inset: 0; }
  .tag { position: absolute; top: .45rem; right: .45rem; font-size: .58rem;
         font-weight: 700; letter-spacing: .09em; text-transform: uppercase;
         padding: .16rem .38rem; background: var(--ui-ground);
         color: var(--ui-muted); border: 1px solid var(--ui-line); }
  .tag.inert { color: var(--ui-accent); border-color: var(--ui-accent); }

  .meta { padding: .55rem .65rem .65rem; }
  .name { font-weight: 700; color: var(--ui-strong); letter-spacing: -.01em;
          word-break: break-word; }
  .val { font-size: .78rem; color: var(--ui-muted); text-transform: lowercase;
         word-break: break-all; margin-top: .1rem; }
  .role { font-size: .74rem; color: var(--ui-muted); margin-top: .3rem; }
  .cr { font-size: .7rem; color: var(--ui-muted); margin-top: .25rem; }
  .cr.warn { color: var(--ui-accent); }

  details.detail { margin-top: 1.4rem; border: 1px solid var(--ui-line); }
  details.detail summary { cursor: pointer; padding: .6rem .8rem;
    font-size: .78rem; letter-spacing: .1em; text-transform: uppercase;
    font-weight: 700; color: var(--ui-muted); }
  details.detail summary:focus-visible { outline: 2px solid var(--ui-accent);
                                         outline-offset: -2px; }
  .detail-body { padding: 0 .8rem .8rem; font-size: .8rem; }
  table { width: 100%; border-collapse: collapse; font-size: .78rem; }
  th, td { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid
           var(--ui-line); vertical-align: top; }
  th { color: var(--ui-muted); font-weight: 700; }

  .warn-box { border: 1px solid var(--ui-accent); padding: .8rem 1rem;
              margin-bottom: 1.6rem; font-size: .84rem; }
  .warn-box h3 { margin: 0 0 .4rem; font-size: .72rem; letter-spacing: .1em;
                 text-transform: uppercase; color: var(--ui-accent); }
  .warn-box ul { margin: 0; padding-left: 1.1rem; color: var(--ui-muted); }

  /* T24: always-present, unlike .warn-box -- explains the category even on
     a site that triggers none of it, the same way STATUS_BLURBS explains
     every status regardless of which ones a given palette has. Neutral
     border rather than --ui-accent: this is a standing limit of the method,
     not a site-specific problem to flag. */
  .caveat-box { border: 1px solid var(--ui-line); padding: .8rem 1rem;
                margin-bottom: 1.6rem; font-size: .84rem; color: var(--ui-muted); }
  .caveat-box h3 { margin: 0 0 .4rem; font-size: .72rem; letter-spacing: .1em;
                   text-transform: uppercase; color: var(--ui-strong); }
  .caveat-box p { margin: 0 0 .5rem; max-width: 64ch; }
  .caveat-box ul { margin: 0; padding-left: 1.1rem; }

  .pairs { display: grid; gap: 8px;
           grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); }
  .pair { border: 1px solid var(--ui-line); padding: .7rem .8rem; }
  .pair .demo { font-size: 1.02rem; font-weight: 600; }
  .pair .lab { font-size: .68rem; margin-top: .35rem; opacity: .75; }

  footer { margin-top: 2.6rem; padding-top: 1.2rem;
           border-top: 1px solid var(--ui-line); font-size: .78rem;
           color: var(--ui-muted); }

  #toast { position: fixed; left: 50%; bottom: 1.4rem;
    transform: translate(-50%, 160%); background: var(--ui-toast-bg);
    color: var(--ui-toast-fg); font-weight: 700; font-size: .84rem;
    padding: .5rem 1rem; transition: transform .18s ease-out; z-index: 50; }
  #toast.show { transform: translate(-50%, 0); }
  @media (prefers-reduced-motion: reduce) {
    #toast { transition: none; }
  }
  @media (max-width: 480px) { body { padding: 1.25rem 1rem 4rem; } }
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>__TITLE_HTML__<span class="dot">.</span></h1>
  <p class="sub">__SUBTITLE__</p>
  <div class="stats" id="stats"></div>
</header>

<div id="warnings"></div>

<div class="controls">
  <label id="theme-label" hidden>Theme</label>
  <div class="seg cap" role="group" aria-labelledby="theme-label" id="theme"
       hidden></div>
  <label id="fmt-label">Copy as</label>
  <div class="seg" role="group" aria-labelledby="fmt-label" id="fmt"></div>
  <label id="show-label" style="margin-left:auto">Show</label>
  <div class="seg" role="group" aria-labelledby="show-label" id="filter"></div>
</div>

<div id="groups"></div>

<section id="pairs-section">
  <h2>Contrast</h2>
  <p class="blurb">Every extracted color against the ground, at body size.
     Ratios below 4.5:1 are marked — that is the WCAG AA floor for normal text.</p>
  <div class="pairs" id="pairs"></div>
</section>

<details class="detail">
  <summary>Where each color came from</summary>
  <div class="detail-body">
    <table id="prov"><thead><tr>
      <th>Token</th><th>Value</th><th>Score</th><th>Uses</th>
      <th>Seen in</th>
    </tr></thead><tbody></tbody></table>
  </div>
</details>

<details class="detail">
  <summary>Extraction report</summary>
  <div class="detail-body" id="report"></div>
</details>

<div id="caveats"></div>

<footer id="footer"></footer>
</div>

<div id="toast" role="status" aria-live="polite"></div>

<script type="application/json" id="palette-data">__DATA__</script>
<script>
(function () {
  "use strict";
  var doc = JSON.parse(document.getElementById("palette-data").textContent);

  var GROUP_TITLES = __GROUP_TITLES__;
  var GROUP_BLURBS = __GROUP_BLURBS__;
  var GROUP_ORDER = ["ground", "surface", "ink", "line", "neutral", "chroma"];
  var STATUS_TITLES = __STATUS_TITLES__;
  var STATUS_BLURBS = __STATUS_BLURBS__;
  var STATUS_ORDER = ["live", "saved", "inert", "unmatched"];

  var fmt = "hex";
  var filter = "live";

  /* Always at least one entry, so everything below has one code path whether
     or not the site shipped a second theme. Each carries its own ground, and
     every contrast figure in it was measured against that ground — which is
     why switching themes redraws rather than recolours. */
  var THEMES = doc.themes;
  var themeIx = 0;

  /* A report about two themes should open in the one the reader is set up
     for, exactly as the site itself would. */
  if (THEMES.length > 1 && window.matchMedia) {
    var want = window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
    for (var i = 0; i < THEMES.length; i++) {
      if (THEMES[i].appearance === want) { themeIx = i; break; }
    }
  }

  function theme() { return THEMES[themeIx]; }

  function applyTheme() {
    /* Swaps the report's own reading colors. The swatches are redrawn by
       render(), since their values and ratios differ per theme. */
    document.documentElement.setAttribute("data-pk-theme", theme().id);
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function valueFor(c) {
    if (fmt === "declared") {
      return c.source ? c.source.declaredAs : c.hex;
    }
    return c.css[fmt] || c.hex;
  }

  function visible() {
    return theme().colors.filter(function (c) {
      return filter === "all" ? true : c.status === "live";
    });
  }

  /* ---------- stats ---------- */
  var stats = document.getElementById("stats");
  function stat(label, value) {
    var s = el("span");
    s.appendChild(el("b", null, String(value)));
    s.appendChild(document.createTextNode(" " + label));
    stats.appendChild(s);
  }
  function renderStats() {
    stats.textContent = "";
    var t = theme();
    stat("tokens", t.colors.length);
    stat("declarations scanned", t.stats.declarationsScanned);
    stat("stylesheets", t.stats.stylesheets);
    stat("distinct colors before merge", t.stats.distinctColors);
  }

  /* ---------- warnings ---------- */
  if (doc.warnings && doc.warnings.length) {
    var box = el("div", "warn-box");
    box.appendChild(el("h3", null, "Read this before trusting the palette"));
    var ul = el("ul");
    doc.warnings.forEach(function (w) { ul.appendChild(el("li", null, w)); });
    box.appendChild(ul);
    document.getElementById("warnings").appendChild(box);
  }

  /* ---------- controls ---------- */
  if (THEMES.length > 1) {
    var themeHost = document.getElementById("theme");
    /* Label by appearance, which is what a reader recognises. When both
       themes land on the same side of the light/dark line the appearance is
       no longer a distinction, so fall back to the rule that defines each —
       two buttons both reading "dark" would be worse than no toggle. */
    var sameLook = THEMES[0].appearance === THEMES[1].appearance;
    THEMES.forEach(function (t, i) {
      var b = el("button", null, sameLook ? t.id : t.appearance);
      b.setAttribute("aria-pressed", String(i === themeIx));
      b.addEventListener("click", function () {
        themeIx = i;
        themeHost.querySelectorAll("button").forEach(function (x, j) {
          x.setAttribute("aria-pressed", String(j === themeIx));
        });
        applyTheme();
        render();
      });
      themeHost.appendChild(b);
    });
    themeHost.hidden = false;
    document.getElementById("theme-label").hidden = false;
  }

  var FORMATS = [["hex", "hex"], ["rgb", "rgb"], ["hsl", "hsl"],
                 ["oklch", "oklch"], ["declared", "as declared"]];
  var fmtHost = document.getElementById("fmt");
  FORMATS.forEach(function (f) {
    var b = el("button", null, f[1]);
    b.setAttribute("aria-pressed", String(f[0] === fmt));
    b.addEventListener("click", function () {
      fmt = f[0];
      fmtHost.querySelectorAll("button").forEach(function (x, i) {
        x.setAttribute("aria-pressed", String(FORMATS[i][0] === fmt));
      });
      render();
    });
    fmtHost.appendChild(b);
  });

  var FILTERS = [["live", "rendered only"], ["all", "everything found"]];
  var filtHost = document.getElementById("filter");
  FILTERS.forEach(function (f) {
    var b = el("button", null, f[1]);
    b.setAttribute("aria-pressed", String(f[0] === filter));
    b.addEventListener("click", function () {
      filter = f[0];
      filtHost.querySelectorAll("button").forEach(function (x, i) {
        x.setAttribute("aria-pressed", String(FILTERS[i][0] === filter));
      });
      render();
    });
    filtHost.appendChild(b);
  });

  /* ---------- swatches ---------- */
  function swatch(c) {
    var btn = el("button", "sw");
    btn.setAttribute("aria-label", "Copy " + valueFor(c) + " — " + c.name);
    btn.title = c.usedIn.join(", ");

    var chip = el("div", "chip" + (c.source ? " alpha" : ""));
    var fill = el("div", "fill");
    fill.style.background = c.source ? c.source.declaredAs : c.hex;
    chip.appendChild(fill);

    if (c.status !== "live") {
      var tag = el("span", "tag " + c.status, c.status);
      chip.appendChild(tag);
    }

    var meta = el("div", "meta");
    meta.appendChild(el("div", "name", c.name));
    meta.appendChild(el("div", "val mono", valueFor(c)));
    meta.appendChild(el("div", "role", c.role + " · " + c.occurrences +
      (c.occurrences === 1 ? " use" : " uses")));

    var cr = el("div", "cr mono" + (c.contrastOnGround < 4.5 ? " warn" : ""),
      c.contrastOnGround.toFixed(2) + ":1 · " + c.wcagOnGround);
    meta.appendChild(cr);

    btn.appendChild(chip);
    btn.appendChild(meta);
    btn.addEventListener("click", function () { copy(valueFor(c)); });
    return btn;
  }

  function render() {
    var host = document.getElementById("groups");
    host.textContent = "";
    var cols = visible();

    var byGroup = {};
    cols.forEach(function (c) {
      (byGroup[c.group] = byGroup[c.group] || []).push(c);
    });

    GROUP_ORDER.forEach(function (g) {
      var list = byGroup[g];
      if (!list || !list.length) return;
      var sec = el("section");
      sec.appendChild(el("h2", null, GROUP_TITLES[g] || g));
      sec.appendChild(el("p", "blurb", GROUP_BLURBS[g] || ""));

      /* T20: sub-group by status so a reader can see *why* a swatch isn't
         live without leaving the section — a per-status heading and one-line
         description, right beside the colors it explains. Skipped when the
         section is purely live (the default "rendered only" view, and any
         section with nothing else to explain), so the common case renders
         exactly as before. */
      var byStatus = {};
      list.forEach(function (c) {
        (byStatus[c.status] = byStatus[c.status] || []).push(c);
      });
      var statusesPresent = Object.keys(byStatus);
      var showStatusHeadings =
        statusesPresent.length > 1 || statusesPresent[0] !== "live";

      STATUS_ORDER.forEach(function (s) {
        var sub = byStatus[s];
        if (!sub || !sub.length) return;
        if (showStatusHeadings) {
          sec.appendChild(el("h3", "status-heading", STATUS_TITLES[s] || s));
          sec.appendChild(el("p", "status-blurb", STATUS_BLURBS[s] || ""));
        }
        var grid = el("div", "grid");
        sub.forEach(function (c) { grid.appendChild(swatch(c)); });
        sec.appendChild(grid);
      });
      host.appendChild(sec);
    });

    renderStats();
    renderPairs(cols);
    renderProv(cols);
    renderReport();
    renderFooter();
    renderCaveats();
  }

  function renderPairs(cols) {
    var host = document.getElementById("pairs");
    host.textContent = "";
    cols.forEach(function (c) {
      var d = el("div", "pair");
      /* The active theme's ground, not the document's — the ratio printed
         beside each sample was measured against this exact background. */
      d.style.background = theme().ground;
      var demo = el("div", "demo", "Sample text");
      demo.style.color = c.source ? c.source.declaredAs : c.hex;
      var lab = el("div", "lab mono",
        c.name + " · " + c.contrastOnGround.toFixed(2) + ":1 · " + c.wcagOnGround);
      lab.style.color = c.source ? c.source.declaredAs : c.hex;
      d.appendChild(demo);
      d.appendChild(lab);
      host.appendChild(d);
    });
  }

  function renderProv(cols) {
    var tb = document.querySelector("#prov tbody");
    tb.textContent = "";
    cols.forEach(function (c) {
      var tr = el("tr");
      tr.appendChild(el("td", "mono", c.name));
      tr.appendChild(el("td", "mono", valueFor(c)));
      tr.appendChild(el("td", "mono", String(c.score)));
      tr.appendChild(el("td", "mono", String(c.occurrences)));
      var ex = (c.examples || []).slice(0, 3).map(function (e) {
        var s = e.selector + " { " + e.property + " }";
        if (typeof e.matchCount === "number") {
          s += " (" + e.matchCount + (e.matchCount === 1 ? " match" : " matches") + ")";
        }
        return s;
      }).join("  ·  ");
      tr.appendChild(el("td", "mono", ex));
      tb.appendChild(tr);
    });
  }

  /* ---------- report ---------- */
  var rep = document.getElementById("report");

  function renderReport() {
    rep.textContent = "";
    var t = theme();
    var dl = el("table");
    var tbody = el("tbody");
    function row(k, v) {
      var tr = el("tr");
      tr.appendChild(el("th", null, k));
      tr.appendChild(el("td", "mono", v));
      tbody.appendChild(tr);
    }
    row("Source", doc.source || "(local files)");
    if (THEMES.length > 1) {
      row("Theme", t.id + " (" + t.appearance + ")" +
          (t.scope ? " \\u2014 from rules scoped to " + t.scope : " \\u2014 " +
           "from rules belonging to no theme"));
    }
    row("Ground", t.ground + "  (" + t.groundSource + ")");
    row("Generated", doc.generated);
    row("Custom properties", t.stats.customProperties + " declared, " +
        t.stats.customPropertiesReferenced + " referenced");
    if (doc.images) {
      row("Images sampled", doc.images.imageCount + " (" +
          doc.images.neutralSharePct + "% of pixels visually neutral)");
    }
    dl.appendChild(tbody);
    rep.appendChild(dl);

    if (t.stats.sources && t.stats.sources.length) {
      rep.appendChild(el("p", null, "Stylesheets read:"));
      var st = el("table");
      var sh = el("thead");
      var shr = el("tr");
      ["Source", "Declarations", "Third party"].forEach(function (h) {
        shr.appendChild(el("th", null, h));
      });
      sh.appendChild(shr);
      st.appendChild(sh);
      var stb = el("tbody");
      t.stats.sources.forEach(function (s) {
        var tr = el("tr");
        tr.appendChild(el("td", "mono", s.source));
        tr.appendChild(el("td", "mono", String(s.declarations)));
        tr.appendChild(el("td", "mono", s.thirdParty ? "yes" : "no"));
        stb.appendChild(tr);
      });
      st.appendChild(stb);
      rep.appendChild(st);
    }
  }

  /* ---------- footer ---------- */
  function renderFooter() {
    var f = document.getElementById("footer");
    f.textContent =
      "Ground " + theme().ground + ". Values are read from the site's " +
      "stylesheets, not sampled from pixels. Non-live statuses are labelled " +
      "and described next to the colors they apply to, above. " +
      (THEMES.length > 1
        ? "The site ships two themes; each was extracted separately, so every " +
          "ratio above is measured against that theme's own ground. "
        : "") +
      "Colors themselves are not copyrightable, but fonts and images on the " +
      "source page are licensed separately.";
  }

  /* ---------- caveats ---------- */
  /* T24: always present, unlike #warnings -- explains the category even when
     this theme has no example of it, then names the entries it does have.
     Per-theme (dynamicOnly is a per-color flag), so it lives in render()
     rather than the one-time #warnings block above. */
  function renderCaveats() {
    var host = document.getElementById("caveats");
    host.textContent = "";
    var box = el("div", "caveat-box");
    box.appendChild(el("h3", null, "What “live” can't promise"));
    box.appendChild(el("p", null,
      "A color is marked live once this tool can show its selector on the " +
      "page it captured. A selector written only for an interaction state " +
      "— :hover, :focus, and the like — has no resting state to " +
      "capture: the state doesn't exist until someone is actually " +
      "interacting, so no capture, however complete, can confirm or rule " +
      "it out. Those colors stay live — unconfirmed is not the same " +
      "as absent — but nothing here has verified they render."));
    var dyn = theme().colors.filter(function (c) { return c.dynamicOnly; });
    if (dyn.length) {
      var p2 = el("p", null, dyn.length === 1
        ? "One color in this theme rests entirely on that kind of rule:"
        : dyn.length + " colors in this theme rest entirely on that kind " +
          "of rule:");
      box.appendChild(p2);
      var ul = el("ul");
      dyn.forEach(function (c) {
        ul.appendChild(el("li", null, c.name + " (" + c.hex + ")"));
      });
      box.appendChild(ul);
    }
    host.appendChild(box);
  }

  /* ---------- copy ---------- */
  var toast = document.getElementById("toast");
  var timer;
  function copy(text) {
    var done = function (ok) {
      toast.textContent = ok ? "Copied " + text : text;
      toast.classList.add("show");
      clearTimeout(timer);
      timer = setTimeout(function () { toast.classList.remove("show"); }, 1400);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); },
                                               function () { done(false); });
    } else {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "absolute";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      done(ok);
    }
  }

  applyTheme();
  render();
})();
</script>
</body>
</html>
"""


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
        sub += (f" The site ships two themes ({looks}) — switch between them "
                "above; every value and ratio is re-read for the one shown.")
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
    # nothing — invariant 11's standalone guarantee broken by the site's own
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
