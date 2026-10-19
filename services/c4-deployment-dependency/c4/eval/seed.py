"""Build the seed set: the study's first cases, every one observed locally and free.

    uv run python -m c4.eval.seed --bump ~/.cache/sdlc-c4/bump --out studies/cases/seed

Four sources, each through its loader, and none of them chosen by hand beyond
the worked case:

- **BUMP**: eight recorded breaks from the dev split. The worked case (dubbo
  2.7.3 to 2.7.21, a patch by number that failed to compile) and seven more in
  a fixed hash order: three majors, two minors and two patches as BUMP itself
  read them.
- **The platform's generated Task Tracker**, its tree as installed on
  2026-06-01, crossed with its dependencies' updates since: eight of the
  dev split's crossings in the same hash order, three majors, three minors, two
  patches.
- **The four seeded npm clients.**
- **The Java client**, crossed with the JUnit BOM's updates.

Where a source offers more candidates than the seed takes, it takes them from
the dev split, so every chosen case can be developed against; the loaders at
scale fill the held out side. A seeded client is one case whichever side its
key falls on.

Every case is written as soon as it is observed, and a case already written is
not observed again, so an interrupted build resumes where it stopped. Nothing
here calls a model.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Iterable
from datetime import date
from functools import partial
from pathlib import Path

import httpx

from ..harness.container import MAVEN_CACHE, NPM_CACHE, Lane, StepSpec
from ..harness.reproduce import Reproduction
from ..harness.steps import smoke_paths
from ..intake import maven_central, npm_registry
from ..intake.cache import Cache
from ..intake.fetch import Fetcher
from ..intake.lockfile import LOCKFILE, Pin, pin
from ..intake.manifests import declared_dependencies
from .cases import LabelledCase
from .loaders import maven_negatives, npm_platform, npm_seeded
from .loaders.bump import load_checkout
from .loaders.clients import read_client
from .loaders.crossings import CrossingKind, Releases, selection_order, targets
from .split import held_out

#: BUMP's worked case: a patch by its number, observed failing to compile.
WORKED_CASE = "bump-dc9a40fde9a9"

BUMP_QUOTA: dict[str, int] = {"major": 3, "minor": 2, "patch": 2}
PLATFORM_QUOTA: dict[str, int] = {"major": 3, "minor": 3, "patch": 2}

#: The day the platform client's tree is reconstructed at: the first of a month
#: after the newest release any of its ranges requires (tailwindcss 4.3.0,
#: published 2026-05-08), so every range can be satisfied.
PLATFORM_INSTALLED_ON = date(2026, 6, 1)
PLATFORM_CLIENT = "task-tracker"


def by_quota(cases: Iterable, kind_of, key_of, quota: dict[str, int]) -> list:
    """The first cases of each kind in the fixed hash order, up to that kind's quota."""
    taken: list = []
    left = dict(quota)
    for case in sorted(cases, key=lambda c: selection_order(key_of(c))):
        kind = kind_of(case)
        if left.get(kind, 0) > 0:
            taken.append(case)
            left[kind] -= 1
    return taken


def select_bump(cases: list[LabelledCase]) -> list[LabelledCase]:
    """The worked case, then the quota from the rest, all from the dev split."""
    dev = [case for case in cases if case.split == "dev"]
    worked = [case for case in dev if case.case_id == WORKED_CASE]
    if not worked:
        raise SystemExit(f"the worked case {WORKED_CASE} is not among the dev split's cases")
    rest = [case for case in dev if case.case_id != WORKED_CASE]
    return worked + by_quota(rest, lambda c: c.source_change, lambda c: c.update.key, BUMP_QUOTA)


def bump_seed(checkout: Path) -> list[LabelledCase]:
    return select_bump(load_checkout(checkout))


def _write(case: LabelledCase, out: Path) -> None:
    body = json.dumps(case.model_dump(by_alias=True, mode="json"), indent=2, sort_keys=True)
    (out / f"{case.case_id}.json").write_text(body + "\n")
    print(f"  wrote {case.case_id}", flush=True)


def _done(case_id: str, out: Path) -> bool:
    if (out / f"{case_id}.json").exists():
        print(f"  {case_id} already observed, kept", flush=True)
        return True
    return False


#: How many times a case is observed before a lost download is taken as its result.
ATTEMPTS = 3


def _observed(observe: Callable[[], Reproduction], case_id: str) -> tuple[Reproduction, int]:
    """Observe until no download failure cut a run short, at most `ATTEMPTS` times.

    A lost download says nothing about the update, so observing again is not
    choosing a result: the step outcomes a project or an update caused are
    never retried, only runs that the network cut short. The count is kept on
    the case. A case that never got a clean run is not written (`_keep`), and is
    observed again on the next run: a network that was down for an hour is not
    a fact about the case, and a written case is never observed again.
    """
    for attempt in range(1, ATTEMPTS + 1):
        reproduction = observe()
        lost = [
            step.name
            for step in (*reproduction.baseline, *reproduction.candidate)
            if step.outcome == "unavailable"
        ]
        if not lost:
            return reproduction, attempt
        print(f"  {case_id}: a download failed in {lost} on attempt {attempt}", flush=True)
    return reproduction, ATTEMPTS


def _keep(case: LabelledCase, attempts: int, out: Path) -> None:
    """Write an observed case, unless a download cut every attempt short."""
    lost = [
        step.name
        for step in (*case.observed.baseline, *case.observed.candidate)
        if step.outcome == "unavailable"
    ]
    if lost:
        print(
            f"  {case.case_id}: a download failed in {lost} on every attempt; "
            "not written, and observed again next run",
            flush=True,
        )
        return
    _write(_with_attempts(case, attempts), out)


def _with_attempts(case: LabelledCase, attempts: int) -> LabelledCase:
    return case.model_copy(
        update={"observed": case.observed.model_copy(update={"attempts": attempts})}
    )


def _toolchain(lane: Lane, command: str) -> str:
    result = lane.run({}, [StepSpec("versions", command, timeout=120)])
    said = " ".join(result.steps[0].output.split())
    return f"{lane.image} ({said})"


async def _npm_releases(names: list[str], cache: Path) -> dict[str, Releases]:
    found: dict[str, Releases] = {}
    async with httpx.AsyncClient(headers={"User-Agent": "sdlc-platform-c4-study"}) as client:
        fetcher = Fetcher(client, cache=Cache(cache))
        for name in names:
            package = await npm_registry.fetch(fetcher, name)
            if isinstance(package, npm_registry.NotFound):
                print(f"  {name}: {package.detail}", flush=True)
                continue
            found[name] = Releases(package.versions, package.latest)
    return found


async def _maven_releases(coordinates: str, cache: Path) -> Releases:
    async with httpx.AsyncClient(headers={"User-Agent": "sdlc-platform-c4-study"}) as client:
        artifact = await maven_central.fetch(Fetcher(client, cache=Cache(cache)), coordinates)
    if isinstance(artifact, npm_registry.NotFound):
        raise SystemExit(f"{coordinates}: {artifact.detail}")
    return Releases(artifact.versions, artifact.release)


def _pinned(files: dict[str, str], stored: Path, *, before: date | None = None):
    """Pin the client's tree, keep the lockfile beside the clients, and say if it moved."""
    pinned = pin(files, before=before)
    if stored.exists() and stored.read_text() != pinned.text:
        print(f"  note: the pin at {stored} differs from the tree resolved now; replaced")
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_text(pinned.text)
    return pinned


def _platform_key(crossing: npm_platform.Crossing) -> str:
    return f"npm:{crossing.package}@{crossing.from_version}->{crossing.to_version}"


def select_platform(every: list[npm_platform.Crossing]) -> list[npm_platform.Crossing]:
    """The quota from the dev split's crossings, in the fixed hash order."""
    dev = [crossing for crossing in every if not held_out(_platform_key(crossing))]
    return by_quota(dev, lambda c: c.kind, _platform_key, PLATFORM_QUOTA)


def platform_tree(
    studies: Path, *, cache: Path, on: date, pins: Path | None = None
) -> tuple[dict[str, str], Pin, Path, list[npm_platform.Crossing]]:
    """The platform client's tree as installed on a day, and every crossing it admits.

    The lockfile is kept under `pins` (the study's own, `studies/pins`, unless a
    plan asks for somewhere else), because each case records the pin it used.
    """
    files = read_client(studies / "clients" / PLATFORM_CLIENT)
    stored = (pins or studies / "pins") / f"{PLATFORM_CLIENT}-{on}.package-lock.json"
    pinned = _pinned(files, stored, before=on)
    files = {**files, LOCKFILE: pinned.text}
    names = sorted(
        {
            d.package
            for d in declared_dependencies(files)
            if d.ecosystem == "npm" and not d.not_registry
        }
    )
    releases = asyncio.run(_npm_releases(names, cache))
    return files, pinned, stored, npm_platform.crossings(files, pinned, releases)


def observe_platform(
    chosen: list[npm_platform.Crossing],
    files: dict[str, str],
    pinned: Pin,
    stored: Path,
    *,
    studies: Path,
    out: Path,
    on: date,
    captured_at: str,
) -> None:
    """Observe each chosen crossing not already written, and write it as soon as it is."""
    lane = Lane(caches=NPM_CACHE)
    toolchain = _toolchain(lane, "node --version; npm --version")
    for crossing in chosen:
        if _done(crossing.case_id, out):
            continue
        print(f"  observing {crossing.case_id}", flush=True)
        reproduction, attempts = _observed(
            partial(npm_platform.observe, lane, files, crossing, smoke_paths(files)),
            crossing.case_id,
        )
        case = npm_platform.case_for(
            crossing,
            reproduction,
            client=PLATFORM_CLIENT,
            files=files,
            pinned=pinned,
            pin_path=str(stored.relative_to(studies.parent)),
            installed_on=on.isoformat(),
            toolchain=toolchain,
            captured_at=captured_at,
        )
        _keep(case, attempts, out)


def platform_seed(studies: Path, out: Path, *, cache: Path, captured_at: str) -> None:
    files, pinned, stored, every = platform_tree(studies, cache=cache, on=PLATFORM_INSTALLED_ON)
    print(f"  {len(every)} crossings from the tree as installed on {PLATFORM_INSTALLED_ON}:")
    for crossing in every:
        print(
            f"    {crossing.kind:5} {crossing.package} {crossing.from_version} -> {crossing.to_version}"
        )
    observe_platform(
        select_platform(every),
        files,
        pinned,
        stored,
        studies=studies,
        out=out,
        on=PLATFORM_INSTALLED_ON,
        captured_at=captured_at,
    )


def seeded_seed(studies: Path, out: Path, *, captured_at: str) -> None:
    lane = Lane(caches=NPM_CACHE)
    toolchain = _toolchain(lane, "node --version; npm --version")
    for seeded in npm_seeded.SEEDED:
        if _done(seeded.case_id, out):
            continue
        files = read_client(studies / "clients" / "seeded" / seeded.client)
        stored = studies / "pins" / f"seeded-{seeded.client}.package-lock.json"
        pinned = _pinned(files, stored)
        files = {**files, LOCKFILE: pinned.text}
        print(f"  observing {seeded.case_id}", flush=True)
        reproduction, attempts = _observed(
            partial(npm_seeded.observe, lane, files, seeded), seeded.case_id
        )
        case = npm_seeded.case_for(
            seeded,
            reproduction,
            files=files,
            pinned=pinned,
            pin_path=str(stored.relative_to(studies.parent)),
            toolchain=toolchain,
            captured_at=captured_at,
        )
        _keep(case, attempts, out)


def maven_seed(studies: Path, out: Path, *, cache: Path, captured_at: str) -> None:
    files = read_client(studies / "clients" / "java-records")
    installed = maven_negatives.installed_version(files)
    releases = asyncio.run(_maven_releases(maven_negatives.PACKAGE, cache))
    found: dict[CrossingKind, str] = targets(installed, releases)
    print(f"  {maven_negatives.PACKAGE} {installed}: {found}")
    lane = Lane(maven_negatives.MAVEN_IMAGE, caches=MAVEN_CACHE)
    toolchain = _toolchain(lane, "mvn -v | head -3")
    for kind, target in found.items():
        case_id = maven_negatives.case_id(installed, target)
        if _done(case_id, out):
            continue
        print(f"  observing {case_id}", flush=True)
        reproduction, attempts = _observed(
            partial(maven_negatives.observe, lane, files, installed, target), case_id
        )
        case = maven_negatives.case_for(
            kind,
            installed,
            target,
            reproduction,
            files=files,
            toolchain=toolchain,
            captured_at=captured_at,
        )
        _keep(case, attempts, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m c4.eval.seed", description=__doc__)
    parser.add_argument("--bump", type=Path, help="a checkout of chains-project/bump")
    parser.add_argument("--studies", type=Path, default=Path("studies"))
    parser.add_argument("--out", type=Path, default=Path("studies/cases/seed"))
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path.home() / ".cache" / "sdlc-c4" / f"study-registry-{date.today()}",
        help="where registry answers are cached; one per capture day, so the capture is fresh",
    )
    parser.add_argument("--only", default="bump,platform,seeded,maven")
    parser.add_argument("--captured-at", default=date.today().isoformat())
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(","))

    if "bump" in only:
        if args.bump is None:
            parser.error("--bump is required for the BUMP cases")
        print("BUMP")
        for case in bump_seed(args.bump):
            _write(case, args.out)
    if "seeded" in only:
        print("seeded npm clients")
        seeded_seed(args.studies, args.out, captured_at=args.captured_at)
    if "maven" in only:
        print("Maven client")
        maven_seed(args.studies, args.out, cache=args.cache, captured_at=args.captured_at)
    if "platform" in only:
        print("platform client")
        platform_seed(args.studies, args.out, cache=args.cache, captured_at=args.captured_at)
    return 0


if __name__ == "__main__":
    sys.exit(main())
