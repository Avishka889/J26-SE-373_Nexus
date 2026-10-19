"""What the npm registry knows about one package.

The package document (`GET /{name}`) lists every published version, when each
was published, the `latest` tag, each version's tarball, and the repository the
package says it comes from. It has no changelog field, which is why release
notes are looked for elsewhere: in the repository's releases, or in a changelog
file inside the tarball.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from .fetch import Fetcher

REGISTRY = "https://registry.npmjs.org"


@dataclass(frozen=True)
class Repository:
    """A GitHub repository, and the package's directory in it for a monorepo."""

    owner: str
    name: str
    directory: str = ""

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"


@dataclass(frozen=True)
class NpmPackage:
    name: str
    versions: tuple[str, ...]
    latest: str | None
    published: dict[str, datetime]
    tarballs: dict[str, str]
    deprecated: dict[str, str]
    repository: Repository | None


@dataclass(frozen=True)
class NotFound:
    """Why the registry could not describe the package."""

    reason: str
    detail: str


_GITHUB = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s#]+?)(?:\.git)?(?:[/#].*)?$")


def github_repository(raw: object) -> Repository | None:
    """The GitHub repository a manifest's `repository` field points at, if any.

    Accepts the object form and the shorthands npm allows: `github:owner/repo`,
    a bare `owner/repo`, and the URL forms with `git+`, `git://` and `.git`.
    """
    directory = ""
    if isinstance(raw, dict):
        directory = str(raw.get("directory") or "")
        raw = raw.get("url")
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.startswith("github:"):
        text = "github.com/" + text.removeprefix("github:")
    elif re.fullmatch(r"[\w.-]+/[\w.-]+", text):
        text = "github.com/" + text
    found = _GITHUB.search(text)
    if found is None:
        return None
    return Repository(owner=found.group(1), name=found.group(2), directory=directory)


def _versions_in_order(document: dict) -> tuple[str, ...]:
    """Published versions in the order they were published, oldest first."""
    times = document.get("time") or {}
    versions = list((document.get("versions") or {}).keys())
    return tuple(sorted(versions, key=lambda v: (times.get(v) or "", v)))


async def fetch(fetcher: Fetcher, name: str) -> NpmPackage | NotFound:
    url = f"{REGISTRY}/{quote(name, safe='@')}"
    answer = await fetcher.get(url, registry="npm")
    if answer.status is None:
        return NotFound("registry-unreachable", f"the npm registry did not answer: {answer.error}")
    if answer.status in (404, 410):
        return NotFound("package-not-found", f"the npm registry has no package called {name}")
    if not answer.ok:
        return NotFound(
            "registry-unreachable", f"the npm registry answered {answer.status} for {name}"
        )
    try:
        document = json.loads(answer.body)
    except json.JSONDecodeError:
        return NotFound(
            "registry-unreachable", f"the npm registry sent something unreadable for {name}"
        )

    versions = document.get("versions") or {}
    times = document.get("time") or {}
    published = {}
    for version, stamp in times.items():
        if version in versions and isinstance(stamp, str):
            try:
                published[version] = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                continue
    latest_repository = None
    latest = (document.get("dist-tags") or {}).get("latest")
    if latest in versions:
        latest_repository = versions[latest].get("repository")
    return NpmPackage(
        name=name,
        versions=_versions_in_order(document),
        latest=latest,
        published=published,
        tarballs={
            version: body.get("dist", {}).get("tarball", "")
            for version, body in versions.items()
            if body.get("dist", {}).get("tarball")
        },
        deprecated={
            version: str(body["deprecated"])
            for version, body in versions.items()
            if body.get("deprecated")
        },
        repository=github_repository(document.get("repository") or latest_repository),
    )
