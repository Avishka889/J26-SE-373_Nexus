"""Clients frozen in this repository, read the same way by every loader.

A study client is a directory of text files under `studies/clients/`. What a
case records about it is its path there and one hash over its files, so a rerun
on a changed client is visible as a different hash rather than as a different
result nobody can explain.
"""

import hashlib
from pathlib import Path

#: Directories that are never part of a client, whatever a copy carried along.
_SKIPPED = frozenset({"node_modules", "dist", "target", ".git"})


def read_client(directory: Path) -> dict[str, str]:
    """Every file of the client, by its path relative to the client's directory."""
    files: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        if _SKIPPED.intersection(relative.split("/")[:-1]):
            continue
        files[relative] = path.read_text()
    return files


def files_sha256(files: dict[str, str]) -> str:
    """One hash over the paths and contents, independent of the order they were read in."""
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(files[path].encode()).hexdigest().encode())
        digest.update(b"\n")
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
