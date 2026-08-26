"""The words the platform writes for people: stage, phase and provider names, and notes.

Audit entries and thread messages are read in Activity and in each phase's
conversation. They said "Generated uml-diagrams", "Component c3 on ...",
"Connected github" and "digest: None": a stage id, a component code, a provider
key and a Python value, none of them words a reader uses. The stage names here
are the pages' own (each phase's `model/stages.ts`), and `tests/test_wording.py`
holds the two to the same words.
"""

from typing import Any

STAGE_LABELS: dict[str, str] = {
    # Requirements and Design
    "requirements": "Requirements Analysis",
    "domain-model": "Domain Model",
    "architecture-graph": "Architecture Graph",
    "architecture-recommendation": "Architecture Recommendation",
    "uml-diagrams": "UML Diagrams",
    "wireframes": "Wireframes",
    "sprint-plan": "Sprint Planning",
    "design-review": "Design Review",
    # Code Generation
    "sprint-scope": "Sprint Scope",
    "tech-stack": "Tech Stack",
    "api-contract": "API Contract",
    "frontend-code": "Frontend Code",
    "backend-code": "Backend Code",
    "contract-agreement": "Contract Agreement",
    "build": "Build",
    "code-review": "Code Review",
    # Testing and Security
    "test-generation": "Test Generation",
    "test-run": "Test Run",
    "test-quality": "Test Quality",
    "self-healing": "Self Healing",
    "security-scan": "Security",
    "remediation": "Remediation",
    "test-review": "Test Review",
    # Deployment
    "dependency-updates": "Dependency Updates",
    "changelog-analysis": "Changelog Analysis",
    "impact-analysis": "Impact Analysis",
    "risk-assessment": "Risk Assessment",
    "pipeline-generation": "CI/CD Pipeline",
    "staging-verification": "Staging",
    "rollback-planning": "Rollback Plan",
    "deployment-review": "Deployment Review",
    "release": "Release",
    "monitoring": "Monitoring",
}

#: Each component as its phase is called on the pages; the codes stay internal.
PHASE_NAMES: dict[str, str] = {
    "c1": "Requirements and Design",
    "c2": "Code Generation",
    "c3": "Testing and Security",
    "c4": "Deployment",
}

#: Each stored credential's provider as its owner knows it.
PROVIDER_NAMES: dict[str, str] = {
    "github": "GitHub",
    "vercel": "Vercel",
    "render": "Render",
    "render-deploy-hook": "the Render deploy hook",
    "atlas": "MongoDB Atlas",
}


#: A connection check's verdict as the Settings page says it.
VERDICT_WORDS: dict[str, str] = {
    "SUITABLE": "Works",
    "WORKABLE": "Works with limits",
    "UNUSABLE": "Does not work",
}


#: What a run asked its model about thinking, as Activity says it (0014).
THINKING_WORDS: dict[str, str] = {
    "disabled": "thinking off",
    "default": "thinking left to the provider",
    # A component's switch turned on (`Thinking` in the configuration).
    "low": "thinking on, low effort",
    "high": "thinking on, high effort",
    "max": "thinking on, max effort",
    "enabled": "thinking on",
}


def verdict_words(verdict: str) -> str:
    return VERDICT_WORDS.get(verdict, verdict.capitalize())


def run_setup_words(model: str, thinking: str | None) -> str:
    """A run's model and thinking setting: "deepseek:deepseek-flash, thinking off".

    The model alone where its thinking was not recorded, rather than a guess.
    """
    if not thinking:
        return model
    return f"{model}, {THINKING_WORDS.get(thinking, f'thinking {thinking}')}"


def stage_label(stage_id: str) -> str:
    """A stage as the pages name it; an id with no name reads as words, not as a key."""
    return STAGE_LABELS.get(stage_id, stage_id.replace("-", " "))


def phase_name(component: str) -> str:
    return PHASE_NAMES.get(component, component)


def provider_name(provider: str) -> str:
    return PROVIDER_NAMES.get(provider, provider)


def readable_notes(notes: dict[str, Any]) -> str:
    """A stage's notes as one line of words: a list as its items, nothing as "none"."""
    return ", ".join(f"{name.replace('_', ' ')}: {_value(value)}" for name, value in notes.items())


def _value(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        if not value:
            return "none"
        return "; ".join(
            f"{str(key).replace('_', ' ')} {_value(item)}" for key, item in value.items()
        )
    if isinstance(value, list | tuple | set | frozenset):
        return ", ".join(_value(item) for item in value) if value else "none"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
