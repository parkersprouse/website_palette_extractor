#!/usr/bin/env python3
"""Build palettekit.pyz — the vendored, single-file zipapp.

A zipapp carries no dependency metadata, so `tinycss2` and `cssselect2`
(and tinycss2's own dependency, `webencodings`) have to be vendored into
the staging directory or the .pyz only works on a machine that happens
to have them installed already (PLAN.md T1). zipapp also refuses a
source tree that already has a top-level __main__.py, hence the shim.

    python3 build.py

Rebuild whenever anything under palettekit/ changes — CLAUDE.md's
"Rebuild the zipapp before a work session is finished" — and verify
with an interpreter that has neither dependency installed; every
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
OUTPUT = ROOT / "palettekit.pyz"

SHIM = (
    "import sys\n"
    "from palettekit.__main__ import main\n"
    "sys.exit(main())\n"
)

_NAME_SPLIT = re.compile(r"[<>=!~\[; ]")


def _dependencies() -> list[str]:
    """Read [project.dependencies] rather than hold a second copy here."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return data["project"]["dependencies"]


def _required_packages() -> tuple[str, ...]:
    """Every top-level package the archive must contain.

    Derived from [project.dependencies] rather than a second hardcoded
    list — otherwise a dependency added there gets vendored by pip but
    silently skipped by this check, the exact drift reading the
    dependency list from one place was meant to prevent. `webencodings`
    is the one name added by hand: it arrives as tinycss2's own
    transitive dependency and is never itself in pyproject.toml.
    """
    names = (_NAME_SPLIT.split(req, maxsplit=1)[0] for req in _dependencies())
    return ("palettekit", "webencodings", *names)


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
        if not any(n.startswith(f"{pkg}/") for n in names)
    ]
    if missing:
        raise RuntimeError(
            f"palettekit.pyz is missing vendored package(s): {missing}"
        )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="palettekit-build-") as tmp:
        stage = Path(tmp)
        shutil.copytree(ROOT / "palettekit", stage / "palettekit")
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
