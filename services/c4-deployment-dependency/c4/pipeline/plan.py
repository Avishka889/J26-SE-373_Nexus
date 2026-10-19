"""The deploy plan: what a release will create, in what order, and how each step is undone.

The plan is an artefact a person reads before anything is created, and the
orchestrator's saga executes it step by step (architecture decisions 2 and 3).
Every step says who carries it out, what it depends on, how it is compensated,
and whether it moves production traffic: compensation runs automatically only
before that step, and after it undoing is a rollback, which a person must
approve (FR20).

**Local target**: the dev loop and the controlled failure scenarios. The staging
container, already verified, is the preview; the release starts the candidate's
image beside the running release, checks it, then moves the release port to it.

**Cloud target**: the orchestrator commits the deployment layer on top of C2's
commit, stores the deploy secrets in the repository, dispatches `deploy.yml`
with the commit and the candidate hash, and verifies what both hosts serve. The
workflow's backend and frontend jobs are where traffic moves, so the dispatch
is the step that moves it.

**Rollback** is application only: the generated app keeps its data in memory,
so a restart of any release, the rolled back one included, starts it empty, and
there is no schema to leave alone.
"""

from sdlc_contracts import (
    DeployPlan,
    DeployStep,
    DeployTarget,
    EnvironmentProtection,
    RollbackPolicy,
    WiringRule,
)

from .generate import Generated

_RUNTIME_ONE_PROCESS = "the backend serves the built frontend: one process, one port"

_PROTECTION_REASON = {
    "configured": "GitHub's environment rule mirrors the platform's decision",
    "unavailable-private-repo": (
        "C2 pushes private repositories, and GitHub Free has no environments on them; "
        "the platform gate is the only lock"
    ),
    "unavailable-plan": "the owner's plan has environments without required reviewers",
    "not-applicable": "the local target runs no workflow",
}


ROLLBACK_NOTE = (
    "Application only. A rollback redeploys the recorded verified release, never the "
    "provider's previous deploy. "
)
MEMORY_ROLLBACK = (
    "The generated app keeps its data in memory, so any restart, a rollback's included, "
    "starts it empty."
)
#: For code that reads MONGODB_URL, released to the cloud, which is where a
#: project has a database. The note said memory whatever the code did, while the
#: rollback plan beside it said a database (review item C4-12). Whether this
#: release has one is known only once staging has run it, so the plan says when.
DATABASE_ROLLBACK = (
    "This code keeps its records in the project's database when the release has one, and a "
    "rollback does not touch them: the restored release is older code and may not read "
    "records the newer one wrote. Without a database it keeps them in memory, and any "
    "restart, a rollback's included, starts it empty."
)


def _node(generated: Generated) -> str:
    runtime = generated.detected.runtime if generated.detected else None
    minimum = runtime.node_minimum if runtime else None
    return f"node {minimum}+ (strip types)" if minimum else "node"


def deploy_plan(
    generated: Generated,
    *,
    project_id: str,
    release_target: str,
    github_protection: str | None,
    version: int,
    reads_database: bool = False,
) -> DeployPlan:
    """The plan for a supported stack's generated layer."""
    config = generated.config
    layout = config.stack.layout
    if not config.stack.supported or layout is None:
        raise ValueError("an unsupported stack has no plan: nothing was generated to deploy")
    notes = generated.notes
    common = {
        "plan_id": f"{project_id}-deploy-v{version}",
        "project_id": project_id,
        "generated_by": "c4 pipeline generation, mern templates",
        "generated_at": config.generated_at,
        "deploy_version": version,
        "stack": "mern",
        "candidate_hash": config.candidate_hash,
        "rollback": RollbackPolicy(
            note=ROLLBACK_NOTE
            + (
                DATABASE_ROLLBACK
                if release_target == "cloud" and reads_database
                else MEMORY_ROLLBACK
            )
        ),
    }
    if release_target == "local":
        return DeployPlan(
            **common,
            target="local",
            targets=[
                DeployTarget(
                    role="app",
                    provider="local-docker",
                    resource=f"the image {notes.get('image')}, run on 127.0.0.1",
                    root_dir=".",
                    runtime=_node(generated),
                    note=_RUNTIME_ONE_PROCESS,
                )
            ],
            steps=[
                DeployStep(
                    id="start",
                    label="Start the verified candidate beside the running release",
                    provider="local-docker",
                    compensation="stop and remove the candidate's container",
                ),
                DeployStep(
                    id="check",
                    label="Check it serves the candidate's fingerprint, and answers health and smoke",
                    depends_on="start",
                ),
                DeployStep(
                    id="switch",
                    label="Move the release port to the candidate",
                    provider="local-docker",
                    depends_on="check",
                    compensation=(
                        "start the recorded verified release's image by digest on the release "
                        "port, once a person approves the rollback"
                    ),
                    moves_traffic=True,
                ),
                DeployStep(
                    id="verify",
                    label="Check the release port serves the candidate",
                    depends_on="switch",
                ),
            ],
            wiring=[
                WiringRule(
                    name="Same origin",
                    **{"from": layout.frontend_dir or "frontend"},
                    to="the backend on the same port",
                )
            ],
            environment_protection=EnvironmentProtection(
                github="not-applicable", reason=_PROTECTION_REASON["not-applicable"]
            ),
        )

    protection = github_protection or "unavailable-private-repo"
    return DeployPlan(
        **common,
        target="cloud",
        targets=[
            DeployTarget(
                role="backend",
                provider="render",
                resource=f"the Render web service the platform made, at {notes.get('backend_origin')}",
                root_dir=".",
                runtime=f"docker, {_node(generated)}",
                note="built from the generated Dockerfile; it also serves the pages",
            ),
            DeployTarget(
                role="frontend",
                provider="vercel",
                resource=f"the Vercel project, at {notes.get('frontend_origin')}",
                root_dir=".",
                runtime=f"static build of {layout.frontend_dir}",
                note="calls the backend through its /api rewrite, so no CORS is needed",
            ),
        ],
        steps=[
            # No compensation: a commit serves nothing, and undoing it would rewrite
            # the repository's history. The ledger records it either way.
            DeployStep(
                id="commit",
                label="Commit the deployment layer on top of the code commit",
                provider="github",
            ),
            DeployStep(
                id="secrets",
                label="Store the Vercel secrets in the repository, sealed to its public key",
                provider="github",
                depends_on="commit",
                compensation="delete the secrets this release created",
            ),
            # The commit tested and its frontend built before anything moves traffic:
            # the backend went live on Render first, so a failing test needed a
            # rollback (review item C4-8). Nothing to undo: a run serves nothing.
            DeployStep(
                id="test",
                label="Dispatch deploy.yml to test the commit and build its frontend",
                provider="github",
                depends_on="secrets",
            ),
            # The platform deploys the backend itself, through Render's API: Render's
            # API cannot make the deploy hook GitHub would otherwise have called, and
            # the Render key never leaves the orchestrator.
            DeployStep(
                id="backend",
                label="Deploy the commit's backend on Render, through Render's API",
                provider="render",
                depends_on="test",
                compensation=(
                    "redeploy the recorded verified release's commit on Render, once a person "
                    "approves the rollback"
                ),
                moves_traffic=True,
            ),
            DeployStep(
                id="dispatch",
                label="Dispatch deploy.yml to deploy the commit's frontend and verify both",
                provider="github",
                depends_on="backend",
                compensation=(
                    "dispatch deploy.yml with the recorded verified release's commit, once a "
                    "person approves the rollback"
                ),
                moves_traffic=True,
            ),
            DeployStep(
                id="verify",
                label="Check both hosts serve the candidate's fingerprint, then health and smoke",
                depends_on="dispatch",
            ),
        ],
        wiring=[
            WiringRule(
                name="VITE_API_URL",
                **{"from": "the frontend build"},
                to="/api, which vercel.json rewrites to the backend",
            ),
            WiringRule(
                name="The /api rewrite",
                **{"from": "vercel.json"},
                to=str(notes.get("backend_origin")),
            ),
        ],
        environment_protection=EnvironmentProtection(
            github=protection,  # type: ignore[arg-type]
            reason=_PROTECTION_REASON.get(protection, ""),
        ),
    )
