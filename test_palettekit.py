"""Tests for palettekit.  Run: python3 test_palettekit.py

These cover the parts that are easy to get quietly wrong — color maths,
cascade order, and the merge rules — rather than every code path.
"""
import json
import os
import tempfile
import unittest

from palettekit import emit, extract, sources
from palettekit.color import (
    contrast_ratio,
    delta_ok,
    find_colors,
    hue_name,
    parse_color,
)
from palettekit.cssparse import (
    is_inert_shadow,
    parse_stylesheet,
    resolve_vars,
    selector_weight,
)


class TestParsing(unittest.TestCase):
    def test_hex_forms(self):
        self.assertEqual(parse_color("#fff").hex, "#ffffff")
        self.assertEqual(parse_color("#151515").hex, "#151515")
        self.assertEqual(parse_color("#12345678").hexa, "#12345678")
        self.assertAlmostEqual(parse_color("#0000007f").a, 127 / 255, places=3)

    def test_functional_forms(self):
        self.assertEqual(parse_color("rgb(255 0 0)").hex, "#ff0000")
        self.assertEqual(parse_color("rgba(255,0,0,.5)").a, 0.5)
        self.assertEqual(parse_color("rgb(255 0 0 / 50%)").a, 0.5)
        self.assertEqual(parse_color("hsl(0 100% 50%)").hex, "#ff0000")
        self.assertEqual(parse_color("hsl(120deg 100% 25%)").hex, "#008000")
        self.assertEqual(parse_color("oklab(0.628 0.225 0.126)").hex, "#ff0000")

    def test_named_and_nonsense(self):
        self.assertEqual(parse_color("rebeccapurple").hex, "#663399")
        for bad in ("transparent", "currentColor", "inherit", "none",
                    "notacolor", "", "var(--x)"):
            self.assertIsNone(parse_color(bad), bad)

    def test_find_colors_skips_keywords(self):
        got = [c.hex for c in find_colors("1px solid #abc, 0 0 0 rgba(0,0,0,.5)")]
        self.assertEqual(got, ["#aabbcc", "#000000"])
        self.assertEqual(find_colors("none"), [])


class TestColorMaths(unittest.TestCase):
    def test_alpha_flatten(self):
        ground = parse_color("#151515")
        ink = parse_color("rgba(255,255,255,0.75)")
        self.assertEqual(ink.over(ground).hex, "#c4c4c4")

    def test_contrast_matches_reported_hex(self):
        """A ratio must be reproducible from the hex we print beside it."""
        ground = parse_color("#151515")
        flat = parse_color("rgba(255,255,255,0.75)").over(ground)
        from_flat = contrast_ratio(parse_color(flat.hex), ground)
        self.assertAlmostEqual(contrast_ratio(flat, ground), from_flat,
                               places=6)
        self.assertAlmostEqual(round(from_flat, 2), 10.47, places=2)

    def test_known_contrasts(self):
        g = parse_color("#151515")
        self.assertAlmostEqual(
            round(contrast_ratio(parse_color("#dcdcdc"), g), 2), 13.32)
        self.assertAlmostEqual(
            round(contrast_ratio(parse_color("#ff0000"), g), 2), 4.57)
        self.assertAlmostEqual(
            round(contrast_ratio(parse_color("#ffffff"),
                                 parse_color("#000000")), 2), 21.0)

    def test_achromatic_hue_is_not_invented(self):
        for h in ("#151515", "#808080", "#ffffff"):
            self.assertEqual(parse_color(h).oklch()[2], 0.0)

    def test_hue_names_use_oklch_angles(self):
        cases = {"#ff0000": "red", "#ffc600": "yellow", "#13330d": "green",
                 "#0064e1": "blue", "#663399": "violet", "#00ffff": "teal",
                 "#f68219": "orange"}
        for hexv, want in cases.items():
            self.assertEqual(hue_name(parse_color(hexv)), want, hexv)

    def test_delta_ok_merges_only_indistinguishable(self):
        self.assertLess(delta_ok(parse_color("#1a1a1a"),
                                 parse_color("#191919")), 0.02)
        self.assertGreater(delta_ok(parse_color("#151515"),
                                    parse_color("#c4c4c4")), 0.02)


class TestCss(unittest.TestCase):
    def test_comments_and_strings_are_not_colors(self):
        css = """
        /* #ff0000 in a comment */
        .a { content: "#00ff00"; color: #0000ff; }
        """
        sheet = parse_stylesheet(css, "t")
        found = [c.hex for d in sheet.declarations for c in find_colors(d.value)]
        self.assertEqual(found, ["#0000ff"])

    def test_var_resolution(self):
        table = {"--a": "#123456"}
        self.assertEqual(resolve_vars("var(--a)", table), "#123456")
        self.assertEqual(resolve_vars("var(--missing, #abcdef)", table),
                         "#abcdef")

    def test_circular_var_terminates(self):
        out = resolve_vars("var(--a)", {"--a": "var(--b)", "--b": "var(--a)"})
        self.assertIsInstance(out, str)

    def test_inert_shadow_detection(self):
        self.assertTrue(is_inert_shadow("filter",
                                        "drop-shadow(0rem 0rem 0rem #13330d)"))
        self.assertTrue(is_inert_shadow("box-shadow", "0 0 0 #000"))
        self.assertFalse(is_inert_shadow("box-shadow", "0 2px 4px #000"))
        self.assertFalse(is_inert_shadow("color", "#000"))

    def test_page_selectors_outweigh_components(self):
        self.assertGreater(selector_weight("body", ()),
                           selector_weight(".card", ()))
        self.assertGreater(selector_weight(".card", ()),
                           selector_weight(".card:hover", ()))


def write_fixture(content: str, name: str = "page.html") -> str:
    """Write a fragment to a fresh temp dir and return its path."""
    path = os.path.join(tempfile.mkdtemp(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


FIXTURE = """<!DOCTYPE html><html><head>
<style id="framework">
  body { background: #ffffff; color: #333333; }
  .btn { background: #cccccc; }
</style>
<style>
  :root { --brand: #2563eb; --never-used: #ff00ff; }
  body { background: #101418; }
  h1 { color: var(--brand); }
  p { color: rgba(255,255,255,0.75); }
  hr { border-top: 1px solid rgba(255,255,255,0.2); }
  .x { filter: drop-shadow(0 0 0 #00ff00); }
</style>
</head><body></body></html>
"""


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.page = write_fixture(FIXTURE)
        bundle = sources.load_any(self.page)
        self.pal = extract.extract(bundle)
        self.doc = emit.to_document(self.pal)
        self.by_name = {c["name"]: c for c in self.doc["colors"]}

    def test_ground_follows_cascade_not_weight(self):
        """The later body rule wins, exactly as the browser would decide."""
        self.assertEqual(self.doc["ground"], "#101418")

    def test_ground_is_a_token(self):
        grounds = [c for c in self.doc["colors"] if c["name"] == "ground"]
        self.assertEqual(len(grounds), 1)
        self.assertEqual(grounds[0]["hex"], "#101418")

    def test_unreferenced_custom_property_is_saved(self):
        magenta = [c for c in self.doc["colors"] if c["hex"] == "#ff00ff"]
        self.assertEqual(len(magenta), 1)
        self.assertEqual(magenta[0]["status"], "saved")

    def test_zero_length_shadow_is_inert(self):
        green = [c for c in self.doc["colors"] if c["hex"] == "#00ff00"]
        self.assertEqual(len(green), 1)
        self.assertEqual(green[0]["status"], "inert")

    def test_alpha_is_flattened_and_recorded(self):
        alpha = [c for c in self.doc["colors"] if "source" in c]
        self.assertTrue(alpha)
        for c in alpha:
            self.assertIn("declaredAs", c["source"])
            self.assertEqual(c["source"]["flattenedOver"], self.doc["ground"])

    def test_code_outputs_exclude_unrendered_by_default(self):
        css = emit.emit_css(self.doc, "c")
        self.assertNotIn("#ff00ff", css)
        self.assertIn("#ff00ff", emit.emit_css(self.doc, "c",
                                               include_unused=True))

    def test_json_is_serialisable_and_complete(self):
        text = json.dumps(self.doc)
        again = json.loads(text)
        self.assertEqual(len(again["colors"]), len(self.doc["colors"]))
        for c in again["colors"]:
            for key in ("name", "hex", "status", "role", "contrastOnGround",
                        "css"):
                self.assertIn(key, c)

    def test_html_report_is_standalone_and_valid(self):
        html = emit.emit_html(self.doc, self.pal)
        self.assertNotIn("__", html.split("<script")[0].replace(
            "__", "", 0) if False else "")
        self.assertNotIn("fetch(", html)
        self.assertNotIn("<link", html)
        import re
        left = re.findall(r"__[A-Z_]+__", html)
        self.assertEqual(left, [], f"unreplaced placeholders: {left}")
        payload = re.search(
            r'<script type="application/json" id="palette-data">(.*?)</script>',
            html, re.S).group(1)
        json.loads(payload.replace("<\\/", "</"))

    def test_report_theme_is_readable(self):
        theme = emit._pick_report_theme(self.doc)
        g = parse_color(theme["ground"])
        for role, floor in (("strong", 7.0), ("body", 4.5), ("muted", 3.0)):
            ratio = contrast_ratio(parse_color(theme[role]), g)
            self.assertGreaterEqual(
                ratio, floor, f"{role} only {ratio:.2f}:1 on the ground")


class TestMerging(unittest.TestCase):
    def test_same_color_different_roles_stays_split(self):
        html = """<style>
          body { background: #151515; }
          p { color: #c4c4c4; }
          .btn { background: #c4c4c4; }
        </style>"""
        p = write_fixture(html)
        doc = emit.to_document(extract.extract(sources.load_any(p)))
        same = [c for c in doc["colors"] if c["hex"] == "#c4c4c4"]
        self.assertEqual(len(same), 2, "text and surface should be separate")
        self.assertEqual({c["role"] for c in same}, {"text", "surface"})

    def test_indistinguishable_same_role_merges(self):
        html = """<style>
          body { background: #ffffff; }
          .a { color: #1a1a1a; }
          .b { color: #191919; }
        </style>"""
        p = write_fixture(html)
        doc = emit.to_document(extract.extract(sources.load_any(p)))
        inks = [c for c in doc["colors"] if c["role"] == "text"]
        self.assertEqual(len(inks), 1)
        self.assertTrue(inks[0].get("mergedFrom"))

    def test_fully_transparent_is_dropped(self):
        html = """<style>
          body { background: #151515; }
          .a { color: rgba(255,255,255,0); }
        </style>"""
        p = write_fixture(html)
        doc = emit.to_document(extract.extract(sources.load_any(p)))
        self.assertEqual([c for c in doc["colors"] if c["role"] == "text"], [])


class TestBadInput(unittest.TestCase):
    def test_malformed_har(self):
        p = write_fixture("not json", "bad.har")
        with self.assertRaises(RuntimeError):
            sources.load_any(p)

    def test_json_that_is_not_a_har(self):
        p = write_fixture('{"hello": 1}', "x.har")
        with self.assertRaises(RuntimeError):
            sources.load_any(p)

    def test_unknown_target(self):
        with self.assertRaises(RuntimeError):
            sources.load_any("/nonexistent/thing.xyz")


if __name__ == "__main__":
    unittest.main(verbosity=2)
