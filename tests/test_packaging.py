"""The Python-floor constant against pyproject.toml's own requires-python."""
import tomllib
import unittest
from pathlib import Path

from palettekit import PYTHON_FLOOR


class TestPackaging(unittest.TestCase):
    def test_pyproject_floor_matches_python_floor(self):
        """PLAN.md T1/T2: one number, not two copies that can drift.

        __main__.main()'s version guard and build.py both read
        palettekit.PYTHON_FLOOR; this is what keeps that constant honest
        against pyproject.toml's requires-python instead of trusting
        whoever last bumped one of them to also bump the other.

        The exact-string comparison is deliberate, not a shortcut to
        replace with a version parse — this project writes exactly one
        floor string (">=3.11"), so matching it precisely is stricter
        than parsing would be.
        """
        root = Path(__file__).parent.parent
        data = tomllib.loads((root / "pyproject.toml").read_text())
        requires = data["project"]["requires-python"]
        self.assertEqual(requires, ">={}.{}".format(*PYTHON_FLOOR))


if __name__ == "__main__":
    unittest.main(verbosity=2)
