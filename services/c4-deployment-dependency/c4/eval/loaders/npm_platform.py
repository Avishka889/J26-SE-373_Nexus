"""The platform's own generated project, crossed with what its dependencies released since.

The client is a project C2 generated and C3 tested on this platform, frozen
under `studies/clients/`. Generated projects declare caret ranges and carry no
lockfile, so a fresh pin resolves every range to its newest release and the only
updates left are new majors. To see patches and minors as well, the tree is
reconstructed as it would have been installed on an earlier day (npm's
`--before`), and every direct dependency is crossed with up to three updates
from there, as the registry stands at capture: its newest patch, its newest
minor and its latest major (`crossings.targets`).

Each crossing is reproduced in the container lane with the steps staging uses
(`harness.steps.mern_steps`): a control run with the dependency held at the
installed version, and a candidate run with it held at the target, both from the
same reconstructed lockfile.
"""

import re
from dataclasses import dataclass

from ...harness.container import Lane
from ...harness.reproduce import Reproduction, reproduce
from ...harness.steps import mern_steps, with_smoke_script
from ...intake.lockfile import LOCKFILE, Pin
from ...intake.manifests import declared_dependencies
from ..cases import CaseClient, CaseUpdate, LabelledCase, Observed
from .clients import files_sha256, text_sha256
from .crossings import CrossingKind, Releases, targets


@dataclass(frozen=True)
class Crossing:
    package: str
    from_version: str
    to_version: str
    kind: CrossingKind
    #: The workspaces that declare the package, each of which the update moves.
    workspaces: tuple[str, ...]
    manifest_paths: tuple[str, ...]
    scope: str

    @property
    def case_id(self) -> str:
        slug = re.sub(r"[^a-z0-9.]+", "-", f"{self.package}-{self.from_version}-{self.to_version}")
        return f"platform-{slug.strip('-')}"


def crossings(files: dict[str, str], pinned: Pin, releases: dict[str, Releases]) -> list[Crossing]:
    """Every crossing the reconstructed tree admits, grouped across the workspaces that share it."""
    declared: dict[tuple[str, str], list] = {}
    for dependency in declared_dependencies(files):
        if dependency.ecosystem != "npm" or dependency.not_registry:
            continue
        workspace = dependency.manifest_path.removesuffix("package.json").rstrip("/")
        installed = pinned.resolved.get(workspace, {}).get(dependency.package)
        if installed is None:
            continue
        declared.setdefault((dependency.package, installed), []).append((workspace, dependency))

    found: list[Crossing] = []
    for (package, installed), where in sorted(declared.items()):
        if package not in releases:
            continue
        for kind, target in targets(installed, releases[package]).items():
            found.append(
                Crossing(
                    package=package,
                    from_version=installed,
                    to_version=target,
                    kind=kind,
                    workspaces=tuple(w for w, _ in where if w),
                    manifest_paths=tuple(d.manifest_path for _, d in where),
                    scope=where[0][1].scope,
                )
            )
    return found


def observe(
    lane: Lane, files: dict[str, str], crossing: Crossing, smoke_paths: list[str]
) -> Reproduction:
    """The control and candidate runs of one crossing, with the steps staging uses."""
    return reproduce(
        lane,
        with_smoke_script(files),
        package=crossing.package,
        old=crossing.from_version,
        new=crossing.to_version,
        steps=mern_steps(smoke_paths),
        workspaces=crossing.workspaces,
    )


def case_for(
    crossing: Crossing,
    reproduction: Reproduction,
    *,
    client: str,
    files: dict[str, str],
    pinned: Pin,
    pin_path: str,
    installed_on: str,
    toolchain: str,
    captured_at: str,
) -> LabelledCase:
    """The labelled case for one reproduced crossing; the level is the rubric's, at load time."""
    return LabelledCase(
        case_id=crossing.case_id,
        source="npm-platform",
        client=CaseClient(
            kind="platform",
            snapshot=f"studies/clients/{client}",
            snapshot_sha256=files_sha256({p: t for p, t in files.items() if p != LOCKFILE}),
        ),
        update=CaseUpdate(
            ecosystem="npm",
            package=crossing.package,
            from_version=crossing.from_version,
            to_version=crossing.to_version,
            manifest_paths=list(crossing.manifest_paths),
            scope=crossing.scope,
        ),
        source_change=crossing.kind,
        observed=Observed(
            method="container-reproduction",
            captured_at=captured_at,
            toolchain=toolchain,
            baseline=reproduction.baseline,
            candidate=reproduction.candidate,
            warnings=reproduction.warnings,
        ),
        frozen_inputs={pin_path: text_sha256(files[LOCKFILE])},
        provenance=(
            f"npm_platform loader: the generated client {client}, its tree reconstructed as "
            f"installed on {installed_on} ({pinned.record.resolved_by}), crossed with the "
            f"{crossing.kind} update the registry listed at capture"
        ),
    )
