"""The deployment phase's nodes.

C1's two rules hold unchanged: nodes compute and persist idempotently and never
write run or gate lifecycle rows, and the gate node contains nothing but
`interrupt()`, because LangGraph re-executes an interrupted node on resume.

Four things are C4's own.

**Every stage reads at pinned versions.** A run pins the test version whose
approval it starts from. The first stage looks up the code version that test
version tested and puts it in state, and every later stage reads the code, the
contract, the manifest and the graph at that version, and the design version
behind it. Code regenerated while a deployment run is in flight cannot change
what it analyses.

**Which stages can fail a run.** Detection, the risk assessment, pipeline
generation and staging are load bearing: each is what a later stage stands on.
The changelog, impact and rollback stages are leaves. When one of the first two
fails, its signal abstains and the risk assessment says so, which is the honest
version of a missing signal rather than a missing run. A failed rollback plan
leaves every high update without a prepared rollback, which the release guards
refuse.

**A candidate that does not build is an outcome, not a failure.** Staging exists
to find exactly that, so a failed build completes the stage with an unverified
candidate. A stage with nothing to do, because the stack has no templates or no
Docker daemon answers, is skipped and says why.

**Release and monitoring are not here.** They outlive a run, so the saga runner
and the monitor execute them after the gate. Until they land, an approval ends
the run.
"""

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from langgraph.graph import END
from langgraph.types import Command, interrupt
from psycopg_pool import AsyncConnectionPool
from sdlc_contracts import (
    ApiContract,
    ApiContractArtefact,
    ArchitectureGraph,
    ChangelogReport,
    CodeRepository,
    DependencyUpdates,
    DeployPlan,
    ImpactReport,
    ManifestRow,
    PipelineConfig,
    ReleaseCandidate,
    RepositoryPointer,
    RiskReport,
    TechStackArtefact,
    VerifiedRelease,
)

from ..clients.c3 import StageNotApplicable
from ..clients.c4 import C4Client
from ..db import store
from ..errors import readable_failure
from ..model_use import stage_model_use
from ..wording import readable_notes, stage_label
from .state import C4RunState

AUTHOR = "Deployment agent"
CATEGORY = "deployment"
GATE_KIND = "c4-deploy-review"


class ApprovalMissing(RuntimeError):
    """The test review has not approved the version this run was pinned to."""


# ------------------------------------------------------------------- reading


async def _deploy_body(pool: AsyncConnectionPool, state: C4RunState, kind: str) -> Any:
    async with pool.connection() as conn:
        rows = await store.artefacts_at(
            conn, state["project_id"], version=state["deploy_version"], kinds=(kind,)
        )
    found = rows.get(kind)
    return found["body"] if found else None


async def _code_body(pool: AsyncConnectionPool, state: C4RunState, kind: str) -> Any:
    async with pool.connection() as conn:
        rows = await store.artefacts_at(
            conn, state["project_id"], version=state["code_version"], kinds=(kind,)
        )
    found = rows.get(kind)
    return found["body"] if found else None


async def _updates(pool: AsyncConnectionPool, state: C4RunState) -> DependencyUpdates:
    body = await _deploy_body(pool, state, "dependency-updates")
    if body is None:
        raise RuntimeError("no dependency updates were recorded at this deploy version")
    return DependencyUpdates.model_validate(body)


async def _optional[T](
    pool: AsyncConnectionPool, state: C4RunState, kind: str, model: type[T]
) -> T | None:
    body = await _deploy_body(pool, state, kind)
    return model.model_validate(body) if body is not None else None  # type: ignore[attr-defined]


async def _files(pool: AsyncConnectionPool, state: C4RunState) -> dict[str, str]:
    async with pool.connection() as conn:
        return await store.code_files(conn, state["project_id"], version=state["code_version"])


async def _with_baseline(pool: AsyncConnectionPool, state: C4RunState) -> dict[str, str]:
    """The code with the baseline pin beside it: what the analysis starts from,
    and what the candidate's lockfile is the included updates applied to."""
    files = await _files(pool, state)
    async with pool.connection() as conn:
        pinned = await store.deploy_files(
            conn,
            state["project_id"],
            version=state["deploy_version"],
            stage_id="dependency-updates",
        )
    if "package-lock.json" in pinned:
        files = {**files, "package-lock.json": pinned["package-lock.json"]}
    return files


def _pipeline_settings(state: C4RunState) -> dict[str, Any]:
    """What generation needs that the files do not say. The slug names the Render
    service and the Vercel project, so it is the project id, which is unique,
    in the characters both accept."""
    project = state["project_id"]
    slug = re.sub(r"[^a-z0-9-]+", "-", project.lower()).strip("-")[:40] or "app"
    return {"project_id": project, "project_slug": slug}


async def _cloud_settings(pool: AsyncConnectionPool, c4: C4Client, state: C4RunState):
    """The project's cloud resources, made now if they do not exist, and what GitHub enforces.

    Made before the layer is generated, so the layer names the real addresses:
    the frontend's `/api` rewrite points at the backend Render gave, not at a
    name it was hoped Render would give. The canned component answers for the
    resources in tests, so a test never reaches Vercel or Render.
    """
    from ..config import get_settings
    from ..crypto import decrypt
    from ..deploy import provision as provisioning
    from ..probes.github import repository_protection

    project_id = state["project_id"]
    async with pool.connection() as conn:
        project = await store.project_without_owner_check(conn, project_id)
        if project is None:
            raise RuntimeError("the project no longer exists")
        owner = project["owner_id"]
        github = await store.get_secret(conn, f"{owner}:github")
        found, _ = await store.repository_field_through_patches(
            conn, project_id, state["code_version"], "repository"
        )
    canned = getattr(c4, "provision_cloud", None)
    made = (
        await canned(project_id)
        if canned is not None
        else await provisioning.provision(
            pool, project_id, owner=owner, secret_key=get_settings().secret_key
        )
    )
    settings: dict[str, Any] = {
        "backend_origin": made.render.origin,
        "frontend_origin": made.vercel.origin,
    }
    pointer = RepositoryPointer.model_validate(found) if found else None
    if github is not None and pointer is not None and canned is None:
        protection, _ = await repository_protection(
            decrypt(get_settings().secret_key, github), pointer.owner, pointer.name
        )
        settings["github_protection"] = protection
    return settings


async def _contract(pool: AsyncConnectionPool, state: C4RunState) -> ApiContract | None:
    body = await _code_body(pool, state, "api-contract")
    return ApiContractArtefact.model_validate(body).contract if body else None


async def _manifest(pool: AsyncConnectionPool, state: C4RunState) -> list[ManifestRow]:
    body = await _code_body(pool, state, "code-repository")
    return list(CodeRepository.model_validate(body).manifest) if body else []


async def _design_version(pool: AsyncConnectionPool, state: C4RunState) -> int | None:
    async with pool.connection() as conn:
        return await store.design_version_for_code(conn, state["project_id"], state["code_version"])


async def _graph(pool: AsyncConnectionPool, design_version: int | None, project_id: str):
    """The Semantic Architecture Graph at the design version behind the code.

    Pinned, never the latest: a design that moved on after this code was
    generated describes components this code does not have.
    """
    if not design_version:
        return None
    async with pool.connection() as conn:
        rows = await store.artefacts_at(
            conn, project_id, version=design_version, kinds=("architecture-graph",)
        )
    found = rows.get("architecture-graph")
    return ArchitectureGraph.model_validate(found["body"]) if found else None


async def _choices(pool: AsyncConnectionPool, project_id: str) -> dict[tuple[str, str], store.Row]:
    """The newest human decision per kind and target, across versions."""
    async with pool.connection() as conn:
        rows = await store.overlays(conn, project_id)
    latest: dict[tuple[str, str], store.Row] = {}
    for row in rows:
        latest[(row["kind"], row["target_id"])] = row
    return latest


async def _stack_id(pool: AsyncConnectionPool, state: C4RunState) -> str:
    """The stack C2 chose: a person's selection if there is one, else C2's own.

    The newest selection, as the code read model takes it too.
    """
    choice = (await _choices(pool, state["project_id"])).get(("stack_selection", "stack"))
    if choice:
        return str(choice["value"])
    body = await _code_body(pool, state, "tech-stack")
    if body:
        stack = TechStackArtefact.model_validate(body)
        return stack.selected_id or stack.recommended_id
    return "mern"


async def _release_target(pool: AsyncConnectionPool, state: C4RunState) -> str:
    from ..config import get_settings

    choice = (await _choices(pool, state["project_id"])).get(("release_target", "target"))
    return str(choice["value"]) if choice else get_settings().c4_release_target_default


async def _has_a_database(pool: AsyncConnectionPool, state: C4RunState) -> bool:
    """Whether the platform made this project a database for its cloud releases."""
    from ..deploy.provision import cloud_resources_of

    async with pool.connection() as conn:
        project = await store.project_without_owner_check(conn, state["project_id"])
        if project is None:
            return False
        made = await cloud_resources_of(conn, state["project_id"], project["owner_id"])
    return made is not None and made.database is not None


async def _previous_release(pool: AsyncConnectionPool, state: C4RunState) -> VerifiedRelease | None:
    """The release a rollback would return to, or None on a first release."""
    from ..deploy.records import verified_release

    async with pool.connection() as conn:
        row = await store.latest_verified_release(conn, state["project_id"])
    return verified_release(row) if row is not None else None


async def _decisions(pool: AsyncConnectionPool, project_id: str) -> dict[str, dict[str, Any]]:
    """Each update's newest decision, from any deploy version, as the guards read them."""
    from ..deploy.guards import newest_decisions

    async with pool.connection() as conn:
        rows = newest_decisions(await store.overlays(conn, project_id))
    return {
        update_id: dict(row["value"])
        for update_id, row in rows.items()
        if isinstance(row["value"], dict)
    }


def _selection(
    risk: RiskReport,
    previous: VerifiedRelease | None,
    release_target: str,
    decisions: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[str], list[dict[str, str]]]:
    """Which updates the candidate carries.

    One candidate per run: every update the rule rated low or medium, and a high
    update only when a verified release on the release's own target exists to
    fall back to, because FR17's prepared rollback needs somewhere to go, and a
    release on another target is nowhere it can go (the rollback plan says so,
    and G2 would refuse the release). The gate decides about the rest.

    An update a person left out or deferred at a review stays out, with their
    note, for as long as the decision counts (G3's rule: until its level rises
    above the one it was taken at). Without that, the rebuild G3 asks for carried
    the update again, and G3 refused it again.
    """
    from ..deploy.guards import still_counts

    included: list[str] = []
    excluded: list[dict[str, str]] = []
    if previous is None:
        nowhere = (
            "a high update needs a verified release to roll back to, and this project has none yet"
        )
    elif previous.target != release_target:
        nowhere = (
            f"a high update needs a verified release on the {release_target} target to roll "
            f"back to, and this project's is on the {previous.target} one"
        )
    else:
        nowhere = ""
    for assessment in risk.assessments:
        decision = (decisions or {}).get(assessment.update_id) or {}
        if decision.get("decision") in ("rejected", "deferred") and still_counts(
            decision.get("levelAtDecision"), assessment.arbitration.final
        ):
            excluded.append(
                {
                    "updateId": assessment.update_id,
                    "reason": str(decision["decision"]),
                    "detail": str(decision.get("note") or "").strip()
                    or f"{decision['decision']} at a review",
                }
            )
        elif assessment.arbitration.final == "high" and nowhere:
            excluded.append(
                {
                    "updateId": assessment.update_id,
                    "reason": "no-restore-target",
                    "detail": nowhere,
                }
            )
        else:
            included.append(assessment.update_id)
    return included, excluded


# ------------------------------------------------------------------- writing


async def _beat(pool: AsyncConnectionPool, state: C4RunState) -> None:
    async with pool.connection() as conn:
        await store.heartbeat(conn, uuid.UUID(state["run_id"]))


async def _audit(conn: Any, state: C4RunState, action: str, detail: str) -> None:
    await store.record(
        conn,
        actor=AUTHOR,
        action=action,
        target=f"deploy version {state['deploy_version']}",
        detail=detail,
        project_id=state["project_id"],
        run_id=uuid.UUID(state["run_id"]),
        category=CATEGORY,
    )


async def _persist(
    pool: AsyncConnectionPool,
    state: C4RunState,
    *,
    stage_id: str,
    artefacts: dict[str, dict[str, Any]],
    summary: str,
    notes: dict[str, Any],
    files: dict[str, str] | None = None,
) -> None:
    """One stage's artefacts, files and record, in one transaction."""
    async with pool.connection() as conn:
        for kind, body in artefacts.items():
            await store.put_artefact(
                conn,
                project_id=state["project_id"],
                kind=kind,  # type: ignore[arg-type]
                version=state["deploy_version"],
                body=body,
                run_id=uuid.UUID(state["run_id"]),
            )
        if files is not None:
            await store.put_deploy_files(
                conn,
                state["project_id"],
                version=state["deploy_version"],
                stage_id=stage_id,
                files=files,
            )
        await store.set_stage(
            conn,
            state["project_id"],
            stage_id,  # type: ignore[arg-type]
            status="complete",
            version=state["deploy_version"],
            summary=summary,
            model_use=stage_model_use(notes),
        )
        await _audit(conn, state, f"Generated {stage_label(stage_id)}", readable_notes(notes))


async def _skip(pool: AsyncConnectionPool, state: C4RunState, stage_id: str, reason: str) -> None:
    async with pool.connection() as conn:
        await store.set_stage(
            conn,
            state["project_id"],
            stage_id,  # type: ignore[arg-type]
            status="skipped",
            summary=reason,
        )
        await _audit(conn, state, f"Skipped {stage_id}", reason)


async def _fail(
    pool: AsyncConnectionPool, state: C4RunState, stage_id: str, error: Exception
) -> None:
    reason = readable_failure(error)
    async with pool.connection() as conn:
        await store.set_stage(
            conn,
            state["project_id"],
            stage_id,  # type: ignore[arg-type]
            status="failed",
            error=reason,
        )
        await _audit(conn, state, f"Failed to generate {stage_label(stage_id)}", reason)


@asynccontextmanager
async def _recording_failure(
    pool: AsyncConnectionPool, state: C4RunState, stage_id: str
) -> AsyncIterator[None]:
    """Mark a load bearing stage failed on the way out, then fail the run."""
    await _beat(pool, state)
    try:
        yield
    except StageNotApplicable as skip:
        await _skip(pool, state, stage_id, skip.reason)
    except Exception as error:
        await _fail(pool, state, stage_id, error)
        raise


def _leaf(stage_id: str, pool: AsyncConnectionPool, call):
    """A stage whose failure the run survives: its signal abstains instead."""

    async def node(state: C4RunState) -> C4RunState:
        await _beat(pool, state)
        try:
            await call(state)
        except StageNotApplicable as skip:
            await _skip(pool, state, stage_id, skip.reason)
        except Exception as error:
            await _fail(pool, state, stage_id, error)
        return state

    node.__name__ = stage_id.replace("-", "_")
    return node


# --------------------------------------------------------------------- nodes


def make_dependency_updates(pool: AsyncConnectionPool, c4: C4Client):
    """What the registries offer, for the code the test review approved.

    Load bearing, and the place the approval is checked again: the route that
    started the run checked it, and a run resumed a day later checks it here,
    because a deployment analysis of code nobody approved is analysis of the
    wrong thing.
    """

    async def node(state: C4RunState) -> C4RunState:
        stage_id = "dependency-updates"
        async with _recording_failure(pool, state, stage_id):
            project_id = state["project_id"]
            async with pool.connection() as conn:
                approved = await store.version_is_approved(
                    conn, project_id, gate_kind="c3-test-review", version=state["test_version"]
                )
                tested = await store.run_for_version(
                    conn, project_id, component="c3", version=state["test_version"]
                )
            if not approved:
                raise ApprovalMissing(
                    f"test version {state['test_version']} has not been approved, "
                    "so there is nothing this phase may deploy"
                )
            code_version = int((tested or {}).get("source_version") or 0)
            if not code_version:
                raise RuntimeError(
                    f"no testing run produced test version {state['test_version']}, "
                    "so the code it tested is unknown"
                )
            state = {**state, "code_version": code_version}

            from .code_nodes import _github_token

            choice = (await _choices(pool, project_id)).get(("update_scope", "scope"))
            scope = choice["value"] if choice else {}
            outcome = await c4.detect_updates(
                await _files(pool, state),
                target=str(scope.get("target", "generated"))
                if isinstance(scope, dict)
                else "generated",
                version=state["deploy_version"],
                code_version=code_version,
                test_version=state["test_version"],
                packages=scope.get("packages") if isinstance(scope, dict) else None,
                github_token=await _github_token(pool, project_id),
            )
            await _persist(
                pool,
                state,
                stage_id=stage_id,
                artefacts={
                    "dependency-updates": outcome.report.model_dump(by_alias=True, mode="json")
                },
                summary=outcome.summary,
                notes=outcome.notes,
                files=outcome.texts,
            )
        return state

    return node


def make_changelog_analysis(pool: AsyncConnectionPool, c4: C4Client):
    """Claims from the release notes, each quote checked. A leaf: its signal abstains."""

    async def call(state: C4RunState) -> None:
        updates = await _updates(pool, state)
        async with pool.connection() as conn:
            texts = await store.deploy_files(
                conn,
                state["project_id"],
                version=state["deploy_version"],
                stage_id="dependency-updates",
            )
        outcome = await c4.analyse_changelogs(updates, texts, version=state["deploy_version"])
        await _persist(
            pool,
            state,
            stage_id="changelog-analysis",
            artefacts={"changelog-report": outcome.artefact.model_dump(by_alias=True, mode="json")},
            summary=outcome.summary,
            notes=outcome.notes,
        )

    return _leaf("changelog-analysis", pool, call)


def make_impact_analysis(pool: AsyncConnectionPool, c4: C4Client):
    """Files that use what changed, and the graph nodes they are. A leaf."""

    async def call(state: C4RunState) -> None:
        design_version = await _design_version(pool, state)
        # The baseline pin's `bin` entries say which package a script's command
        # belongs to.
        files = await _with_baseline(pool, state)
        outcome = await c4.analyse_impact(
            files,
            await _updates(pool, state),
            await _optional(pool, state, "changelog-report", ChangelogReport),
            graph=await _graph(pool, design_version, state["project_id"]),
            contract=await _contract(pool, state),
            manifest=await _manifest(pool, state),
            version=state["deploy_version"],
            code_version=state["code_version"],
            design_version=design_version,
        )
        await _persist(
            pool,
            state,
            stage_id="impact-analysis",
            artefacts={"impact-report": outcome.artefact.model_dump(by_alias=True, mode="json")},
            summary=outcome.summary,
            notes=outcome.notes,
        )

    return _leaf("impact-analysis", pool, call)


def make_risk_assessment(pool: AsyncConnectionPool, c4: C4Client):
    """Three votes per update and the rule that combines them. Load bearing."""

    async def node(state: C4RunState) -> C4RunState:
        async with _recording_failure(pool, state, "risk-assessment"):
            outcome = await c4.assess_risk(
                await _updates(pool, state),
                await _optional(pool, state, "changelog-report", ChangelogReport),
                await _optional(pool, state, "impact-report", ImpactReport),
                version=state["deploy_version"],
            )
            await _persist(
                pool,
                state,
                stage_id="risk-assessment",
                artefacts={"risk-report": outcome.artefact.model_dump(by_alias=True, mode="json")},
                summary=outcome.summary,
                notes=outcome.notes,
            )
        return state

    return node


def make_pipeline_generation(pool: AsyncConnectionPool, c4: C4Client):
    """The pipeline and deployment configuration for the stack C2 chose. Load bearing."""

    async def node(state: C4RunState) -> C4RunState:
        async with _recording_failure(pool, state, "pipeline-generation"):
            risk = await _optional(pool, state, "risk-report", RiskReport)
            if risk is None:
                raise RuntimeError("there is no risk report to generate a pipeline from")
            included, _ = _selection(
                risk,
                await _previous_release(pool, state),
                await _release_target(pool, state),
                await _decisions(pool, state["project_id"]),
            )
            release_target = await _release_target(pool, state)
            settings = _pipeline_settings(state)
            if release_target == "cloud":
                settings |= await _cloud_settings(pool, c4, state)
            outcome = await c4.generate_pipeline(
                await _with_baseline(pool, state),
                await _updates(pool, state),
                risk,
                stack_id=await _stack_id(pool, state),
                contract=await _contract(pool, state),
                release_target=release_target,
                included=included,
                settings=settings,
                version=state["deploy_version"],
                code_version=state["code_version"],
            )
            artefacts = {"pipeline-config": outcome.config.model_dump(by_alias=True, mode="json")}
            if outcome.plan is not None:
                plan = outcome.plan.model_copy(update={"project_id": state["project_id"]})
                artefacts["deploy-plan"] = plan.model_dump(by_alias=True, mode="json")
            await _persist(
                pool,
                state,
                stage_id="pipeline-generation",
                artefacts=artefacts,
                summary=outcome.summary,
                notes=outcome.notes,
                files=outcome.files,
            )
        return state

    return node


def make_staging_verification(pool: AsyncConnectionPool, c4: C4Client):
    """The candidate built, tested, booted and smoke tested. Load bearing."""

    async def node(state: C4RunState) -> C4RunState:
        async with _recording_failure(pool, state, "staging-verification"):
            config = await _optional(pool, state, "pipeline-config", PipelineConfig)
            if config is None or not config.stack.supported:
                raise StageNotApplicable(
                    "the stack has no validated templates, so there is no candidate to build"
                )
            risk = await _optional(pool, state, "risk-report", RiskReport)
            included, excluded = (
                _selection(
                    risk,
                    await _previous_release(pool, state),
                    await _release_target(pool, state),
                    await _decisions(pool, state["project_id"]),
                )
                if risk
                else ([], [])
            )
            async with pool.connection() as conn:
                layer = await store.deploy_files(
                    conn,
                    state["project_id"],
                    version=state["deploy_version"],
                    stage_id="pipeline-generation",
                )
            outcome = await c4.verify_candidate(
                await _files(pool, state),
                layer,
                candidate_hash=config.candidate_hash,
                included=included,
                excluded=excluded,
                version=state["deploy_version"],
                code_version=state["code_version"],
                updates=await _updates(pool, state),
                settings=_pipeline_settings(state),
            )
            await _persist(
                pool,
                state,
                stage_id="staging-verification",
                artefacts={
                    "release-candidate": outcome.artefact.model_dump(by_alias=True, mode="json")
                },
                summary=outcome.summary,
                notes=outcome.notes,
            )
        return state

    return node


def make_rollback_planning(pool: AsyncConnectionPool, c4: C4Client):
    """Where a restore would return to, prepared before anything ships. A leaf."""

    async def call(state: C4RunState) -> None:
        candidate = await _optional(pool, state, "release-candidate", ReleaseCandidate)
        risk = await _optional(pool, state, "risk-report", RiskReport)
        if candidate is None or risk is None:
            raise StageNotApplicable("there is no candidate to prepare a rollback for")
        target = await _release_target(pool, state)
        outcome = await c4.plan_rollback(
            candidate,
            risk,
            await _previous_release(pool, state),
            release_target=target,
            version=state["deploy_version"],
            database=target == "cloud" and await _has_a_database(pool, state),
        )
        await _persist(
            pool,
            state,
            stage_id="rollback-planning",
            artefacts={"rollback-plan": outcome.artefact.model_dump(by_alias=True, mode="json")},
            summary=outcome.summary,
            notes=outcome.notes,
        )

    return _leaf("rollback-planning", pool, call)


def deployment_review(
    state: C4RunState,
) -> Command[Literal["dependency_updates", "release_handover"]]:
    """The phase gate, and deliberately nothing else.

    Everything above `interrupt()` re-runs when a human answers, so there is
    nothing above it. Approval hands the release over with the decision that
    authorised it; a change is regenerated at the version the route allocated,
    and a change without one is refused, as every other gate refuses it.
    """
    decision: dict[str, Any] = interrupt(
        {
            "kind": GATE_KIND,
            "projectId": state["project_id"],
            "runId": state["run_id"],
            "requirementsVersion": state["deploy_version"],
            "testVersion": state["test_version"],
            "codeVersion": state.get("code_version", 0),
        }
    )

    if decision.get("kind") == "approved":
        return Command(
            goto="release_handover",
            update={
                "release_authorisation": {
                    "by": decision.get("by") or "",
                    "gateId": decision.get("gateId") or "",
                    "goAhead": bool(decision.get("goAhead")),
                    "note": decision.get("note") or "",
                }
            },
        )

    version = decision.get("version")
    if not isinstance(version, int):
        raise ValueError(
            "the changes decision carried no deploy version; only the store allocates "
            "version numbers, so there is nothing safe to regenerate at"
        )
    return Command(goto="dependency_updates", update={"deploy_version": version})


def make_release_handover(pool: AsyncConnectionPool):
    """After an approved review: the release written down once, for the saga to carry out.

    The guards run again first, with the go ahead the decision carried, because
    the review and this node are separate moments. A release they refuse is not
    written, and the thread says why. A release they allow is one deployment row,
    keyed by the gate that approved it, so a node that runs twice writes one.
    The saga runner picks the row up; the run ends here.
    """
    from ..deploy import guards
    from ..saga.executor import deployment_key

    async def node(state: C4RunState) -> C4RunState:
        authorisation = dict(state.get("release_authorisation") or {})
        project_id = state["project_id"]
        version = state["deploy_version"]
        target = await _release_target(pool, state)
        async with pool.connection() as conn:
            project = await store.project_without_owner_check(conn, project_id)
            facts = await guards.gather(
                conn,
                project_id,
                owner=project["owner_id"] if project else "",
                deploy_version=version,
                target=target,
                test_version=state.get("test_version", 0),
                go_ahead=bool(authorisation.get("goAhead")),
            )
            blockers = guards.release_blockers(facts)
            if blockers:
                await store.post_thread_message(
                    conn,
                    project_id,
                    kind="system",
                    author="platform",
                    content="The release was not started: "
                    + "; ".join(blocker.message for blocker in blockers),
                    stage_id="release",  # type: ignore[arg-type]
                )
                return state
            found = await store.artefacts_at(
                conn, project_id, version=version, kinds=("deploy-plan",)
            )
            plan = DeployPlan.model_validate(found["deploy-plan"]["body"])
            gate_id = str(authorisation.get("gateId") or "")
            by_policy = authorisation.get("kind") == "policy"
            authorised = (
                {
                    "kind": "policy",
                    "policy": authorisation.get("policy") or "",
                    "by": authorisation.get("by") or "",
                    "goAhead": bool(authorisation.get("goAhead")),
                    "testVersion": state.get("test_version", 0),
                }
                if by_policy
                else {
                    "kind": "gate",
                    "by": authorisation.get("by") or "",
                    "gateId": gate_id,
                    "goAhead": bool(authorisation.get("goAhead")),
                    "testVersion": state.get("test_version", 0),
                }
            )
            try:
                row, created = await store.create_deployment(
                    conn,
                    project_id=project_id,
                    deploy_version=version,
                    kind="release",
                    target=target,
                    plan_id=plan.plan_id,
                    candidate_hash=plan.candidate_hash,
                    idempotency_key=deployment_key(
                        project_id,
                        plan.plan_id,
                        "release",
                        f"policy:{state['run_id']}" if by_policy else f"gate:{gate_id}",
                    ),
                    authorised=authorised,
                    requested_by=authorisation.get("by") or "unknown",
                    gate_id=uuid.UUID(gate_id) if gate_id and not by_policy else None,
                )
            except store.DeploymentInFlight as busy:
                await store.post_thread_message(
                    conn,
                    project_id,
                    kind="system",
                    author="platform",
                    content=f"The release was not started: {busy}",
                    stage_id="release",  # type: ignore[arg-type]
                )
                return state
            if created:
                await store.post_thread_message(
                    conn,
                    project_id,
                    kind="system",
                    author="platform",
                    content=f"Releasing deploy version {version} to the {target} target"
                    + (
                        f", automatically under the policy {authorised['by']} set."
                        if by_policy
                        else "."
                    ),
                    stage_id="release",  # type: ignore[arg-type]
                )
                await store.record(
                    conn,
                    actor=authorisation.get("by") or "platform",
                    action="Started a release",
                    target=f"deploy version {version}, {target}",
                    detail=f"deployment {row['id']}, candidate {plan.candidate_hash[:12]}",
                    project_id=project_id,
                    run_id=uuid.UUID(state["run_id"]),
                    category="deployment",
                )
        return state

    return node


def auto_release_refused(
    policy: dict[str, Any],
    target: str,
    candidate: ReleaseCandidate,
    levels: dict[str, str],
    previous: VerifiedRelease | None,
) -> str:
    """Why this run's release is reviewed rather than shipped under the policy, or "".

    Automatic release is for Low updates only (FR17), under a policy a person
    set, locally unless they also opted the cloud in, and never a project's
    first release: there is nothing verified behind it yet to return to.
    """
    if not policy.get("autoDeployLow"):
        return "the release policy does not ship Low updates automatically"
    if target == "cloud" and not policy.get("cloudAutoDeploy"):
        return "automatic releases to the cloud were not opted into"
    if previous is None:
        return "a project's first release is always reviewed"
    if not candidate.included:
        return "there is no update to release"
    above = [u for u in candidate.included if levels.get(u, "high") != "low"]
    if above:
        return f"{len(above)} included update(s) above Low need a person's decision"
    if not candidate.verified:
        return "the candidate was not verified in staging"
    return ""


def make_release_route(pool: AsyncConnectionPool):
    """Where the run goes after its stages: the review, a release under the policy, or no further.

    A run with no candidate at all (a stack no template fits, or no Docker to
    stage in) ends as analysis only, saying why: there is nothing any decision
    could release. An unverified candidate still goes to the review, because
    requesting changes is how a person rebuilds without the update that broke it.
    A release the policy allows skips the review, with the guards run first and
    the policy recorded as its authorisation.
    """
    from ..deploy import guards

    async def node(
        state: C4RunState,
    ) -> Command[Literal["deployment_review", "release_handover", "__end__"]]:
        project_id = state["project_id"]
        candidate = await _optional(pool, state, "release-candidate", ReleaseCandidate)
        if candidate is None:
            config = await _optional(pool, state, "pipeline-config", PipelineConfig)
            reason = (
                config.stack.reason
                if config is not None and not config.stack.supported
                else "staging built no candidate"
            )
            async with pool.connection() as conn:
                await store.post_thread_message(
                    conn,
                    project_id,
                    kind="system",
                    author="platform",
                    content=f"Analysis only: {reason}. Nothing from this run can be released.",
                    stage_id="deployment-review",  # type: ignore[arg-type]
                )
            return Command(goto=END)

        choice = (await _choices(pool, project_id)).get(("release_policy", "policy"))
        policy = choice["value"] if choice and isinstance(choice["value"], dict) else {}
        target = await _release_target(pool, state)
        risk = await _optional(pool, state, "risk-report", RiskReport)
        levels = {a.update_id: a.arbitration.final for a in (risk.assessments if risk else [])}
        previous = await _previous_release(pool, state)
        why_not = auto_release_refused(policy, target, candidate, levels, previous)
        go_ahead = target == "cloud" and bool(policy.get("cloudAutoDeploy"))
        if not why_not:
            async with pool.connection() as conn:
                project = await store.project_without_owner_check(conn, project_id)
                facts = await guards.gather(
                    conn,
                    project_id,
                    owner=project["owner_id"] if project else "",
                    deploy_version=state["deploy_version"],
                    target=target,
                    test_version=state.get("test_version", 0),
                    go_ahead=go_ahead,
                )
            blockers = guards.release_blockers(facts)
            if blockers:
                why_not = "the release guards refuse it: " + "; ".join(
                    blocker.message for blocker in blockers
                )
        if why_not:
            if policy.get("autoDeployLow"):
                async with pool.connection() as conn:
                    await store.post_thread_message(
                        conn,
                        project_id,
                        kind="system",
                        author="platform",
                        content=f"Held for review: {why_not}.",
                        stage_id="deployment-review",  # type: ignore[arg-type]
                    )
            return Command(goto="deployment_review")
        return Command(
            goto="release_handover",
            update={
                "release_authorisation": {
                    "kind": "policy",
                    "policy": "autoDeployLow",
                    "by": choice["by"] if choice else "",
                    "goAhead": go_ahead,
                }
            },
        )

    return node
