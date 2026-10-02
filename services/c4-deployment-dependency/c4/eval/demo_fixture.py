"""The deployment page's demo data, written by the product's own code.

    uv run python -m c4.eval.demo_fixture \\
        --out ../../ai-sdlc-platform-frontend/src/features/deployment/fixtures/deploymentData.ts

The frontend's fixtures answer until the deployment feature is flipped live, and
a fixture that states a level no rule would produce teaches the page to render
something the server never sends. So the artefacts are made here, by the code
that makes them in production, and every one is validated by its contract
before a line of TypeScript is written.

**Recorded.** The six updates are ones the Epoch 4 study recorded against the
platform's generated application (`studies/votes/epoch-4-corpus-dev-changelog.json`):
their versions, their release notes' sources, the claims the changelog signal
verified (a few of each, quoted exactly as the notes say them) and the usage
signal's findings. The risk assessments are `assess` over them, so the levels,
advisories and strategies are the rules' own. Reading them needs the whole
changelog and impact reports those votes were made from, which are kept outside
the repository, under `~/.cache/sdlc-c4/study-reports/epoch-4-corpus-dev`.

**Made for the demo, through the same code.** The pipeline and the deploy plan
are `generate` and `deploy_plan` over the generated sample application, with its
real validators, and only the npm resolution stubbed. The rollback plans are
`plan`, and the feedback is `derive`. The release history (a verified release,
and a later one that went down in a controlled failure and waits on a person's
rollback decision) is written through the contract models, which check it the
way the store's readers would. The rollback itself is left for the demo to
approve, because FR20 is the one decision a reader should get to make.

No explanation is asked of a model here, because that would spend on demo data:
each assessment carries the rule written summary, and says why.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sdlc_contracts import (
    BaselinePin,
    BuildStepReport,
    ChangelogReport,
    DependencyUpdates,
    DeploymentEvent,
    DeploymentStepView,
    DeploymentView,
    DeployPlan,
    ImpactReport,
    MonitoringReport,
    PipelineConfig,
    ProbeSummary,
    RegistryQuery,
    RejectedUpdate,
    ReleaseCandidate,
    ReleaseNoteRef,
    RiskReport,
    SmokeCheck,
    StateInterval,
    VerifiedRelease,
    changelog_level,
)

from ..feedback import derive
from ..pipeline.candidate import Resolution
from ..pipeline.generate import generate
from ..pipeline.plan import deploy_plan
from ..risk.assess import assess
from ..risk.changelog import _rationale, _vote
from ..risk.explain import summary
from ..rollback.plan import plan as rollback_plan
from .votes import REPORTS, client_for, update_for

RECORD = Path("studies/votes/epoch-4-corpus-dev-changelog.json")
PROJECT = "p4"

#: The recorded cases, and which of each one's verified claims the demo shows.
KEEP: dict[str, list[int]] = {
    "platform-react-router-dom-7.16.0-7.18.4": [0, 1, 2, 10, 18],
    "platform-tailwindcss-4.3.2-4.3.3": [11, 2, 14],
    "platform-supertest-7.2.2-7.3.0": [0, 1, 3],
    "platform-react-19.2.6-19.2.8": [0, 1],
    "platform-testing-library-react-16.3.2-16.3.3": [0],
    "platform-types-react-dom-19.2.4-19.2.7": [],
}
SAMPLE = "platform-react-router-dom-7.16.0-7.18.4"

#: The demo's clock: the current run, and the releases before it.
RUN = datetime(2026, 9, 24, 9, 30, tzinfo=UTC)
FIRST = datetime(2026, 9, 18, 10, 5, tzinfo=UTC)
SECOND = datetime(2026, 9, 21, 14, 10, tzinfo=UTC)

DEPLOY_VERSION = 3
CODE_VERSION = 4
TEST_VERSION = 3
REVIEWER = "Alex Chen"
LOCAL_URL = "http://127.0.0.1:8081"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dump(model: BaseModel) -> Any:
    return model.model_dump(by_alias=True, mode="json")


def recorded(studies: Path) -> tuple[DependencyUpdates, ChangelogReport, ImpactReport, RiskReport]:
    """The six recorded updates, their changelog and usage evidence, and the product's assessment."""
    from .__main__ import load_cases

    votes = json.loads(RECORD.read_text())["votes"]
    reports = REPORTS / RECORD.stem.removesuffix("-changelog")
    cases = {case.case_id: case for case in load_cases(studies / "cases" / "corpus")}
    whole = ChangelogReport.model_validate_json((reports / "changelog-report.json").read_text())

    updates, analyses, per_update, symbols = [], [], [], []
    extraction = None
    for case_id, keep in KEEP.items():
        case = cases[case_id]
        update = update_for(case, client_for(case, studies).files)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", update.package)
        notes = [
            ReleaseNoteRef(
                source=note["source"],
                url=note["url"],
                version=note["version"],
                path=f"notes/{safe}/{note['source']}-{note['version']}.md",
                sha256=note["sha256"],
                chars=note["chars"],
                truncated=note["truncated"],
            )
            for note in votes[case_id]["changelog"].get("notes", [])
        ]
        update = update.model_copy(update={"notes": notes})
        updates.append(update)

        analysis = next(a for a in whole.per_update if a.update_id == update.id)
        if analysis.notes_found:
            claims = [analysis.claims[index] for index in keep]
            level = changelog_level([claim.kind for claim in claims], notes_found=True, refused=0)
            vote = _vote(level, "", _rationale(level, claims, 0), [claim.id for claim in claims])
            analysis = analysis.model_copy(update={"claims": claims, "refused": [], "vote": vote})
        analyses.append(analysis)

        impact = ImpactReport.model_validate_json((reports / f"{case_id}.impact.json").read_text())
        extraction = extraction or impact.extraction
        per_update.extend(impact.per_update)
        symbols.extend(impact.changed_symbols)

    dependency_updates = DependencyUpdates(
        version=DEPLOY_VERSION,
        generated_at=RUN,
        code_version=CODE_VERSION,
        test_version=TEST_VERSION,
        target="generated",
        baseline=BaselinePin(
            lockfile_path="package-lock.json",
            lockfile_sha256=_sha("notifyhub baseline lockfile, deploy version 3"),
            packages=412,
            direct=14,
            resolved_by="npm 10.9.2 install --package-lock-only --ignore-scripts",
        ),
        updates=updates,
        rejected=[
            RejectedUpdate(
                package="@app/contract",
                ecosystem="npm",
                manifest_path="apps/api/package.json",
                declared="*",
                reason="not-a-registry-dependency",
                detail=(
                    '@app/contract is the project\'s own workspace package, declared as "*"; no '
                    "registry publishes it, so there is no newer release to assess."
                ),
            )
        ],
        queried=[
            RegistryQuery(
                registry="npm",
                url=f"https://registry.npmjs.org/{update.package}",
                at=RUN,
                status=200,
            )
            for update in updates
        ],
    )
    changelog = ChangelogReport.model_validate(
        {
            **_dump(whole),
            "version": DEPLOY_VERSION,
            "generatedAt": RUN.isoformat(),
            "perUpdate": [_dump(analysis) for analysis in analyses],
        }
    )
    impact = ImpactReport(
        version=DEPLOY_VERSION,
        generated_at=RUN,
        code_version=CODE_VERSION,
        design_version=2,
        granularity="graph-node",
        extraction=extraction,
        changed_symbols=symbols,
        per_update=per_update,
    )
    assessed = []
    for update in updates:
        # A fixed clock, so the latency the fixture shows is the same every time.
        assessment = assess(update, changelog, impact, clock=iter([0.0, 0.002]).__next__)
        assessed.append(
            assessment.model_copy(
                update={
                    "explanation": summary(assessment),
                    "explanation_source": "rule",
                    "explanation_unavailable": "the demo does not ask a model",
                }
            )
        )
    risk = RiskReport.model_validate(
        _dump(RiskReport(version=DEPLOY_VERSION, generated_at=RUN, assessments=assessed))
    )
    return dependency_updates, changelog, impact, risk


def pipeline(
    studies: Path, updates: DependencyUpdates
) -> tuple[PipelineConfig, DeployPlan, list[str]]:
    """The generated deployment layer for the sample application, validated for real."""
    from .__main__ import load_cases

    case = next(c for c in load_cases(studies / "cases" / "corpus") if c.case_id == SAMPLE)
    files = client_for(case, studies).files

    def unchanged(tree: dict[str, str], chosen: list) -> Resolution:
        # The one step stubbed: the candidate's lockfile is the baseline's, so no
        # npm install runs to make demo data.
        return Resolution(
            lockfile=tree["package-lock.json"],
            applied=[u.id for u in chosen],
            resolved_by="npm 10.9.2 install --package-lock-only --ignore-scripts",
        )

    generated = generate(
        files,
        updates,
        stack_id="mern",
        contract=None,
        included=[u.id for u in updates.updates],
        settings={"projectSlug": "notifyhub"},
        version=DEPLOY_VERSION,
        code_version=CODE_VERSION,
        now=RUN + timedelta(minutes=2),
        resolver=unchanged,
    )
    plan = deploy_plan(
        generated,
        project_id=PROJECT,
        release_target="local",
        github_protection=None,
        version=DEPLOY_VERSION,
    )
    return generated.config, plan, ["/", "/release.json"]


def _steps(candidate_hash: str) -> list[BuildStepReport]:
    return [
        BuildStepReport(
            name="install",
            command="npm ci --ignore-scripts",
            outcome="passed",
            duration_seconds=21.4,
            log_tail="added 412 packages in 21s",
        ),
        BuildStepReport(
            name="build",
            command="npm run build --workspaces --if-present",
            outcome="passed",
            duration_seconds=14.8,
            log_tail="apps/web: vite build\n  dist/index.html  0.46 kB\n  built in 3.9s",
        ),
        BuildStepReport(
            name="image",
            command="docker build --target runtime -t sdlc-c4-app:v3 .",
            outcome="passed",
            duration_seconds=48.2,
            log_tail="naming to docker.io/library/sdlc-c4-app:v3 done",
        ),
        BuildStepReport(
            name="boot",
            command="docker run -d -p 127.0.0.1:8082:3001 sdlc-c4-app:v3",
            outcome="passed",
            duration_seconds=2.1,
            log_tail=f"listening on http://0.0.0.0:3001\nrelease.json serves {candidate_hash[:12]}",
        ),
    ]


def candidate(config: PipelineConfig, risk: RiskReport, smoke: list[str]) -> ReleaseCandidate:
    """A staging build that passed, over every assessed update."""
    return ReleaseCandidate(
        version=DEPLOY_VERSION,
        generated_at=RUN + timedelta(minutes=4),
        code_version=CODE_VERSION,
        candidate_hash=config.candidate_hash,
        lockfile_sha256=_sha("notifyhub candidate lockfile, deploy version 3"),
        included=[a.update_id for a in risk.assessments],
        image="sdlc-c4-app:v3",
        image_digest="sha256:" + _sha("sdlc-c4-app:v3"),
        toolchain="node 22.17.0, npm 10.9.2",
        isolation="a local Docker container on loopback, 512 MB, no host mounts",
        steps=_steps(config.candidate_hash),
        smoke=[
            SmokeCheck(path=path, status_code=200, ok=True, detail="answered in under 200 ms")
            for path in smoke
        ],
        fingerprint=config.candidate_hash,
    )


def history() -> tuple[list[DeploymentView], VerifiedRelease, MonitoringReport]:
    """Deploy version 1 serves, verified; 2 went down in a controlled failure and waits on a person."""
    first_hash, second_hash = _sha("notifyhub candidate v1"), _sha("notifyhub candidate v2")
    first_id = "4f1c2d9e-8a7b-4c6d-9e0f-1a2b3c4d5e61"
    second_id = "7a3e5b1c-2d4f-4e6a-8b9c-0d1e2f3a4b72"

    def step(
        seq: int, step_id: str, label: str, state: str, at: datetime, **extra: Any
    ) -> DeploymentStepView:
        return DeploymentStepView(
            seq=seq,
            step_id=step_id,
            label=label,
            provider=extra.pop("provider", "local-docker"),
            state=state,
            attempt=1,
            started_at=at,
            finished_at=at + timedelta(seconds=20),
            **extra,
        )

    first = DeploymentView(
        id=first_id,
        kind="release",
        target="local",
        state="succeeded",
        candidate_hash=first_hash,
        deploy_version=1,
        verified=True,
        requested_by=REVIEWER,
        authorised_by=REVIEWER,
        url=LOCAL_URL,
        created_at=FIRST,
        finished_at=FIRST + timedelta(minutes=2),
        steps=[
            step(
                0,
                "start",
                "Start the verified candidate beside the running release",
                "succeeded",
                FIRST,
                command="docker run -d sdlc-c4-app:v1",
            ),
            step(
                1,
                "check",
                "Check it serves the candidate's fingerprint, and answers health and smoke",
                "succeeded",
                FIRST + timedelta(seconds=20),
                provider=None,
                log_tail=f"release.json: {first_hash[:12]}\nGET / 200\nGET /release.json 200",
            ),
            step(
                2,
                "switch",
                "Move the release port to the candidate",
                "succeeded",
                FIRST + timedelta(seconds=40),
                moves_traffic=True,
                command="docker run -d -p 127.0.0.1:8081:3001 sdlc-c4-app:v1",
            ),
            step(
                3,
                "verify",
                "Check the release port serves the candidate",
                "succeeded",
                FIRST + timedelta(seconds=60),
                provider=None,
                log_tail=f"{LOCAL_URL}/release.json: {first_hash[:12]}",
            ),
        ],
    )
    second = DeploymentView(
        id=second_id,
        kind="release",
        target="local",
        state="awaiting-rollback-approval",
        candidate_hash=second_hash,
        deploy_version=2,
        verified=True,
        cause=(
            "the release stopped answering 4 minutes after it was verified: GET /release.json "
            "and GET / refused the connection"
        ),
        fault_injected="stop-container",
        requested_by=REVIEWER,
        authorised_by=REVIEWER,
        url=LOCAL_URL,
        created_at=SECOND,
        finished_at=SECOND + timedelta(minutes=2),
        steps=[
            step(
                0,
                "start",
                "Start the verified candidate beside the running release",
                "succeeded",
                SECOND,
                command="docker run -d sdlc-c4-app:v2",
            ),
            step(
                1,
                "check",
                "Check it serves the candidate's fingerprint, and answers health and smoke",
                "succeeded",
                SECOND + timedelta(seconds=20),
                provider=None,
                log_tail=f"release.json: {second_hash[:12]}\nGET / 200\nGET /release.json 200",
            ),
            step(
                2,
                "switch",
                "Move the release port to the candidate",
                "succeeded",
                SECOND + timedelta(seconds=40),
                moves_traffic=True,
                command="docker run -d -p 127.0.0.1:8081:3001 sdlc-c4-app:v2",
            ),
            step(
                3,
                "verify",
                "Check the release port serves the candidate",
                "succeeded",
                SECOND + timedelta(seconds=60),
                provider=None,
                log_tail=f"{LOCAL_URL}/release.json: {second_hash[:12]}",
            ),
        ],
    )
    serving = VerifiedRelease(
        deployment_id=first_id,
        deploy_version=1,
        candidate_hash=first_hash,
        lockfile_sha256=_sha("notifyhub candidate lockfile, deploy version 1"),
        target="local",
        image_digest="sha256:" + _sha("sdlc-c4-app:v1"),
        url=LOCAL_URL,
        verified_at=FIRST + timedelta(minutes=2),
    )

    opened = SECOND + timedelta(minutes=2)
    went_down = opened + timedelta(minutes=4)
    closed = opened + timedelta(minutes=10)
    monitoring = MonitoringReport(
        version=2,
        generated_at=closed,
        deployment_id=second_id,
        target="local",
        urls=[LOCAL_URL],
        source="orchestrator HTTP probes every 30 s from this host",
        window_start=opened,
        window_end=closed,
        probe_interval_seconds=30,
        probes=[
            ProbeSummary(
                probe="GET /release.json",
                samples=20,
                ok=8,
                p50_ms=41.0,
                p95_ms=63.0,
                last_error="connection refused",
            ),
            ProbeSummary(
                probe="GET /",
                samples=20,
                ok=8,
                p50_ms=38.0,
                p95_ms=57.0,
                last_error="connection refused",
            ),
        ],
        states=[
            StateInterval(
                state="healthy",
                start=opened,
                end=went_down,
                samples=8,
                evidence="every probe answered, the fingerprint matched, p95 under 2000 ms",
            ),
            StateInterval(
                state="down",
                start=went_down,
                end=closed,
                samples=12,
                evidence="12 rounds in a row, every probe refused the connection",
            ),
        ],
        current_state="down",
        expected_candidate_hash=second_hash,
        fingerprint_matches=True,
        events=[
            DeploymentEvent(
                at=SECOND + timedelta(minutes=2),
                kind="released",
                deployment_id=second_id,
                detail="deploy version 2 on the release port",
            ),
            DeploymentEvent(
                at=SECOND + timedelta(minutes=2),
                kind="verified",
                deployment_id=second_id,
                detail="fingerprint, health and smoke answered",
            ),
            DeploymentEvent(
                at=went_down,
                kind="down",
                deployment_id=second_id,
                detail="controlled failure: stop-container",
            ),
            DeploymentEvent(
                at=went_down + timedelta(seconds=30),
                kind="rollback-requested",
                deployment_id=second_id,
                detail="waiting for a person's decision (FR20)",
            ),
        ],
        idle_seconds=0.0,
        idle_from="released",
    )
    return [second, first], serving, monitoring


def build(studies: Path) -> dict[str, Any]:
    updates, changelog, impact, risk = recorded(studies)
    config, plan, smoke = pipeline(studies, updates)
    ledger, serving, monitoring = history()
    staged = candidate(config, risk, smoke)
    rollback = rollback_plan(
        staged,
        risk,
        serving,
        release_target="local",
        version=DEPLOY_VERSION,
        now=RUN + timedelta(minutes=5),
    )
    feedback = derive(
        monitoring,
        None,
        None,
        project_id=PROJECT,
        deploy_version=2,
        fault_injected="stop-container",
        now=monitoring.generated_at + timedelta(seconds=5),
    )
    return {
        "DEMO_UPDATES": ("DependencyUpdates", updates),
        "DEMO_CHANGELOG": ("ChangelogReport", changelog),
        "DEMO_IMPACT": ("ImpactReport", impact),
        "DEMO_RISK": ("RiskReport", risk),
        "DEMO_PIPELINE": ("PipelineConfig", config),
        "DEMO_PLAN": ("DeployPlan", plan),
        "DEMO_CANDIDATE": ("ReleaseCandidate", staged),
        "DEMO_ROLLBACK": ("RollbackPlan", rollback),
        "DEMO_MONITORING": ("MonitoringReport", monitoring),
        "DEMO_FEEDBACK": ("FeedbackReport", feedback),
        "DEMO_LEDGER": ("DeploymentView[]", ledger),
        "DEMO_SERVING": ("VerifiedRelease", serving),
    }


_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _ts(value: Any, indent: int = 0) -> str:
    """A value as a TypeScript literal, in the frontend's style."""
    pad, inner = " " * indent, " " * (indent + 2)
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = [
            f"{inner}{key if _IDENTIFIER.match(key) else json.dumps(key)}: {_ts(item, indent + 2)},"
            for key, item in value.items()
        ]
        return "{\n" + "\n".join(rows) + f"\n{pad}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        flat = "[" + ", ".join(_ts(item) for item in value) + "]"
        if all(not isinstance(item, dict | list) for item in value) and len(flat) + indent < 90:
            return flat
        return "[\n" + "\n".join(f"{inner}{_ts(item, indent + 2)}," for item in value) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False)


def render(built: dict[str, Any]) -> str:
    kinds = sorted({kind.removesuffix("[]") for kind, _ in built.values()})
    lines = [
        "// Generated by `uv run python -m c4.eval.demo_fixture` in",
        "// services/c4-deployment-dependency. Do not edit by hand: change the generator",
        "// and run it again, so every artefact here stays one its contract accepts.",
        "//",
        "// The six updates, their verified release note claims and the usage signal's",
        "// findings are recorded ones (Epoch 4, the platform's generated application);",
        "// the risk assessments are the product's own rules over them. The pipeline, the",
        "// plans, the release history and the monitoring window are demo data made by",
        "// the same code. See the generator's docstring.",
        "",
        "import type {",
        *[f"  {kind}," for kind in kinds],
        '} from "../api/types";',
        "",
    ]
    for name, (kind, model) in built.items():
        value = [_dump(item) for item in model] if isinstance(model, list) else _dump(model)
        lines.append(f"export const {name}: {kind} = {_ts(value)};")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m c4.eval.demo_fixture", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--studies", type=Path, default=Path("studies"))
    args = parser.parse_args(argv)
    text = render(build(args.studies))
    if re.search("[\u2013\u2014]", text):
        print("refused: the generated text holds an em or en dash", file=sys.stderr)
        return 2
    args.out.write_text(text)
    print(f"wrote {args.out} ({len(text)} characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
