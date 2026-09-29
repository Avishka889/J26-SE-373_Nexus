"""Install the pinned tools the impact stage runs, checked against their published hashes.

    uv run python -m c4.impact.tools install

Roseau is not a Python dependency: it is a release archive carrying its own
Java runtime. It is fetched once into `~/.cache/sdlc-c4/tools`, its sha256 is
compared with the one its release publishes before anything is unpacked, and
an archive that does not match is deleted rather than run.
"""

import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

from .api_diff import ROSEAU, ROSEAU_ARCHIVE, ROSEAU_SHA256, ROSEAU_URL, tools_directory


def install_roseau(directory: Path | None = None) -> Path:
    """Fetch, check and unpack Roseau; return its launcher."""
    target = directory or tools_directory()
    target.mkdir(parents=True, exist_ok=True)
    launcher = target / ROSEAU_ARCHIVE / "bin" / "roseau"
    if launcher.is_file():
        return launcher
    archive = target / f"{ROSEAU_ARCHIVE}.zip"
    if not archive.is_file():
        urllib.request.urlretrieve(ROSEAU_URL, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != ROSEAU_SHA256:
        archive.unlink()
        raise RuntimeError(f"{ROSEAU}'s archive hashes to {digest}, not {ROSEAU_SHA256}")
    with zipfile.ZipFile(archive) as unpacked:
        unpacked.extractall(target)
    for program in (target / ROSEAU_ARCHIVE / "bin").iterdir():
        program.chmod(0o755)
    return launcher


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args != ["install"]:
        print("usage: python -m c4.impact.tools install", file=sys.stderr)
        return 2
    print(f"{ROSEAU}: {install_roseau()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
