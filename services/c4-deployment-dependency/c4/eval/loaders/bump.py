"""BUMP's breaking updates, as labelled cases.

BUMP (chains-project/bump, MIT) is 571 reproducible breaking dependency updates
from Maven projects: each record names the project, the breaking commit, the
dependency and both versions, what BUMP itself called the version change, and
the category of failure its reproduction observed. Every one is a positive, a
break that happened; negatives come from elsewhere.

What is recorded here is what BUMP observed: the control build at the previous
version passed, and the build with the update failed in the named way. Where a
failure's file and line are needed for Table 5 they come from running the
breaking image, one case at a time, which the reproduction harness does
separately; nothing here pulls an image.
"""

import json
import re
import subprocess
from pathlib import Path

from ..cases import CaseClient, CaseUpdate, FailureLocation, LabelledCase, Observed, ObservedStep

#: The step each BUMP category was observed at.
STEP_FOR = {
    "COMPILATION_FAILURE": "compile",
    "WERROR_FAILURE": "compile",
    "TEST_FAILURE": "test",
    "DEPENDENCY_RESOLUTION_FAILURE": "resolution",
    "DEPENDENCY_LOCK_FAILURE": "resolution",
    "ENFORCER_FAILURE": "build",
}


def case_from_record(record: dict, *, dataset_commit: str, captured_at: str) -> LabelledCase:
    dependency = record["updatedDependency"]
    category = record["failureCategory"]
    breaking = record["breakingCommit"]
    image = str(record.get("breakingUpdateReproductionCommand", "")).split()[-1:] or [""]
    return LabelledCase(
        case_id=f"bump-{breaking[:12]}",
        source="bump",
        client=CaseClient(
            kind="github",
            repo_url=f"https://github.com/{record['projectOrganisation']}/{record['project']}",
            commit=breaking,
            image=image[0],
        ),
        update=CaseUpdate(
            ecosystem="maven",
            package=f"{dependency['dependencyGroupID']}:{dependency['dependencyArtifactID']}",
            from_version=dependency["previousVersion"],
            to_version=dependency["newVersion"],
            scope=dependency.get("dependencyScope", ""),
        ),
        source_change=dependency.get("versionUpdateType", ""),
        observed=Observed(
            method="bump-recorded",
            captured_at=captured_at,
            toolchain=f"Java {record.get('javaVersionUsedForReproduction', '')}".strip(),
            baseline=[
                ObservedStep(
                    name="compile",
                    command=str(record.get("preCommitReproductionCommand", "")),
                    outcome="passed",
                )
            ],
            candidate=[
                ObservedStep(
                    name=STEP_FOR.get(category, "build"),  # type: ignore[arg-type]
                    command=str(record.get("breakingUpdateReproductionCommand", "")),
                    outcome="failed",
                )
            ],
            failure_category=category,
        ),
        provenance=(
            f"BUMP (chains-project/bump, MIT) data/benchmark/{breaking}.json at {dataset_commit}"
        ),
    )


def dataset_version(checkout: Path) -> tuple[str, str]:
    """The checkout's commit and that commit's date.

    The date is when BUMP's observations became what this checkout holds, so it
    is the capture date of every case read from it. Using the day the records
    were read instead would give the same records a new corpus hash every day.
    """
    done = subprocess.run(
        ["git", "-C", str(checkout), "log", "-1", "--format=%H %cs"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit, day = done.stdout.split()
    return commit, day


def load_checkout(checkout: Path) -> list[LabelledCase]:
    """Every record in a git checkout of BUMP, stamped with the checkout's commit and date."""
    commit, day = dataset_version(checkout)
    return load_directory(checkout / "data" / "benchmark", dataset_commit=commit, captured_at=day)


def load_directory(directory: Path, *, dataset_commit: str, captured_at: str) -> list[LabelledCase]:
    """Every record in a checkout of BUMP's `data/benchmark` directory."""
    return [
        case_from_record(
            json.loads(path.read_text()), dataset_commit=dataset_commit, captured_at=captured_at
        )
        for path in sorted(directory.glob("*.json"))
    ]


#: A javac error as Maven prints it: `[ERROR] /work/dir/path/A.java:[43,47] message`.
_COMPILER_ERROR = re.compile(
    r"^\[ERROR\] (?P<path>/\S+?\.java):\[(?P<line>\d+),\d+\]", re.MULTILINE
)


def failure_locations(log: str, *, workdir: str) -> list[FailureLocation]:
    """The files and lines a breaking image's compiler reported, each once, in order.

    `workdir` is the image's working directory, stripped so the paths are the
    project's own, as the impact report names them.
    """
    prefix = workdir.rstrip("/") + "/"
    seen: dict[tuple[str, int], FailureLocation] = {}
    for match in _COMPILER_ERROR.finditer(log):
        path = match.group("path").removeprefix(prefix)
        line = int(match.group("line"))
        seen.setdefault((path, line), FailureLocation(path=path, line=line))
    return list(seen.values())
