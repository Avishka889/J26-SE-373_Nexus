"""Signal three (FR9): what this project's own use of an update's changes implies.

The changed symbols come from two places, each tagged on the symbol: the API
diff of the two releases, and the symbols named in verified release note
claims. A claim's kind says what happened to what it names:

| claim | the symbols it names are |
|---|---|
| removal | removed |
| breaking | breaking-behaviour |
| behavioural | behaviour-changed |
| deprecation | deprecated |
| security, fix, feature, other | touched |

`usage-rule/1` then rates the kinds of the changed symbols the project was
found to use, read back from its files. Using a removed or changed symbol is
High; using one whose behaviour changed or that is deprecated is Medium; a
package the project imports while using none of what changed is Low, and is
recorded as low project specific impact rather than as nothing found. With no
changed symbols known at all there is nothing to look for, and the signal
abstains.
"""

from sdlc_contracts import (
    USAGE_RULE,
    ChangedSymbol,
    ChangeKind,
    ChangelogReport,
    ClaimKind,
    DependencyUpdate,
    RefusedReference,
    SignalVote,
    UpdateImpact,
    UsageReference,
    usage_level,
)

from .api_diff import ApiDiff
from .index import SymbolIndex
from .references import candidates, importable, maven_scope, read_back

CLAIM_CHANGE: dict[ClaimKind, ChangeKind] = {
    "removal": "removed",
    "breaking": "breaking-behaviour",
    "behavioural": "behaviour-changed",
    "deprecation": "deprecated",
    "security": "touched",
    "fix": "touched",
    "feature": "touched",
    "other": "touched",
}

#: The changes that decide a High, then a Medium, named in a rationale in this order.
_SEVERITY: tuple[ChangeKind, ...] = (
    "removed",
    "signature-changed",
    "renamed",
    "breaking-behaviour",
    "behaviour-changed",
    "deprecated",
)


def claimed_symbols(
    changelog: ChangelogReport | None, update: DependencyUpdate
) -> list[ChangedSymbol]:
    """The symbols verified release note claims name for this update, each tagged with its claim."""
    if changelog is None:
        return []
    found: list[ChangedSymbol] = []
    for analysis in changelog.per_update:
        if analysis.update_id != update.id:
            continue
        for claim in analysis.claims:
            for symbol in claim.symbols:
                found.append(
                    ChangedSymbol(
                        update_id=update.id,
                        symbol=symbol,
                        kind=CLAIM_CHANGE[claim.kind],
                        source="changelog",
                        tool=f"claim:{claim.id}",
                        detail=f"{claim.kind} in {claim.version}: {claim.quote[:160]}",
                    )
                )
    return found


def evidence_id(update: DependencyUpdate, position: int) -> str:
    """The id the risk assessment cites a reference by: its place in the impact, from one."""
    return f"{update.id}-r{position}"


def _rationale(
    update: DependencyUpdate,
    level: str,
    references: list[UsageReference],
    symbols: list[ChangedSymbol],
    importers: list[str],
) -> str:
    """Written by code from the checked references, never by a model."""
    if not references:
        where = (
            f"imported in {len(importers)} file{'s' if len(importers) != 1 else ''}"
            if importers
            else "not imported by any source file"
        )
        return (
            f"{update.package} is {where}, and none of its {len(symbols)} changed "
            f"symbol{'s' if len(symbols) != 1 else ''} is used: low project specific impact."
        )
    decisive = (
        next(
            reference
            for kind in _SEVERITY
            for reference in references
            if reference.symbol_kind == kind
        )
        if level != "low"
        else references[0]
    )
    files = sorted({reference.span.path for reference in references})
    return (
        f"The project uses {len({r.symbol for r in references})} of {update.package}'s "
        f"changed symbols in {len(files)} file{'s' if len(files) != 1 else ''}. The most "
        f"severe, {decisive.symbol} ({decisive.symbol_kind}), is at "
        f"{decisive.span.path}:{decisive.span.start_line}, which {USAGE_RULE} rates "
        f"{level.capitalize()}."
    )


def update_impact(
    update: DependencyUpdate,
    index: SymbolIndex,
    files: dict[str, str],
    *,
    api: ApiDiff,
    claimed: list[ChangedSymbol],
) -> tuple[UpdateImpact, list[RefusedReference], list[ChangedSymbol]]:
    """Signal three for one update: its references, what was refused, and its symbols."""
    symbols = [*api.symbols, *claimed]
    scope = maven_scope(files, update) if update.ecosystem == "maven" else ()
    found, importers = candidates(index, update, symbols, scope=scope)
    references, refused = read_back(found, files, update_id=update.id)
    used = {reference.symbol for reference in references}
    unreferenced = sorted({symbol.symbol for symbol in symbols} - used)
    names = importable(update)
    scripts = any(tool.package in names for tool in index.tools)
    level = usage_level(
        [reference.symbol_kind for reference in references],
        changed_symbols_known=bool(symbols),
    )
    if level is None:
        detail = f" ({api.reason})" if api.reason else ""
        diff = {
            "ran": f"ran and found no breaking change{detail}",
            "unavailable": f"was unavailable{detail}",
            "failed": f"failed{detail}",
        }[api.state]
        reason = (
            f"no changed symbols are known for this update: the API diff {diff}, and no "
            "verified release note claim names a symbol"
        )
        vote = SignalVote(
            signal="usage",
            abstained_reason=reason,
            rule_id=USAGE_RULE,
            rationale=f"The usage signal abstains: {reason}.",
        )
    else:
        vote = SignalVote(
            signal="usage",
            level=level,
            rule_id=USAGE_RULE,
            rationale=_rationale(update, level, references, symbols, importers),
            evidence_ids=[evidence_id(update, n) for n in range(1, len(references) + 1)],
        )
    impact = UpdateImpact(
        update_id=update.id,
        imports_package=bool(importers) if update.ecosystem == "npm" else bool(references),
        used_by_scripts=scripts,
        references=references,
        unreferenced=unreferenced,
        api_diff=api.state,
        api_diff_reason=api.reason,
        vote=vote,
    )
    return impact, refused, symbols
