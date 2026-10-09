"""Closing a review that the phase has moved past, so the phase can start again.

A run waits at its review pinned to what it was made from: code to a design
version, tests to a code version, a release analysis to a test version and the
code that tested. When that moves on and the newer one is settled, the review
waiting on it is of something no longer current, and deciding it only repeats
the old input: requesting changes regenerates from the same pin, and an
approval is either refused (a release over code its tests no longer cover) or
approves what is no longer there.

So starting the phase again closes it. The review is resolved as changes, by
the person whose action closed it, with the reason as its note, which is what
it was in effect; its run is superseded, which the runner treats as finished;
and a run of its own starts on the current version, with provenance of its own
rather than a pin rewritten underneath an older one.
"""

from typing import Any

from ..db import store
from ..errors import Conflict


async def close_stale_review(
    conn: Any,
    project_id: str,
    gate: store.Row,
    *,
    by: str,
    reason: str,
    stage_id: str,
    category: str,
    what: str,
) -> None:
    """Resolve the review as moved past, supersede its run, and say so where it is read.

    `what` names the version under review, as Activity names it ("code version 3").
    """
    resolved = await store.resolve_gate(conn, gate["id"], decision="changes", by=by, note=reason)
    if resolved is None:
        raise Conflict("that review was decided while this was being started")
    await store.set_run_state(conn, gate["run_id"], "superseded", resume_payload=None)
    await store.post_thread_message(
        conn,
        project_id,
        kind="system",
        author=by,
        content=f"Closed the review of {what}: {reason}",
        stage_id=stage_id,
    )
    await store.record(
        conn,
        actor=by,
        action="Closed a review the phase moved past",
        target=what,
        detail=reason[:500],
        project_id=project_id,
        run_id=gate["run_id"],
        category=category,
    )
