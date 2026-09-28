"""FR1 to FR3: the updates the registries offer, what is known about each, and what could not be analysed.

For every dependency a manifest declares:

1. A dependency no registry can answer about (a workspace package, a file or
   git reference, a Maven version managed elsewhere) is rejected, with why.
2. The installed version is the one the baseline pin resolved for npm, and the
   declared one for Maven, which has no lockfile. A version that cannot be
   determined is rejected rather than guessed.
3. The registry is asked for the package. Its answer, or its silence, is
   recorded; a package it does not have, or an installed version it does not
   list, is rejected with what it said.
4. Two candidates can exist: the newest release the declared range already
   admits, which is what an unpinned install would pick up without anyone
   asking, and the registry's latest. Each newer than the installed version
   becomes an update; when both exist the in-range one names the other.
5. Each update carries the version change as a fact, its flags, when the target
   was published, where its source lives, and the release notes inside its
   window, stored and hashed.

Rejections are first class: every one names its reason and a sentence a
developer can act on, and the study counts them as coverage (FR3).
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sdlc_contracts import (
    BaselinePin,
    DependencyUpdate,
    DependencyUpdates,
    RejectedUpdate,
    RejectionReason,
    update_id_for,
    update_key,
)
from univers.version_range import NpmVersionRange
from univers.versions import SemverVersion

from ..risk.semver_rule import SameRelease, is_upgrade, movement
from . import maven_central, npm_registry
from .fetch import Fetcher
from .lockfile import Pin, PinFailed
from .manifests import Declared, declared_dependencies
from .releases import release_notes

NPM_SCOPES = {"prod": "prod", "dev": "dev", "peer": "peer", "optional": "optional"}


@dataclass
class Detected:
    """What detection produced, before it becomes the report."""

    updates: list[DependencyUpdate] = field(default_factory=list)
    rejected: list[RejectedUpdate] = field(default_factory=list)
    up_to_date: list[str] = field(default_factory=list)
    texts: dict[str, str] = field(default_factory=dict)
    baseline: BaselinePin | None = None


def _reject(declared: Declared, reason: RejectionReason, detail: str, **versions) -> RejectedUpdate:
    return RejectedUpdate(
        package=declared.package,
        ecosystem=declared.ecosystem,
        manifest_path=declared.manifest_path,
        declared=declared.declared,
        reason=reason,
        detail=detail,
        **versions,
    )


def _workspace_of(manifest_path: str) -> str:
    return manifest_path.removesuffix("package.json").rstrip("/")


def _newest_in_range(versions: tuple[str, ...], declared: str, installed: str) -> str | None:
    """The newest stable release the declared range admits, if newer than installed."""
    try:
        admitted = NpmVersionRange.from_native(declared)
    except Exception:
        return None
    best: str | None = None
    for version in versions:
        try:
            parsed = SemverVersion(version)
        except Exception:
            continue
        if parsed.prerelease or parsed not in admitted:
            continue
        if is_upgrade("npm", installed, version) and (
            best is None or is_upgrade("npm", best, version)
        ):
            best = version
    return best


async def _npm(
    declared: Declared,
    installed: str,
    fetcher: Fetcher,
    token: str | None,
    out: Detected,
) -> None:
    package = await npm_registry.fetch(fetcher, declared.package)
    if isinstance(package, npm_registry.NotFound):
        out.rejected.append(
            _reject(declared, package.reason, package.detail, from_version=installed)
        )  # type: ignore[arg-type]
        return
    if installed not in package.versions:
        out.rejected.append(
            _reject(
                declared,
                "version-not-found",
                f"the installed version {installed} of {declared.package} is not one the npm "
                "registry lists, so there is nothing to compare it with",
                from_version=installed,
            )
        )
        return
    latest = package.latest
    in_range = _newest_in_range(package.versions, declared.declared, installed)
    candidates: list[tuple[str, str, str | None]] = []
    if in_range and in_range != latest:
        candidates.append(
            (
                in_range,
                "in-range",
                latest if latest and is_upgrade("npm", in_range, latest) else None,
            )
        )
    if latest and is_upgrade("npm", installed, latest):
        candidates.append((latest, "latest", None))
    if not candidates:
        out.up_to_date.append(declared.package)
        return
    for target, candidate, superseded in candidates:
        await _update(
            declared,
            installed,
            target,
            candidate=candidate,
            superseded_by=superseded,
            published=package.published.get(target),
            repository=package.repository,
            tarball=package.tarballs.get(target),
            fetcher=fetcher,
            token=token,
            out=out,
        )


async def _maven(declared: Declared, fetcher: Fetcher, token: str | None, out: Detected) -> None:
    installed = declared.declared
    if installed.startswith(("[", "(")):
        out.rejected.append(
            _reject(
                declared,
                "unresolvable-version",
                f"{declared.package} is declared as the range {installed}, and without a build "
                "there is no telling which version inside it is installed",
            )
        )
        return
    artifact = await maven_central.fetch(fetcher, declared.package)
    if isinstance(artifact, npm_registry.NotFound):
        out.rejected.append(
            _reject(declared, artifact.reason, artifact.detail, from_version=installed)
        )  # type: ignore[arg-type]
        return
    if installed not in artifact.versions:
        out.rejected.append(
            _reject(
                declared,
                "version-not-found",
                f"the declared version {installed} of {declared.package} is not one Maven Central "
                "lists, so there is nothing to compare it with",
                from_version=installed,
            )
        )
        return
    target = artifact.release
    if not target or not is_upgrade("maven", installed, target):
        out.up_to_date.append(declared.package)
        return
    await _update(
        declared,
        installed,
        target,
        candidate="latest",
        superseded_by=None,
        published=None,
        repository=artifact.repository,
        tarball=None,
        fetcher=fetcher,
        token=token,
        out=out,
    )


async def _update(
    declared: Declared,
    installed: str,
    target: str,
    *,
    candidate: str,
    superseded_by: str | None,
    published: datetime | None,
    repository,
    tarball: str | None,
    fetcher: Fetcher,
    token: str | None,
    out: Detected,
) -> None:
    try:
        moved = movement(declared.ecosystem, installed, target)
    except SameRelease:
        out.up_to_date.append(declared.package)
        return
    if moved.change == "downgrade":
        out.rejected.append(
            _reject(
                declared,
                "not-an-upgrade",
                f"the registry's {candidate} release of {declared.package}, {target}, is older than "
                f"the installed {installed}",
                from_version=installed,
                to_version=target,
            )
        )
        return
    key = update_key(declared.ecosystem, declared.package, installed, target)
    earlier = next((update for update in out.updates if update.key == key), None)
    if earlier is not None:
        # The same move declared by another manifest, as the generated projects
        # declare TypeScript and Vitest in both apps: one update, which says
        # where else it applies, rather than a second copy the report refuses.
        if declared.manifest_path not in (earlier.manifest_path, *earlier.also_declared_in):
            earlier.also_declared_in.append(declared.manifest_path)
        return
    notes = await release_notes(
        fetcher,
        ecosystem=declared.ecosystem,
        package=declared.package,
        old=installed,
        new=target,
        repository=repository,
        tarball=tarball,
        token=token,
    )
    out.texts.update(notes.texts)
    out.updates.append(
        DependencyUpdate(
            id=update_id_for(key),
            key=key,
            ecosystem=declared.ecosystem,
            package=declared.package,
            manifest_path=declared.manifest_path,
            manifest_line=declared.line,
            scope=declared.scope,  # type: ignore[arg-type]
            declared=declared.declared,
            from_version=installed,
            to_version=target,
            candidate=candidate,  # type: ignore[arg-type]
            superseded_by=superseded_by,
            change=moved.change,
            flags=list(moved.flags),
            published_at=published,
            repository_url=repository.url if repository else None,
            notes=notes.refs,
            notes_unavailable=notes.unavailable,
        )
    )


async def detect(
    files: dict[str, str],
    *,
    fetcher: Fetcher,
    pinner: Callable[[dict[str, str]], Pin],
    packages: list[str] | None = None,
    token: str | None = None,
) -> Detected:
    """Every update the registries offer for this project, and every one that could not be read."""
    out = Detected()
    everything = declared_dependencies(files)
    declared = [d for d in everything if packages is None or d.package in packages]

    resolved: dict[str, dict[str, str]] = {}
    pin_failure = ""
    # The whole tree, whatever this run looks at: the candidate is built from the
    # baseline lockfile (`npm ci` needs one), so a run scoped to one package, or to
    # none at all, still pins it. Found by the first live cloud run, scoped to none.
    if any(d.ecosystem == "npm" and not d.not_registry for d in everything):
        try:
            # In a thread: the pin is an npm install that can take minutes, and
            # run on the event loop it froze every route of the orchestrator
            # that hosts this, found on the live walkthrough.
            pinned = await asyncio.to_thread(pinner, files)
            out.baseline = pinned.record
            out.texts[pinned.record.lockfile_path] = pinned.text
            resolved = pinned.resolved
        except PinFailed as error:
            pin_failure = str(error)

    seen: set[tuple[str, str, str]] = set()
    for dependency in declared:
        if dependency.not_registry:
            out.rejected.append(
                _reject(dependency, "not-a-registry-dependency", dependency.not_registry)
            )
            continue
        if dependency.ecosystem == "maven":
            await _maven(dependency, fetcher, token, out)
            continue
        installed = resolved.get(_workspace_of(dependency.manifest_path), {}).get(
            dependency.package
        )
        if installed is None:
            detail = (
                f"the dependency tree could not be resolved ({pin_failure})"
                if pin_failure
                else f"the lockfile resolved no version of {dependency.package}"
            )
            out.rejected.append(_reject(dependency, "unresolvable-version", detail))
            continue
        marker = (dependency.package, installed, dependency.manifest_path)
        if marker in seen:
            continue
        seen.add(marker)
        await _npm(dependency, installed, fetcher, token, out)
    return out


def report(
    detected: Detected,
    fetcher: Fetcher,
    *,
    version: int,
    code_version: int,
    test_version: int,
    target: str,
    generated_at: datetime,
) -> DependencyUpdates:
    return DependencyUpdates(
        version=version,
        generated_at=generated_at,
        code_version=code_version,
        test_version=test_version,
        target=target,
        baseline=detected.baseline,
        updates=detected.updates,
        rejected=detected.rejected,
        up_to_date=sorted(set(detected.up_to_date)),
        queried=fetcher.queries,
    )
