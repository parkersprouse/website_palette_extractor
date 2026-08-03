"""Emitters: the JSON document contract and the standalone HTML report."""
import json
import re
import unittest

from palettekit import emit, extract, sources
from palettekit.color import contrast_ratio, parse_color

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
