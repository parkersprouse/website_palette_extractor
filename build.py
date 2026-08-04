#!/usr/bin/env python3
"""Build website_palette_extractor.pyz — the vendored, single-file zipapp.

A zipapp carries no dependency metadata, so every runtime dependency —
`tinycss2`, `cssselect2` and `html5lib`, plus the two transitive ones
they pull in, `webencodings` and `six` — has to be vendored into the
staging directory, or the .pyz only works on a machine that happens to
have them installed already (PLAN.md T1). zipapp also refuses a source
tree that already has a top-level __main__.py, hence the shim.

    python3 build.py

Rebuild whenever anything under website_palette_extractor/ changes — CLAUDE.md's
"Rebuild the zipapp before a work session is finished" — and verify
with an interpreter that has none of the dependencies installed; every
interpreter on a dev machine has them, which is exactly what let the
tracked artifact go four phases stale before (PLAN.md T1).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipapp
import zipfile
from pathlib import Path

# uv is preferred (this project's own tooling, and CLAUDE.md's documented
# incantation uses it), but a uv-managed venv's own interpreter has no `pip`
# module of its own, so `sys.executable -m pip` cannot be the only path.
# Which one actually runs is environment-dependent, so a build made without
# uv on PATH may resolve marginally different wheel versions than one with
# it — both still honor the >= constraints, so this doesn't affect output.
_UV = shutil.which("uv")

ROOT = Path(__file__).parent.resolve()

# The import package name, in one place. Everything else here that mentions the
# project by name is derived from it, because the pieces that would break on a
# half-rename break *silently*: `SHIM` is a string compiled only when the built
# .pyz runs, so a stale import inside it passes `_verify`, passes any smoke test
# on the build machine (the old package is still importable there), and fails
# only on a clean interpreter — verbatim the T1 failure this file exists to
# prevent. Renamed from `palettekit` on 2026-08-03.
PACKAGE = "website_palette_extractor"
OUTPUT = ROOT / f"{PACKAGE}.pyz"

SHIM = (
    "import sys\n"
    f"from {PACKAGE}.__main__ import main\n"
    "sys.exit(main())\n"
)

_NAME_SPLIT = re.compile(r"[<>=!~\[; ]")


def _dependencies() -> list[str]:
    """Read [project.dependencies] rather than hold a second copy here."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return data["project"]["dependencies"]


def _required_packages() -> tuple[str, ...]:
    """Every top-level importable name the archive must contain.

    Derived from [project.dependencies] rather than a second hardcoded
    list — otherwise a dependency added there gets vendored by pip but
    silently skipped by this check, the exact drift reading the
    dependency list from one place was meant to prevent.

    Two names are added by hand because they are *transitive* and so never
    appear in pyproject.toml: `webencodings` (tinycss2's) and `six`
    (html5lib's). Both are imported at runtime, so a .pyz missing either
    one fails on a clean interpreter exactly like a missing direct
    dependency — which is the whole failure `_verify` exists to catch.
    """
    names = (_NAME_SPLIT.split(req, maxsplit=1)[0] for req in _dependencies())
    return (PACKAGE, "webencodings", "six", *names)


# emit.py reads this at runtime via importlib.resources, not a path relative
# to __file__ -- the latter would work in the checkout and in site-packages
# and fail only inside this archive, where the package lives in a zip and
# there's no filesystem path to open(). shutil.copytree in main() below
# already carries the file into the staging dir with everything else under
# website_palette_extractor/, so this is belt-and-suspenders the same way
# the six.py story below is: the archive *could* lose a non-.py file to some
# future staging change without any of the dependency-vendoring checks
# noticing, since none of them look inside PACKAGE itself.
_REQUIRED_DATA_FILES = (f"{PACKAGE}/report_template.html",)


def _verify() -> None:
    """Structural check, not a subprocess smoke test.

    Running the built .pyz on this interpreter would pass whether or not
    vendoring happened — site-packages is still on sys.path, and a dev
    machine has these installed regardless. Asserting the packages are
    physically inside the archive is what actually catches a skipped
    vendoring step.
    """
    names = zipfile.ZipFile(OUTPUT).namelist()
    missing = [
        pkg for pkg in _required_packages()
        # A top-level dependency may be vendored either as a package
        # directory (`tinycss2/…`) or as a single module (`six.py`), and
        # checking only for the directory form made the module form
        # permanently undetectable: `six` could vanish from the archive and
        # this check would still pass, leaving a .pyz that imports fine here
        # and dies on `import six` anywhere else. That is precisely the
        # failure a structural check is here to catch instead of a smoke
        # test, so it has to accept both shapes.
        if not any(n == f"{pkg}.py" or n.startswith(f"{pkg}/") for n in names)
    ]
    missing += [f for f in _REQUIRED_DATA_FILES if f not in names]
    if missing:
        raise RuntimeError(
            f"{OUTPUT.name} is missing vendored dependency/dependencies: "
            f"{missing}"
        )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="wpe-build-") as tmp:
        stage = Path(tmp)
        shutil.copytree(ROOT / PACKAGE, stage / PACKAGE)
        (stage / "__main__.py").write_text(SHIM, encoding="utf-8")

        install = (
            [_UV, "pip", "install", "--quiet", "--target", str(stage),
             *_dependencies()] if _UV else
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--target", str(stage), *_dependencies()]
        )
        subprocess.run(install, check=True)

        # __pycache__/*.dist-info are the metadata pip/uv leave behind; .lock
        # is uv's own install-lock marker. None of the three are code.
        for pattern in ("__pycache__", "*.dist-info"):
            for path in stage.rglob(pattern):
                shutil.rmtree(path, ignore_errors=True)
        lock = stage / ".lock"
        if lock.exists():
            lock.unlink()

        if OUTPUT.exists():
            OUTPUT.unlink()
        zipapp.create_archive(
            stage, target=OUTPUT, interpreter="/usr/bin/env python3",
        )

    _verify()
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
