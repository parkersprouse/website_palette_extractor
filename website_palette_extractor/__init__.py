"""website_palette_extractor – read a website's color palette out of its stylesheets.

Command line:

    python3 -m website_palette_extractor site.har -o palette

Programmatic use, if you want the data rather than the files:

    from website_palette_extractor import sources, extract, emit

    bundle = sources.load_any("site.har")
    palette = extract.extract(bundle, exclude=["bootstrap"])
    doc = emit.to_document(palette)      # the same dict the JSON file holds

    for c in doc["colors"]:
        print(c["name"], c["hex"], c["status"], c["contrastOnGround"])
"""

__version__ = "1.1.0"

# Every submodule, plus the two module-level names a consumer is meant to read.
# `dom` was missing: it is phase 2's own module (the `cssselect2` matcher and
# the document tree), not a private helper, and leaving it out made
# `from website_palette_extractor import *` quietly different from the layout CLAUDE.md
# documents.
__all__ = [
    "PYTHON_FLOOR",
    "__version__",
    "color",
    "cssparse",
    "dom",
    "emit",
    "extract",
    "images",
    "sources",
]

# The single source of truth for the supported floor (PLAN.md T2). Checked
# against pyproject.toml's requires-python by test_pyproject_floor_matches_
# python_floor, and read by __main__.main()'s version guard – the zipapp
# carries no requires-python metadata of its own, so that guard is the only
# thing standing between an old interpreter and a crash deep in extract.py's
# zip(strict=) calls (PLAN.md T1).
PYTHON_FLOOR = (3, 11)
