"""Emitters: the JSON document contract and the standalone HTML report."""
import json
import re
import unittest

from website_palette_extractor import emit, extract, sources
from website_palette_extractor.color import contrast_ratio, parse_color

from .helpers import FIXTURE, write_fixture


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
        self.assertNotIn("fetch(", html)
        self.assertNotIn("<link", html)
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

    def test_report_status_subheadings_predicate_is_not_the_naive_one(self):
        """T20: a section that is entirely non-live still gets its heading.

        `STATUS_TITLES`/`STATUS_BLURBS` text and the `status-heading`/
        `status-blurb` classes are emitted into the template unconditionally
        (the injected JSON dict and the stylesheet), so their presence in the
        HTML proves nothing about whether `render()` ever actually shows a
        heading -- a naive first draft (`statusesPresent.length > 1`, which
        hides the heading for a section whose only status is e.g.
        `unmatched`, exactly the shape this task exists to surface) would
        pass a presence-only check. This pins the corrected predicate in the
        emitted JS source instead. Final DOM rendering -- that the fixture's
        purely-`unmatched` `line` section really does show its heading, and a
        mixed section shows all its statuses in order -- was verified by
        hand in a browser against both this fixture and
        `fleshandbonedesign.com.har`; see PLAN.md's T20 entry.
        """
        html = emit.emit_html(self.doc, self.pal)
        self.assertIn(
            'statusesPresent.length > 1 || statusesPresent[0] !== "live"',
            html)

        # The fixture exercises all four statuses (verified directly against
        # extract() output), so every title/blurb pair is load-bearing here,
        # not merely present in the unconditional template scaffolding.
        statuses = {c["status"] for c in self.doc["colors"]}
        self.assertEqual(statuses, {"live", "saved", "inert", "unmatched"})
        for status in statuses:
            self.assertIn(emit.STATUS_TITLES[status], html)
            self.assertIn(emit.STATUS_BLURBS[status], html)

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


class TestReportTemplateSubstitution(unittest.TestCase):
    """The report's placeholders must not be findable in the site's own data.

    `emit_html` used to fill the template with a chain of `str.replace`
    calls, each one rescanning everything the previous ones had already
    written. `__DATA__` — the site's JSON, containing arbitrary selector text
    — was substituted *before* four static placeholders, so a site whose CSS
    contained one of their names had it rewritten inside the data blob. The
    result is invalid JSON in a `<script type="application/json">` element,
    which means `JSON.parse` throws and the report renders nothing: invariant
    11's standalone guarantee broken by the page being measured.
    """

    def _report(self, css: str) -> tuple[dict, str]:
        page = write_fixture(
            f"<!doctype html><html><head><style>{css}</style></head>"
            "<body></body></html>"
        )
        pal = extract.extract(sources.load_any(page))
        doc = emit.to_document(pal)
        return doc, emit.emit_html(doc, pal)

    def _payload(self, html: str) -> dict:
        blob = re.search(
            r'id="palette-data">(.*?)</script>', html, re.S).group(1)
        # `</` is escaped on the way in so the JSON cannot close the element.
        return json.loads(blob.replace("<\\/", "</"))

    def test_site_content_cannot_corrupt_the_report_payload(self):
        """A class literally named for a placeholder is enough to trigger it."""
        for placeholder in ("__GROUP_TITLES__", "__GROUP_BLURBS__",
                            "__STATUS_TITLES__", "__STATUS_BLURBS__"):
            with self.subTest(placeholder=placeholder):
                _doc, html = self._report(
                    f"body {{ background: #123456 }} "
                    f".{placeholder} {{ color: #ff0000 }}"
                )
                data = self._payload(html)          # raises if corrupted
                selectors = [e.get("selector", "")
                             for c in data["colors"]
                             for e in c.get("examples", [])]
                self.assertTrue(
                    any(placeholder in s for s in selectors),
                    "the site's own selector should survive verbatim",
                )

    def test_every_placeholder_is_still_filled(self):
        """The single-pass rewrite must not leave a placeholder behind."""
        _doc, html = self._report("body { background: #123456 }")
        for placeholder in ("__TITLE__", "__TITLE_HTML__", "__SUBTITLE__",
                            "__UI_THEMES__", "__DATA__", "__GROUP_TITLES__",
                            "__GROUP_BLURBS__", "__STATUS_TITLES__",
                            "__STATUS_BLURBS__"):
                # The data blob is excluded: a *site* may legitimately contain
                # the text, and that is precisely what must survive.
            blob = re.search(
                r'id="palette-data">(.*?)</script>', html, re.S).group(1)
            self.assertNotIn(placeholder, html.replace(blob, ""))

    def test_a_backslash_in_site_content_is_not_read_as_a_group_reference(self):
        """`re.sub` reads `\\g<0>` in a *replacement string* as a back-reference.

        The replacements are returned from a callback, which is never
        scanned for those — but Tailwind-style escaped class names put real
        backslashes in selectors, so this is the shape that would break it.
        """
        _doc, html = self._report(
            r"body { background: #123456 } .w-\[\\g\<0\>\] { color: #00ff00 }"
        )
        self._payload(html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
