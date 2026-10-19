"""The deployment plan: C4's artefact, executed by the orchestrator's runner.

A full draft rather than a stub, because the plan is the thing a human reads
before anything is created, and because the saga cannot be designed without
knowing what a step and its compensation look like.

The shape encodes three decisions already recorded: the plan is an artefact and
execution is a job; provisioning is a saga with reverse order compensation, so
every step that creates something says how to undo it; and migrations are
forward only, so a rollback returns the application and leaves the schema alone.

Two things were added when C4 was built (2026-09-27). A step says whether it
moves production traffic, because that is where automatic compensation has to
stop: undoing a step that moved traffic is a rollback, and FR20 lets only a human
start one. And the plan records which approval locks were in force, because the
platform gate is always one and GitHub's environment rule is one only where the
repository's plan allows it.
"""

from typing import Literal

from pydantic import Field, model_validator

from .wire import WireDatetime, WireModel

#: `local-docker` is the release target the dev loop and the controlled failure
#: scenarios use, so nothing is spent in the cloud before a human asks for it.
ProviderId = Literal["github", "vercel", "render", "neon", "atlas", "local-docker"]

#: `app` is the whole one process application, which is how the generated MERN
#: projects run: the API serves the built frontend.
TargetRole = Literal["frontend", "backend", "database", "app"]

#: C2's catalog ids, because C2 owns the stack and C4 only reads it (proposal
#: 4.3). The draft said `spring-boot`, which no catalog entry is called.
StackTrack = Literal["mern", "react-spring-postgres"]

ReleaseTarget = Literal["local", "cloud"]

#: Whether GitHub's environment rule could mirror the platform's decision.
#: Environments do not exist at all on a private repository of a free account,
#: and required reviewers exist on a private repository only on the enterprise
#: plan; a public repository has both on every plan.
GithubProtection = Literal[
    "configured",
    "unavailable-private-repo",
    "unavailable-plan",
    "not-applicable",
]


class DeployTarget(WireModel):
    role: TargetRole
    provider: ProviderId
    #: What will be created, or the existing resource that will be reused.
    resource: str = Field(min_length=1)
    root_dir: str | None = None
    runtime: str | None = None
    note: str | None = None


class DeployStep(WireModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    #: Who carries the step out, or None for a step that asks nobody outside
    #: the orchestrator, such as a check.
    provider: ProviderId | None = None
    #: The step that must succeed first. Null for the first step.
    depends_on: str | None = None
    #: How to undo this step if a later one fails. Null means the step creates
    #: nothing, so there is nothing to undo: a build, not a provision.
    compensation: str | None = None
    #: Whether this step points production at something new. Compensation stops
    #: here: undoing it is a rollback, which only a human may start.
    moves_traffic: bool = False

    @model_validator(mode="after")
    def moving_traffic_says_how_to_move_it_back(self) -> "DeployStep":
        if self.moves_traffic and not self.compensation:
            raise ValueError(
                f"step {self.id} moves traffic, so it must say how traffic is moved back"
            )
        return self


class WiringRule(WireModel):
    """How one part learns the address of another, in plain words."""

    name: str = Field(min_length=1)
    from_: str = Field(min_length=1, alias="from")
    to: str = Field(min_length=1)


class RollbackPolicy(WireModel):
    strategy: Literal["application-only"] = "application-only"
    note: str = Field(min_length=1)


class EnvironmentProtection(WireModel):
    """Which approval locks were in force for this plan."""

    #: The reviewer of record, always.
    mechanism: Literal["platform-gate"] = "platform-gate"
    github: GithubProtection
    reason: str = ""


class DeployPlan(WireModel):
    plan_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    generated_by: str = Field(min_length=1)
    generated_at: WireDatetime
    deploy_version: int = Field(ge=1)
    stack: StackTrack
    target: ReleaseTarget
    #: The hash of every file the candidate is built from: the code version,
    #: the lockfile and the deployment layer. Staging verifies this candidate
    #: and a release deploys it; neither may substitute another.
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    targets: list[DeployTarget] = Field(min_length=1)
    steps: list[DeployStep] = Field(min_length=1)
    wiring: list[WiringRule] = Field(default_factory=list)
    rollback: RollbackPolicy
    environment_protection: EnvironmentProtection

    @model_validator(mode="after")
    def step_order_is_a_real_chain(self) -> "DeployPlan":
        """Dependencies must resolve and must not run backwards, because the
        saga compensates in reverse and a cycle would never terminate."""
        seen: set[str] = set()
        for step in self.steps:
            if step.id in seen:
                raise ValueError(f"step {step.id} appears twice")
            if step.depends_on is not None and step.depends_on not in seen:
                raise ValueError(
                    f"step {step.id} depends on {step.depends_on}, which does not run before it"
                )
            seen.add(step.id)
        return self
