"""The rollback plan: where a restore would return to, how, and how anyone would know it did.

Written for every candidate before the release runs (FR19), and executed only
when a person approves it (FR20); the contract has no other value for approval.

**Where it returns to.** The latest release that was verified where it runs, on
the same target: a local image cannot restore a cloud release, nor the other way
round. A first release has nothing behind it, so its plan is not restorable and
says so, and every High update in it is unavailable, which the release guards
refuse (FR17: a High update ships only with a prepared rollback). The run's
selection already leaves High updates out of a first release; the plan says why
that had to be.

**How.** The recorded verified release is redeployed, never the provider's own
"previous deploy": locally, its image started by digest and the release port
moved to it; in the cloud, `deploy.yml` dispatched with the verified commit and
its candidate hash. Vercel Hobby can return only to the immediately previous
production deployment and Render's free plan only to its two most recent
deploys, so their buttons could not reach an older verified release.

**How anyone would know.** Restored means the served fingerprint is the verified
release's candidate hash, and health and the smoke requests answer; a redeploy
that finished proves nothing about what is served.
"""

from datetime import UTC, datetime

from sdlc_contracts import (
    ReleaseCandidate,
    RestoreStep,
    RiskReport,
    RollbackPlan,
    UpdateRollback,
    VerificationCheck,
    VerifiedRelease,
)

DATA_NOTE = (
    "The generated app keeps its data in memory, so a restore starts it empty, as any "
    "restart does. There is no schema to leave alone."
)
#: When this release keeps its records in the project's database.
DATABASE_NOTE = (
    "This release keeps its records in the project's MongoDB database, which a restore does "
    "not touch: they are still there after it. Nothing checks that the restored release can "
    "read them: it is older code, and this release may have written records with fields it "
    "does not know. A document database has no schema to put back, so compare the two "
    "releases' data models before restoring. A release generated before its code read "
    "MONGODB_URL keeps its records in memory and starts empty."
)


def keeps_a_database(candidate: ReleaseCandidate, database: bool) -> bool:
    """Whether this release keeps its records in a database: the project has one where it
    releases, and staging ran this candidate against one, which it does only for code that
    reads MONGODB_URL."""
    return database and any(
        step.name == "database" and step.outcome == "passed" for step in candidate.steps
    )


CLOUD_CONSTRAINTS = [
    "Vercel Hobby rolls back only to the immediately previous production deployment",
    "Render's free plan rolls back only to its two most recent deploys",
    "so a restore redeploys the verified commit through deploy.yml rather than pressing either",
]


def _unrestorable_reason(
    candidate: ReleaseCandidate, previous: VerifiedRelease | None, release_target: str
) -> str:
    if previous is None:
        return "this project has no verified release yet, so there is nothing to return to"
    if previous.target != release_target:
        return (
            f"the latest verified release ran on the {previous.target} target, and this release "
            f"goes to the {release_target} one"
        )
    if previous.candidate_hash == candidate.candidate_hash:
        return "the candidate is the verified release itself, so there is nothing to return to"
    if release_target == "local" and not previous.image_digest:
        return "the verified release recorded no image digest to start again"
    if release_target == "cloud" and not previous.commit_sha:
        return "the verified release recorded no commit to redeploy"
    return ""


def _steps(previous: VerifiedRelease, release_target: str) -> list[RestoreStep]:
    if release_target == "local":
        return [
            RestoreStep(
                id="start-verified",
                label="Start the verified release's image",
                provider="local-docker",
                action=f"start {previous.image_digest} on a free loopback port",
                constraint="the image is kept locally, by digest, for as long as it can be restored",
            ),
            RestoreStep(
                id="switch-back",
                label="Move the release port back to the verified release",
                provider="local-docker",
                action="stop the failed release's container and move the release port",
                moves_traffic=True,
            ),
        ]
    return [
        RestoreStep(
            id="restore-backend",
            label="Redeploy the verified commit's backend on Render",
            provider="render",
            action=f"deploy commit {previous.commit_sha} on Render, through Render's API",
            moves_traffic=True,
            constraint="Render builds the verified commit again from its Dockerfile",
        ),
        RestoreStep(
            id="redeploy-frontend",
            label="Redeploy the verified commit's frontend",
            provider="github",
            action=(
                f"dispatch deploy.yml with ref {previous.commit_sha} and candidate hash "
                f"{previous.candidate_hash}"
            ),
            moves_traffic=True,
            constraint="the workflow tests the commit, deploys its frontend, then verifies both",
        ),
    ]


def _checks(previous: VerifiedRelease, release_target: str) -> list[VerificationCheck]:
    roles = ["app"] if release_target == "local" else ["backend", "frontend"]
    checks: list[VerificationCheck] = []
    for role in roles:
        checks += [
            VerificationCheck(
                id=f"{role}-fingerprint",
                kind="fingerprint",
                role=role,  # type: ignore[arg-type]
                expect=f"/release.json names candidate {previous.candidate_hash}",
            ),
            VerificationCheck(
                id=f"{role}-health",
                kind="health",
                role=role,  # type: ignore[arg-type]
                expect="/release.json answers 200",
            ),
            VerificationCheck(
                id=f"{role}-smoke",
                kind="smoke",
                role=role,  # type: ignore[arg-type]
                expect="the page answers with HTML and every smoke request with JSON",
            ),
        ]
    return checks


def plan(
    candidate: ReleaseCandidate,
    risk: RiskReport,
    previous: VerifiedRelease | None,
    *,
    release_target: str,
    version: int,
    database: bool = False,
    now: datetime | None = None,
) -> RollbackPlan:
    """The plan for rolling back from this candidate, restorable or saying why not.

    `database` says the project has its own database where this release goes,
    which only a cloud release with an Atlas connection has.
    """
    reason = _unrestorable_reason(candidate, previous, release_target)
    restorable = not reason
    levels = {item.update_id: item.arbitration.final for item in risk.assessments}
    updates = []
    for update_id in candidate.included:
        level = levels.get(update_id, "high")
        if level != "high":
            updates.append(UpdateRollback(update_id=update_id, level=level, status="not-required"))
        elif restorable:
            updates.append(UpdateRollback(update_id=update_id, level=level, status="prepared"))
        else:
            updates.append(
                UpdateRollback(
                    update_id=update_id, level=level, status="unavailable", reason=reason
                )
            )
    return RollbackPlan(
        version=version,
        generated_at=now or datetime.now(UTC),
        candidate_hash=candidate.candidate_hash,
        restore_target=previous if restorable else None,
        restorable=restorable,
        unrestorable_reason=reason,
        steps=_steps(previous, release_target) if restorable and previous else [],
        checks=_checks(previous, release_target) if restorable and previous else [],
        updates=updates,
        provider_constraints=CLOUD_CONSTRAINTS if release_target == "cloud" else [],
        data_note=DATABASE_NOTE if keeps_a_database(candidate, database) else DATA_NOTE,
    )
