"""load_har / load_url / load_paths error handling."""
import base64
import json
import unittest
from unittest import mock

from website_palette_extractor import sources

from .helpers import write_fixture


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


def _font_har(url: str = "https://example.com/a.woff2",
              mime: str = "font/woff2") -> str:
    raw = b"\x00fake-font-bytes"
    har = {
        "log": {
            "entries": [{
                "request": {"url": url},
                "response": {"content": {
                    "mimeType": mime,
                    "text": base64.b64encode(raw).decode("ascii"),
                    "encoding": "base64",
                    "size": len(raw),
                }},
            }],
        }
    }
    return json.dumps(har)


class TestFontCapture(unittest.TestCase):
    """`--fonts`: `_kind_for`, `load_har`'s gate, `fetch_binaries`."""

    def test_kind_for_recognises_font_extensions_and_mime_types(self):
        self.assertEqual(sources._kind_for("", "https://x/a.woff2"), "font")
        self.assertEqual(sources._kind_for("", "https://x/a.woff"), "font")
        self.assertEqual(sources._kind_for("", "https://x/a.ttf"), "font")
        self.assertEqual(sources._kind_for("", "https://x/a.otf"), "font")
        self.assertEqual(sources._kind_for("font/woff2", "https://x/a"), "font")

    def test_font_bytes_are_dropped_without_want_fonts(self):
        """Mirrors the pre-existing `--images` gate: opt-in, since embedding
        real font files can be sizeable and most runs don't need them."""
        p = write_fixture(_font_har(), "x.har")
        bundle = sources.load_har(p)
        self.assertEqual(bundle.by_kind("font"), [])

    def test_font_bytes_are_kept_with_want_fonts(self):
        p = write_fixture(_font_har(), "x.har")
        bundle = sources.load_har(p, want_fonts=True)
        fonts = bundle.by_kind("font")
        self.assertEqual(len(fonts), 1)
        self.assertEqual(fonts[0].data, b"\x00fake-font-bytes")
        self.assertEqual(fonts[0].url, "https://example.com/a.woff2")

    def test_load_any_threads_want_fonts_through_to_load_har(self):
        p = write_fixture(_font_har(), "x.har")
        bundle = sources.load_any(p, want_fonts=True)
        self.assertEqual(len(bundle.by_kind("font")), 1)


class TestFetchBinaries(unittest.TestCase):
    """`fetch_binaries` -- only ever called for a live target, never a HAR
    (see its own docstring for why); network calls are mocked here so this
    stays a fast, offline test."""

    def test_data_uris_are_never_fetched(self):
        got = sources.fetch_binaries(["data:font/woff2;base64,AA=="])
        self.assertEqual(got, {})

    def test_a_failed_fetch_is_dropped_not_raised(self):
        """A report missing one weight's real preview is still useful; an
        error that kills the whole run over one broken font URL is not."""
        with mock.patch.object(sources, "_get", side_effect=OSError("boom")):
            got = sources.fetch_binaries(["https://example.com/broken.woff2"])
        self.assertEqual(got, {})

    def test_a_successful_fetch_is_returned_keyed_by_url(self):
        with mock.patch.object(
            sources, "_get", return_value=(b"\x00\x01", "font/woff2", "final")
        ):
            got = sources.fetch_binaries(["https://example.com/a.woff2"])
        self.assertEqual(got, {"https://example.com/a.woff2": b"\x00\x01"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
