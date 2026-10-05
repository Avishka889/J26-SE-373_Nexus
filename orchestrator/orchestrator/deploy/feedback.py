"""Feedback after a window (FR22): what the release taught, kept for a person to send or not.

After every monitoring window, C4 is asked what the window and the release's own
assessment suggest for requirements (`summarise_feedback`), and its answer is
kept as the `feedback` artefact at the release's deploy version. Nothing goes to
C1 from here. A person reads each item and sends it (`POST
/projects/{id}/deployment/feedback/{itemId}/decision`), and only then does it
become a design change note for C1's next run (M5).
"""

import logging
import uuid
from typing import Any

from psycopg_pool import AsyncConnectionPool
from sdlc_contracts import FeedbackReport, ImpactReport, MonitoringReport, RiskReport

from ..db import store

log = logging.getLogger(__name__)


async def after_window(
    pool: AsyncConnectionPool, c4: Any, report: MonitoringReport
) -> FeedbackReport | None:
    """Ask C4 what one window suggests, keep it, and say so in the thread."""
    async with pool.connection() as conn:
        row = await store.get_deployment(conn, uuid.UUID(report.deployment_id))
        if row is None:
            return None
        found = await store.artefacts_at(
            conn, row["project_id"], version=report.version, kinds=("risk-report", "impact-report")
        )
    risk = (
        RiskReport.model_validate(found["risk-report"]["body"]) if "risk-report" in found else None
    )
    impact = (
        ImpactReport.model_validate(found["impact-report"]["body"])
        if "impact-report" in found
        else None
    )
    outcome = await c4.summarise_feedback(
        report,
        risk,
        impact,
        project_id=row["project_id"],
        deploy_version=report.version,
        fault_injected=row.get("fault_injected") or None,
    )
    feedback: FeedbackReport = outcome.artefact
    async with pool.connection() as conn:
        await store.put_artefact(
            conn,
            project_id=row["project_id"],
            kind="feedback",
            version=report.version,
            body=feedback.model_dump(by_alias=True, mode="json"),
        )
        if feedback.items:
            await store.post_thread_message(
                conn,
                row["project_id"],
                kind="system",
                author="platform",
                content=(
                    f"Deploy version {report.version}'s window suggests "
                    f"{len(feedback.items)} requirement change(s). Nothing is sent to "
                    "requirements until you send it."
                ),
                stage_id="monitoring",  # type: ignore[arg-type]
            )
    return feedback
