"""The CLI: argument validation, exit codes, and what gets written.

`__main__.py` had no tests at all before this module, and every bug the
2026-08-03 sweep found in it was a *silent* one — a bad flag accepted and then
quietly doing something other than what it said, or a real failure arriving as
a traceback instead of the `error: …`/exit-code pair every other failure in
`main` uses. Those are exactly the failures a test suite that only ever calls
`extract()` cannot see.

`main()` is called directly rather than through a subprocess: it returns its
exit code instead of raising `SystemExit` for everything except argparse's own
usage errors, which is what makes that possible.
"""
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from website_palette_extractor import __main__ as cli

from .helpers import FIXTURE, write_fixture


def run(*argv: str) -> tuple[int, str, str]:
    """Call `main` with argv, returning (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestArgumentValidation(unittest.TestCase):
    """Bad options are rejected before any work, not absorbed silently."""

    def setUp(self):
        self.page = write_fixture(FIXTURE)
        self.out = tempfile.mkdtemp()

    def test_an_unknown_format_is_rejected_rather_than_dropped(self):
        """`--formats jsn` used to write nothing and still exit 0.

        The writer block matches format names with `in want`, so an
        unrecognised one simply never matched a branch: an empty output
        directory, an empty "wrote:" list, and a success code — which reads
        exactly like a site that legitimately has no colors.
        """
        code, _out, err = run(self.page, "--formats", "jsn", "-o", self.out)
        self.assertEqual(code, 2)
        self.assertIn("jsn", err)
        self.assertIn("json", err)          # the valid list is offered
        self.assertEqual(os.listdir(self.out), [])

    def test_an_empty_format_list_is_rejected(self):
        code, _out, err = run(self.page, "--formats", ",", "-o", self.out)
        self.assertEqual(code, 2)
        self.assertIn("--formats", err)

    def test_a_negative_limit_is_rejected_not_applied_backwards(self):
        """`--limit -5` reached `entries[:-5]` and trimmed from the *end*.

        A negative slice bound is valid Python and silently keeps everything
        but the last five tokens, so the palette came back smaller with no
        indication the flag had been misread.
        """
        code, _out, err = run(self.page, "--limit", "-5", "-o", self.out)
        self.assertEqual(code, 2)
        self.assertIn("--limit", err)

    def test_a_negative_merge_distance_is_rejected(self):
        code, _out, err = run(self.page, "--merge", "-1", "-o", self.out)
        self.assertEqual(code, 2)
        self.assertIn("--merge", err)

    def test_a_negative_min_score_is_rejected(self):
        code, _out, err = run(self.page, "--min-score", "-2", "-o", self.out)
        self.assertEqual(code, 2)
        self.assertIn("--min-score", err)

    def test_a_non_positive_timeout_is_rejected(self):
        code, _out, err = run(self.page, "--timeout", "0", "-o", self.out)
        self.assertEqual(code, 2)
        self.assertIn("--timeout", err)

    def test_a_valid_limit_of_zero_still_means_no_limit(self):
        """0 is the documented default and must stay accepted."""
        code, _out, _err = run(self.page, "--limit", "0", "--formats", "json",
                               "-o", self.out, "--quiet")
        self.assertEqual(code, 0)


class TestOutput(unittest.TestCase):
    """What a successful run writes, and how a failed write reports itself."""

    def setUp(self):
        self.page = write_fixture(FIXTURE)
        self.out = tempfile.mkdtemp()

    def test_each_requested_format_is_written_and_nothing_else(self):
        code, _out, _err = run(self.page, "--formats", "json,css", "-o",
                               self.out, "--quiet")
        self.assertEqual(code, 0)
        written = sorted(os.listdir(self.out))
        self.assertEqual(len(written), 2)
        self.assertTrue(any(f.endswith(".json") for f in written))
        self.assertTrue(any(f.endswith(".css") for f in written))

    def test_all_formats_write_six_files(self):
        code, _out, _err = run(self.page, "-o", self.out, "--quiet")
        self.assertEqual(code, 0)
        self.assertEqual(len(os.listdir(self.out)), 6)
        self.assertIn("index.html", os.listdir(self.out))

    def test_an_unwritable_output_directory_reports_rather_than_traces(self):
        """The one failure in `main` that used to end in a raw traceback.

        It also arrives *after* the whole extraction has run, so the cost of
        not reporting it cleanly is a user who cannot tell a permissions
        problem from a crash in the parser.
        """
        blocked = os.path.join(tempfile.mkdtemp(), "wall")
        # A regular file where the output directory should go: makedirs on a
        # path whose parent is a file raises the same OSError family as a
        # read-only mount, without needing one.
        with open(blocked, "w", encoding="utf-8") as fh:
            fh.write("x")
        code, _out, err = run(self.page, "--formats", "json",
                              "-o", os.path.join(blocked, "sub"))
        self.assertEqual(code, 2)
        self.assertIn("error:", err)

    def test_a_target_that_is_not_readable_exits_two(self):
        code, _out, err = run("/nonexistent/thing.xyz", "-o", self.out)
        self.assertEqual(code, 2)
        self.assertIn("error:", err)

    def test_list_sources_exits_without_writing(self):
        code, out, _err = run(self.page, "--list-sources", "-o", self.out)
        self.assertEqual(code, 0)
        self.assertIn("stylesheet", out)
        self.assertEqual(os.listdir(self.out), [])


class TestFormatsConstant(unittest.TestCase):
    """`FORMATS` and the writer block must not drift apart."""

    def test_every_advertised_format_actually_writes_a_file(self):
        """A name in `FORMATS` with no branch in `main` would be the same
        silent no-op the validator was added to prevent, just spelled
        correctly. Checked per format rather than in aggregate so the
        failure names the offender."""
        page = write_fixture(FIXTURE)
        for fmt in cli.FORMATS:
            with self.subTest(fmt=fmt):
                out = tempfile.mkdtemp()
                code, _o, _e = run(page, "--formats", fmt, "-o", out,
                                   "--quiet")
                self.assertEqual(code, 0)
                self.assertEqual(len(os.listdir(out)), 1,
                                 f"--formats {fmt} wrote nothing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
