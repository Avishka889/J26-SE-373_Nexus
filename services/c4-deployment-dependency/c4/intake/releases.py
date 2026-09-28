"""The release notes between two versions, from wherever the project keeps them.

The npm registry has no changelog field and Maven Central has none either, so
notes are looked for where projects actually keep them, in this order:

1. **GitHub Releases** for the repository the registry names, one release per
   tag. Tags are matched to versions as projects write them: `v5.0.0`, `5.0.0`,
   and in a monorepo `name@5.0.0` or `name-v5.0.0`.
2. **A changelog file in the repository**: `CHANGELOG.md`, `HISTORY.md`,
   `History.md` or `CHANGES.md` at the root, or in the package's own directory
   for a monorepo, split into one section per release heading.
3. **A changelog file in the npm tarball**, for packages that ship one and keep
   no releases.

Only releases inside the window count: after the installed version (exclusive)
and up to the target (inclusive), ordered by the ecosystem's own rules. A
release outside the window describes a change the update does not make, and a
model quoting it would be quoting the wrong release; the changelog check refuses
such a quote, and this is where the window is decided.

Every text kept is returned with the path it will be stored at and the sha256
of exactly what was stored, because the changelog check has to run against the
text the model was shown. Missing notes are not an error: the update is still
analysed, and the changelog signal abstains and says why (decision 8).
"""

import base64
import gzip
import hashlib
import io
import json
import re
import tarfile
from dataclasses import dataclass, field
from typing import Literal

from sdlc_contracts import ReleaseNoteRef

from ..risk.notes import Section, render, split_changelog
from ..risk.semver_rule import is_upgrade
from .fetch import Fetcher
from .npm_registry import Repository

GITHUB_API = "https://api.github.com"

#: Enough for any release window in practice, and a ceiling on what one update
#: can cost the model call that reads it.
MAX_CHARS = 60_000

CHANGELOG_FILES = ("CHANGELOG.md", "HISTORY.md", "History.md", "CHANGES.md", "changelog.md")


@dataclass
class Notes:
    """What was found for one update, ready to store and to show a model."""

    sections: list[Section] = field(default_factory=list)
    refs: list[ReleaseNoteRef] = field(default_factory=list)
    texts: dict[str, str] = field(default_factory=dict)
    #: Why notes could not be read when a source refused to answer, so a limit
    #: is never reported as a release with no notes. Empty otherwise.
    unavailable: str = ""

    @property
    def found(self) -> bool:
        return bool(self.sections)


def in_window(ecosystem: Literal["npm", "maven"], version: str, old: str, new: str) -> bool:
    """After the installed version, up to and including the target."""
    return version == new or (
        is_upgrade(ecosystem, old, version) and is_upgrade(ecosystem, version, new)
    )


def tag_version(tag: str, package: str) -> str:
    """The version a release tag names, as projects write their tags."""
    text = tag.strip()
    short = package.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    for prefix in (f"{package}@", f"{short}@", f"{package}-v", f"{short}-v", f"{short}-"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.removeprefix("v").removeprefix("V")


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _limited(answer) -> bool:
    """GitHub's rate limit: a 403 or 429 whose body says so."""
    return answer.status in (403, 429) and b"rate limit" in answer.body.lower()


async def _github_releases(
    fetcher: Fetcher, repository: Repository, token: str | None
) -> tuple[list[dict], bool]:
    """Every release, newest first, and whether GitHub's rate limit cut the listing short."""
    releases: list[dict] = []
    for page in (1, 2, 3):
        answer = await fetcher.get(
            f"{GITHUB_API}/repos/{repository.owner}/{repository.name}/releases?per_page=100&page={page}",
            registry="github",
            headers=_headers(token),
        )
        if _limited(answer):
            return releases, True
        if not answer.ok:
            break
        batch = json.loads(answer.body)
        if not isinstance(batch, list) or not batch:
            break
        releases.extend(batch)
        if len(batch) < 100:
            break
    return releases, False


async def _repository_file(
    fetcher: Fetcher, repository: Repository, token: str | None
) -> tuple[tuple[str, str] | None, bool]:
    """The first changelog file the repository holds, and whether the rate limit stopped the look."""
    folders = [repository.directory, ""] if repository.directory else [""]
    for folder in folders:
        for name in CHANGELOG_FILES:
            path = f"{folder}/{name}".lstrip("/")
            answer = await fetcher.get(
                f"{GITHUB_API}/repos/{repository.owner}/{repository.name}/contents/{path}",
                registry="github",
                headers=_headers(token),
            )
            if _limited(answer):
                return None, True
            if not answer.ok:
                continue
            body = json.loads(answer.body)
            if isinstance(body, dict) and body.get("encoding") == "base64":
                text = base64.b64decode(body.get("content", "")).decode("utf-8", "replace")
                return (str(body.get("html_url") or path), text), False
    return None, False


async def _tarball_file(fetcher: Fetcher, tarball: str) -> tuple[str, str] | None:
    answer = await fetcher.get(tarball, registry="npm")
    if not answer.ok:
        return None
    try:
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(answer.body)), mode="r:") as archive:
            for member in archive.getmembers():
                name = member.name.split("/", 1)[-1]
                if name in CHANGELOG_FILES and member.isfile():
                    handle = archive.extractfile(member)
                    if handle is not None:
                        return f"{tarball}#{name}", handle.read().decode("utf-8", "replace")
    except (OSError, tarfile.TarError, EOFError):
        return None
    return None


def _keep(
    notes: Notes,
    sections: list[Section],
    *,
    source: Literal["github-release", "changelog-file", "migration-guide"],
    url: str,
    package: str,
) -> None:
    if not sections:
        return
    text = render(sections)
    truncated = len(text) > MAX_CHARS
    text = text[:MAX_CHARS]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", package)
    path = f"notes/{safe}/{source}-{sections[0].version}.md"
    notes.sections.extend(sections)
    notes.texts[path] = text
    notes.refs.append(
        ReleaseNoteRef(
            source=source,
            url=url,
            version=sections[0].version,
            path=path,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            chars=len(text),
            truncated=truncated,
        )
    )


async def release_notes(
    fetcher: Fetcher,
    *,
    ecosystem: Literal["npm", "maven"],
    package: str,
    old: str,
    new: str,
    repository: Repository | None,
    tarball: str | None = None,
    token: str | None = None,
) -> Notes:
    """The notes of every release in the window, newest first, from the first source that has any."""
    notes = Notes()

    def windowed(sections: list[Section]) -> list[Section]:
        kept = [s for s in sections if in_window(ecosystem, s.version, old, new)]
        return sorted(kept, key=lambda s: _order_key(ecosystem, s.version), reverse=True)

    limited = False
    if repository is not None:
        releases, limited = await _github_releases(fetcher, repository, token)
        from_releases = windowed(
            [
                Section(
                    tag_version(str(release.get("tag_name", "")), package),
                    str(release.get("body") or "").strip(),
                )
                for release in releases
                if str(release.get("body") or "").strip()
            ]
        )
        if from_releases:
            _keep(
                notes,
                from_releases,
                source="github-release",
                url=repository.url + "/releases",
                package=package,
            )
            return notes
        found = None
        if not limited:
            found, limited = await _repository_file(fetcher, repository, token)
        if found is not None:
            _keep(
                notes,
                windowed(split_changelog(found[1])),
                source="changelog-file",
                url=found[0],
                package=package,
            )
            if notes.found:
                return notes

    if tarball:
        found = await _tarball_file(fetcher, tarball)
        if found is not None:
            _keep(
                notes,
                windowed(split_changelog(found[1])),
                source="changelog-file",
                url=found[0],
                package=package,
            )
    if limited and not notes.found:
        notes.unavailable = (
            "GitHub answered with its rate limit, so the releases and the changelog it holds "
            "could not be read"
        )
    return notes


def oldest_first(ecosystem: Literal["npm", "maven"], versions: list[str]) -> list[str]:
    """Distinct versions in the ecosystem's own order, oldest first."""
    return sorted(set(versions), key=lambda version: _order_key(ecosystem, version))


def _order_key(ecosystem: Literal["npm", "maven"], version: str):
    """A sort key in the ecosystem's own order, with unreadable versions last."""
    from functools import cmp_to_key

    def compare(a: str, b: str) -> int:
        if a == b:
            return 0
        return 1 if is_upgrade(ecosystem, b, a) else -1

    return cmp_to_key(compare)(version)
