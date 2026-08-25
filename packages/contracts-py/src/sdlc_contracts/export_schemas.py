"""Write `contracts/*.schema.json` from the Pydantic models.

The models are the author and the committed JSON is the frozen artefact: other
components read the schema, the TypeScript types generate from it, and a
breaking change shows up in a diff that needs sign off. Maintaining a schema and
a model side by side by hand is how the two quietly disagree, so this generates
one from the other and CI fails when the committed copy is stale.

    uv run python -m sdlc_contracts.export_schemas          # write
    uv run python -m sdlc_contracts.export_schemas --check  # CI: fail if stale
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .api_contract import ApiContractArtefact
from .architecture import ArchitectureRecommendation
from .changelog_report import ChangelogReport
from .code_repository import CodeRepository
from .code_snapshot import CodeSnapshot
from .contract_agreement import ContractAgreement
from .dependency_update import DependencyUpdates
from .deploy_plan import DeployPlan
from .deploy_snapshot import DeploySnapshot
from .feedback import FeedbackReport
from .heal_report import HealReport
from .impact_report import ImpactReport
from .monitoring_report import MonitoringReport
from .pipeline_config import PipelineConfig
from .release_candidate import ReleaseCandidate
from .remediation_proposal import RemediationProposals
from .requirements import RequirementsArtefact
from .risk_report import RiskReport
from .rollback_plan import RollbackPlan
from .sag import ArchitectureGraph
from .settings import SettingsState
from .snapshot import DesignSnapshot
from .sprint import SprintPlan
from .sprint_scope import SprintScope
from .tech_stack import TechStackArtefact
from .test_report import TestReport
from .test_snapshot import TestSnapshot
from .uml import UmlArtefact
from .validation_report import ValidationReport
from .wireframes import WireframesArtefact

#: Schema file name to model. The names are the canonical vocabulary: the same
#: strings are the C1 endpoint paths, the run event stage keys and the
#: frontend's stage ids, so an artefact can be named once and found everywhere.
ARTEFACT_SCHEMAS: dict[str, type[BaseModel]] = {
    "requirements": RequirementsArtefact,
    "architecture-graph": ArchitectureGraph,
    "architecture-recommendation": ArchitectureRecommendation,
    "uml-diagrams": UmlArtefact,
    "wireframes": WireframesArtefact,
    "sprint-plan": SprintPlan,
    # Seams for components that do not exist yet. Committed as named, versioned
    # stubs so the components after them have something to be designed against,
    # rather than a schema that arrives late and is shaped by its first caller.
    "sprint-scope": SprintScope,
    "api-contract": ApiContractArtefact,
    "tech-stack": TechStackArtefact,
    "contract-agreement": ContractAgreement,
    "code-repository": CodeRepository,
    "test-report": TestReport,
    "heal-report": HealReport,
    "validation-report": ValidationReport,
    "remediation-proposal": RemediationProposals,
    # C4's own artefacts, drafted in full: the plan is read by a human before
    # anything is created, and the saga cannot be designed without knowing what
    # a step and its compensation look like.
    "deploy-plan": DeployPlan,
    "feedback": FeedbackReport,
    "dependency-updates": DependencyUpdates,
    "changelog-report": ChangelogReport,
    "impact-report": ImpactReport,
    "risk-report": RiskReport,
    "pipeline-config": PipelineConfig,
    "release-candidate": ReleaseCandidate,
    "rollback-plan": RollbackPlan,
    "monitoring-report": MonitoringReport,
}

#: Not a cross service seam: the browser's read model, assembled by the
#: orchestrator from the artefacts above. Generated so the frontend's types can
#: come from one place, and labelled so nobody mistakes it for a contract
#: between components.
VIEW_SCHEMAS: dict[str, type[BaseModel]] = {
    "code-snapshot": CodeSnapshot,
    "test-snapshot": TestSnapshot,
    "deploy-snapshot": DeploySnapshot,
    "design-snapshot": DesignSnapshot,
    "settings": SettingsState,
}

_TITLES = {
    "requirements": "Requirements artefact (C1)",
    "architecture-graph": "Semantic Architecture Graph (C1 to C2)",
    "architecture-recommendation": "Architecture recommendation (C1)",
    "uml-diagrams": "UML diagrams (C1)",
    "wireframes": "Wireframes (C1 to C2)",
    "sprint-plan": "Sprint plan (C1 to C3)",
    "sprint-scope": "Sprint scope (C2): what this build covers",
    "api-contract": "API contract (C2 to C3): both arms, the comparison, the choice",
    "tech-stack": "Tech stack proposal and selection (C2)",
    "contract-agreement": "Static contract agreement report (C2)",
    "code-repository": "Generated repository: manifest, build report, pointer (C2)",
    "validation-report": "Validation report (C3 to C4) STUB",
    "deploy-plan": "Deploy plan (C4)",
    "feedback": "Runtime and dependency feedback (C4 to C1)",
    "dependency-updates": "Dependency updates and their release notes (C4)",
    "changelog-report": "Release note claims, verified against the notes (C4)",
    "impact-report": "Affected files and architectural components (C4)",
    "risk-report": "Dependency update risk: three votes and the rule that combined them (C4)",
    "pipeline-config": "Generated CI/CD pipeline and deployment configuration, as validated (C4)",
    "release-candidate": "The release candidate, built and proved in a container (C4)",
    "rollback-plan": "The rollback prepared before a release (C4)",
    "monitoring-report": "Runtime health of a release over a named window (C4)",
    "code-snapshot": "Code snapshot (orchestrator to browser, a view model)",
    "test-snapshot": "Testing snapshot (orchestrator to browser, a view model)",
    "deploy-snapshot": "Deployment snapshot (orchestrator to browser, a view model)",
    "design-snapshot": "Design snapshot (orchestrator to browser, a view model)",
    "settings": "Settings state (orchestrator to browser, a view model, secret free)",
}


def contracts_dir() -> Path:
    """The repository's `contracts/` directory."""
    # src/sdlc_contracts/export_schemas.py -> packages/contracts-py -> packages -> repo
    return Path(__file__).resolve().parents[3].parent / "contracts"


def build_schema(name: str, model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema(by_alias=True, mode="serialization")
    # A stable header so the diff of a regenerated file shows real changes only.
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://sdlc.local/contracts/{name}.schema.json",
        "title": _TITLES.get(name, name),
        **schema,
    }


def render(name: str, model: type[BaseModel]) -> str:
    return json.dumps(build_schema(name, model), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit non zero if any committed schema is stale",
    )
    args = parser.parse_args(argv)

    target = contracts_dir()
    target.mkdir(parents=True, exist_ok=True)
    everything = {**ARTEFACT_SCHEMAS, **VIEW_SCHEMAS}

    stale: list[str] = []
    for name, model in sorted(everything.items()):
        path = target / f"{name}.schema.json"
        rendered = render(name, model)
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != rendered:
                stale.append(path.name)
        else:
            path.write_text(rendered, encoding="utf-8")

    if args.check:
        if stale:
            print(
                "These committed schemas no longer match the models: "
                + ", ".join(sorted(stale))
                + "\nRun: uv run python -m sdlc_contracts.export_schemas",
                file=sys.stderr,
            )
            return 1
        print(f"{len(everything)} schemas match the models")
        return 0

    print(f"wrote {len(everything)} schemas to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
