"""A disk cache for what the registries and release pages answered.

An evaluation rerun has to read the same release notes and the same version
lists the first run read, or two epochs differ for reasons that have nothing to
do with the engine. So every answer can be kept, keyed by the URL it came from,
with the time it was first retrieved. A cached answer reports that time, not the
time it was read back: a quote verified against notes fetched last month was
verified against last month's notes, and the record says so.

No directory means no cache, which is what the tests and a one-off run use.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class Cached:
    body: bytes
    status: int
    retrieved_at: datetime


class Cache:
    def __init__(self, root: Path | None) -> None:
        self._root = root

    @property
    def root(self) -> Path | None:
        """Where answers are kept, or None when nothing is."""
        return self._root

    def _paths(self, url: str) -> tuple[Path, Path] | None:
        if self._root is None:
            return None
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        folder = self._root / key[:2]
        return folder / f"{key}.body", folder / f"{key}.json"

    def get(self, url: str) -> Cached | None:
        paths = self._paths(url)
        if paths is None or not paths[0].exists() or not paths[1].exists():
            return None
        meta = json.loads(paths[1].read_text())
        return Cached(
            body=paths[0].read_bytes(),
            status=int(meta["status"]),
            retrieved_at=datetime.fromisoformat(meta["retrievedAt"]),
        )

    def put(self, url: str, body: bytes, status: int) -> Cached:
        retrieved = datetime.now(UTC)
        paths = self._paths(url)
        if paths is not None:
            paths[0].parent.mkdir(parents=True, exist_ok=True)
            paths[0].write_bytes(body)
            paths[1].write_text(
                json.dumps({"url": url, "status": status, "retrievedAt": retrieved.isoformat()})
            )
        return Cached(body=body, status=status, retrieved_at=retrieved)
