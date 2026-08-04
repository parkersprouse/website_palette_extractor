"""Color parsing, color-space maths, color-mix(), and light-dark()."""
import unittest

from palettekit import extract, sources
from palettekit.color import (
    contrast_ratio,
    delta_ok,
    find_colors,
    hue_name,
    parse_color,
)

from .helpers import write_fixture


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

    `color-scheme: light dark` (T10, `PLAN.md`) is in `PAGE` deliberately —
    without it a `light-dark()` site is not confirmed two-themed at all (see
    `TestLightDarkNeedsColorScheme` below), and this fixture exists to test
    that a *confirmed* one still is, not to test the confirmation itself.
    """

    PAGE = """<!DOCTYPE html><html><head><style>
      :root {
        color-scheme: light dark;
        --page: light-dark(#ffffff, #18191b); --ink: light-dark(#111111, #eeeeee);
      }
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


class TestLightDarkNeedsColorScheme(unittest.TestCase):
    """T10 (`PLAN.md`): `light-dark()` alone is not proof of two themes.

    Invariant 23's own overreach caveat: the function resolves against the
    *used* `color-scheme`, whose initial value is `normal` — light. A page
    that writes `light-dark()` and never declares `color-scheme: light dark`
    (or `dark light`) renders the light branch always, whatever the OS says,
    and calling that page two-themed invents a palette it never shows.

    No corpus site exercised the negative case until now — MDN and
    `pawelgrzybek.com`'s light/dark example both confirm both keywords, so
    both stay positive controls (`TestLightDark`, and the corpus check in
    `PLAN.md`/`CLAUDE.md`). These are synthetic because the gate itself needs
    a fixture that omits the confirmation on purpose.
    """

    def _page(self, color_scheme: str = "") -> str:
        decl = f"color-scheme: {color_scheme};" if color_scheme else ""
        return f"""<!DOCTYPE html><html><head><style>
          :root {{ {decl} --page: light-dark(#ffffff, #18191b); }}
          html {{ background-color: var(--page); }}
        </style></head><body></body></html>"""

    def test_no_color_scheme_declared_stays_one_theme_reading_light(self):
        pal = extract.extract(sources.load_any(write_fixture(self._page())))
        self.assertIsNone(pal.alternate)
        self.assertEqual(pal.ground.hex, "#ffffff")

    def test_color_scheme_normal_stays_one_theme_reading_light(self):
        """`normal` is the initial value — spelled out, not just absent."""
        pal = extract.extract(
            sources.load_any(write_fixture(self._page("normal"))))
        self.assertIsNone(pal.alternate)
        self.assertEqual(pal.ground.hex, "#ffffff")

    def test_color_scheme_dark_alone_stays_one_theme_reading_dark(self):
        """Confirmed dark-only, not light — the other half of the caveat."""
        pal = extract.extract(
            sources.load_any(write_fixture(self._page("dark"))))
        self.assertIsNone(pal.alternate)
        self.assertEqual(pal.ground.hex, "#18191b")

    def test_color_scheme_light_dark_confirms_two_themes(self):
        """The positive case, isolated from `TestLightDark`'s richer fixture."""
        pal = extract.extract(
            sources.load_any(write_fixture(self._page("light dark"))))
        self.assertIsNotNone(pal.alternate)
        self.assertEqual((pal.ground.hex, pal.alternate.ground.hex),
                         ("#ffffff", "#18191b"))

    def test_color_scheme_dark_light_order_does_not_matter(self):
        pal = extract.extract(
            sources.load_any(write_fixture(self._page("dark light"))))
        self.assertIsNotNone(pal.alternate)


class TestSelectorScopedColorScheme(unittest.TestCase):
    """T26 (`PLAN.md`): a `color-scheme` confirmed only inside a theme scope.

    `TestLightDarkNeedsColorScheme` above only ever confirms `color-scheme`
    through an *unscoped* declaration reaching the page via the cascade. A
    real `[data-theme="dark"] { color-scheme: dark }` toggle — the fixture
    the owner supplied for T24, `pseudo_selector_example.har` — is a
    different shape: a static capture freezes one `data-theme` state, so the
    *other* keyword's rule structurally cannot DOM-match in the same
    capture. Before T26 this meant that gate could confirm at most one
    keyword from such a site, however completely the CSS declared both.
    """

    def _page(self, captured_theme: str) -> str:
        return f"""<!DOCTYPE html><html data-theme="{captured_theme}"><head><style>
          [data-theme="light"] {{ color-scheme: light; }}
          [data-theme="dark"] {{ color-scheme: dark; }}
          :root {{ --page: light-dark(#efefec, #202122); }}
          html {{ background-color: var(--page); }}
        </style></head><body></body></html>"""

    def test_confirms_both_keywords_from_the_captured_side_alone(self):
        """Only `[data-theme="dark"]` can DOM-match here; `light` still confirms."""
        pal = extract.extract(sources.load_any(write_fixture(self._page("dark"))))
        self.assertIsNotNone(pal.alternate)
        self.assertEqual((pal.theme_id, pal.alternate.theme_id), ("light", "dark"))
        self.assertEqual(pal.ground.hex, "#efefec")
        self.assertEqual(pal.alternate.ground.hex, "#202122")

    def test_confirms_both_keywords_from_the_other_captured_side(self):
        """Symmetric: capturing the light state confirms `dark` the same way."""
        pal = extract.extract(sources.load_any(write_fixture(self._page("light"))))
        self.assertIsNotNone(pal.alternate)
        self.assertEqual(pal.ground.hex, "#efefec")
        self.assertEqual(pal.alternate.ground.hex, "#202122")

    def test_a_single_selector_scoped_keyword_does_not_confirm_both(self):
        """Only a `dark` toggle rule exists — still one theme, reading dark."""
        page = """<!DOCTYPE html><html data-theme="dark"><head><style>
          [data-theme="dark"] { color-scheme: dark; }
          :root { --page: light-dark(#ffffff, #18191b); }
          html { background-color: var(--page); }
        </style></head><body></body></html>"""
        pal = extract.extract(sources.load_any(write_fixture(page)))
        self.assertIsNone(pal.alternate)
        self.assertEqual(pal.ground.hex, "#18191b")

    def test_a_media_scoped_keyword_does_not_confirm_unconditionally(self):
        """A `prefers-color-scheme` block is conditional, unlike a selector toggle.

        Trusting it the same way a selector-scoped declaration is trusted
        would let a single `@media (prefers-color-scheme: dark)` block
        confirm `dark` for every visitor, including one whose browser is not
        in dark mode — the same overreach T10's own gate exists to prevent.
        """
        page = """<!DOCTYPE html><html><head><style>
          @media (prefers-color-scheme: dark) { :root { color-scheme: dark; } }
          :root { --page: light-dark(#ffffff, #18191b); }
          html { background-color: var(--page); }
        </style></head><body></body></html>"""
        pal = extract.extract(sources.load_any(write_fixture(page)))
        self.assertIsNone(pal.alternate)
        self.assertEqual(pal.ground.hex, "#ffffff")


if __name__ == "__main__":
    unittest.main(verbosity=2)
