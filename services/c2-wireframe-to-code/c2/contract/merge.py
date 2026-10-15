"""Comparing the two arms, and the merged contract a human may choose.

The comparison is the ablation data: which endpoints both arms produced,
which only one did, and where they disagree about a shared endpoint. The
merge is a union with the rule arm's version winning shared keys, because
the deterministic arm is the baseline; each conflict is surfaced so the
human deciding on merged sees exactly what the choice papered over.
"""

from sdlc_contracts import (
    ApiContract,
    ArmComparison,
    ArmCounts,
    ContractConflict,
)

from ..rules.findings import Report
from .vocab import canonical

#: The endpoint fields worth a conflict row when the arms disagree.
_COMPARED_FIELDS = ("method", "path", "summary", "auth", "request", "response")


def _rendered(endpoint) -> dict[str, str]:
    return {
        "method": endpoint.method,
        "path": endpoint.path,
        "summary": endpoint.summary,
        "auth": ", ".join(sorted(endpoint.auth_actors)),
        "request": endpoint.request.model_dump_json() if endpoint.request else "",
        "response": endpoint.response.model_dump_json() if endpoint.response else "",
    }


def compare_arms(
    rule: ApiContract,
    llm: ApiContract | None,
    *,
    rule_report: Report,
    llm_report: Report | None,
    llm_attempts: int,
) -> ArmComparison:
    rule_by_key = {canonical(e.method, e.path): e for e in rule.endpoints}
    llm_by_key = {canonical(e.method, e.path): e for e in llm.endpoints} if llm is not None else {}

    agreed = sorted(set(rule_by_key) & set(llm_by_key))
    conflicts: list[ContractConflict] = []
    for key in agreed:
        rule_fields = _rendered(rule_by_key[key])
        llm_fields = _rendered(llm_by_key[key])
        for field in _COMPARED_FIELDS:
            if field in ("method", "path"):
                continue  # equal by key construction
            if rule_fields[field] != llm_fields[field]:
                conflicts.append(
                    ContractConflict(
                        endpoint_key=key,
                        field=field,
                        rule_value=rule_fields[field][:200],
                        llm_value=llm_fields[field][:200],
                    )
                )

    union = set(rule_by_key) | set(llm_by_key)
    return ArmComparison(
        rule=ArmCounts(
            endpoints=len(rule.endpoints),
            errors=len(rule_report.errors),
            warnings=len(rule_report.warnings),
            attempts=1,
        ),
        llm=ArmCounts(
            endpoints=len(llm.endpoints) if llm else 0,
            errors=len(llm_report.errors) if llm_report else 0,
            warnings=len(llm_report.warnings) if llm_report else 0,
            attempts=llm_attempts,
        ),
        agreed=agreed,
        rule_only=sorted(set(rule_by_key) - set(llm_by_key)),
        llm_only=sorted(set(llm_by_key) - set(rule_by_key)),
        conflicts=conflicts,
        agreement_rate=(len(agreed) / len(union)) if union else 0.0,
    )


def merge_contracts(rule: ApiContract, llm: ApiContract) -> ApiContract:
    """Union by canonical key. Shared keys keep the rule arm's endpoint with
    traces unioned, marked merged; each arm's exclusives ride along whole."""
    llm_by_key = {canonical(e.method, e.path): e for e in llm.endpoints}
    merged = []
    taken: set[str] = set()

    for endpoint in rule.endpoints:
        key = canonical(endpoint.method, endpoint.path)
        other = llm_by_key.get(key)
        if other is None:
            merged.append(endpoint)
            continue
        taken.add(key)
        traces = endpoint.traces.model_copy(
            update={
                "screen_ids": sorted(
                    set(endpoint.traces.screen_ids) | set(other.traces.screen_ids)
                ),
                "action_ids": sorted(
                    set(endpoint.traces.action_ids) | set(other.traces.action_ids)
                ),
                "story_ids": sorted(set(endpoint.traces.story_ids) | set(other.traces.story_ids)),
                "requirement_ids": sorted(
                    set(endpoint.traces.requirement_ids) | set(other.traces.requirement_ids)
                ),
            }
        )
        merged.append(endpoint.model_copy(update={"traces": traces, "origin": "merged"}))

    for endpoint in llm.endpoints:
        key = canonical(endpoint.method, endpoint.path)
        if key not in taken and key not in {canonical(e.method, e.path) for e in rule.endpoints}:
            merged.append(endpoint)

    entity_names = {entity.name for entity in rule.entities}
    entities = list(rule.entities) + [
        entity for entity in llm.entities if entity.name not in entity_names
    ]
    return ApiContract(version=rule.version, entities=entities, endpoints=merged)
