"""palettekit — extract a site's color palette and build a browsable page.

    python3 -m palettekit <target> [-o outdir] [options]

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

from . import emit, extract, images, sources


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="palettekit",
        description="Extract a color palette from a website's styles and "
                    "render it as an interactive page.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python3 -m palettekit site.har -o palette\n"
            "  python3 -m palettekit https://example.com -o palette\n"
            "  python3 -m palettekit site.har --images --all\n"
            "  python3 -m palettekit ./saved-page/ -o out --prefix brand\n"
        ),
    )
    p.add_argument("target", help=".har file, URL, or local html/css path")
    p.add_argument("-o", "--out", default="palette-out",
                   help="output directory (default: palette-out)")
    p.add_argument("--prefix", default="c",
                   help="CSS custom property prefix (default: c)")
    p.add_argument("--var-name", default="palette",
                   help="exported name in the TypeScript file")
    p.add_argument("--merge", type=float, default=0.02, metavar="D",
                   help="OKLab distance below which colors are merged "
                        "(default 0.02; 0 disables)")
    p.add_argument("--min-score", type=float, default=0.0,
                   help="drop colors scoring below this (default 0)")
    p.add_argument("--limit", type=int, default=0,
                   help="keep only the top N colors by score")
    p.add_argument("--all", action="store_true",
                   help="keep third-party stylesheets at full weight instead "
                        "of down-weighting them")
    p.add_argument("--no-third-party", action="store_true",
                   help="ignore stylesheets served from another origin")
    p.add_argument("--only", action="append", metavar="TEXT",
                   help="only read stylesheets whose source contains TEXT "
                        "(repeatable)")
    p.add_argument("--exclude", action="append", metavar="TEXT",
                   help="skip stylesheets whose source contains TEXT "
                        "(repeatable) — useful for dropping a framework or "
                        "site-builder bundle")
    p.add_argument("--list-sources", action="store_true",
                   help="list the stylesheets found, with their color counts, "
                        "then exit")
    p.add_argument("--flat", action="store_true",
                   help="one token per distinct color, instead of separating "
                        "a color used for text from the same color used for "
                        "a background")
    p.add_argument("--no-themes", action="store_true",
                   help="treat the site as having one theme, even where it "
                        "scopes rules to prefers-color-scheme or a .dark class")
    p.add_argument("--include-unused", action="store_true",
                   help="also put saved/inert colors in the css, scss, ts and "
                        "tailwind files (they are always in the json)")
    p.add_argument("--images", action="store_true",
                   help="also quantize the page's images to check whether the "
                        "artwork carries color (needs pillow + numpy)")
    p.add_argument("--timeout", type=float, default=20.0,
                   help="network timeout in seconds when fetching a URL")
    p.add_argument("--formats", default="html,json,css,scss,ts,tailwind",
                   help="comma-separated outputs to write")
    p.add_argument("--quiet", action="store_true", help="suppress the summary")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    want = {f.strip().lower() for f in args.formats.split(",") if f.strip()}

    if args.images:
        ok, msg = images.available()
        if not ok:
            print(f"warning: {msg}", file=sys.stderr)

    try:
        bundle = sources.load_any(args.target, want_images=args.images,
                                  timeout=args.timeout)
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
              "style itself with JavaScript — try a HAR export instead.",
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

    doc = emit.to_document(pal)
    os.makedirs(args.out, exist_ok=True)
    slug = emit._slug(pal)
    written = []

    def write(name: str, text: str) -> None:
        path = os.path.join(args.out, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        written.append(path)

    if "json" in want:
        write(f"{slug}.json", json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    if "css" in want:
        write(f"{slug}.css", emit.emit_css(doc, args.prefix, args.include_unused))
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
        write("index.html", emit.emit_html(doc, pal))

    if not args.quiet:
        _summarise(doc, pal, written)
    return 0


def _list_sources(bundle, args) -> None:
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
        for d in sh.declarations:
            from .color import find_colors
            from .cssparse import resolve_vars
            n_col += len(find_colors(resolve_vars(d.value, table)))
        print(f"  {i:>2}  {len(sh.declarations):>6}  {n_col:>7}  "
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


def _summarise(doc: dict, pal, written: list[str]) -> None:
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
