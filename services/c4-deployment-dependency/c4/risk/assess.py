"""The assessment (FR4 to FR8): three votes per update, the rule that combines them, the strategy.

Every level here is produced by a rule and re-derived by the report's own
validators, so nothing in this module can decide one by writing it down:

- **signal one** is `semver-rule/1` over the version change detection recorded;
- **signal two** is the changelog stage's vote, carried over with the claims it
  rests on; a changelog stage that produced nothing leaves it abstaining;
- **signal three** is the impact stage's vote, carried over with the checked
  references it rests on; likewise;
- **the final level** is `safety-first-max/1`, the most cautious vote cast, and
  High with no vote at all, because nothing supports a lower one;
- **the strategy** is `risk-strategy/1`: Low deploys automatically, Medium waits
  for approval, High waits for approval with a manual review and a prepared
  rollback.

When the votes cast disagree, or none was cast, the assessment says so in a
sentence a developer can act on (NFR10). Each assessment carries the evidence
its votes cite and the files and components the update reaches, so a level is
never shown apart from why (NFR11). The same votes give the same outcome
whatever the ecosystem (NFR12): nothing below reads it.

The risk stage is given reports, never files: the code was indexed once, by
the impact stage (NFR2).
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime

from sdlc_contracts import (
    ARBITRATION_RULE,
    SEMVER_RULE,
    STRATEGY_RULE,
    Arbitration,
    ChangelogAnalysis,
    ChangelogReport,
    DependencyUpdate,
    DependencyUpdates,
    EvidenceRef,
    ImpactReport,
    Latency,
    RiskReport,
    SignalVote,
    Strategy,
    UpdateAssessment,
    UpdateImpact,
    safety_first,
    semver_level,
    strategy_for,
)

from ..impact.usage import evidence_id

_READABLE = {"semver": "SemVer", "changelog": "the changelog", "usage": "usage"}


def _level(level: str | None) -> str:
    return level.capitalize() if level else "no vote"


def version_evidence(update: DependencyUpdate) -> str:
    return f"{update.id}-version"


def semver_vote(update: DependencyUpdate) -> SignalVote:
    """Signal one, from the version change detection recorded as a fact."""
    level = semver_level(update.change)
    flags = f" ({', '.join(update.flags)})" if update.flags else ""
    if level is None:
        reason = (
            f"{update.from_version} to {update.to_version} is {update.change}, which "
            "cannot be read by position"
        )
        return SignalVote(
            signal="semver",
            abstained_reason=reason,
            rule_id=SEMVER_RULE,
            rationale=f"SemVer abstains: {reason}.",
        )
    return SignalVote(
        signal="semver",
        level=level,
        rule_id=SEMVER_RULE,
        rationale=(
            f"{update.from_version} to {update.to_version} is a {update.change} change"
            f"{flags}, which {SEMVER_RULE} rates {_level(level)}."
        ),
        evidence_ids=[version_evidence(update)],
    )


def _abstaining(signal: str, rule: str, reason: str) -> SignalVote:
    return SignalVote(
        signal=signal,  # type: ignore[arg-type]
        abstained_reason=reason,
        rule_id=rule,
        rationale=f"The {signal} signal abstains: {reason}.",
    )


def _analysis(changelog: ChangelogReport | None, update: DependencyUpdate):
    if changelog is None:
        return None
    return next((a for a in changelog.per_update if a.update_id == update.id), None)


def _impact(impact: ImpactReport | None, update: DependencyUpdate) -> UpdateImpact | None:
    if impact is None:
        return None
    return next((i for i in impact.per_update if i.update_id == update.id), None)


def changelog_vote(analysis: ChangelogAnalysis | None, *, stage_ran: bool) -> SignalVote:
    if analysis is not None:
        return analysis.vote
    reason = (
        "the changelog stage produced no analysis of this update"
        if stage_ran
        else "the changelog stage did not produce a report"
    )
    return _abstaining("changelog", "changelog-rule/1", reason)


def usage_vote(update_impact: UpdateImpact | None, *, stage_ran: bool) -> SignalVote:
    if update_impact is not None:
        return update_impact.vote
    reason = (
        "the impact stage produced no analysis of this update"
        if stage_ran
        else "the impact stage did not produce a report"
    )
    return _abstaining("usage", "usage-rule/1", reason)


def evidence(
    update: DependencyUpdate,
    analysis: ChangelogAnalysis | None,
    update_impact: UpdateImpact | None,
    impact: ImpactReport | None,
) -> list[EvidenceRef]:
    """Everything the votes cite, each summarised for a reader, and the components reached."""
    flags = f", {', '.join(update.flags)}" if update.flags else ""
    found = [
        EvidenceRef(
            id=version_evidence(update),
            kind="version",
            summary=f"{update.package} {update.from_version} to {update.to_version}: "
            f"{update.change}{flags}",
        )
    ]
    for claim in analysis.claims if analysis else []:
        named = f" ({', '.join(claim.symbols)})" if claim.symbols else ""
        found.append(
            EvidenceRef(
                id=claim.id,
                kind="claim",
                summary=f"{claim.kind}{named} in {claim.version}: {claim.quote[:200]}",
            )
        )
    if update_impact is not None:
        for position, reference in enumerate(update_impact.references, start=1):
            line = (
                reference.span.snippet.strip().splitlines()[0][:160]
                if reference.span.snippet
                else ""
            )
            found.append(
                EvidenceRef(
                    id=evidence_id(update, position),
                    kind="reference",
                    summary=f"{reference.symbol} ({reference.symbol_kind}) at "
                    f"{reference.span.path}:{reference.span.start_line}: {line}",
                )
            )
        found.append(
            EvidenceRef(
                id=f"{update.id}-api-diff",
                kind="api-diff",
                summary=f"API diff {update_impact.api_diff}"
                + (f": {update_impact.api_diff_reason}" if update_impact.api_diff_reason else ""),
            )
        )
    for component in impact.affected_components if impact else []:
        if update.id not in component.update_ids:
            continue
        found.append(
            EvidenceRef(
                id=f"{update.id}-component-{component.node_id}",
                kind="component",
                summary=f"{component.label} ({component.kind}): "
                + "; ".join(link.detail for link in component.links[:3]),
            )
        )
    return found


def advisory(votes: list[SignalVote], final: str) -> str:
    """NFR10: a sentence when the votes disagree or none was cast, written by code."""
    cast = {vote.level for vote in votes if vote.level is not None}
    said = ", ".join(f"{_READABLE[vote.signal]} says {_level(vote.level)}" for vote in votes)
    if not cast:
        return (
            f"No signal could vote ({said}). Nothing supports a lower level, so the update "
            f"is treated as {final.capitalize()} until a developer reviews it."
        )
    if len(cast) > 1:
        return (
            f"The signals disagree: {said}. The most cautious, {final.capitalize()}, was "
            "taken; a developer should confirm it."
        )
    return ""


def assess(
    update: DependencyUpdate,
    changelog: ChangelogReport | None,
    impact: ImpactReport | None,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> UpdateAssessment:
    started = clock()
    analysis = _analysis(changelog, update)
    update_impact = _impact(impact, update)
    votes = [
        semver_vote(update),
        changelog_vote(analysis, stage_ran=changelog is not None),
        usage_vote(update_impact, stage_ran=impact is not None),
    ]
    final, decided_by = safety_first({vote.signal: vote.level for vote in votes})
    high = final == "high"
    files = sorted(
        {reference.span.path for reference in update_impact.references} if update_impact else set()
    )
    components = sorted(
        component.node_id
        for component in (impact.affected_components if impact else [])
        if update.id in component.update_ids
    )
    arbitration_seconds = clock() - started
    return UpdateAssessment(
        update_id=update.id,
        key=update.key,
        package=update.package,
        ecosystem=update.ecosystem,
        from_version=update.from_version,
        to_version=update.to_version,
        change=update.change,
        votes=votes,
        arbitration=Arbitration(
            rule_id=ARBITRATION_RULE,
            final=final,
            decided_by=list(decided_by),
            advisory=advisory(votes, final),
        ),
        strategy=Strategy(
            rule_id=STRATEGY_RULE,
            deploy=strategy_for(final),
            manual_review_required=high,
            rollback_required=high,
        ),
        affected_files=files,
        affected_components=components,
        evidence=evidence(update, analysis, update_impact, impact),
        latency=Latency(
            changelog_seconds=analysis.model.duration_seconds
            if analysis is not None and analysis.model is not None
            else 0.0,
            usage_seconds=update_impact.seconds if update_impact is not None else 0.0,
            arbitration_seconds=round(arbitration_seconds, 6),
        ),
    )


def report(
    updates: DependencyUpdates,
    changelog: ChangelogReport | None,
    impact: ImpactReport | None,
    *,
    version: int,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> RiskReport:
    return RiskReport(
        version=version,
        generated_at=now or datetime.now(UTC),
        assessments=[assess(update, changelog, impact, clock=clock) for update in updates.updates],
    )
