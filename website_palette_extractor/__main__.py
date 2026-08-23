"""Website Palette Extractor – build a browsable page from a site's extracted color palette.

    python3 -m website_palette_extractor <target> [-o outdir] [options]

<target> is a .har export, an http(s) URL, or a local .html/.css file or
directory. A HAR is the most reliable input: it is what the browser actually
loaded, so it includes styles injected at runtime and works on sites that
refuse automated requests.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import PYTHON_FLOOR, emit, extract, images, sources
from .color import find_colors
from .cssparse import FONT_PROPERTIES, resolve_vars
from .sources import Bundle

# The outputs `--formats` accepts. Kept beside the writer block in `main()`
# that consumes it – an unknown name used to be dropped silently, so
# `--formats jsn` created an empty directory, printed an empty "wrote:" list
# and exited 0, which reads exactly like a site with no colors in it.
FORMATS = ("html", "json", "css", "scss", "ts", "tailwind")

PROG_NAME = "website-palette-extractor"


def requested_formats(spec: str) -> set[str]:
    """Split a `--formats` value the one way it is ever split.

    `_validate` decides what is acceptable and `main` decides what to write;
    if they parsed the string separately, a change to the splitting rule
    would leave the validator describing something other than what gets
    written – the kind of duplication that only shows up once it diverges.
    """
    return {f.strip().lower() for f in spec.split(",") if f.strip()}


def build_parser() -> argparse.ArgumentParser:
    cmd_prefix = PROG_NAME
    try:
        suffix = sys.argv[0].split('/')[-1]
        cmd_prefix = "python3 -m website_palette_extractor" if suffix == "__main__.py" else suffix
    except: # noqa: E722
        # we're not concerned about any errors thrown to get us here since we're
        # just going to fall back to using the default assigned script name
        pass

    p = argparse.ArgumentParser(
        # The installed console script, which is hyphenated; the underscored
        # form in the examples below is the *import package*, which `-m` needs.
        prog=PROG_NAME,
        description="Extract a color palette from a website's styles and "
                    "render it as an interactive page.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            f"  {cmd_prefix} site.har -o palette\n"
            f"  {cmd_prefix} https://example.com -o palette\n"
            f"  {cmd_prefix} site.har --images --all\n"
            f"  {cmd_prefix} ./page/ -o out --prefix brand\n"
        ),
    )
    p.add_argument("target", help=".har file, URL, or local html/css path")
    p.add_argument("-o", "--out", default="palette-out",
                   help="output directory (default: palette-out)")
    p.add_argument("--all", action="store_true",
                   help="keep third-party stylesheets at full weight instead "
                        "of down-weighting them")
    p.add_argument("--exclude", action="append", metavar="TEXT",
                   help="skip stylesheets whose source contains TEXT "
                        "(repeatable) – useful for dropping a framework or "
                        "site-builder bundle")
    p.add_argument("--fonts", action="store_true",
                   help="also embed the page's real font files in the HTML "
                        "report, for accurate Typography-section previews "
                        "(metadata is always extracted; this only adds the "
                        "actual bytes). Uses bytes already in a HAR capture "
                        "as-is; for a live URL target it also fetches the "
                        "binaries the CSS points to")
    p.add_argument("--flat", action="store_true",
                   help="one token per distinct color, instead of separating "
                        "a color used for text from the same color used for "
                        "a background")
    p.add_argument("--formats", default="html,json,css,scss,ts,tailwind",
                   help="comma-separated outputs to write")
    p.add_argument("--images", action="store_true",
                   help="also quantize the page's images to check whether the "
                        "artwork carries color (needs pillow + numpy)")
    p.add_argument("--include-unused", action="store_true",
                   help="also put saved/inert colors in the css, scss, ts and "
                        "tailwind files (they are always in the json)")
    p.add_argument("--limit", type=int, default=0, metavar="N",
                   help="keep only the top N colors by score")
    p.add_argument("--list-sources", action="store_true",
                   help="list the stylesheets found, with their color counts, "
                        "then exit")
    p.add_argument("--merge", type=float, default=0.02, metavar="D",
                   help="OKLab distance below which colors are merged "
                        "(default 0.02; 0 disables)")
    p.add_argument("--min-score", type=float, default=0.0, metavar="SCORE",
                   help="drop colors that score below this value (default 0 -- don't drop any)")
    p.add_argument("--no-themes", action="store_true",
                   help="treat the site as having one theme, even where it "
                        "scopes rules to prefers-color-scheme or a .dark class")
    p.add_argument("--no-third-party", action="store_true",
                   help="ignore stylesheets served from another origin")
    p.add_argument("--only", action="append", metavar="TEXT",
                   help="only read stylesheets whose source contains TEXT "
                        "(repeatable)")
    p.add_argument("--prefix", default="c",
                   help="CSS custom property prefix (default: c)")
    p.add_argument("--quiet", action="store_true", help="suppress the summary")
    p.add_argument("--timeout", type=float, default=20.0,
                   help="network timeout in seconds when fetching a URL")
    p.add_argument("--var-name", default="palette",
                   help="exported name in the TypeScript file")
    return p


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < PYTHON_FLOOR:
        have = ".".join(map(str, sys.version_info[:3]))
        need = ".".join(map(str, PYTHON_FLOOR))
        print(
            f"error: {PROG_NAME} requires Python {need}+ (running {have}).",
            file=sys.stderr
        )
        return 1

    args = build_parser().parse_args(argv)

    problem = _validate(args)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2

    want = requested_formats(args.formats)

    if args.images:
        ok, msg = images.available()
        if not ok:
            print(f"warning: {msg}", file=sys.stderr)

    try:
        bundle = sources.load_any(args.target, want_images=args.images,
                                  want_fonts=args.fonts, timeout=args.timeout)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not bundle.assets:
        print("error: nothing readable in that target.", file=sys.stderr)
        return 2

    if args.list_sources:
        _list_sources(bundle, args)
        return 0

    pal = extract.extract(
        bundle,
        merge_threshold=args.merge,
        include_third_party=not args.no_third_party,
        third_party_weight=1.0 if args.all else 0.25,
        min_score=args.min_score,
        only=args.only,
        exclude=args.exclude,
        flat=args.flat,
        themes=not args.no_themes,
    )

    if args.limit:
        # Applied per theme, so the two stay comparable.
        for p in [pal, pal.alternate]:
            if p and len(p.entries) > args.limit:
                p.entries = p.entries[: args.limit]

    if not pal.entries:
        print("error: no colors found. If the target was a URL, the page may "
              "style itself with JavaScript – try a HAR export instead.",
              file=sys.stderr)
        return 1

    if args.images:
        blobs = [a.data for a in bundle.by_kind("image") if a.data]
        pal.image_report = images.analyse(blobs)
        if pal.image_report and pal.image_report["neutralSharePct"] < 70:
            pal.warnings.append(
                "The page's imagery carries color that the stylesheet does "
                "not. A CSS-only palette will miss it."
            )

    font_bytes = None
    if args.fonts and "html" in want:
        # Only ever consumed by emit_html below – for a URL target this can
        # mean a live network fetch (sources.fetch_binaries), which a
        # `--formats json` run has no use for; gating on "html" in want
        # stops that fetch from happening at all rather than happening and
        # being discarded.
        #
        # A HAR target stays bytes-already-present-only – it is a frozen
        # capture, and fetching fresh binaries for it defeats the point and
        # can hit an expired/blocked URL (sources.fetch_binaries' own
        # docstring). Every other target (a live URL, or local files that
        # happen to reference a CDN font) may fetch.
        is_har = args.target.lower().endswith(".har") and os.path.exists(args.target)
        font_bytes = _collect_font_bytes(pal, bundle, args.timeout,
                                         allow_fetch=not is_har)

    doc = emit.to_document(pal)
    try:
        os.makedirs(args.out, exist_ok=True)
    except OSError as e:
        # Every other failure in this function reports itself and returns a
        # code; an unwritable -o used to be the one that ended in a traceback,
        # and it does so *after* the whole extraction has already run.
        print(f"error: could not create output directory {args.out}: {e}",
              file=sys.stderr)
        return 2
    slug = emit.slug(pal)
    written = []

    def write(name: str, text: str) -> None:
        path = os.path.join(args.out, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        written.append(path)

    try:
        if "json" in want:
            write(f"{slug}.json",
                  json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        if "css" in want:
            write(f"{slug}.css",
                  emit.emit_css(doc, args.prefix, args.include_unused))
        if "scss" in want:
            write(f"{slug}.scss",
                  emit.emit_scss(doc, args.prefix, args.include_unused))
        if "ts" in want:
            write(f"{slug}.ts",
                  emit.emit_ts(doc, args.var_name, args.include_unused))
        if "tailwind" in want:
            write(f"{slug}.tailwind.js",
                  emit.emit_tailwind(doc, args.include_unused))
        if "html" in want:
            write("index.html", emit.emit_html(doc, pal, font_bytes=font_bytes))
    except OSError as e:
        # A full disk or a read-only directory is the same class of failure as
        # an uncreatable one above, and reporting the files already written
        # matters: the run is partially complete, not a clean no-op.
        print(f"error: could not write output: {e}", file=sys.stderr)
        if written:
            print(f"  wrote {len(written)} file(s) before failing.",
                  file=sys.stderr)
        return 2

    if not args.quiet:
        _summarise(doc, pal, written)
    return 0


def _validate(args: argparse.Namespace) -> str | None:
    """Check the numeric and enumerated options before any work happens.

    Returns the message to print, or None if the arguments are usable. These
    are checked here rather than with argparse `type=` callables so that all
    of them are reachable from a plain `main([...])` call in a test without
    catching `SystemExit`, the same way every other failure in `main` is.

    Each of these used to be accepted and then quietly do the wrong thing
    rather than fail: a negative `--limit` reached `entries[:limit]` and
    trimmed tokens off the *end* of the palette (`[:-5]` drops five), which
    looks like a smaller site rather than a rejected flag.
    """
    want = requested_formats(args.formats)
    unknown = sorted(f for f in want if f not in FORMATS)
    if unknown:
        return (f"unknown --formats value(s): {', '.join(unknown)}. "
                f"Valid: {', '.join(FORMATS)}.")
    if not want:
        return f"--formats is empty. Valid: {', '.join(FORMATS)}."
    if args.limit < 0:
        return f"--limit must be 0 or more, got {args.limit}."
    if args.merge < 0:
        return f"--merge must be 0 or more, got {args.merge} (0 disables merging)."
    if args.min_score < 0:
        return f"--min-score must be 0 or more, got {args.min_score}."
    if args.timeout <= 0:
        return f"--timeout must be greater than 0, got {args.timeout}."
    return None


def _collect_font_bytes(pal: extract.Palette, bundle: Bundle, timeout: float,
                        allow_fetch: bool) -> dict[str, bytes]:
    """Bytes for every font `src` URL `pal.fonts` references, keyed by URL.

    Bytes already sitting in the bundle (a HAR capture, once `--fonts`
    widened `sources._kind_for` to keep them) are used first and are free;
    `allow_fetch` gates whether a live request is made for whatever's still
    missing – see `main`'s own call site and `sources.fetch_binaries` for why
    a HAR target never sets it.
    """
    urls = {s["url"]
           for entry in pal.fonts for face in entry.get("faces", [])
           for s in face.get("src", [])}
    have = {a.url: a.data for a in bundle.by_kind("font") if a.data and a.url in urls}
    missing = urls - have.keys()
    if missing and allow_fetch:
        have.update(sources.fetch_binaries(sorted(missing), timeout=timeout))
    return have


def _list_sources(bundle: Bundle, args: argparse.Namespace) -> None:
    """Show what CSS was found and how much color each source carries.

    On a site built with a page builder or a component framework, most colors
    come from one bundle that has nothing to do with the site's own design.
    Seeing the split is the fastest way to know whether to --exclude it.
    """
    sheets = extract.collect_sheets(
        bundle, include_third_party=not args.no_third_party
    )
    table = extract.build_var_table(sheets)
    print(f"\n{len(sheets)} stylesheet(s), in the order the page applies them:\n")
    print(f"  {'#':>2}  {'decls':>6}  {'colors':>7}  {'3p':>3}  source")
    for i, sh in enumerate(sheets):
        n_col = 0
        # Excludes only the newly-kept font declarations, not every
        # `role == "other"` one – that would also drop `color-scheme`
        # (its own role is "other" too), which this table always counted.
        # See `extract._source_stats`'s own comment for the full reasoning;
        # this is the same fix for the same latent bug.
        n_decl = sum(1 for d in sh.declarations if d.prop not in FONT_PROPERTIES)
        for d in sh.declarations:
            n_col += len(find_colors(resolve_vars(d.value, table)))
        print(f"  {i:>2}  {n_decl:>6}  {n_col:>7}  "
              f"{'yes' if sh.third_party else '  -':>3}  {sh.source}")
    print("\n  Narrow with --only TEXT or --exclude TEXT (substring match).\n")


def _summarise_theme(t: dict, label: bool) -> None:
    live = [c for c in t["colors"] if c["status"] == "live"]
    other = [c for c in t["colors"] if c["status"] != "live"]

    if label:
        print(f"\n  [{t['id']}]")
    print(f"  ground {t['ground']}  ({t['groundSource']})")
    print(f"  scanned {t['stats']['declarationsScanned']} declarations in "
          f"{t['stats']['stylesheets']} stylesheets")
    print(f"  {t['stats']['distinctColors']} distinct colors -> "
          f"{len(t['colors'])} tokens after merging\n")

    width = max((len(c["name"]) for c in t["colors"]), default=8)
    for c in live:
        flag = "" if c["contrastOnGround"] >= 4.5 else "  low contrast"
        print(f"  {c['name']:<{width}}  {c['hex']}  {c['role']:<8} "
              f"{c['contrastOnGround']:>6.2f}:1{flag}")
    if other:
        print()
        for c in other:
            print(f"  {c['name']:<{width}}  {c['hex']}  [{c['status']}]")


def _summarise(doc: dict, pal: extract.Palette, written: list[str]) -> None:
    themes = doc["themes"]
    print(f"\n{doc['name']}")
    if len(themes) > 1:
        print("  two themes: " + ", ".join(
            f"{t['id']} ({t['appearance']}, ground {t['ground']})"
            for t in themes))
    for t in themes:
        _summarise_theme(t, len(themes) > 1)

    if doc.get("images"):
        im = doc["images"]
        print(f"\n  images: {im['imageCount']} sampled, "
              f"{im['neutralSharePct']}% of pixels neutral")
        print(f"  {im['verdict']}")

    if doc["warnings"]:
        print("\n  notes:")
        for w in doc["warnings"]:
            print(f"    - {w}")

    print("\n  wrote:")
    for p in written:
        print(f"    {p}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
