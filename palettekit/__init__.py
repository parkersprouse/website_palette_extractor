"""palettekit — read a website's color palette out of its stylesheets.

Command line:

    python3 -m palettekit site.har -o palette

Programmatic use, if you want the data rather than the files:

    from palettekit import sources, extract, emit

    bundle = sources.load_any("site.har")
    palette = extract.extract(bundle, exclude=["bootstrap"])
    doc = emit.to_document(palette)      # the same dict the JSON file holds

    for c in doc["colors"]:
        print(c["name"], c["hex"], c["status"], c["contrastOnGround"])
"""

__version__ = "1.0.0"
__all__ = ["color", "cssparse", "sources", "extract", "emit", "images"]
