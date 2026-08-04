"""tinycss2 integration: parsing, var() resolution, theme scoping."""
import unittest

import tinycss2

from website_palette_extractor.color import find_colors
from website_palette_extractor.cssparse import (
    is_inert_shadow,
    parse_stylesheet,
    resolve_vars,
    selector_weight,
    split_selector_list,
    strip_theme_scope,
    supports_condition,
    theme_scope,
    var_refs,
)


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

        `.a { color: red; @media (min-width:1px) { color: blue } }` – `blue`
        belongs to `.a`, exactly as if the `@media` wrapper weren't there. The
        old brace walker (and `_walk` until this fix) pushed an empty selector
        for every at-rule block regardless of nesting, so this declaration
        was read for its `var()` references only and then dropped.
        """
        css = ".a { color: red; @media (min-width:1px) { color: blue } }"
        sheet = parse_stylesheet(css, "t")
        got = [(d.selector, d.prop, d.value) for d in sheet.declarations]
        self.assertEqual(got, [(".a", "color", "red"), (".a", "color", "blue")])

        # A *top-level* at-rule still resets to no selector – a qualified
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
        which `_theme_plan` treats as belonging to *every* theme – inventing a
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
        # nested media query – the enclosing rule already said which theme it
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
        the same way `var(--foo)` would – invariant 9's mistake, recurring one
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
        # Case and surrounding whitespace do not matter – it is a keyword.
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
        the wrong one the moment the fallback contains a function – it cut the
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
        counted twice – 204 declarations across three corpus sites. The colors
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
        the hex `#fff100` – a bright yellow that appeared 18 times on
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

        Read the marker as a scope and the dark theme's whole token block –
        124 declarations of it, the ground among them – is filed under light.
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
        # Stripping must leave the negation intact – `html:not()` is not a
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

        Splitting there leaves `:where(, *)`, which matches nothing – so the
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
        `\\:bg-x` – which then matches nothing, including the body's own class.
        """
        sel = r".dark\:bg-dark-primary:is(.dark *)"
        self.assertEqual(theme_scope(sel, ()), "dark")
        self.assertEqual(strip_theme_scope(sel), r".dark\:bg-dark-primary")
        # The name alone, with no :is() to scope it, is not a theme at all.
        self.assertEqual(theme_scope(r".dark\:bg-dark-primary", ()), "")


def _prelude(css: str):
    return tinycss2.parse_component_value_list(css)


class TestSupports(unittest.TestCase):
    """T23: `@supports` used to be read as though every block always applies.

    That's backwards for a `not (...)` fallback guarding a feature this tool
    already treats as real browser behaviour (invariants 22-23) – exactly
    pawelgrzybek.com's `@supports not (color: light-dark(white,black))`,
    which otherwise outranks the real `light-dark()` declaration on document
    order alone. See PLAN.md T23 and CLAUDE.md's `@supports` known limit.
    """

    def test_a_recognised_color_function_is_confirmed_supported(self):
        self.assertTrue(
            supports_condition(_prelude("(color: light-dark(white,black))")))
        self.assertFalse(
            supports_condition(_prelude(
                "not (color: light-dark(white,black))")))

    def test_a_property_this_tool_cannot_judge_stays_unknown(self):
        """`display` isn't a pure-`<color>` property; guessing invites a
        false negative on something genuinely supported everywhere."""
        self.assertIsNone(supports_condition(_prelude("(display: grid)")))
        self.assertIsNone(supports_condition(_prelude("not (display: grid)")))

    def test_a_custom_property_is_always_supported(self):
        self.assertTrue(supports_condition(_prelude("(--x: anything(1))")))

    def test_and_or_use_three_valued_logic(self):
        # `not X or Y` isn't valid `@supports` grammar on its own – mixing
        # `not`/`and`/`or` at the same level needs explicit disambiguating
        # parens (CSS Conditional Rules 3), same as `(not X) or Y` below.
        false_and_unknown = _prelude(
            "not (color: light-dark(white,black)) and (display: grid)")
        self.assertFalse(supports_condition(false_and_unknown))
        false_or_unknown = _prelude(
            "(not (color: light-dark(white,black))) or (display: grid)")
        self.assertIsNone(supports_condition(false_or_unknown))
        true_or_unknown = _prelude(
            "(color: light-dark(white,black)) or (display: grid)")
        self.assertTrue(supports_condition(true_or_unknown))

    def test_nested_parens_are_handled_via_tinycss2s_own_grouping(self):
        self.assertFalse(supports_condition(_prelude(
            "not ((color: light-dark(white,black)))")))

    def test_an_unsupported_fallback_block_never_applies(self):
        """The pawelgrzybek.com shape: a `@supports not (...)` fallback for
        browsers that can't parse `light-dark()`, sitting after the real
        declaration in document order. Read at face value it wins last-wins
        over the real one; skipped, it never reaches `sheet.declarations` or
        `sheet.var_refs` at all – not merely unrecorded as a color.
        """
        css = (
            ":root { --bg: light-dark(white, black); }"
            "@supports not (color: light-dark(white,black)) {"
            "  :root { --bg: white; --only-in-fallback: var(--never-used); }"
            "}"
        )
        sheet = parse_stylesheet(css, "t")
        got = [(d.selector, d.prop, d.value) for d in sheet.declarations]
        self.assertEqual(got, [(":root", "--bg", "light-dark(white, black)")])
        self.assertNotIn("--never-used", sheet.var_refs)

    def test_a_confirmed_supported_block_still_applies(self):
        css = ("@supports (color: light-dark(white,black)) {"
               " :root { --a: red } }")
        sheet = parse_stylesheet(css, "t")
        got = [(d.selector, d.prop) for d in sheet.declarations]
        self.assertEqual(got, [(":root", "--a")])

    def test_an_undecidable_condition_still_applies_as_before(self):
        css = "@supports (display: grid) { :root { --a: red } }"
        sheet = parse_stylesheet(css, "t")
        got = [(d.selector, d.prop) for d in sheet.declarations]
        self.assertEqual(got, [(":root", "--a")])


class TestPropertyRegistration(unittest.TestCase):
    """`@property` registrations (T22, `PLAN.md`): read for `inherits`/
    `initial-value`, kept off `sheet.declarations` and `sheet.var_refs`."""

    def test_a_property_rule_is_recorded_on_the_sheet(self):
        css = '@property --tw-ring-color { syntax: "*"; inherits: false; }'
        sheet = parse_stylesheet(css, "t")
        self.assertEqual(sheet.properties["--tw-ring-color"], ("false", None))

    def test_initial_value_is_captured(self):
        css = ('@property --tw-ring-offset-color '
               '{ syntax: "*"; inherits: false; initial-value: #fff; }')
        sheet = parse_stylesheet(css, "t")
        self.assertEqual(sheet.properties["--tw-ring-offset-color"],
                         ("false", "#fff"))

    def test_a_property_rule_contributes_no_declaration_or_var_ref(self):
        """The Tailwind shape this was found against: `@property` metadata
        must not be mistaken for a paintable declaration the way an ordinary
        block-shaped at-rule with no enclosing selector reads its contents
        for `var()` references only (T22 is a deliberate `continue`, not a
        reliance on that fallback)."""
        css = ('@property --tw-gradient-from '
               '{ syntax: "*"; inherits: false; initial-value: #0000; }')
        sheet = parse_stylesheet(css, "t")
        self.assertEqual(sheet.declarations, [])
        self.assertEqual(sheet.var_refs, set())

    def test_a_later_registration_overrides_an_earlier_one(self):
        css = ('@property --x { inherits: true; }'
               '@property --x { inherits: false; initial-value: red; }')
        sheet = parse_stylesheet(css, "t")
        self.assertEqual(sheet.properties["--x"], ("false", "red"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
