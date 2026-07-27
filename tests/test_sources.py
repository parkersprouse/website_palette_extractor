"""load_har / load_url / load_paths error handling."""
import unittest

from palettekit import sources

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
