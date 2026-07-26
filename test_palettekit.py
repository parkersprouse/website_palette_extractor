"""Tests for palettekit.  Run: python3 test_palettekit.py

These cover the parts that are easy to get quietly wrong — color maths,
cascade order, and the merge rules — rather than every code path.
"""
import json
import os
import re
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
    split_selector_list,
    strip_theme_scope,
    theme_scope,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
