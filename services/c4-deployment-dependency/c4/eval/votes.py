"""Every signal's vote on every case, computed once, kept, and read by every arm.

    uv run python -m c4.eval.votes --cases studies/cases/seed --split dev --out studies/votes/NAME.json

An arm is a way of combining votes, so the votes are what is recorded, one per
signal per case, with what each rests on; the arms of a table are then computed
from that record and never by running a signal again. The usage vote is the
product's own: the case's client is indexed and searched by the impact stage,
over the API diff of the update's two releases.

**The clients.** A case on a client frozen in this repository reads it from
`studies/clients/`, with the lockfile the case recorded. A BUMP case reads its
project at the breaking commit: fetched once, at exactly that commit, into a
cache outside the repository (`~/.cache/sdlc-c4/clients`), and read from there.
A Venturini case reads its client as published: the registry's tarball of that
version, unpacked once into the same cache.

**The changelog vote** is only recorded when it has been run, because running
it spends model calls; until then it is recorded as not run, and no arm that
needs it is computed.
"""

import argparse
import asyncio
import io
import json
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from sdlc_contracts import (
    DependencyUpdate,
    DependencyUpdates,
    RiskLevel,
    update_id_for,
)

from ..impact import sag, stage
from ..impact.api_diff import roseau_launcher
from ..impact.index import language_of
from ..intake.cache import Cache
from ..intake.fetch import Fetcher
from ..intake.manifests import declared_dependencies
from ..risk.semver_rule import SameRelease, movement
from .cases import LabelledCase
from .loaders.clients import read_client
from .study import semver_arm

CLIENTS = Path.home() / ".cache" / "sdlc-c4" / "clients"

#: Whole reports behind a votes record, kept outside the repository because they
#: quote clients' code and release notes, one directory per record.
REPORTS = Path.home() / ".cache" / "sdlc-c4" / "study-reports"

#: What a client is read for: the code, and the manifests that say who declares what.
_READ = (".java", "pom.xml", "package.json", "tsconfig.json", ".css")


@dataclass(frozen=True)
class Client:
    files: dict[str, str]
    #: Where the files came from, for the record.
    source: str


def _checkout(repo_url: str, commit: str, root: Path) -> Path:
    """The project at exactly one commit, fetched once into the cache."""
    owner_repo = repo_url.removeprefix("https://github.com/").strip("/")
    target = root / f"{owner_repo.replace('/', '__')}@{commit[:12]}"
    if (target / ".git").is_dir():
        head = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        if head == commit:
            return target
    target.mkdir(parents=True, exist_ok=True)
    for command in (
        ["git", "init", "-q"],
        ["git", "remote", "add", "origin", f"{repo_url}.git"],
        ["git", "fetch", "-q", "--depth", "1", "origin", commit],
        ["git", "checkout", "-q", "FETCH_HEAD"],
    ):
        done = subprocess.run(
            command, cwd=target, capture_output=True, text=True, timeout=600, check=False
        )
        if done.returncode != 0 and "already exists" not in done.stderr:
            raise RuntimeError(f"{' '.join(command)} failed in {target}: {done.stderr.strip()}")
    return target


def _unpacked(spec: str, root: Path) -> Path:
    """A published npm package at one version, unpacked once into the cache.

    Read from the registry's own tarball, so it is exactly what was published.
    Extracted with the `data` filter, which refuses links and paths that leave
    the target.
    """
    name, _, version = spec.rpartition("@")
    target = root / "npm" / f"{name.replace('/', '__')}@{version}"
    if (target / "package").is_dir():
        return target / "package"
    metadata = httpx.get(
        f"https://registry.npmjs.org/{name.replace('/', '%2f')}",
        headers={"User-Agent": "sdlc-platform-c4-study"},
        timeout=60,
        follow_redirects=True,
    )
    metadata.raise_for_status()
    tarball = metadata.json()["versions"][version]["dist"]["tarball"]
    answer = httpx.get(tarball, timeout=120, follow_redirects=True)
    answer.raise_for_status()
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(answer.content), mode="r:gz") as archive:
        archive.extractall(target, filter="data")
    return target / "package"


def _read_tree(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if not (relative.endswith(_READ) or language_of(relative)):
            continue
        try:
            files[relative] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
    return files


def client_for(case: LabelledCase, studies: Path, *, cache: Path = CLIENTS) -> Client:
    if case.client.snapshot:
        files = read_client(studies.parent / case.client.snapshot)
        for path in case.frozen_inputs:
            if path.endswith("package-lock.json"):
                files["package-lock.json"] = (studies.parent / path).read_text()
        return Client(files, case.client.snapshot)
    if case.client.repo_url and case.client.commit:
        root = _checkout(case.client.repo_url, case.client.commit, cache)
        return Client(_read_tree(root), f"{case.client.repo_url}@{case.client.commit}")
    if case.client.package_spec:
        root = _unpacked(case.client.package_spec, cache)
        return Client(_read_tree(root), f"npm {case.client.package_spec}")
    raise ValueError(f"{case.case_id} names no client this study can read")


def update_for(case: LabelledCase, files: dict[str, str]) -> DependencyUpdate:
    """The case's update as the product would have detected it in this client."""
    key = case.update.key
    try:
        change = movement(
            case.update.ecosystem, case.update.from_version, case.update.to_version
        ).change
    except SameRelease:
        change = "unparseable"
    declared = [
        d
        for d in declared_dependencies(files)
        if d.ecosystem == case.update.ecosystem and d.package == case.update.package
    ]
    manifest = (
        declared[0].manifest_path
        if declared
        else ("pom.xml" if case.update.ecosystem == "maven" else "package.json")
    )
    return DependencyUpdate(
        id=update_id_for(key),
        key=key,
        ecosystem=case.update.ecosystem,
        package=case.update.package,
        manifest_path=manifest,
        scope="compile" if case.update.ecosystem == "maven" else "prod",
        declared=case.update.from_version,
        from_version=case.update.from_version,
        to_version=case.update.to_version,
        candidate="latest",
        change=change,  # type: ignore[arg-type]
    )


def truth_of(case: LabelledCase, files: dict[str, str], granularity: str, update_id: str) -> dict:
    """Where the case's break really pointed, at the granularity the analysis named components in.

    The files are the failure's own; the components are those files mapped by the
    same function the impact stage maps its affected files with, so Table 5 compares
    like with like. Recorded only for a case whose failure locations are known.
    """
    paths = sorted({location.path for location in case.observed.failure_locations})
    if not paths:
        return {}
    components: list[str] = []
    if granularity == "module":
        mapped, _ = sag.map_to_modules({path: {update_id} for path in paths}, files)
        components = [component.node_id for component in mapped]
    return {"truth": {"files": paths, "components": components, "granularity": granularity}}


async def usage_of(
    case: LabelledCase,
    client: Client,
    *,
    fetcher: Fetcher,
    launcher: Path | None,
    keep: Path | None = None,
) -> dict:
    """The impact stage over one case's client: the usage vote and what it rests on.

    With `keep`, the whole impact report is written there too, as
    `<case>.impact.json`, so an explanation can later be asked of the real
    assessment. It quotes the client's code, so it is kept outside the repository.
    """
    update = update_for(case, client.files)
    updates = DependencyUpdates(
        version=1,
        generated_at=datetime.now(UTC),
        code_version=1,
        test_version=1,
        target="study",
        updates=[update],
    )
    report = await stage.analyse(
        client.files,
        updates,
        None,
        graph=None,
        contract=None,
        manifest=[],
        version=1,
        code_version=1,
        design_version=None,
        fetcher=fetcher,
        launcher=launcher,
        cache_dir=fetcher.cache.root,
    )
    [impact] = report.per_update
    if keep is not None:
        keep.mkdir(parents=True, exist_ok=True)
        (keep / f"{case.case_id}.impact.json").write_text(
            report.model_dump_json(by_alias=True) + "\n"
        )
    return {
        **truth_of(case, client.files, report.granularity, update.id),
        "level": impact.vote.level,
        "abstained": impact.vote.abstained_reason,
        "rationale": impact.vote.rationale,
        "apiDiff": impact.api_diff,
        "apiDiffReason": impact.api_diff_reason,
        "changedSymbols": len(report.changed_symbols),
        "references": len(impact.references),
        "affectedFiles": [item.path for item in report.affected_files],
        "components": [c.node_id for c in report.affected_components],
        "granularity": report.granularity,
        "filesIndexed": report.extraction.files_indexed,
        "seconds": impact.seconds,
    }


async def record(
    cases: list[LabelledCase],
    studies: Path,
    *,
    cache: Path,
    launcher: Path | None,
    reports: Path | None = None,
    log=print,
) -> dict:
    votes: dict[str, dict] = {}
    async with httpx.AsyncClient(headers={"User-Agent": "sdlc-platform-c4-study"}) as http:
        fetcher = Fetcher(http, cache=Cache(cache))
        for case in cases:
            log(f"  {case.case_id}", flush=True)
            client = client_for(case, studies)
            semver: RiskLevel | None = semver_arm(case)
            try:
                usage = await usage_of(
                    case, client, fetcher=fetcher, launcher=launcher, keep=reports
                )
            except Exception as error:  # recorded, never raised: one case cannot stop the rest
                usage = {"level": None, "abstained": f"the impact stage failed: {error}"}
            votes[case.case_id] = {
                "client": client.source,
                "semver": semver,
                "changelog": None,
                "changelogRun": False,
                "usage": usage,
            }
            log(f"    semver {semver}, usage {usage.get('level')} ({usage.get('apiDiff')})")
    return votes


def main(argv: list[str] | None = None) -> int:
    from .__main__ import load_cases

    parser = argparse.ArgumentParser(prog="python -m c4.eval.votes", description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--studies", type=Path, default=Path("studies"))
    parser.add_argument("--split", default="dev", choices=["dev", "all"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--cache", type=Path, default=Path.home() / ".cache" / "sdlc-c4" / "votes-registry"
    )
    parser.add_argument(
        "--reports",
        type=Path,
        default=None,
        help="where each case's whole impact report is kept (default: the study reports cache)",
    )
    args = parser.parse_args(argv)
    reports = args.reports or REPORTS / args.out.stem
    cases = [c for c in load_cases(args.cases) if args.split == "all" or c.split == args.split]
    launcher = roseau_launcher()
    print(f"{len(cases)} cases, Roseau {'at ' + str(launcher) if launcher else 'not installed'}")
    votes = asyncio.run(
        record(cases, args.studies, cache=args.cache, launcher=launcher, reports=reports)
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"recordedOn": date.today().isoformat(), "split": args.split, "votes": votes},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
