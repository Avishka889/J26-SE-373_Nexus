"""The impact stage: one index, every update's references, and the components they reach.

The project is indexed once, before any update is looked at, and every update's
search runs over that one index (NFR2). Each update's API diff runs beside the
others, a few at a time, because Roseau holds a Java runtime and a tarball can
be large. What the stage produces is the `impact-report`: the changed symbols
and who named them, each update's references and usage vote, the affected
files, and the components those files are, with every file either mapped
through recorded links or listed as unmapped.
"""

import asyncio
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sdlc_contracts import (
    AffectedFile,
    ApiContract,
    ArchitectureGraph,
    ChangedSymbol,
    ChangelogReport,
    DependencyUpdates,
    ImpactReport,
    ManifestRow,
    RefusedReference,
    UpdateImpact,
)

from ..intake.fetch import Fetcher
from .api_diff import diff
from .index import build
from .sag import map_to_graph, map_to_modules
from .usage import claimed_symbols, update_impact

#: How many API diffs run at once.
DIFFS_AT_ONCE = 2

#: The file the baseline pin is stored as, which names every command's package.
LOCKFILE = "package-lock.json"


async def analyse(
    files: dict[str, str],
    updates: DependencyUpdates,
    changelog: ChangelogReport | None,
    *,
    graph: ArchitectureGraph | None,
    contract: ApiContract | None,
    manifest: list[ManifestRow],
    version: int,
    code_version: int,
    design_version: int | None,
    fetcher: Fetcher,
    launcher: Path | None = None,
    cache_dir: Path | None = None,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ImpactReport:
    # In a thread, like every other long step of a run: indexing a large
    # project takes seconds to minutes, and the event loop is the orchestrator's.
    index = await asyncio.to_thread(build, files, lockfile=files.get(LOCKFILE))

    gate = asyncio.Semaphore(DIFFS_AT_ONCE)

    async def one(update):
        async with gate:
            started = clock()
            result = await diff(update, fetcher=fetcher, launcher=launcher, cache_dir=cache_dir)
            return result, clock() - started

    diffs = await asyncio.gather(*(one(update) for update in updates.updates))

    per_update: list[UpdateImpact] = []
    refused: list[RefusedReference] = []
    symbols: list[ChangedSymbol] = []
    affected: dict[str, set[str]] = defaultdict(set)
    counts: Counter[str] = Counter()
    for update, (api, diff_seconds) in zip(updates.updates, diffs, strict=True):
        started = clock()
        impact, refusals, found = update_impact(
            update, index, files, api=api, claimed=claimed_symbols(changelog, update)
        )
        spent = index.seconds + diff_seconds + (clock() - started)
        impact = impact.model_copy(update={"seconds": round(spent, 3)})
        per_update.append(impact)
        refused.extend(refusals)
        symbols.extend(found)
        for reference in impact.references:
            affected[reference.span.path].add(update.id)
            counts[reference.span.path] += 1

    rows = {row.path: row for row in manifest}
    affected_files = [
        AffectedFile(
            path=path,
            update_ids=sorted(affected[path]),  # type: ignore[arg-type]
            reference_count=counts[path],
            manifest_stage=rows[path].stage if path in rows else None,
            implements=list(rows[path].implements) if path in rows else [],
        )
        for path in sorted(affected)
    ]
    by_module = graph is None and any(
        path == "pom.xml" or path.endswith("/pom.xml") for path in files
    )
    if by_module:
        components, unmapped = map_to_modules(affected, files)
    else:
        components, unmapped = map_to_graph(
            affected, graph=graph, contract=contract, manifest=manifest
        )
    return ImpactReport(
        version=version,
        generated_at=now or datetime.now(UTC),
        code_version=code_version,
        design_version=design_version,
        granularity="module" if by_module else "graph-node",
        extraction=index.record(),
        changed_symbols=symbols,
        per_update=per_update,
        affected_files=affected_files,
        affected_components=components,
        unmapped_files=unmapped,
        refused_references=refused,
    )
