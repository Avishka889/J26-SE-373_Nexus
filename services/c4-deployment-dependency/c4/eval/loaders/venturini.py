"""Venturini et al.'s manifesting breaking changes in npm, as labelled cases.

Daniel Venturini, Filipe Roseiro Cogo, Igor Scaliante Wiese, Ivanilton Polato and
Marco Aurelio Gerosa, "I depended on you and you broke me: An empirical study of
manifesting breaking changes in client packages", TOSEM 32(4), 2023. Their
replication package, doi:10.5281/zenodo.5558085 (published 2020-11-10), is
licensed CC BY 4.0, which permits this reuse with this attribution. It lists 64
breaking changes that manifested in 44 npm client packages when a provider
released a new version.

What is recorded is what the authors observed: the client's tests passed with
the provider's earlier release and failed with the release that introduced the
break. Nothing here re-runs a client, many of which are years old; like BUMP's,
these are recorded breaks, and every one is a positive.

**Only the cases this study's model can hold are read.** A direct dependency
(`impacted_by` explicit: a transitive break is not an update of anything the
client declares), one provider, and a minor or patch release by the dataset's
own reading. Eight of the sixty-four are; the rest are counted and not read.

**The version before the break is not in the dataset.** It is read from the
registry: the provider's newest release below the one that broke, in the same
major line, at load.

The dataset is fetched once into a cache outside the repository:

    mkdir -p ~/.cache/sdlc-c4/venturini && cd ~/.cache/sdlc-c4/venturini
    curl -sSfLO "https://zenodo.org/records/5558085/files/breaking-changes-cases.json"
    curl -sSfLO "https://zenodo.org/records/5558085/files/clients.csv"
"""

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import semver

from ..cases import CaseClient, CaseUpdate, LabelledCase, Observed, ObservedStep

RECORD = "doi:10.5281/zenodo.5558085"
PUBLISHED = "2020-11-10"
CITATION = (
    "Venturini, Cogo, Wiese, Polato and Gerosa, TOSEM 32(4), 2023; replication package "
    f"{RECORD} (CC BY 4.0)"
)


@dataclass(frozen=True)
class Skipped:
    """A case the study's model cannot hold, and why."""

    client: str
    provider: str
    reason: str


def _stable(version: str) -> semver.Version | None:
    try:
        parsed = semver.Version.parse(version)
    except ValueError:
        return None
    return None if parsed.prerelease else parsed


def previous_release(introduced: str, versions: list[str]) -> str | None:
    """The newest stable release below `introduced`, in its major line."""
    target = _stable(introduced)
    if target is None:
        return None
    earlier = [
        parsed
        for parsed in (_stable(version) for version in versions)
        if parsed is not None and parsed < target and parsed.major == target.major
    ]
    return str(max(earlier)) if earlier else None


def _split_spec(spec: str) -> tuple[str, str] | None:
    """`name@version` into its parts; a scoped name keeps its leading `@`."""
    name, _, version = spec.rpartition("@")
    return (name, version) if name and version else None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-")


def usable(record: dict) -> str | None:
    """Why a record cannot be read as a direct, non-major update, or None when it can."""
    if record.get("impacted_by") != "explicit":
        return "transitive: not an update of a declared dependency"
    if ";" in record.get("provider_name", ""):
        return "more than one provider"
    if record.get("semver_introduce") not in ("minor", "patch"):
        return f"a {record.get('semver_introduce')} release, not minor or patch"
    if not _split_spec(record.get("provider_version_introduced", "")) or not _split_spec(
        record.get("client_version_introduced", "")
    ):
        return "no version given"
    return None


def load(
    cases_json: Path, clients_csv: Path | None, releases: dict[str, list[str]]
) -> tuple[list[LabelledCase], list[Skipped]]:
    """Every usable case, and every other one with its reason.

    `releases` maps a provider to the versions its registry lists, so the release
    before the break can be read; a provider missing from it is skipped, saying so.
    """
    raw = cases_json.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    urls: dict[str, str] = {}
    if clients_csv is not None and clients_csv.exists():
        with clients_csv.open(newline="") as handle:
            for row in csv.DictReader(handle):
                urls[row["name"].split("--")[0]] = row.get("url", "")
    cases: list[LabelledCase] = []
    skipped: list[Skipped] = []
    for client_name, records in sorted(json.loads(raw).items()):
        for record in records:
            provider = record.get("provider_name", "")
            reason = usable(record)
            if reason is not None:
                skipped.append(Skipped(client_name, provider, reason))
                continue
            package, introduced = _split_spec(record["provider_version_introduced"])  # type: ignore[misc]
            client_package, client_version = _split_spec(record["client_version_introduced"])  # type: ignore[misc]
            if package not in releases:
                skipped.append(Skipped(client_name, provider, "the registry was not read"))
                continue
            before = previous_release(introduced, releases[package])
            if before is None:
                skipped.append(
                    Skipped(client_name, provider, f"no earlier release of {introduced}'s line")
                )
                continue
            detail = (
                f"category {record.get('category', '')}; documented by "
                f"{record.get('documentation', '')}; fixed by {record.get('fixed_by', '')}"
            )
            cases.append(
                LabelledCase(
                    case_id=f"venturini-{_slug(client_package)}-{_slug(package)}-{introduced}",
                    source="npm-venturini",
                    client=CaseClient(
                        kind="npm-package",
                        repo_url=urls.get(client_package, ""),
                        package_spec=f"{client_package}@{client_version}",
                    ),
                    update=CaseUpdate(
                        ecosystem="npm",
                        package=package,
                        from_version=before,
                        to_version=introduced,
                        manifest_paths=["package.json"],
                    ),
                    source_change=record["semver_introduce"],
                    observed=Observed(
                        method="venturini-recorded",
                        captured_at=PUBLISHED,
                        toolchain="as the authors ran each client's tests",
                        baseline=[
                            ObservedStep(
                                name="test",
                                command=f"the client's tests with {package}@{before}",
                                outcome="passed",
                            )
                        ],
                        candidate=[
                            ObservedStep(
                                name="test",
                                command=f"the client's tests with {package}@{introduced}",
                                outcome="failed",
                                tail=detail,
                            )
                        ],
                    ),
                    frozen_inputs={f"{RECORD}/breaking-changes-cases.json": sha},
                    provenance=(
                        f"{CITATION}: {client_package}@{client_version} broke when {package} "
                        f"released {introduced}; the release before it, {before}, read from "
                        "the registry at load"
                    ),
                )
            )
    return cases, skipped
