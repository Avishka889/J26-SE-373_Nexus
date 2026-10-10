"""The architecture recommendation.

Two axes, deliberately kept apart. A deployment shape (how the system is
deployed and scaled) is scored against other deployment shapes. A code
organisation style (how the source is arranged inside whatever is deployed) is
recorded as a note, because scoring "Clean Architecture 71" against
"Microservices 68" compares two things that are not alternatives.

Scores come from a rule based function over the parsed scope and the graph. The
model writes the explanation only, and cannot write a score because there is no
field here for it to write one into.
"""

from pydantic import Field

from .wire import Prose, WireDatetime, WireModel


class TopologyCandidate(WireModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    #: Rule based, computed from the parsed scope and the graph.
    score: int = Field(ge=0, le=100)
    rationale: Prose = Field(min_length=1)
    pros: list[Prose] = Field(min_length=1)
    #: At least two, because a candidate listing only upside makes the score the
    #: single honest thing on the card, and a comparison of three such cards is
    #: not a comparison.
    cons: list[Prose] = Field(min_length=2)


class ArchitectureStyleNote(WireModel):
    """A code organisation style: applies inside whichever shape is chosen."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    note: Prose = Field(min_length=1)


class ArchitectureRecommendation(WireModel):
    candidates: list[TopologyCandidate] = Field(min_length=2)
    #: What the scoring function suggests.
    recommended_candidate_id: str
    #: What the human chose. Null until somebody decides, and the gate will not
    #: let an approval through without it.
    selected_candidate_id: str | None = None
    selected_at: WireDatetime | None = None
    selected_by: str | None = None
    style: ArchitectureStyleNote

    def model_post_init(self, _context: object) -> None:
        known = {c.id for c in self.candidates}
        if self.recommended_candidate_id not in known:
            raise ValueError(
                f"recommendedCandidateId {self.recommended_candidate_id!r} is not a candidate"
            )
        if self.selected_candidate_id is not None and self.selected_candidate_id not in known:
            raise ValueError(
                f"selectedCandidateId {self.selected_candidate_id!r} is not a candidate"
            )
