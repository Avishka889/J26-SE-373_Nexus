"""Whether this machine has the JDK the Java sample is compiled with.

`shutil.which("javac")` was the guard until 2026-09-27, and it asks the wrong
question. CI has a JDK; it had JDK 17, and the sample sets
`maven.compiler.release` to 21. So nothing skipped, four tests ran, and all four
failed inside Maven with a hundred and eighty lines of download log around

    error: release version 21 not supported

which says what happened three layers below the thing that is actually wrong.
A guard that checks presence when the requirement is a version reports a
mismatch as a fault in the code under test.

The required version is read from the sample's own `pom.xml` rather than written
here, so the guard cannot drift from what it guards.
"""

import re
import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest

SAMPLE_POM = Path(__file__).resolve().parents[1] / "fixtures" / "java-sample" / "pom.xml"

_RELEASE = re.compile(r"<maven\.compiler\.release>\s*(\d+)\s*</maven\.compiler\.release>")
_VERSION = re.compile(r"(\d+)")


@cache
def required() -> int:
    """The release the sample is compiled at, from the sample."""
    found = _RELEASE.search(SAMPLE_POM.read_text()) if SAMPLE_POM.is_file() else None
    return int(found.group(1)) if found else 21


@cache
def installed() -> int | None:
    """The major version of the `javac` on PATH, or nothing if there is none.

    `javac`, not `java`: a JRE runs the wrapper and cannot compile the sample,
    which is the distinction the original guard was right about and kept.
    """
    if shutil.which("javac") is None:
        return None
    try:
        done = subprocess.run(
            ["javac", "-version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    found = _VERSION.search(f"{done.stdout} {done.stderr}")
    return int(found.group(1)) if found else None


def _why() -> str:
    have = installed()
    if have is None:
        return f"needs a JDK {required()}, and there is no javac on PATH"
    return f"needs a JDK {required()} to compile the sample, and javac here is {have}"


#: Skips when the sample cannot be compiled, and says which version was missing.
needs_jdk = pytest.mark.skipif(
    installed() is None or installed() < required(),  # type: ignore[operator]
    reason=_why(),
)
