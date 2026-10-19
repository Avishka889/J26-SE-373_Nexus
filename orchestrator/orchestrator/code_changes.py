"""What changed between two code versions, file by file.

The code review showed the files of the version under review and nothing of
what changed since the one before (review item C2-8). Both versions are whole
file sets in the file store, so the difference is computed here, from what was
stored, rather than asked of a repository that may not be connected.
"""

import difflib
from typing import Any

#: A file's diff past this many lines is cut, and says so: the review is read
#: by a person, and a regenerated lockfile is not what they came to read.
MAX_DIFF_LINES = 400


def changes_between(before: dict[str, str], after: dict[str, str]) -> list[dict[str, Any]]:
    """Every file added, removed or changed, by path, with its unified diff.

    The counts are of the whole change, whatever the diff shown was cut to.
    """
    changed: list[dict[str, Any]] = []
    for path in sorted({*before, *after}):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        lines = [
            line.rstrip("\n")
            for line in difflib.unified_diff(
                (old or "").splitlines(keepends=True),
                (new or "").splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=3,
            )
        ]
        body = [line for line in lines if not line.startswith(("---", "+++"))]
        changed.append(
            {
                "path": path,
                "status": "added" if old is None else "removed" if new is None else "changed",
                "additions": sum(1 for line in body if line.startswith("+")),
                "deletions": sum(1 for line in body if line.startswith("-")),
                "diff": "\n".join(lines[:MAX_DIFF_LINES]),
                "truncated": len(lines) > MAX_DIFF_LINES,
            }
        )
    return changed
