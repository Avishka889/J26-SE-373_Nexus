"""Failure locations from BUMP's breaking images: read once, one image at a time, and only javac's.

`docker` is scripted: the pull, the working directory, the run's log and the
removal are answers written here, so what is checked is what the command does
with them, not what a registry happens to serve today.
"""

import json
from pathlib import Path

from c4.eval.loaders.bump import case_from_record
from c4.eval.locations import run_over

IMAGE = "ghcr.io/chains-project/breaking-updates:" + "d" * 40 + "-breaking"
LOG = """[INFO] Compiling 12 source files
[ERROR] /arex-agent-java/arex-instrumentation/dubbo/src/main/java/io/arex/Dubbo.java:[43,47] cannot find symbol
[ERROR] /arex-agent-java/arex-instrumentation/dubbo/src/main/java/io/arex/Dubbo.java:[43,47] cannot find symbol
[ERROR] /arex-agent-java/arex-core/src/main/java/io/arex/Core.java:[9,1] incompatible types
[INFO] BUILD FAILURE
"""


def _case(tmp_path: Path, commit: str, category: str) -> Path:
    record = {
        "breakingCommit": commit,
        "project": "arex-agent-java",
        "projectOrganisation": "arextest",
        "failureCategory": category,
        "breakingUpdateReproductionCommand": f"docker run {IMAGE}",
        "updatedDependency": {
            "dependencyGroupID": "org.apache.dubbo",
            "dependencyArtifactID": "dubbo",
            "previousVersion": "2.7.3",
            "newVersion": "2.7.21",
            "versionUpdateType": "patch",
        },
    }
    case = case_from_record(record, dataset_commit="c", captured_at="2024-01-01")
    path = tmp_path / f"{case.case_id}.json"
    path.write_text(json.dumps(case.model_dump(by_alias=True, mode="json")))
    return path


class Docker:
    def __init__(self, log: str = LOG) -> None:
        self.log = log
        self.asked: list[str] = []

    def __call__(self, command: list[str], timeout: float) -> tuple[int, str]:
        self.asked.append(" ".join(command[:2]))
        if command[1] == "image":
            return 0, "/arex-agent-java\n"
        if command[1] == "run":
            return 1, self.log
        return 0, ""


def test_a_compile_failure_gets_javacs_files_and_lines_once_each(tmp_path) -> None:
    path = _case(tmp_path, "a" * 40, "COMPILATION_FAILURE")
    docker = Docker()

    counts = run_over(tmp_path, limit=None, run=docker, log=lambda *a, **k: None)

    assert counts == {"located": 1, "no-compiler-error": 0, "failed": 0}
    body = json.loads(path.read_text())
    assert body["observed"]["failureLocations"] == [
        {"path": "arex-instrumentation/dubbo/src/main/java/io/arex/Dubbo.java", "line": 43},
        {"path": "arex-core/src/main/java/io/arex/Core.java", "line": 9},
    ]
    assert len(body["observed"]["candidate"][0]["logSha256"]) == 64
    assert "failure locations read from running" in body["provenance"]
    # One image at a time: pulled, read, removed.
    assert docker.asked == ["docker pull", "docker image", "docker run", "docker rmi"]


def test_a_located_case_is_not_run_again(tmp_path) -> None:
    _case(tmp_path, "a" * 40, "COMPILATION_FAILURE")
    run_over(tmp_path, limit=None, run=Docker(), log=lambda *a, **k: None)
    again = Docker()

    counts = run_over(tmp_path, limit=None, run=again, log=lambda *a, **k: None)

    assert counts["located"] == 0 and again.asked == []


def test_a_test_failure_is_not_guessed_at(tmp_path) -> None:
    _case(tmp_path, "b" * 40, "TEST_FAILURE")
    docker = Docker()
    assert run_over(tmp_path, limit=None, run=docker, log=lambda *a, **k: None)["located"] == 0
    assert docker.asked == []


def test_a_run_that_names_no_compiler_error_leaves_the_case_as_it_was(tmp_path) -> None:
    path = _case(tmp_path, "c" * 40, "COMPILATION_FAILURE")
    before = path.read_text()

    counts = run_over(
        tmp_path, limit=None, run=Docker(log="[INFO] BUILD SUCCESS\n"), log=lambda *a, **k: None
    )

    assert counts["no-compiler-error"] == 1 and path.read_text() == before
