"""The corpus at scale: every source through its loader, planned before anything is observed.

    uv run python -m c4.eval.corpus --bump ~/.cache/sdlc-c4/bump \\
        --venturini ~/.cache/sdlc-c4/venturini                      # the plan, observing nothing
    uv run python -m c4.eval.corpus ... --build --out studies/cases/corpus

The seed set takes a few cases from each source's dev split. The corpus takes
what each source can honestly give, from both splits, in the same fixed hash
order, so the held out side fills too and nobody picks a case by hand:

- **BUMP**: recorded breaks, a quota per BUMP's own version change reading,
  with the worked case always in;
- **Venturini et al.**: every recorded npm break the study's model can hold;
- **the platform client**, its tree reconstructed as installed on each of
  several days, crossed with what its dependencies released since. One case
  per update: a crossing another day already gave, from the same version to the
  same version, is the same update and is not observed twice;
- **the seeded npm clients**, and **the Java client** crossed with the JUnit
  BOM's updates, as in the seed;
- **BUMP's own projects** (`loaders/bump_crossings.py`): the projects of the
  chosen BUMP cases, each at the commit before its break, crossed with its other
  dependencies' updates in BUMP's pre image, two per project once its control
  passes, up to a quota. How many there are is known only after the controls
  run, so the plan states the quota rather than a count.

**Without `--build` nothing is observed or written.** The plan prints what each
source gives, recorded or to observe, by ecosystem, by version change and by
split, and how long the observations are expected to take, from what the seed's
own observations took. `--build` writes the recorded cases and observes the rest,
one at a time, each written as soon as it is observed; a case already in the
seed set is copied rather than observed again, and one already in the corpus is
kept, so an interrupted build resumes.

**Why the platform side is small.** The four other generated clients
(`clients/c2-rule/*`) declare exactly the task tracker's dependencies, from the
same catalog, so crossing them gives the same updates again: near copies of one
case, not more evidence. They are left out, and the plan says so.
"""

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from sdlc_contracts import update_key

from ..intake import npm_registry
from ..intake.cache import Cache
from ..intake.fetch import Fetcher
from ..risk.semver_rule import movement
from .cases import LabelledCase
from .loaders import bump_crossings, maven_negatives, npm_seeded, venturini
from .loaders.bump import dataset_version, load_checkout
from .loaders.crossings import Releases, selection_order, targets
from .seed import (
    PLATFORM_INSTALLED_ON,
    WORKED_CASE,
    _maven_releases,
    _write,
    by_quota,
    maven_seed,
    observe_platform,
    platform_tree,
    seeded_seed,
)

#: BUMP's own reading of each change, and how many of each the corpus takes.
BUMP_QUOTA: dict[str, int] = {"major": 25, "minor": 25, "patch": 10, "other": 10}

#: The days the platform client's tree is reconstructed at: the seed's day, and
#: the first of each month after it. None can be earlier, because a range the
#: client declares (tailwindcss ^4.3.0) needs a release from 2026-05-08.
PLATFORM_DATES: tuple[date, ...] = (
    PLATFORM_INSTALLED_ON,
    date(2026, 7, 1),
    date(2026, 8, 1),
    date(2026, 9, 1),
)

#: Seconds one observation takes, from the seed's own runs (control plus
#: candidate, all steps): what the plan's estimate is made from.
SECONDS_PER_OBSERVATION: dict[str, float] = {
    "npm-platform": 240.0,
    "npm-seeded": 120.0,
    "maven-negative": 180.0,
    "bump-crossing": 300.0,
}


@dataclass(frozen=True)
class Planned:
    """One case the corpus will hold: recorded already, or to be observed."""

    case_id: str
    source: str
    ecosystem: str
    change: str
    split: str
    recorded: bool


def select_bump(every: list[LabelledCase]) -> list[LabelledCase]:
    """The worked case, then BUMP's quota per version change, from both splits."""
    worked = [case for case in every if case.case_id == WORKED_CASE]
    rest = [case for case in every if case.case_id != WORKED_CASE]
    return worked + by_quota(
        rest, lambda c: c.source_change or "other", lambda c: c.update.key, BUMP_QUOTA
    )


def bump_cases(checkout: Path) -> list[LabelledCase]:
    return select_bump(load_checkout(checkout))


async def _versions(names: list[str], cache: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    async with httpx.AsyncClient(headers={"User-Agent": "sdlc-platform-c4-study"}) as client:
        fetcher = Fetcher(client, cache=Cache(cache))
        for name in names:
            package = await npm_registry.fetch(fetcher, name)
            if not isinstance(package, npm_registry.NotFound):
                found[name] = list(package.versions)
    return found


async def _maven_versions(names: list[str], cache: Path) -> dict[str, Releases]:
    from ..intake import maven_central

    found: dict[str, Releases] = {}
    async with httpx.AsyncClient(headers={"User-Agent": "sdlc-platform-c4-study"}) as client:
        fetcher = Fetcher(client, cache=Cache(cache))
        for name in names:
            artifact = await maven_central.fetch(fetcher, name)
            if not isinstance(artifact, npm_registry.NotFound):
                found[name] = Releases(artifact.versions, artifact.release)
    return found


def venturini_cases(directory: Path, cache: Path) -> tuple[list[LabelledCase], list]:
    records = json.loads((directory / "breaking-changes-cases.json").read_text())
    providers = sorted(
        {
            record["provider_version_introduced"].rpartition("@")[0]
            for group in records.values()
            for record in group
            if venturini.usable(record) is None
        }
    )
    releases = asyncio.run(_versions(providers, cache))
    return venturini.load(
        directory / "breaking-changes-cases.json", directory / "clients.csv", releases
    )


def one_per_update(by_day: dict[date, list]) -> dict[date, list]:
    """Each day's crossings, keeping only updates no earlier day already gave."""
    seen: set[str] = set()
    fresh_by_day: dict[date, list] = {}
    for day in sorted(by_day):
        fresh = []
        for crossing in sorted(by_day[day], key=lambda c: selection_order(_key(c))):
            if _key(crossing) not in seen:
                seen.add(_key(crossing))
                fresh.append(crossing)
        fresh_by_day[day] = fresh
    return fresh_by_day


def platform_trees(studies: Path, *, cache: Path, pins: Path, log=print) -> dict[date, tuple]:
    """Each day's pinned tree and crossings, pinned once each, tried twice.

    A day whose pin still fails is left out and said; the caller decides what a
    missing day means.
    """
    import subprocess

    from ..intake.lockfile import PinFailed

    trees: dict[date, tuple] = {}
    for day in PLATFORM_DATES:
        for attempt in (1, 2):
            try:
                trees[day] = platform_tree(studies, cache=cache, on=day, pins=pins)
                break
            except (PinFailed, subprocess.TimeoutExpired) as error:
                log(
                    f"  {day}: pinning failed on attempt {attempt}: {str(error)[-200:]}", flush=True
                )
    return trees


def platform_crossings(studies: Path, *, cache: Path, pins: Path) -> dict[date, list]:
    trees = platform_trees(studies, cache=cache, pins=pins)
    return one_per_update({day: tree[3] for day, tree in trees.items()})


def _key(crossing) -> str:
    return update_key("npm", crossing.package, crossing.from_version, crossing.to_version)


def _split(key: str) -> str:
    from .split import held_out

    return "held-out" if held_out(key) else "dev"


def plan(
    *, bump: Path | None, venturini_dir: Path | None, studies: Path, cache: Path
) -> list[Planned]:
    planned: list[Planned] = []
    if bump is not None:
        for case in bump_cases(bump):
            planned.append(
                Planned(
                    case.case_id, "bump", "maven", case.source_change or "other", case.split, True
                )
            )
    if venturini_dir is not None:
        cases, _ = venturini_cases(venturini_dir, cache)
        for case in cases:
            planned.append(
                Planned(case.case_id, "npm-venturini", "npm", case.source_change, case.split, True)
            )
    with tempfile.TemporaryDirectory(prefix="c4-plan-pins-") as scratch:
        for crossings in platform_crossings(studies, cache=cache, pins=Path(scratch)).values():
            for crossing in crossings:
                planned.append(
                    Planned(
                        crossing.case_id,
                        "npm-platform",
                        "npm",
                        crossing.kind,
                        _split(_key(crossing)),
                        False,
                    )
                )
    for seeded in npm_seeded.SEEDED:
        key = update_key("npm", seeded.package, seeded.from_version, seeded.to_version)
        change = movement("npm", seeded.from_version, seeded.to_version).change
        planned.append(Planned(seeded.case_id, "npm-seeded", "npm", change, _split(key), False))
    files_dir = studies / "clients" / "java-records"
    from .loaders.clients import read_client

    installed = maven_negatives.installed_version(read_client(files_dir))
    releases = asyncio.run(_maven_releases(maven_negatives.PACKAGE, cache))
    for kind, target in targets(installed, releases).items():
        key = update_key("maven", maven_negatives.PACKAGE, installed, target)
        planned.append(
            Planned(
                maven_negatives.case_id(installed, target),
                "maven-negative",
                "maven",
                kind,
                _split(key),
                False,
            )
        )
    return planned


def render_plan(planned: list[Planned]) -> str:
    lines = ["| source | ecosystem | recorded | to observe | dev | held out | by change |"]
    lines.append("|---|---|---|---|---|---|---|")
    for source in sorted({item.source for item in planned}):
        mine = [item for item in planned if item.source == source]
        changes = Counter(item.change for item in mine)
        lines.append(
            f"| {source} | {mine[0].ecosystem} | {sum(i.recorded for i in mine)} | "
            f"{sum(not i.recorded for i in mine)} | {sum(i.split == 'dev' for i in mine)} | "
            f"{sum(i.split == 'held-out' for i in mine)} | "
            + ", ".join(f"{kind} {count}" for kind, count in sorted(changes.items()))
            + " |"
        )
    by_ecosystem = Counter(item.ecosystem for item in planned)
    seconds = sum(
        SECONDS_PER_OBSERVATION.get(item.source, 180.0) for item in planned if not item.recorded
    )
    lines += [
        "",
        f"{len(planned)} cases: npm {by_ecosystem['npm']}, Maven {by_ecosystem['maven']}. "
        f"{sum(not i.recorded for i in planned)} to observe, about {seconds / 3600:.1f} hours "
        "of container time at the seed's pace.",
        "Left out: the four other generated clients (`clients/c2-rule/*`), which declare the "
        "task tracker's dependencies and would give the same updates again.",
        f"Not in the count: BUMP's own projects, crossed with their other dependencies, up to "
        f"{bump_crossings.QUOTA} ({bump_crossings.PER_PROJECT} per project once its control "
        f"passes), about {bump_crossings.QUOTA * SECONDS_PER_OBSERVATION['bump-crossing'] / 3600:.1f} "
        "more hours; how many is known only after each project's control runs.",
    ]
    return "\n".join(lines) + "\n"


def build(
    *,
    bump: Path | None,
    venturini_dir: Path | None,
    studies: Path,
    out: Path,
    cache: Path,
    captured_at: str,
    seed: Path,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for existing in sorted(seed.glob("*.json")):
        if not (out / existing.name).exists():
            shutil.copy(existing, out / existing.name)
    if bump is not None:
        print("BUMP")
        chosen = bump_cases(bump)
        for case in chosen:
            if not (out / f"{case.case_id}.json").exists():
                _write(case, out)
        print("BUMP's own projects, crossed with their other dependencies")
        held = bump_crossings.build(
            bump_crossings.records_of(chosen, bump / "data" / "benchmark"),
            out,
            out.parent / f"{out.name}-bump-crossing-skips.json",
            releases_for=lambda names: asyncio.run(_maven_versions(names, cache)),
            captured_at=captured_at,
            dataset_commit=dataset_version(bump)[0],
        )
        print(f"  {held} crossing(s) in the corpus")
    if venturini_dir is not None:
        print("Venturini et al.")
        cases, skipped = venturini_cases(venturini_dir, cache)
        for case in cases:
            if not (out / f"{case.case_id}.json").exists():
                _write(case, out)
        print(f"  {len(skipped)} records the study's model cannot hold, not read")
    print("seeded npm clients")
    seeded_seed(studies, out, captured_at=captured_at)
    print("Maven client")
    maven_seed(studies, out, cache=cache, captured_at=captured_at)
    print("platform client")
    trees = platform_trees(studies, cache=cache, pins=studies / "pins")
    if len(trees) < len(PLATFORM_DATES):
        # Which day an update is observed under decides the pin its case records, so
        # the crossings wait for a run that has every day, rather than shift.
        print("  a day's tree could not be pinned; the platform crossings wait for the next run")
        return
    for day, crossings in one_per_update({d: tree[3] for d, tree in trees.items()}).items():
        files, pinned, stored, _ = trees[day]
        print(f"  {day}: {len(crossings)} update(s) no earlier day gave")
        observe_platform(
            crossings,
            files,
            pinned,
            stored,
            studies=studies,
            out=out,
            on=day,
            captured_at=captured_at,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m c4.eval.corpus",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--bump", type=Path, help="a checkout of chains-project/bump")
    parser.add_argument("--venturini", type=Path, help="the replication package's two files")
    parser.add_argument("--studies", type=Path, default=Path("studies"))
    parser.add_argument("--out", type=Path, default=Path("studies/cases/corpus"))
    parser.add_argument("--seed", type=Path, default=Path("studies/cases/seed"))
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path.home() / ".cache" / "sdlc-c4" / f"study-registry-{date.today()}",
    )
    parser.add_argument("--captured-at", default=date.today().isoformat())
    parser.add_argument("--build", action="store_true", help="write and observe, not only plan")
    args = parser.parse_args(argv)
    if args.build:
        build(
            bump=args.bump,
            venturini_dir=args.venturini,
            studies=args.studies,
            out=args.out,
            cache=args.cache,
            captured_at=args.captured_at,
            seed=args.seed,
        )
        return 0
    print(
        render_plan(
            plan(
                bump=args.bump, venturini_dir=args.venturini, studies=args.studies, cache=args.cache
            )
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
