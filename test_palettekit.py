"""Tests for palettekit.  Run: python3 test_palettekit.py

These cover the parts that are easy to get quietly wrong — color maths,
cascade order, and the merge rules — rather than every code path.
"""
import json
import os
import re
import tempfile
import tomllib
import unittest
from pathlib import Path

from palettekit import PYTHON_FLOOR, emit, extract, sources
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
    split_selector_list,
    strip_theme_scope,
    theme_scope,
    var_refs,
)
from palettekit.dom import matches_page_element, page_elements
from palettekit.extract import layer_order


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

    def test_cie_lab_and_lch(self):
        """CIE Lab is D50 and 0-100, unlike the OKLab pair right next to it.

        Tailwind v4 emits `lab()` *after* a hex fallback, so it wins the
        cascade and skipping it loses the color rather than degrading to the
        fallback. Values below are the sRGB primaries round-tripped through
        CSS Color 4.
        """
        cases = {
            "lab(100% 0 0)": "#ffffff",
            "lab(100 0 0)": "#ffffff",
            "lab(0% 0 0)": "#000000",
            "lab(53.585% 0 0)": "#808080",
            "lab(54.291% 80.805 69.891)": "#ff0000",
            "lab(87.818% -79.271 80.99)": "#00ff00",
            "lab(29.568% 68.299 -112.03)": "#0000ff",
            "lch(54.291% 106.839 40.858)": "#ff0000",
            "lch(100% 0 0)": "#ffffff",
        }
        for text, want in cases.items():
            self.assertEqual(parse_color(text).hex, want, text)
        self.assertAlmostEqual(parse_color("lab(50% 0 0 / 0.5)").a, 0.5)

    def test_lab_agrees_with_the_fallback_authored_beside_it(self):
        """A real build wrote both forms for the same token; they must match."""
        self.assertEqual(parse_color("lab(2.75381% 0 0)").hex,
                         parse_color("#0a0a0a").hex)

    def test_named_and_nonsense(self):
        self.assertEqual(parse_color("rebeccapurple").hex, "#663399")
        for bad in ("transparent", "currentColor", "inherit", "none",
                    "notacolor", "", "var(--x)"):
            self.assertIsNone(parse_color(bad), bad)

    def test_find_colors_skips_keywords(self):
        got = [c.hex for c in find_colors("1px solid #abc, 0 0 0 rgba(0,0,0,.5)")]
        self.assertEqual(got, ["#aabbcc", "#000000"])
        self.assertEqual(find_colors("none"), [])

    def test_a_color_function_nested_two_levels_deep_finds_nothing(self):
        """T17: the old `COLOR_TOKEN` regex tolerated exactly one level of
        nested parens and failed closed past that — `rgb(min(calc(1 + 2), 3)
        0 0)` matched nothing, silently, rather than reading a wrong color.

        A `tinycss2` token walk delimits a `FunctionBlock` correctly no
        matter how deep its arguments nest, so the boundary itself is no
        longer the reason this returns nothing — `min()`/`calc()` channel
        values are still outside what `_num`/`_hue` evaluate, which is a
        separate, still-open gap (see `PLAN.md` T17's "Known limits" note).
        What matters here is that a color *after* the unreadable one is not
        swallowed along with it, the way an under-bounded scanner could.

        Does not discriminate against the old regex — it already failed
        closed the same way for this exact shape, since the PLAN.md write-up
        that motivated T17 predicted no corpus site exercises the gap in a
        way that flips output. Kept as forward regression coverage for the
        new mechanism, not as proof of a behavior change; see the two tests
        below for what the corpus diff actually found.
        """
        self.assertEqual(find_colors("rgb(min(calc(1 + 2), 3) 0 0)"), [])
        got = find_colors("rgb(min(calc(1 + 2), 3) 0 0) red")
        self.assertEqual([c.hex for c in got], ["#ff0000"])

    def test_a_quoted_url_does_not_read_its_own_markup_as_color(self):
        """T17, found by the corpus diff rather than predicted in advance.

        `background-image: url("data:image/svg+xml,...stroke='black'...")` is
        a real corpus shape (tailwindcss.com.har's bundled DocSearch icon CSS,
        fleshandbonedesign.com's checkbox glyph): a quoted `url()` whose
        content is inline SVG markup, itself carrying `stroke=`/`fill=`
        attributes that look exactly like CSS color syntax. The old regex
        scanned the whole declaration value as flat text and read those as
        real colors — the same class of mistake invariant 9 exists to
        forbid for `content: "#fff"`, just one `url()` layer deeper than that
        invariant's own test reaches. A `url()`'s argument arrives as a
        `StringToken`, which the walk never opens, so nothing inside it is
        ever visited.
        """
        value = ('url("data:image/svg+xml,%3Csvg stroke=\'black\' '
                 "fill='white'/%3E\")")
        self.assertEqual(find_colors(value), [])

    def test_a_bare_url_does_not_read_its_filename_as_a_named_color(self):
        """T17, the corpus diff's other finding: ground.news links a
        `bg-black.png` background image, unquoted — `url(.../bg-black.png)`.

        `\\bblack\\b` matched the word inside the filename, the same way it
        would match a real `black` keyword sitting anywhere else in the
        value; a bare `url(...)` is its own token type in `tinycss2`
        (a `URLToken`, distinct from the `FunctionBlock` a quoted `url("...")`
        produces), and the walk does not open it either way.
        """
        got = find_colors("black url(https://example.com/assets/bg-black.png)")
        self.assertEqual([c.hex for c in got], ["#000000"])


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
    def test_statement_at_rules_do_not_eat_the_first_rule(self):
        """`@charset`/`@import`/`@layer a,b;` end in `;`, not a block.

        Left in the buffer they are glued onto the next rule's prelude, so the
        first rule of the sheet parses as one long broken selector and is lost.
        Bootstrap opens with `@charset`, which cost its entire `:root` token
        block and left 550 `var()` references unresolvable.
        """
        for prefix in ('@charset "UTF-8";', "@import url(x.css);",
                       "@layer base, utilities;", "@namespace svg url(#ns);"):
            sheet = parse_stylesheet(prefix + " :root{--a:#112233}", "t")
            got = [(d.selector, d.prop) for d in sheet.declarations]
            self.assertEqual(got, [(":root", "--a")], prefix)

    def test_an_at_rule_nested_in_a_style_rule_keeps_the_enclosing_selector(self):
        """T6 (`PLAN.md`): native CSS nesting has no selector of its own.

        `.a { color: red; @media (min-width:1px) { color: blue } }` — `blue`
        belongs to `.a`, exactly as if the `@media` wrapper weren't there. The
        old brace walker (and `_walk` until this fix) pushed an empty selector
        for every at-rule block regardless of nesting, so this declaration
        was read for its `var()` references only and then dropped.
        """
        css = ".a { color: red; @media (min-width:1px) { color: blue } }"
        sheet = parse_stylesheet(css, "t")
        got = [(d.selector, d.prop, d.value) for d in sheet.declarations]
        self.assertEqual(got, [(".a", "color", "red"), (".a", "color", "blue")])

        # A *top-level* at-rule still resets to no selector — a qualified
        # rule found inside it computes its own selector regardless.
        css2 = "@media (min-width:1px) { .b { color: green } }"
        sheet2 = parse_stylesheet(css2, "t")
        got2 = [(d.selector, d.prop, d.value) for d in sheet2.declarations]
        self.assertEqual(got2, [(".b", "color", "green")])

    def test_a_nested_media_theme_is_still_found_as_a_scope(self):
        """A nested `@media (prefers-color-scheme: dark)` is not just carried
        through as unscoped text (T6, `PLAN.md`).

        Simply propagating the enclosing rule's `theme` unchanged would fix
        the dropped-declaration bug but introduce its mirror image: an
        unscoped `.a` means this declaration would come back `theme == ""`,
        which `_theme_plan` treats as belonging to *every* theme — inventing a
        color the light theme never paints, the same failure invariant 13
        guards against from the other direction.
        """
        css = ".a { color: red; @media (prefers-color-scheme: dark) { color: blue } }"
        sheet = parse_stylesheet(css, "t")
        by_value = {d.value: d for d in sheet.declarations}
        self.assertEqual(by_value["red"].theme, "")
        self.assertEqual(by_value["blue"].theme, "dark")
        self.assertTrue(by_value["blue"].theme_media)
        self.assertEqual(by_value["blue"].selector, ".a")

        # A selector-derived theme on the enclosing rule still wins over a
        # nested media query — the enclosing rule already said which theme it
        # is, so the media scope doesn't get to override that.
        css2 = (".dark .a { color: red; "
                "@media (prefers-color-scheme: light) { color: blue } }")
        sheet2 = parse_stylesheet(css2, "t")
        by_value2 = {d.value: d for d in sheet2.declarations}
        self.assertEqual(by_value2["blue"].theme, "dark")
        self.assertFalse(by_value2["blue"].theme_media)

    def test_comments_and_strings_are_not_colors(self):
        css = """
        /* #ff0000 in a comment */
        .a { content: "#00ff00"; color: #0000ff; }
        """
        sheet = parse_stylesheet(css, "t")
        found = [c.hex for d in sheet.declarations for c in find_colors(d.value)]
        self.assertEqual(found, ["#0000ff"])

    def test_var_refs_do_not_read_string_content(self):
        """A `--name`-shaped string literal is not a reference to that property.

        `var_refs` used to be a regex over the serialized value with no token
        boundaries, so `content: "--foo"` counted as a reference to `--foo`
        the same way `var(--foo)` would — invariant 9's mistake, recurring one
        step downstream of color reading, in the collection that decides
        `live` vs `saved` (invariant 10) rather than in `find_colors` itself.
        """
        sheet = parse_stylesheet(
            '.a { content: "--foo"; } .b { width: var(--used); }', "t")
        self.assertNotIn("--foo", sheet.var_refs)
        self.assertIn("--used", sheet.var_refs)

    def test_var_refs_recurse_into_a_fallback(self):
        """A `var()` nested inside another `var()`'s own fallback still counts.

        Tailwind's gradient stops nest three deep this way (invariant 25):
        `var(--tw-gradient-stops, var(--tw-gradient-via-stops, var(--x) 0%,
        var(--y) 100%))`. Every name has to survive the recursion, not just
        the outermost one.
        """
        self.assertEqual(var_refs("var(--a, var(--b, red))"), {"--a", "--b"})
        self.assertEqual(
            var_refs("var(--tw-gradient-stops, var(--tw-gradient-via-stops, "
                     "var(--tw-gradient-from) 0%, var(--tw-gradient-to) 100%))"),
            {"--tw-gradient-stops", "--tw-gradient-via-stops",
             "--tw-gradient-from", "--tw-gradient-to"},
        )

    def test_var_resolution(self):
        table = {"--a": "#123456"}
        self.assertEqual(resolve_vars("var(--a)", table), "#123456")
        self.assertEqual(resolve_vars("var(--missing, #abcdef)", table),
                         "#abcdef")

    def test_initial_custom_property_falls_back(self):
        """`initial` on a custom property is guaranteed-invalid, not a value.

        Tailwind v4 guards every registered property with
        `--tw-gradient-via-stops: initial;` for browsers with no `@property`,
        so a browser resolving `var(--tw-gradient-via-stops, <stops>)` uses
        the fallback rather than substituting the text `initial`. Reading it
        as an ordinary stored value dropped 108 declarations' worth of color
        on tailwindcss.com's dark theme.
        """
        table = {"--tw-gradient-via-stops": "initial"}
        self.assertEqual(
            resolve_vars("var(--tw-gradient-via-stops, #7c3aed)", table),
            "#7c3aed",
        )
        # No fallback and an `initial` value: nothing to substitute with.
        self.assertEqual(resolve_vars("var(--tw-gradient-via-stops)", table), "")
        # Case and surrounding whitespace do not matter — it is a keyword.
        self.assertEqual(
            resolve_vars("var(--a, #000)", {"--a": "  Initial  "}), "#000",
        )
        # A value that merely contains the word is not the keyword itself.
        self.assertEqual(
            resolve_vars("var(--a, #000)", {"--a": "initial-value"}),
            "initial-value",
        )

    def test_circular_var_terminates(self):
        out = resolve_vars("var(--a)", {"--a": "var(--b)", "--b": "var(--a)"})
        self.assertIsInstance(out, str)

    def test_a_var_fallback_may_contain_parentheses(self):
        """A fallback is a whole value, so it can hold functions of its own.

        The non-greedy regex this replaced stopped at the first `)`, which is
        the wrong one the moment the fallback contains a function — it cut the
        call short and left the rest of the declaration behind as an orphaned
        tail. ui.shadcn.com writes
        `background-image: var(--shimmer-image, linear-gradient(…))`, and what
        HEAD made of that was `none), currentColor calc(50% - 5rem)), …`.

        The known-name case is the one that discriminates: the fallback is
        discarded, so all that is left of the regex's mistake is a stray `)`,
        and nothing but the string itself shows it.
        """
        self.assertEqual(
            resolve_vars("var(--a, linear-gradient(red, blue))",
                         {"--a": "#123456"}),
            "#123456",
        )
        table = {"--angle": "90deg", "--base": "#000000", "--spread": "5rem",
                 "--highlight": "#378add"}
        value = ("var(--shimmer-image, linear-gradient("
                 "calc(90deg + var(--angle)), "
                 "var(--base) calc(50% - var(--spread)), "
                 "color-mix(in oklch, var(--highlight), var(--base) 50%) 50%))")
        self.assertEqual(
            resolve_vars(value, table),
            "linear-gradient(calc(90deg + 90deg), #000000 calc(50% - 5rem), "
            "color-mix(in oklch, #378add, #000000 50%) 50%)",
        )

    def test_a_discarded_fallback_does_not_come_back_as_a_second_copy(self):
        """The largest class the balanced parse fixed, and it double-counted.

        Tailwind v4 writes `--tw-gradient-stops: var(--tw-gradient-via-stops,
        <the same stops written out>)`, and a `.via-*` utility defines the
        name. Cut at the first `)`, the call resolved from the table *and* the
        orphaned tail resolved as well, so every color in the fallback was
        counted twice — 204 declarations across three corpus sites. The colors
        were right and their weight was doubled, which is invisible in a hex
        set and visible in every ranking built from it.
        """
        table = {"--stops": "var(--from) 0%, var(--to) 100%",
                 "--from": "#ff0000", "--to": "#0000ff"}
        value = "var(--stops, var(--pos), var(--from) 0%, var(--to) 100%)"
        self.assertEqual([c.hex for c in find_colors(resolve_vars(value, table))],
                         ["#ff0000", "#0000ff"])

    def test_var_substitution_does_not_glue_two_tokens_into_one(self):
        """CSS substitutes tokens; this substitutes text, so it has to pad.

        Tailwind v4 minifies to
        `color-mix(in oklab,var(--color-white)var(--tw-shadow-alpha),transparent)`.
        Pasted together those give `#fff100%`, which the color scanner reads as
        the hex `#fff100` — a bright yellow that appeared 18 times on
        ground.news and is painted nowhere on it. Two correct values and one
        missing space manufacture a whole color.
        """
        table = {"--white": "#fff", "--alpha": "100%"}
        value = "color-mix(in oklab,var(--white)var(--alpha),transparent)"
        self.assertEqual([c.hexa for c in find_colors(resolve_vars(value, table))],
                         ["#ffffffff"])
        # And nothing gains a space it did not need.
        self.assertEqual(resolve_vars("1px solid var(--white)", table),
                         "1px solid #fff")

    def test_inert_shadow_detection(self):
        self.assertTrue(is_inert_shadow("filter",
                                        "drop-shadow(0rem 0rem 0rem #13330d)"))
        self.assertTrue(is_inert_shadow("box-shadow", "0 0 0 #000"))
        self.assertFalse(is_inert_shadow("box-shadow", "0 2px 4px #000"))
        self.assertFalse(is_inert_shadow("color", "#000"))

    def test_escaped_quote_in_a_selector_does_not_swallow_the_rest(self):
        r"""Tailwind arbitrary values put escaped quotes in the *selector*.

        `.bg-\[url\(\"…\"\)\]` is not a string. Read as one, masking runs to
        the next quote, swallows the `{`, and leaves the brace walker a level
        deep for the remainder of the file. The parse still succeeds and
        simply returns less, which is why this went unnoticed: on one real
        stylesheet it cost 178 of 181 themed rules and two thirds of every
        declaration.
        """
        css = (
            r'.bg-\[url\(\"https://x/y.png\"\)\] { background-image: '
            r'url(https://x/y.png); }'
            "\n.after { color: #abcdef; }\nbody { background: #123456; }"
        )
        sheet = parse_stylesheet(css, "t")
        found = [c.hex for d in sheet.declarations for c in find_colors(d.value)]
        self.assertIn("#abcdef", found, "rules after the escaped quote were lost")
        self.assertIn("#123456", found)

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

    def test_document_has_a_schema_version(self):
        """schemaVersion is the only intended addition to the key set.

        The fixture carries no image report, so `images` (conditional on
        `pal.image_report`) is absent here — this is the unconditional set.
        """
        self.assertEqual(self.doc["schemaVersion"], 1)
        self.assertEqual(set(self.doc.keys()), {
            "name", "source", "ground", "groundSource", "generated",
            "schemaVersion", "stats", "warnings", "defaultTheme", "themes",
            "colors",
        })


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


class TestThemeScopes(unittest.TestCase):
    """The selector matching, which is the cheapest place to be quietly wrong.

    A false positive splits an ordinary palette in half; a false negative
    leaves the dark theme inheriting the light ground, and every ratio
    reported for it is then measured against a background it never uses.
    """

    def test_scope_from_selector(self):
        cases = {
            ".dark body": "dark",
            "html.dark": "dark",
            ".dark": "dark",
            ':root[data-theme="dark"]': "dark",
            "[data-theme='light'] .card": "light",
            "html[data-bs-theme=dark]": "dark",
            "[data-color-mode=dark] a": "dark",
            ".theme-dark .x": "dark",
            ".dark-mode": "dark",
            ".is-light": "light",
            # Component classes that merely contain the word.
            ".dark-blue": "",
            ".darken": "",
            ".sidebar-dark": "",
            ".highlight": "",
            ".lighter": "",
            "body": "",
        }
        for sel, want in cases.items():
            self.assertEqual(theme_scope(sel, ()), want, sel)

    def test_scope_from_media_query(self):
        self.assertEqual(
            theme_scope(":root", ("@media (prefers-color-scheme: dark)",)),
            "dark")
        self.assertEqual(
            theme_scope(":root",
                        ("@media (min-width:600px) and "
                         "(prefers-color-scheme:light)",)),
            "light")
        self.assertEqual(theme_scope(":root", ("@media print",)), "")

    def test_strip_theme_scope(self):
        cases = {
            ".dark body": "body",
            # The marker usually rides on <html>, and `html body` is `body`.
            "html.dark body": "body",
            "html.dark": "html",
            ':root[data-theme="dark"]': ":root",
            '[data-theme="dark"] body': "body",
            ".dark .card": ".card",
            # A compound that was nothing but the marker is the root itself.
            ".dark": ":root",
            ".dark h1, .dark h2": "h1, h2",
        }
        for sel, want in cases.items():
            self.assertEqual(strip_theme_scope(sel), want, sel)

    def test_a_list_mixing_scoped_and_unscoped_is_unscoped(self):
        """Bootstrap 5.3 writes `:root,[data-bs-theme=light]` for base tokens.

        Judging the list as a whole tags every root variable light-only, they
        vanish from the base var table, and several hundred `var()` references
        resolve to nothing.
        """
        self.assertEqual(theme_scope(":root,[data-bs-theme=light]", ()), "")
        self.assertEqual(theme_scope(".dark .a, .b", ()), "")
        # All parts scoped the same way is still a theme.
        self.assertEqual(theme_scope(".dark h1, .dark h2", ()), "dark")
        self.assertEqual(theme_scope("[data-bs-theme=dark]", ()), "dark")
        # Contradictory lists cannot be attributed, so they stay unscoped.
        self.assertEqual(theme_scope(".dark .a, .light .b", ()), "")

    def test_a_marker_inside_not_is_a_negation_not_a_scope(self):
        """django's docs write the dark theme as `:not([data-theme="light"])`.

            @media (prefers-color-scheme: dark) {
              html:not([data-theme="light"]) { --body-bg: #0e1117; … }
            }

        Read the marker as a scope and the dark theme's whole token block —
        124 declarations of it, the ground among them — is filed under light.
        Skipping the negation lets the rule fall through to the media query,
        which says dark, which is what it is.

        On its own, with no media query, "everything except light" is not
        attributable to one theme either, so it comes back unscoped.
        """
        dark_media = ("@media (prefers-color-scheme: dark)",)
        self.assertEqual(
            theme_scope('html:not([data-theme="light"])', dark_media), "dark")
        self.assertEqual(
            theme_scope(':root:not([data-theme="light"]) .highlight', ()), "")
        self.assertEqual(theme_scope("html:not(.dark)", ()), "")
        # A real marker outside the negation still scopes the rule.
        self.assertEqual(theme_scope(".dark .a:not(.light)", ()), "dark")
        # Stripping must leave the negation intact — `html:not()` is not a
        # selector, and the ground would never be matched through it.
        self.assertEqual(strip_theme_scope('html:not([data-theme="light"])'),
                         'html:not([data-theme="light"])')
        self.assertEqual(strip_theme_scope(".dark .a:not(.light)"),
                         ".a:not(.light)")

    def test_selector_list_splits_outside_parens_only(self):
        """A comma inside `:is()`/`:where()`/`[]` does not start a selector."""
        cases = {
            ".a:is(.b, .c), .d": [".a:is(.b, .c)", ".d"],
            'a[data-x="p,q"], b': ['a[data-x="p,q"]', "b"],
            ":nth-child(2n, 3n).y, .z": [":nth-child(2n, 3n).y", ".z"],
            "h1, h2 , h3": ["h1", "h2", "h3"],
            # An escaped comma is part of the class name, not a separator.
            r".a\,b, .c": [r".a\,b", ".c"],
            ".x": [".x"],
        }
        for sel, want in cases.items():
            self.assertEqual(split_selector_list(sel), want, sel)

    def test_tailwind_v4_dark_variant_survives_the_split(self):
        """Tailwind v4 puts a comma inside the scope: `:where(.dark,.dark *)`.

        Splitting there leaves `:where(, *)`, which matches nothing — so the
        theme's own rules stop being recognised as the theme's, and its ground
        falls back to a guess. v3's `:is(.dark *)` has no comma, which is why
        this survived a site built on v3.
        """
        v4 = r".dark\:bg-gray-950:where(.dark,.dark *)"
        self.assertEqual(theme_scope(v4, ()), "dark")
        self.assertEqual(strip_theme_scope(v4), r".dark\:bg-gray-950")

    def test_tailwind_variant_class_is_not_a_theme_root(self):
        """`.dark\\:bg-x` is a class *named* `dark:bg-x`, not a theme root.

        The scope is stated by the `:is(.dark *)` beside it. Reading the name
        as the marker strips it out of the middle of the class and leaves
        `\\:bg-x` — which then matches nothing, including the body's own class.
        """
        sel = r".dark\:bg-dark-primary:is(.dark *)"
        self.assertEqual(theme_scope(sel, ()), "dark")
        self.assertEqual(strip_theme_scope(sel), r".dark\:bg-dark-primary")
        # The name alone, with no :is() to scope it, is not a theme at all.
        self.assertEqual(theme_scope(r".dark\:bg-dark-primary", ()), "")


class TestPageElement(unittest.TestCase):
    """Which rules actually land on the element the page is painted on.

    A utility framework says this on the element, not in the stylesheet, so
    the class attribute is the only place the information exists.
    """

    HTML = ('<html lang="en-US"><body id="pg" '
            'class="flex bg-light-primary dark:bg-dark-primary">')

    def test_matches_only_what_selects_the_page_element(self):
        els = page_elements(self.HTML)
        cases = {
            ".bg-light-primary": True,
            # Selectors escape what HTML writes literally, and Tailwind emits
            # either form depending on version. Both have to reach the class
            # the body actually carries.
            r".dark\:bg-dark-primary": True,
            r".dark\3a bg-dark-primary": True,
            "body": True, "html": True, ":root": True,
            "body.flex": True, "#pg": True, '[lang="en-US"]': True,
            # The same utility sitting on some other element.
            ".bg-dark-primary": False,
            # A descendant of the body is not the body. Still false, but now
            # because the body is not a descendant of itself — not because
            # combinators are refused wholesale.
            ".flex .bg-light-primary": False,
            ".flex > .x": False,
            # A hover state is not the page's resting background.
            ".bg-light-primary:hover": False,
            ".bg-light-primary:before": False,
            "body.nope": False, "#other": False, "div.flex": False,
        }
        for sel, want in cases.items():
            self.assertIs(matches_page_element(sel, els), want, sel)

    def test_a_real_matcher_answers_what_the_narrow_one_refused(self):
        """The lifted restriction: combinators and functional pseudo-classes.

        Every one of these was False before phase 2, because a hand-rolled
        matcher stopped at the first thing it did not model. `_PAGE_SEL` caught
        `html body` anyway; the rest were simply lost.
        """
        els = page_elements(self.HTML)
        for sel in ("html body", "html > body", "body:not(.nope)",
                    ":is(.bg-light-primary, .zzz)", "body:where(.flex)",
                    'html:not([data-theme="light"])'):
            self.assertIs(matches_page_element(sel, els), True, sel)

    def test_a_blanket_rule_is_not_a_statement_about_the_page(self):
        """`*` selects `<html>` and tells you nothing — see `dom._is_blanket`.

        Tailwind v4 writes its reset this way. Counting it as page-level lets
        `* { --tw-ring-offset-color: #fff }` outrank every utility that sets
        the same property to a color the site actually paints.
        """
        els = page_elements(self.HTML)
        for sel in ("*", ":root *", "body *", "html *", "*, ::before"):
            self.assertIs(matches_page_element(sel, els), False, sel)
        # The probe element is built once at import and shared by every call.
        # `cssselect2` caches ancestry and sibling lookups on a wrapper as it
        # answers, so ask again — with a real match in between — and make sure
        # nothing about it drifts. A probe that quietly starts matching turns
        # `_is_blanket` off and restores the inversion it exists to prevent.
        self.assertIs(matches_page_element(".bg-light-primary", els), True)
        self.assertIs(matches_page_element("*", els), False)

    def test_a_selector_that_will_not_compile_is_false_not_an_error(self):
        """Required, not defensive — two known shapes reach here.

        `strip_theme_scope` can emit `:is( , …)` for the nesting
        `cssparse._not_spans` documents as unmodelled, and real CSS carries
        pseudo-classes cssselect2 does not know.
        """
        els = page_elements(self.HTML)
        for sel in (":is( , .x)", "body:dir(ltr)", "", "body,", "@media"):
            self.assertIs(matches_page_element(sel, els), False, sel)
        # tinycss2's serializer writes `:nth-child(3n+1)` as
        # `:nth-child(3n/**/+1)` so the tokens cannot re-merge, and that string
        # reaches selectors in the JSON. It still has to parse.
        self.assertIs(matches_page_element("body:nth-child(3n/**/+1)", els),
                      True)

    def test_unreadable_document_is_not_an_empty_one(self):
        """None means "could not tell", which is not "carries no classes"."""
        self.assertIsNone(page_elements("no html here"))
        self.assertIs(matches_page_element(".bg-light-primary", None), False)
        # Read, and genuinely bare — the reference fixture's shape.
        bare = page_elements('<html><body style="opacity:0">')
        self.assertEqual([e.classes for e in bare], [frozenset(), frozenset()])

    def test_messy_markup_still_places_the_page_element(self):
        """No implied-tag insertion, so the void elements have to be right.

        Treat `<meta>` as needing a close tag and `<body>` becomes a child of
        `<head>` — at which point `head > *` and `.flex .x` start matching it.
        """
        els = page_elements(
            '<!DOCTYPE html>\n<HTML LANG=en>\n<head><meta charset=utf-8>'
            '<link rel=stylesheet href=a.css>\n<body class="flex">'
            '<p>unclosed<br>text'
        )
        self.assertEqual([e.tag for e in els], ["html", "body"])
        self.assertEqual(els[1].classes, frozenset({"flex"}))
        self.assertIs(matches_page_element("html > body", els), True)
        self.assertIs(matches_page_element("head .flex", els), False)


UTILITY_GROUND = """<!DOCTYPE html><html><head><style>
  :root { --background: #ffffff; }
  .dark { --background: #0a0a0a; }
  body { background-color: var(--background); color: #333333; }
  .bg-light-primary { background-color: #eeefe9; }
  .bg-dark-primary { background-color: #262626; }
  .dark\\:bg-dark-primary:is(.dark *) { background-color: #262626; }
  .dark\\:bg-light-primary:is(.dark *) { background-color: #eeefe9; }
</style></head>
<body class="bg-light-primary dark:bg-dark-primary"></body></html>
"""


class TestUtilityGround(unittest.TestCase):
    """A page painted by utility classes on <body>, not by a `body {}` rule."""

    def doc(self):
        return emit.to_document(extract.extract(sources.load_any(
            write_fixture(UTILITY_GROUND))))

    def test_utility_on_body_outranks_the_body_rule(self):
        """`.bg-light-primary` beats `body {}` — and is what the page shows."""
        themes = {t["id"]: t for t in self.doc()["themes"]}
        self.assertEqual(themes["base"]["ground"], "#eeefe9")
        # Reached by the right path: named for the class, not for `body`.
        self.assertIn("bg-light-primary", themes["base"]["groundSource"])

    def test_a_later_utility_the_body_lacks_does_not_win(self):
        """The case document order alone gets wrong.

        `.dark\\:bg-light-primary` is declared *after* the
        `.dark\\:bg-dark-primary` the body actually carries, so ordering picks
        it unless the class list is consulted. Only the body's own classes
        separate the two.
        """
        themes = {t["id"]: t for t in self.doc()["themes"]}
        self.assertEqual(themes["dark"]["ground"], "#262626")

    def test_tailwind_v4_shape_on_the_html_element(self):
        """The other real shape: v4's `:where(.dark,.dark *)`, marker on <html>.

        Trimmed from tailwindcss.com, which is where the comma split showed up.
        """
        html = """<!DOCTYPE html><html class="antialiased dark:bg-gray-950">
<head><style>
  body { background-color: #ffffff; color: #111111; }
  .dark\\:bg-gray-950:where(.dark,.dark *) { background-color: #030712; }
  .dark\\:bg-gray-800:where(.dark,.dark *) { background-color: #1e2939; }
</style></head><body></body></html>
"""
        doc = emit.to_document(extract.extract(sources.load_any(
            write_fixture(html))))
        themes = {t["id"]: t for t in doc["themes"]}
        self.assertEqual(themes["base"]["ground"], "#ffffff")
        self.assertEqual(themes["dark"]["ground"], "#030712")
        # From the html element's own class, not from a guess.
        self.assertIn("bg-gray-950", themes["dark"]["groundSource"])

    def test_a_var_defined_off_the_page_does_not_win(self):
        """Bootstrap's docs ship a `[data-bs-theme=blue]` nobody selected.

        It sets `--bs-body-bg: var(--bs-blue)`, and last-definition-wins alone
        reports the page background as Bootstrap blue.
        """
        html = """<!DOCTYPE html><html><head><style>
  :root { --bg: #ffffff; }
  [data-bs-theme=blue] { --bg: #0d6efd; }
  body { background-color: var(--bg); color: #212529; }
</style></head><body></body></html>
"""
        doc = emit.to_document(extract.extract(sources.load_any(
            write_fixture(html))))
        self.assertEqual(doc["themes"][0]["ground"], "#ffffff")

    def test_a_bare_body_still_uses_the_body_rule(self):
        """No classes on <body> must leave the old path exactly as it was."""
        html = UTILITY_GROUND.replace(
            '<body class="bg-light-primary dark:bg-dark-primary">', "<body>")
        doc = emit.to_document(extract.extract(sources.load_any(
            write_fixture(html))))
        themes = {t["id"]: t for t in doc["themes"]}
        self.assertEqual(themes["base"]["ground"], "#ffffff")
        self.assertEqual(themes["dark"]["ground"], "#0a0a0a")


class TestCascade(unittest.TestCase):
    """`importance → layer → specificity → document order` (phase 3).

    Every case here is one the previous document-order-only resolution got
    wrong, and none of them appears on the corpus — which is exactly why they
    are written out rather than left to a breadth check.
    """

    def ground_of(self, html, theme="base"):
        doc = emit.to_document(extract.extract(sources.load_any(
            write_fixture(html))))
        return {t["id"]: t for t in doc["themes"]}[theme]

    def test_specificity_beats_a_later_rule_of_lower_specificity(self):
        """The limit phase 3 lifts, stated as the case that used to fail.

        The body carries `.bg-canvas`, and that utility is declared *before*
        the `body {}` rule it competes with — the mirror image of ground.news,
        where the utility happens to come last and document order agreed with
        specificity by luck. A class outranks an element, so `#eeefe9` is what
        the page shows; document order alone reports `#ffffff`.
        """
        html = """<!DOCTYPE html><html><head><style>
  .bg-canvas { background-color: #eeefe9; }
  body { background-color: #ffffff; color: #111111; }
</style></head><body class="bg-canvas"></body></html>
"""
        g = self.ground_of(html)
        self.assertEqual(g["ground"], "#eeefe9")
        self.assertIn("bg-canvas", g["groundSource"])

    def test_important_beats_a_later_normal_declaration(self):
        """Importance is the first term, so order never reaches the question."""
        html = """<!DOCTYPE html><html><head><style>
  body { background-color: #123456 !important; color: #111111; }
  body { background-color: #ffffff; }
</style></head><body></body></html>
"""
        self.assertEqual(self.ground_of(html)["ground"], "#123456")

    def test_an_unlayered_rule_beats_a_layered_one(self):
        """Per spec, and it is the term most likely to look backwards.

        The layered rule is declared last and is *more* specific, and it still
        loses: an unlayered declaration outranks every layer, whatever is
        inside them. Tailwind v4 puts its whole stylesheet in layers, so this
        decides between the framework and anything written beside it.
        """
        html = """<!DOCTYPE html><html><head><style>
  body { background-color: #eeefe9; color: #111111; }
  @layer utilities { html body { background-color: #ffffff; } }
</style></head><body></body></html>
"""
        self.assertEqual(self.ground_of(html)["ground"], "#eeefe9")

    def test_a_later_layer_wins_and_the_statement_form_sets_the_order(self):
        """`@layer base, utilities;` fixes the order before either block exists.

        Both blocks are unlayered-equal on every other term, and `base` is
        written last. It still loses, because the statement at the top reserved
        `utilities` the later position — which is the entire reason a site
        writes that line. Tailwind v4 opens with one.
        """
        html = """<!DOCTYPE html><html><head><style>
  @layer base, utilities;
  @layer utilities { body { background-color: #eeefe9; } }
  @layer base { body { background-color: #ffffff; color: #111111; } }
</style></head><body></body></html>
"""
        self.assertEqual(self.ground_of(html)["ground"], "#eeefe9")

    def test_layer_order_reverses_for_important_declarations(self):
        """The rule that makes importance more than a tiebreak.

        Among `!important` declarations the layer order runs backwards, so the
        *earlier* layer wins — the opposite of the normal case immediately
        above. This is why the cascade is all four terms or none: bolting
        importance on as a final tiebreak gets this exactly wrong.

        The blocks are written in layer order here, so document order picks
        `utilities` and the reversal is the only thing that can pick `base`.
        """
        html = """<!DOCTYPE html><html><head><style>
  @layer base, utilities;
  @layer base { body { background-color: #eeefe9 !important; color: #111; } }
  @layer utilities { body { background-color: #ffffff !important; } }
</style></head><body></body></html>
"""
        self.assertEqual(self.ground_of(html)["ground"], "#eeefe9")

    def test_a_sub_layer_cascades_inside_its_parent(self):
        """`a.x` belongs between `a` and `b`, however late it is mentioned."""
        sheet = parse_stylesheet(
            "@layer a, b; @layer a.x { body { color: #111 } }", "s")
        order = layer_order([sheet])
        self.assertEqual(sorted(order, key=order.get), ["a", "a.x", "b"])

    def test_two_anonymous_layers_are_two_layers(self):
        """`@layer {}` opens a new layer every time, never reopens one."""
        sheet = parse_stylesheet(
            "@layer { body { color: #111 } } @layer { body { color: #222 } }",
            "s")
        self.assertEqual(len(set(sheet.layers)), 2)
        self.assertEqual(len({d.layer for d in sheet.declarations}), 2)

    def test_import_layer_reserves_a_position(self):
        """`@import url(...) layer(name);` reserves a position too (T8).

        The imported sheet is never fetched — `sources.py` doesn't follow
        `@import` — so it contributes no declarations of its own. But the
        position it will cascade at is claimed before `base` appears, the
        same way the statement form of `@layer` reserves one with no block
        behind it yet.
        """
        sheet = parse_stylesheet(
            "@import url(x.css) layer(utilities); "
            "@layer base { body { color: #111 } }", "s")
        order = layer_order([sheet])
        self.assertEqual(sorted(order, key=order.get), ["utilities", "base"])

    def test_import_layer_name_is_found_by_token_not_regex(self):
        """A dotted sub-layer name still comes through the `FunctionBlock`.

        Per the T5/T15 corollary, `layer(...)` is found by walking
        `node.prelude`'s tokens for a `function` node named `layer`, not by
        regexing the serialized prelude string — so a name with a dot in it
        (a sub-layer) still registers its parent too, the same as
        `@layer a.x {}` does.
        """
        sheet = parse_stylesheet(
            "@import url(x.css) layer(utilities.sub);", "s")
        self.assertIn("utilities", sheet.layers)
        self.assertIn("utilities.sub", sheet.layers)

    def test_import_without_layer_registers_nothing(self):
        """A plain `@import` still declares nothing — same as `@charset`."""
        sheet = parse_stylesheet("@import url(x.css);", "s")
        self.assertEqual(sheet.layers, [])

    def test_anonymous_layers_stay_distinct_when_nested(self):
        """The one construct here with a hand-rolled uniqueness scheme.

        No corpus site uses an anonymous layer, so nothing else exercises
        `_anonymous_layer`'s counter — and a collision would not raise, it
        would silently merge two layers and mis-order a palette on the first
        site that used them. Checked at two depths, and in the combinations
        that make the counter skip a value: a *named* layer inside an
        anonymous one registers a NUL-bearing qualified name too.

        Every ancestor must also be registered. `layer_order`'s `path()` falls
        back to "sorts last" for a name it cannot place, which would mask
        exactly this.
        """
        for css in (
            "@layer { body{color:#111} } @layer a { @layer { body{color:#222} } }",
            "@layer { @layer { body{color:#111} } body{color:#222} }",
            "@layer { @layer x { body{color:#111} } } @layer { body{color:#222} }",
            "@layer {body{color:#111}} @layer a.b {body{color:#222}} "
            "@layer {body{color:#333}}",
        ):
            sheet = parse_stylesheet(css, "s")
            order = layer_order([sheet])
            self.assertEqual(len(sheet.layers), len(set(sheet.layers)), css)
            for name in sheet.layers:
                parts = name.split(".")
                for i in range(len(parts)):
                    self.assertIn(".".join(parts[:i + 1]), order, css)

    def test_a_media_theme_loses_to_specificity_but_beats_order(self):
        """Where the theme term sits, and why it sits there.

        A `prefers-color-scheme` block has no specificity advantage over what
        it overrides, so it needs the term to beat a later unscoped `body`
        rule. It must not beat a *more specific* unscoped rule the body
        actually matches, because a browser applying the dark theme still
        applies `.bg-canvas` on top of it.
        """
        html = """<!DOCTYPE html><html><head><style>
  @media (prefers-color-scheme: dark) {
    body { background-color: #0b0f14; color: #e8e8ea; }
  }
  body { background-color: #ffffff; color: #111111; }
  .bg-canvas { background-color: #262626; }
</style></head><body class="bg-canvas"></body></html>
"""
        # The unscoped class outranks the media block on specificity …
        self.assertEqual(self.ground_of(html, "dark")["ground"], "#262626")
        # … and the media block still outranks the later unscoped `body` rule
        # when nothing more specific is in play.
        bare = html.replace(' class="bg-canvas"', "")
        self.assertEqual(self.ground_of(bare, "dark")["ground"], "#0b0f14")

    def test_html_and_body_grounds_resolve_in_separate_pools(self):
        """T7: pooling `<html>` and `<body>` candidates together is luck.

        Both rules are `(0, 0, 1)`, unimportant, unlayered — tied on every
        cascade term this key has — so a single shared pool falls through to
        document order and picks whichever was declared last. Here that is
        `html`. A real browser paints `<body>`'s own background over the
        `<html>` canvas wherever the body covers it, which is the whole
        viewport, so the right answer is body's regardless of order. Fails on
        HEAD's one-pool ranking (`#ffffff`), which is exactly the case
        `detect_ground`'s docstring names as unreachable on the frozen corpus.
        """
        html = """<!DOCTYPE html><html><head><style>
  body { background-color: #eeefe9; color: #111111; }
  html { background-color: #ffffff; }
</style></head><body></body></html>
"""
        self.assertEqual(self.ground_of(html)["ground"], "#eeefe9")

    def test_body_ground_wins_even_when_html_outranks_it_on_every_term(self):
        """The case that actually demonstrates separate pools, not luck.

        `<html>`'s background is `!important`, more specific (an id) and
        declared later — it would win a single shared pool on every cascade
        term there is. It still loses, because `<body>` having any resolved
        background at all takes precedence over whatever `<html>` resolves
        to; the id and the `!important` never get to compete against it.
        """
        html = """<!DOCTYPE html><html id="top"><head><style>
  body { background-color: #eeefe9; color: #111111; }
  html#top { background-color: #ffffff !important; }
</style></head><body></body></html>
"""
        self.assertEqual(self.ground_of(html)["ground"], "#eeefe9")


MEDIA_THEMES = """<!DOCTYPE html><html><head><style>
  :root { --bg: #ffffff; --fg: #1a1a1a; --brand: #2563eb; }
  body { background: var(--bg); color: var(--fg); }
  a { color: var(--brand); }
  .card { background: #f4f4f5; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #0b0f14; --fg: #e8e8ea; --brand: #60a5fa; }
    .card { background: #16181d; }
  }
</style></head><body></body></html>
"""

CLASS_THEMES = """<!DOCTYPE html><html><head><style>
  html { background: #ffffff; }
  body { color: #222222; }
  .btn { background: #2563eb; }
  html.dark { background: #101010; }
  html.dark body { color: #eeeeee; }
  .dark .btn { background: #60a5fa; }
</style></head><body></body></html>
"""


class TestThemes(unittest.TestCase):
    def doc_for(self, html):
        return emit.to_document(extract.extract(sources.load_any(
            write_fixture(html))))

    def test_media_query_themes_get_their_own_ground(self):
        doc = self.doc_for(MEDIA_THEMES)
        self.assertEqual([t["ground"] for t in doc["themes"]],
                         ["#ffffff", "#0b0f14"])
        self.assertEqual([t["appearance"] for t in doc["themes"]],
                         ["light", "dark"])

    def test_class_scoped_themes_get_their_own_ground(self):
        """`html.dark` has to be recognised as the dark theme's page rule."""
        doc = self.doc_for(CLASS_THEMES)
        self.assertEqual([t["ground"] for t in doc["themes"]],
                         ["#ffffff", "#101010"])

    def test_top_level_mirrors_the_default_theme(self):
        """The pre-themes shape of the document has to keep working."""
        doc = self.doc_for(MEDIA_THEMES)
        self.assertEqual(doc["ground"], doc["themes"][0]["ground"])
        self.assertEqual(doc["colors"], doc["themes"][0]["colors"])
        self.assertEqual(doc["defaultTheme"], "base")

    def test_overridden_values_leave_the_theme_that_replaced_them(self):
        """The light `--bg` must not appear as a color of the dark theme."""
        dark = self.doc_for(MEDIA_THEMES)["themes"][1]
        hexes = {c["hex"] for c in dark["colors"]}
        self.assertIn("#0b0f14", hexes)
        self.assertNotIn("#ffffff", hexes)
        self.assertNotIn("#f4f4f5", hexes)

    def test_names_align_across_themes(self):
        """The same token name has to mean the same job in both themes."""
        doc = self.doc_for(CLASS_THEMES)
        light = {c["name"]: c["hex"] for c in doc["themes"][0]["colors"]}
        dark = {c["name"]: c["hex"] for c in doc["themes"][1]["colors"]}
        self.assertEqual(set(light), set(dark))
        self.assertEqual(light["ground"], "#ffffff")
        self.assertEqual(dark["ground"], "#101010")
        # Body text: nearly black on the light theme, nearly white on the
        # dark one, and one token either way.
        ink = [n for n in light if light[n] == "#222222"]
        self.assertEqual(len(ink), 1)
        self.assertEqual(dark[ink[0]], "#eeeeee")

    def test_unthemed_site_reports_one_theme(self):
        doc = emit.to_document(extract.extract(sources.load_any(
            write_fixture(FIXTURE))))
        self.assertEqual(len(doc["themes"]), 1)
        self.assertEqual(doc["themes"][0]["id"], "base")

    def test_themes_can_be_switched_off(self):
        pal = extract.extract(sources.load_any(write_fixture(MEDIA_THEMES)),
                              themes=False)
        self.assertIsNone(pal.alternate)

    def test_a_scope_that_paints_nothing_new_is_not_a_theme(self):
        """A media block with no color of its own is not a second palette."""
        html = """<style>
          body { background: #ffffff; color: #222222; }
          @media (prefers-color-scheme: dark) { img { filter: invert(1); } }
        </style>"""
        self.assertEqual(len(self.doc_for(html)["themes"]), 1)

    def test_css_carries_both_themes_under_matching_names(self):
        doc = self.doc_for(MEDIA_THEMES)
        css = emit.emit_css(doc, "c")
        self.assertIn("@media (prefers-color-scheme: dark)", css)
        self.assertIn('[data-theme="dark"]', css)
        self.assertIn("--c-ground: #ffffff;", css)
        self.assertIn("--c-ground: #0b0f14;", css)

    def test_report_toggles_and_restyles_itself(self):
        doc = self.doc_for(MEDIA_THEMES)
        html = emit.emit_html(doc, None)
        # Reading colors for both themes, so a toggle restyles the page and
        # not just the swatches.
        self.assertIn(':root[data-pk-theme="base"]', html)
        self.assertIn(':root[data-pk-theme="dark"]', html)
        # The toast used to have its colors written straight into its rule,
        # which left it on the first theme's colors after a switch.
        self.assertIn("--ui-toast-bg", html)
        self.assertNotIn("__TOASTBG__", html)
        self.assertEqual(re.findall(r"__[A-Z_]+__", html), [])
        # Still standalone.
        self.assertNotIn("fetch(", html)
        self.assertNotIn("<link", html)

    def test_both_report_themes_are_readable(self):
        for theme in self.doc_for(MEDIA_THEMES)["themes"]:
            ui = emit._pick_report_theme(theme)
            g = parse_color(ui["ground"])
            for role, floor in (("strong", 7.0), ("body", 4.5), ("muted", 3.0)):
                ratio = contrast_ratio(parse_color(ui[role]), g)
                self.assertGreaterEqual(
                    ratio, floor,
                    f"{theme['id']} {role} only {ratio:.2f}:1 on its ground")


class TestColorMix(unittest.TestCase):
    """`color-mix()` — the largest category of color this tool used to skip.

    The corpus shape by a wide margin is Tailwind's opacity modifier,
    `color-mix(in oklab, <color> <p>%, transparent)`, which is why the
    zero-alpha case is asserted exactly rather than approximately.
    """

    def test_a_mix_with_transparent_is_the_color_at_that_alpha(self):
        """Exact, and it has to be: buckets are keyed on the quantised hex.

        With the other alpha at zero the premultiplied algebra collapses to
        "the first color, at `alpha * p`" — no interpolation happens at all.
        A round trip through OKLab would land ±1 off on some channels and
        invent palette entries out of rounding.
        """
        for space in ("oklab", "oklch", "srgb", "lab", "hsl"):
            got = parse_color(f"color-mix(in {space}, #ff0000 25%, transparent)")
            self.assertEqual(got.hexa, "#ff000040", space)
        self.assertEqual(
            parse_color("color-mix(in oklab, transparent, #3b82f6 60%)").hexa,
            "#3b82f699")

    def test_a_mix_is_read_in_the_space_it_names(self):
        """Half way between black and white is not the same color in each."""
        in_srgb = parse_color("color-mix(in srgb, #000000, #ffffff)")
        in_oklab = parse_color("color-mix(in oklab, #000000, #ffffff)")
        self.assertEqual(in_srgb.hex, "#808080")     # 0.5 * 255, rounded
        self.assertNotEqual(in_oklab.hex, in_srgb.hex)
        self.assertEqual(parse_color("color-mix(in srgb, white, black 75%)").hex,
                         "#404040")

    def test_percentages_normalise_and_a_shortfall_scales_alpha(self):
        """`red 30%, blue 30%` is an even mix at 60% alpha, not a 30/70 one."""
        got = parse_color("color-mix(in srgb, #ff0000 30%, #0000ff 30%)")
        self.assertEqual(got.hex, "#800080")
        self.assertAlmostEqual(got.a, 0.6, places=4)
        # One percentage stated, the other implied by it.
        self.assertEqual(parse_color("color-mix(in srgb, #ffffff 25%, #000000)").hex,
                         parse_color("color-mix(in srgb, #ffffff 25%, #000000 75%)").hex)

    def test_a_minified_mix_has_no_space_before_the_percentage(self):
        """ground.news ships `color-mix(in oklab,var(--ring)50%,transparent)`.

        A whitespace split finds no boundary in `rgb(0 0 255)50%`, so the
        component is scanned as a balanced color token with the percentage
        trailing it.
        """
        self.assertEqual(
            parse_color("color-mix(in oklab,rgb(0 0 255)50%,transparent)").hexa,
            "#0000ff80")

    def test_a_component_percentage_may_be_written_first(self):
        """`<percentage> <color>` is spec-legal; nothing on the corpus uses it,
        which is exactly why it was never exercised by a test until T15's
        `_split_component` refactor made it worth checking directly."""
        self.assertEqual(
            parse_color("color-mix(in srgb, 30% #ff0000, #0000ff)").hex,
            parse_color("color-mix(in srgb, #ff0000 30%, #0000ff)").hex)

    def test_a_mix_that_cannot_be_evaluated_yields_nothing(self):
        """Not the arguments inside it — those are colors the page never paints.

        Every one of these has a perfectly readable color in it, and reporting
        that color would be the plausible-looking guess this module exists to
        refuse. `calc(50% - var(--x))` stays in this list even after T5 taught
        `_mix_component` literal `calc()` arithmetic — a `var()` inside `calc()`
        is outside the supported subset on purpose, same as everywhere else a
        `var()` in an unexpected place is refused rather than guessed at.
        """
        for value in (
            "color-mix(in oklch, #b4d455 calc(50% - var(--x)), transparent)",
            "color-mix(in oklab, currentcolor 50%, #b4d455)",
            "color-mix(in jzazbz, #b4d455 50%, transparent)",
            "color-mix(#b4d455 50%, transparent)",
            "color-mix(in oklab, #b4d455 50%)",
        ):
            self.assertIsNone(parse_color(value), value)
            self.assertEqual(find_colors(value), [], value)

    def test_a_literal_calc_percentage_in_a_mix_is_evaluated(self):
        """T5: `calc()` percentages made of literal arithmetic now resolve.

        `calc(60 * 1%)` is the exact shape ui.shadcn.com ships across six
        `.shimmer-color-*` declarations — corpus-driven, not a hypothetical.
        Each assertion is checked against the same mix written as a plain
        percentage, so this tests the arithmetic rather than merely "some
        color came back".
        """
        self.assertEqual(
            parse_color("color-mix(in oklch, #b4d455 calc(60 * 1%), transparent)").hexa,
            parse_color("color-mix(in oklch, #b4d455 60%, transparent)").hexa)
        self.assertEqual(
            parse_color("color-mix(in oklab, #ff0000 calc(2 * 30%), #0000ff)").hex,
            parse_color("color-mix(in oklab, #ff0000 60%, #0000ff)").hex)
        self.assertEqual(
            parse_color("color-mix(in srgb, #ff0000 calc(90% - 30%), #0000ff)").hex,
            parse_color("color-mix(in srgb, #ff0000 60%, #0000ff)").hex)
        self.assertEqual(
            parse_color("color-mix(in srgb, #ff0000 calc(120% / 2), #0000ff)").hex,
            parse_color("color-mix(in srgb, #ff0000 60%, #0000ff)").hex)
        # Scientific notation is valid CSS numeric syntax, tokenized correctly
        # by tinycss2; a hand-rolled digit regex is the thing that misses it.
        self.assertEqual(
            parse_color("color-mix(in srgb, #ff0000 calc(1e2% / 2), #0000ff)").hex,
            parse_color("color-mix(in srgb, #ff0000 50%, #0000ff)").hex)

    def test_calc_outside_the_supported_subset_yields_nothing(self):
        """`calc()` evaluation is a deliberately small subset, not a parser.

        Mixed units, a percentage multiplied by a percentage, and division by
        a percentage are all outside CSS's own type rules for this position —
        evaluating them would require guessing a unit conversion this tool has
        no basis for. Malformed `calc()` (unbalanced parens, trailing junk)
        stays unreadable too.
        """
        for value in (
            "color-mix(in srgb, #ff0000 calc(50% - 5rem), #0000ff)",
            "color-mix(in srgb, #ff0000 calc(50% * 50%), #0000ff)",
            "color-mix(in srgb, #ff0000 calc(50% / 50%), #0000ff)",
            "color-mix(in srgb, #ff0000 calc(50%) extra, #0000ff)",
            "color-mix(in srgb, #ff0000 calc(50% +), #0000ff)",
        ):
            self.assertIsNone(parse_color(value), value)

    def test_a_powerless_hue_is_carried_forward(self):
        """A grey has no hue, so mixing it must not sweep through hues.

        With the angle taken from the other color, interpolating in a polar
        space is the same arithmetic as interpolating in its rectangular one —
        which is exactly the property that says the carry-forward happened.
        Without it the grey's arbitrary 0 degrees is averaged in and the result
        comes out reddened.
        """
        self.assertEqual(parse_color("color-mix(in oklch, #808080, #0000ff)").hex,
                         parse_color("color-mix(in oklab, #808080, #0000ff)").hex)
        self.assertEqual(parse_color("color-mix(in lch, #808080, #0000ff)").hex,
                         parse_color("color-mix(in lab, #808080, #0000ff)").hex)

    def test_the_longer_arc_goes_the_other_way_round(self):
        mid = parse_color("color-mix(in oklch, #ff0000, #00ff00)")
        long = parse_color("color-mix(in oklch longer hue, #ff0000, #00ff00)")
        self.assertNotEqual(mid.hex, long.hex)

    def test_lab_and_xyz_round_trip(self):
        """The inverse matrices are transcribed, so assert they are inverses."""
        from palettekit.color import (
            Color,
            color_to_lab,
            lab_to_color,
            xyz_d65_of,
            xyz_d65_to_color,
        )
        for r, g, b in ((0, 0, 0), (255, 255, 255), (17, 128, 200),
                        (200, 64, 9), (1, 2, 3)):
            c = Color(r, g, b)
            for back in (lab_to_color(*color_to_lab(c)),
                         xyz_d65_to_color(*xyz_d65_of(c))):
                self.assertEqual(back.rgb255, (r, g, b))

    def test_a_mix_inside_a_mix_resolves_outward(self):
        self.assertEqual(
            parse_color("color-mix(in oklab, "
                        "color-mix(in oklab, #ff0000 50%, transparent) 50%, "
                        "transparent)").hexa,
            "#ff000040")


class TestLightDark(unittest.TestCase):
    """`light-dark()` is a theme choice written inline, not a color function.

    developer.mozilla.org is the case that motivates it: its `<html>` rule
    resolves to `light-dark(#fff,#18191b)`, and reading both branches into one
    palette made a site with two obvious themes look like it had one.
    """

    PAGE = """<!DOCTYPE html><html><head><style>
      :root { --page: light-dark(#ffffff, #18191b); --ink: light-dark(#111111, #eeeeee); }
      html { background-color: var(--page); }
      body { color: var(--ink); }
    </style></head><body></body></html>"""

    def test_the_branch_follows_the_theme_being_built(self):
        self.assertEqual([c.hex for c in find_colors("light-dark(#fff,#18191b)")],
                         ["#ffffff"])
        for want, appearance in (("#ffffff", "light"), ("#18191b", "dark")):
            got = find_colors("light-dark(#fff,#18191b)", appearance)
            self.assertEqual([c.hex for c in got], [want], appearance)

    def test_only_the_selected_branch_is_a_color(self):
        """Both used to land in one palette, one of them never painted."""
        got = find_colors("1px solid light-dark(#fff,#18191b)", "dark")
        self.assertEqual([c.hex for c in got], ["#18191b"])

    def test_a_branch_that_will_not_parse_yields_nothing(self):
        """Never the other branch — that is a color this theme does not use."""
        self.assertEqual(find_colors("light-dark(currentcolor,#18191b)", "light"),
                         [])
        self.assertEqual(find_colors("light-dark(#fff)", "light"), [])

    def test_light_dark_alone_makes_a_site_two_themed(self):
        """No media query, no theme class — the function is the whole scope."""
        pal = extract.extract(sources.load_any(write_fixture(self.PAGE)))
        self.assertIsNotNone(pal.alternate)
        self.assertEqual((pal.theme_id, pal.alternate.theme_id),
                         ("light", "dark"))
        self.assertEqual(pal.ground.hex, "#ffffff")
        self.assertEqual(pal.alternate.ground.hex, "#18191b")
        # And the ground is read, not inferred — nothing warns about a guess.
        self.assertEqual([w for w in pal.warnings if "inferred" in w], [])

    def test_each_theme_carries_only_its_own_branch(self):
        pal = extract.extract(sources.load_any(write_fixture(self.PAGE)))
        light = {e.color.hex for e in pal.entries}
        dark = {e.color.hex for e in pal.alternate.entries}
        self.assertIn("#111111", light)
        self.assertNotIn("#eeeeee", light)
        self.assertIn("#eeeeee", dark)
        self.assertNotIn("#111111", dark)


class TestChannelTriplets(unittest.TestCase):
    """The shadcn/ui convention: `--background: 0 0% 3.9%`.

    A bare triplet is not a color. It becomes one only when a color function
    assembles it at the point of use. Both halves of that are asserted here,
    because the tempting "fix" — reading a color out of the bare form — would
    invent colors the page never paints.
    """

    TABLE = {"--bg": "0 0% 3.9%", "--brand": "217.2 91.2% 59.8%",
             "--chan": "255 0 0"}

    def test_triplet_assembled_by_a_color_function_is_read(self):
        cases = {
            "hsl(var(--bg))": "#0a0a0aff",
            "hsl(var(--brand))": "#3b82f6ff",
            "hsl(var(--bg) / 50%)": "#0a0a0a80",
            "hsla(var(--bg) / 0.5)": "#0a0a0a80",
            "rgb(var(--chan))": "#ff0000ff",
            "rgb(var(--chan) / 0.5)": "#ff000080",
            "1px solid hsl(var(--brand))": "#3b82f6ff",
        }
        for value, want in cases.items():
            got = [c.hexa for c in find_colors(resolve_vars(value, self.TABLE))]
            self.assertEqual(got, [want], value)

    def test_bare_triplet_is_not_a_color(self):
        """Correct by design, not a gap waiting to be filled.

        `background-color: var(--bg)` where `--bg` is `0 0% 3.9%` resolves to
        `background-color: 0 0% 3.9%`, which is invalid: a browser computes it
        to rgba(0,0,0,0) and paints nothing. Verified against a real engine
        with CSS.supports and getComputedStyle. Reading a color here would put
        a color in the palette that the page never shows.
        """
        self.assertEqual(find_colors(resolve_vars("var(--bg)", self.TABLE)), [])
        self.assertIsNone(parse_color("0 0% 3.9%"))

    def test_bare_triplet_use_is_reported(self):
        html = """<style>
          :root { --bg: 0 0% 100%; --fg: 0 0% 3.9%; }
          body { background-color: var(--bg); color: var(--fg); }
        </style>"""
        pal = extract.extract(sources.load_any(write_fixture(html)))
        notes = " ".join(pal.warnings)
        self.assertIn("bare channel triplet", notes)
        self.assertIn("--bg", notes)
        # One aggregated note, not one per property.
        self.assertEqual(len([w for w in pal.warnings
                              if "bare channel triplet" in w]), 1)

    def test_triplet_used_correctly_is_not_reported(self):
        """Nothing is wrong with a triplet a color function consumes."""
        html = """<style>
          :root { --bg: 0 0% 100%; }
          body { background-color: hsl(var(--bg)); }
        </style>"""
        pal = extract.extract(sources.load_any(write_fixture(html)))
        self.assertEqual([w for w in pal.warnings
                          if "bare channel triplet" in w], [])
        self.assertIn("#ffffff", [e.color.hex for e in pal.entries])

    def test_ordinary_values_are_not_mistaken_for_triplets(self):
        """The detector must not fire on lengths or on real colors."""
        html = """<style>
          :root { --pad: 1px 2px 3px; --edge: #abcdef; }
          body { background: #ffffff; border: var(--pad) solid var(--edge); }
        </style>"""
        pal = extract.extract(sources.load_any(write_fixture(html)))
        self.assertEqual([w for w in pal.warnings
                          if "bare channel triplet" in w], [])


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


class TestPackaging(unittest.TestCase):
    def test_pyproject_floor_matches_python_floor(self):
        """PLAN.md T1/T2: one number, not two copies that can drift.

        __main__.main()'s version guard and build.py both read
        palettekit.PYTHON_FLOOR; this is what keeps that constant honest
        against pyproject.toml's requires-python instead of trusting
        whoever last bumped one of them to also bump the other.

        The exact-string comparison is deliberate, not a shortcut to
        replace with a version parse — this project writes exactly one
        floor string (">=3.11"), so matching it precisely is stricter
        than parsing would be.
        """
        root = Path(__file__).parent
        data = tomllib.loads((root / "pyproject.toml").read_text())
        requires = data["project"]["requires-python"]
        self.assertEqual(requires, ">={}.{}".format(*PYTHON_FLOOR))


if __name__ == "__main__":
    unittest.main(verbosity=2)
