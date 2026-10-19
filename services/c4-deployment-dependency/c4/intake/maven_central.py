"""What Maven Central knows about one artifact.

`maven-metadata.xml` lists the published versions and names the latest release.
The POM of a version says where the source lives, in its `scm` block, which is
how release notes are found for a Maven artifact. Nothing here builds anything:
Central is read, never resolved against.
"""

import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass

from .fetch import Fetcher
from .npm_registry import NotFound, Repository, github_repository

CENTRAL = "https://repo1.maven.org/maven2"

_POM = "{http://maven.apache.org/POM/4.0.0}"


@dataclass(frozen=True)
class MavenArtifact:
    group: str
    artifact: str
    versions: tuple[str, ...]
    release: str | None
    repository: Repository | None


def _path(group: str, artifact: str) -> str:
    return f"{CENTRAL}/{group.replace('.', '/')}/{artifact}"


def _scm_repository(pom: bytes) -> Repository | None:
    try:
        root = ElementTree.fromstring(pom)
    except ElementTree.ParseError:
        return None
    for path in (f"{_POM}scm/{_POM}url", f"{_POM}scm/{_POM}connection", f"{_POM}url"):
        element = root.find(path)
        if element is not None and element.text:
            found = github_repository(element.text.strip().removeprefix("scm:git:"))
            if found is not None:
                return found
    return None


async def fetch(fetcher: Fetcher, coordinates: str) -> MavenArtifact | NotFound:
    group, _, artifact = coordinates.partition(":")
    if not group or not artifact:
        return NotFound("package-not-found", f"{coordinates} is not a groupId:artifactId pair")
    answer = await fetcher.get(
        f"{_path(group, artifact)}/maven-metadata.xml", registry="maven-central"
    )
    if answer.status is None:
        return NotFound("registry-unreachable", f"Maven Central did not answer: {answer.error}")
    if answer.status in (404, 410):
        return NotFound("package-not-found", f"Maven Central has no artifact {coordinates}")
    if not answer.ok:
        return NotFound(
            "registry-unreachable", f"Maven Central answered {answer.status} for {coordinates}"
        )
    try:
        root = ElementTree.fromstring(answer.body)
    except ElementTree.ParseError:
        return NotFound(
            "registry-unreachable", f"Maven Central sent unreadable metadata for {coordinates}"
        )

    versioning = root.find("versioning")
    listed = versioning.find("versions") if versioning is not None else None
    versions = tuple(
        (element.text or "").strip()
        for element in (list(listed) if listed is not None else [])
        if (element.text or "").strip()
    )
    release_element = versioning.find("release") if versioning is not None else None
    release = (release_element.text or "").strip() if release_element is not None else None

    repository = None
    newest = release or (versions[-1] if versions else None)
    if newest:
        pom = await fetcher.get(
            f"{_path(group, artifact)}/{newest}/{artifact}-{newest}.pom", registry="maven-central"
        )
        if pom.ok:
            repository = _scm_repository(pom.body)
    return MavenArtifact(
        group=group,
        artifact=artifact,
        versions=versions,
        release=release or None,
        repository=repository,
    )
