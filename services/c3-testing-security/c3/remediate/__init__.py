"""Approval gated remediation: propose a fix, let a person decide, then measure.

The governance half of the security pillar rather than a second research core.
C3 proposes and C2 applies, which is why this package produces an artefact
carrying a patch and a decision state rather than editing anything itself.

Four pieces, and each exists to stop a different way this goes wrong:

`guard` refuses a patch that silences the tool instead of fixing the weakness,
which is the security analogue of the assertion weakening the healing loop
refuses. `risk` states the danger as counts a reader can check rather than as
an adjective a model chose. `patch` asks a model for the replacement lines of a
known span, so it is never trusted to locate anything. `reverify` answers "did
it work" by subtraction, and refuses to subtract two passes that were not
measured the same way.
"""

from .guard import Refusal, accepts, refusal_for, suppressions_in
from .patch import PatchOutcome, ProposedFix, build_patcher, propose_patch, read_source
from .propose import MAX_PROPOSALS, ProposalRun, Unproposed, candidates, proposal_for, worst_first
from .reverify import NotComparable, compare, rollback_advice, snapshot_of
from .risk import assess, level_of, measure

__all__ = [
    "MAX_PROPOSALS",
    "NotComparable",
    "PatchOutcome",
    "ProposalRun",
    "ProposedFix",
    "Refusal",
    "Unproposed",
    "accepts",
    "assess",
    "build_patcher",
    "candidates",
    "compare",
    "level_of",
    "measure",
    "proposal_for",
    "propose_patch",
    "read_source",
    "refusal_for",
    "rollback_advice",
    "snapshot_of",
    "suppressions_in",
    "worst_first",
]
