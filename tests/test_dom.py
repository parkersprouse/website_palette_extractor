"""The html.parser -> ElementTree shim and cssselect2 page-element matching."""
import unittest

from palettekit.dom import (
    elements_matching,
    full_tree,
    matches_page_element,
    page_elements,
    selector_matches,
)


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


class TestFullTree(unittest.TestCase):
    """T9's `html5lib`-backed tree — real structure below `<html>`/`<body>`."""

    HTML = ('<html><body><div class="theme-neutral">'
            '<p><span class="bg-card">x</span></p></div>'
            '<span class="bg-card">y</span></body></html>')

    def test_matches_a_real_element_several_levels_deep(self):
        tree = full_tree(self.HTML)
        found = elements_matching(".bg-card", tree)
        self.assertEqual(len(found), 2)
        self.assertEqual({e.local_name for e in found}, {"span"})

    def test_ancestor_relationship_is_real_not_assumed(self):
        """The whole reason this tree exists: distinguish ancestor from sibling.

        One `.bg-card` sits under `.theme-neutral`; the other does not. A
        same-element-only check (T9's rejected first design) cannot tell
        these apart at all.
        """
        tree = full_tree(self.HTML)
        under_theme, outside_theme = elements_matching(".bg-card", tree)
        theme_names = {a.local_name + "." + "".join(a.classes)
                      for a in under_theme.ancestors}
        self.assertIn("div.theme-neutral", theme_names)
        outside_names = {a.local_name + "." + "".join(a.classes)
                         for a in outside_theme.ancestors}
        self.assertNotIn("div.theme-neutral", outside_names)

    def test_selector_matches_returns_specificity_or_none(self):
        tree = full_tree(self.HTML)
        el = elements_matching(".bg-card", tree)[0]
        self.assertEqual(selector_matches(".bg-card", el), (0, 1, 0))
        self.assertIsNone(selector_matches(".theme-neutral", el))

    def test_elements_matching_refuses_pseudo_elements_and_dynamic_state(self):
        tree = full_tree(self.HTML)
        self.assertEqual(elements_matching(".bg-card::after", tree), [])
        self.assertEqual(elements_matching(".bg-card:hover", tree), [])

    def test_a_selector_that_will_not_compile_finds_nothing(self):
        tree = full_tree(self.HTML)
        self.assertEqual(elements_matching(":is( , .x)", tree), [])

    def test_non_string_input_is_none_not_a_raise(self):
        """`html5lib` is lenient about malformed markup by design -- empty
        string and outright garbage both come back a minimal tree, checked
        directly rather than assumed. The one thing that actually raises is
        input that isn't text.
        """
        self.assertIsInstance(full_tree(""), object)
        self.assertIsNotNone(full_tree("not even close to html <<<"))
        self.assertIsNone(full_tree(12345))


if __name__ == "__main__":
    unittest.main(verbosity=2)
