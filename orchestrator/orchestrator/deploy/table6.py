"""Table 6, from the ledger: how releases and rollbacks ended, as the platform recorded them.

    uv run python -m orchestrator.deploy.table6 --out services/c4-deployment-dependency/studies/epochs

Read only from `app.deployments`, every attempt the saga ever made (FR16), in
the database `DATABASE_URL` names. The address is never printed or recorded,
and neither is who approved anything: the table counts, it does not name.

- **Releases, by target**: attempts that ended, how many ended verified, and how
  the rest ended: before traffic moved (`failed`), or after it, waiting on or
  given a rollback.
- **Rollbacks in controlled episodes**: rollbacks of a release a controlled
  failure was injected into (`fault_injected`), each authorised by a person's
  recorded decision (FR20), and how many ended with the guard's "restored": the
  verified release's fingerprint served again, with health and smoke passing.
  Rollbacks of a release nobody injected anything into are counted apart, and
  never mixed into the controlled number.

A deployment still pending or running has not ended and is not counted.
"""

import argparse
import asyncio
import json
import subprocess
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..db import store

ENDED = ("succeeded", "failed", "awaiting-rollback-approval", "rolled-back", "kept-unverified")


def releases(rows: Iterable[store.Row]) -> dict[str, dict[str, int]]:
    """Each target's release attempts that ended, by how."""
    found: dict[str, dict[str, int]] = {}
    for row in rows:
        if row["kind"] != "release" or row["state"] not in ENDED:
            continue
        tally = found.setdefault(
            row["target"],
            {"ended": 0, "verified": 0, "failedBeforeTraffic": 0, "failedAfterTraffic": 0},
        )
        tally["ended"] += 1
        if row["verified"]:
            tally["verified"] += 1
        elif row["state"] == "failed":
            tally["failedBeforeTraffic"] += 1
        else:
            tally["failedAfterTraffic"] += 1
    return found


def rollbacks(rows: list[store.Row]) -> dict[str, dict[str, int]]:
    """Rollbacks that ended, split by whether the release they undid had a fault injected."""
    by_id = {str(row["id"]): row for row in rows}
    found = {
        "controlled": {"ended": 0, "restored": 0},
        "organic": {"ended": 0, "restored": 0},
    }
    for row in rows:
        if row["kind"] != "rollback" or row["state"] not in ENDED:
            continue
        authorised = row.get("authorised") or {}
        undone = by_id.get(str(authorised.get("deploymentId")))
        episode = "controlled" if undone is not None and undone.get("fault_injected") else "organic"
        found[episode]["ended"] += 1
        if row["state"] == "succeeded" and row["verified"]:
            found[episode]["restored"] += 1
    return found


def tally(rows: list[store.Row]) -> dict[str, Any]:
    return {"releases": releases(rows), "rollbacks": rollbacks(rows)}


def _share(top: int, bottom: int) -> str:
    return f"{top} of {bottom}" + (f" ({top / bottom:.0%})" if bottom else "")


def render(record: dict[str, Any]) -> str:
    header = record["study"]
    lines = [
        f"### {header['label']}, {header['date']}",
        "",
        f"Commit `{header['commit']}`. From the orchestrator's ledger (`app.deployments`), "
        f"{header['projects']} project(s); pending and running deployments are not counted.",
        "",
        "| target | releases ended | verified | failed before traffic moved | failed after |",
        "|---|---|---|---|---|",
    ]
    for target, counts in sorted(record["releases"].items()):
        lines.append(
            f"| {target} | {counts['ended']} | {_share(counts['verified'], counts['ended'])} | "
            f"{counts['failedBeforeTraffic']} | {counts['failedAfterTraffic']} |"
        )
    controlled = record["rollbacks"]["controlled"]
    organic = record["rollbacks"]["organic"]
    lines += [
        "",
        "| rollbacks | ended | restored (fingerprint back, health and smoke passing) |",
        "|---|---|---|",
        f"| in controlled episodes | {controlled['ended']} | "
        f"{_share(controlled['restored'], controlled['ended'])} |",
        f"| of releases nothing was injected into | {organic['ended']} | "
        f"{_share(organic['restored'], organic['ended'])} |",
    ]
    return "\n".join(lines) + "\n"


async def _rows(database_url: str) -> tuple[list[store.Row], int]:
    from psycopg import AsyncConnection
    from psycopg.rows import dict_row

    async with (
        await AsyncConnection.connect(database_url) as conn,
        conn.cursor(row_factory=dict_row) as cur,
    ):
        await cur.execute("SELECT * FROM app.deployments ORDER BY created_at")
        rows = await cur.fetchall()
    return rows, len({row["project_id"] for row in rows})


def _commit() -> str:
    done = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or "unknown"


def main(argv: list[str] | None = None) -> int:
    from ..config import get_settings

    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.deploy.table6",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    rows, projects = asyncio.run(_rows(get_settings().database_url))
    record = {
        "study": {
            "label": "Table 6, releases and rollbacks",
            "date": datetime.now(UTC).date().isoformat(),
            "commit": _commit(),
            "projects": projects,
        },
        **tally(rows),
    }
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / "table-6-releases-and-rollbacks.json"
        target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(render(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
