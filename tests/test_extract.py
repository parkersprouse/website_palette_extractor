"""extract(): the cascade, ground detection, merging, and theme scoping."""
import re
import unittest

from palettekit import emit, extract, sources
from palettekit.color import contrast_ratio, find_colors, parse_color
from palettekit.cssparse import parse_stylesheet, resolve_vars
from palettekit.dom import elements_matching, full_tree
from palettekit.extract import layer_order

from .helpers import (
    CLASS_THEMES,
    FIXTURE,
    MEDIA_THEMES,
    UTILITY_GROUND,
    write_fixture,
)


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


class TestResolveByAncestry(unittest.TestCase):
    """T9: resolving an off-page custom property by real inheritance.

    Reproduces the exact shape `PLAN.md` T9's investigation found the
    rejected same-element filter getting wrong: `.theme-neutral { --card:
    ... }` several levels above `.bg-card { background: var(--card) }`. A
    same-element filter tests whether `.theme-neutral` reaches `.bg-card`'s
    own selector, which it never does — that shape is meant to be read
    through inheritance, not by matching the same element.
    """

    CSS = """
      .theme-neutral { --card: #f5f5f5; }
      .theme-blue { --card: #1d4ed8; }
      .bg-card { background: var(--card); }
    """

    def _candidates(self, css=None, prop="--card"):
        sheet = parse_stylesheet(css or self.CSS, "t.css")
        return [d for d in sheet.declarations if d.prop == prop]

    def test_nearest_ancestor_wins_not_same_element(self):
        html = ('<html><body><div class="theme-neutral">'
                '<p><span class="bg-card">x</span></p></div></body></html>')
        consumers = elements_matching(".bg-card", full_tree(html))
        value = extract.resolve_by_ancestry(self._candidates(), consumers, {})
        self.assertEqual(value, "#f5f5f5")

    def test_different_ancestors_give_different_real_answers(self):
        """A same-element filter finds neither; both real answers exist."""
        html = ('<html><body>'
                '<div class="theme-neutral"><span class="bg-card">a</span></div>'
                '<div class="theme-blue"><span class="bg-card">b</span></div>'
                '</body></html>')
        neutral_el, blue_el = elements_matching(".bg-card", full_tree(html))
        candidates = self._candidates()
        self.assertEqual(
            extract.resolve_by_ancestry(candidates, [neutral_el], {}),
            "#f5f5f5")
        self.assertEqual(
            extract.resolve_by_ancestry(candidates, [blue_el], {}),
            "#1d4ed8")

    def test_disagreeing_consumers_collapse_to_none_not_a_guess(self):
        """One declaration painting two differently-themed elements has no
        single answer, and this function refuses to pick one arbitrarily.
        """
        html = ('<html><body>'
                '<div class="theme-neutral"><span class="bg-card">a</span></div>'
                '<div class="theme-blue"><span class="bg-card">b</span></div>'
                '</body></html>')
        both = elements_matching(".bg-card", full_tree(html))
        self.assertIsNone(
            extract.resolve_by_ancestry(self._candidates(), both, {}))

    def test_no_matching_ancestor_is_none(self):
        html = '<html><body><span class="bg-card">x</span></body></html>'
        consumers = elements_matching(".bg-card", full_tree(html))
        self.assertIsNone(
            extract.resolve_by_ancestry(self._candidates(), consumers, {}))

    def test_ties_at_the_same_ancestor_level_use_the_cascade(self):
        """Two candidates matching the *same* ancestor still need a winner --
        this does not stop being a cascade problem just because the pool is
        scoped to one ancestor level instead of the whole page.
        """
        css = """
          .theme-neutral { --card: #f5f5f5; }
          .theme-neutral.override { --card: #123456 !important; }
          .bg-card { background: var(--card); }
        """
        html = ('<html><body><div class="theme-neutral override">'
                '<span class="bg-card">x</span></div></body></html>')
        consumers = elements_matching(".bg-card", full_tree(html))
        value = extract.resolve_by_ancestry(
            self._candidates(css), consumers, {})
        self.assertEqual(value, "#123456")


if __name__ == "__main__":
    unittest.main(verbosity=2)
