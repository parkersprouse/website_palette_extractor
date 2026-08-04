"""`images.py`: the optional image pass, and the sizes that used to crash it.

This module is reached only through `--images` and never contributes to the
token set (invariant: it answers "is the palette in the stylesheet or in the
artwork?"), which is why it went untested — and why a crash in it could take
down a run whose palette was already complete.

Every test skips cleanly when Pillow/numpy are absent, so the suite still
passes on a core install.
"""
import io
import unittest

from website_palette_extractor import images

HAVE_IMAGES, _WHY = images.available()


def png(size: tuple[int, int], rgba: tuple[int, int, int, int]) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", size, rgba).save(buf, "PNG")
    return buf.getvalue()


@unittest.skipUnless(HAVE_IMAGES, f"needs pillow + numpy ({_WHY})")
class TestAnalyse(unittest.TestCase):
    def test_no_images_is_none_not_an_empty_report(self):
        """Absent and empty are different answers; `None` says "not asked"."""
        self.assertIsNone(images.analyse([]))

    def test_a_tiny_image_does_not_crash_the_run(self):
        """Fewer opaque pixels than clusters used to raise `ValueError`.

        Both back-ends reject k > n rather than degrading — the numpy path
        seeds with `rng.choice(..., replace=False)` and sklearn refuses
        `n_clusters > n_samples` — so a page whose only artwork is a tracking
        pixel or a spacer gif killed the run *after* the palette was built.
        k is clamped to the sample count now.
        """
        for side in (1, 2, 3):
            with self.subTest(side=side):
                report = images.analyse([png((side, side), (200, 30, 40, 255))])
                self.assertIsNotNone(report)
                self.assertEqual(report["imageCount"], 1)
                self.assertEqual(report["pixelsSampled"], side * side)
                # One cluster per pixel at most, and at least one.
                self.assertTrue(1 <= len(report["dominant"]) <= side * side)

    def test_a_normal_image_still_gets_the_full_cluster_count(self):
        """Clamping must not reduce k on an image that has pixels to spare."""
        report = images.analyse([png((64, 64), (200, 30, 40, 255))])
        self.assertEqual(len(report["dominant"]), 10)

    def test_a_fully_transparent_image_yields_nothing(self):
        """Alpha <= 128 is dropped, so there is no pixel left to cluster."""
        self.assertIsNone(images.analyse([png((8, 8), (0, 0, 0, 0))]))

    def test_undecodable_bytes_are_skipped_not_fatal(self):
        self.assertIsNone(images.analyse([b"not an image at all"]))

    def test_one_bad_image_does_not_discard_the_good_ones(self):
        report = images.analyse([b"junk", png((32, 32), (10, 200, 90, 255))])
        self.assertIsNotNone(report)
        self.assertEqual(report["imageCount"], 1)

    def test_a_grey_image_reads_as_neutral(self):
        """The neutral share is what decides the report's warning, so the
        two ends of the verdict scale are worth pinning."""
        report = images.analyse([png((32, 32), (128, 128, 128, 255))])
        self.assertEqual(report["neutralSharePct"], 100.0)
        self.assertTrue(all(d["neutral"] for d in report["dominant"]))

    def test_a_saturated_image_reads_as_carrying_color(self):
        report = images.analyse([png((32, 32), (220, 20, 60, 255))])
        self.assertEqual(report["neutralSharePct"], 0.0)
        self.assertIn("incomplete", report["verdict"])


class TestAvailability(unittest.TestCase):
    def test_available_reports_a_reason_when_it_says_no(self):
        """The CLI prints this string, so an empty one would be a bare
        `warning:` with nothing after it."""
        ok, msg = images.available()
        self.assertIsInstance(ok, bool)
        if not ok:
            self.assertTrue(msg.strip())
        else:
            self.assertEqual(msg, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
