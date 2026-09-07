"""UML artefacts, generated from the graph rather than drawn beside it.

Class and entity relationship diagrams carry no source: they are projections
over the SAG, so a rename in the graph reaches them by construction. Sequence
diagrams keep authored steps, because a real interaction has a request, a check,
a persist and a response, and a mechanical rendering of one actor-verb-entity
triple would be a single shallow arrow. What they do not keep is authored names:
participants are node ids and message text carries `{nodeId}` tokens, so a
rename propagates without flattening the interaction.
"""

import re
from typing import Literal

from pydantic import Field, model_validator

from .ids import StoryId, Traces
from .wire import WireModel

UmlDiagramKind = Literal["class", "er", "activity", "sequence"]

#: The token syntax, compiled, next to the description that documents it.
#:
#: It lives here because more than one side needs to agree on it and none of them
#: may depend on the others: the component that writes diagrams, and the
#: orchestrator that later checks whether a token still names a node. A second
#: copy of this pattern would be a second definition of the contract.
NODE_TOKEN = re.compile(r"\{([A-Za-z0-9_-]+)\}")


#: Spelled into the schema rather than left as a code comment, because the
#: convention is the contract. A reader who only has the JSON Schema has to be
#: able to write a conforming step and a conforming renderer from it alone.
_TOKENS = (
    "Names inside the text are written as `{nodeId}` tokens, referring to nodes "
    "of the architecture graph, and are replaced with the node's current label "
    "when the diagram is drawn. Never write a node's name in as text: the copy "
    "would not follow a rename. A token naming no node renders as the literal "
    "braces, which is deliberate, since a silently dropped name reads as correct."
)


class SequenceStep(WireModel):
    from_id: str = Field(
        min_length=1, description="Id of the architecture graph node this step goes from."
    )
    to_id: str = Field(
        min_length=1, description="Id of the architecture graph node this step goes to."
    )
    message: str = Field(min_length=1, description=f"What is asked or answered. {_TOKENS}")
    kind: Literal["call", "return", "note"] = Field(
        description="call for a request, return for an answer, note for an aside."
    )


class UseCase(WireModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    traces: Traces
    #: The story this interaction realises, when there is one.
    story_id: StoryId | None = None
    steps: list[SequenceStep] = Field(min_length=1)


class UmlDiagram(WireModel):
    id: str = Field(min_length=1)
    kind: UmlDiagramKind
    title: str = Field(min_length=1)
    description: str = ""
    source: str | None = Field(
        default=None,
        description=(
            "Authored diagram text, when there is any. Null means the diagram is "
            "projected from the architecture graph when it is drawn, which is the "
            "case for class and entity relationship diagrams: freezing their text "
            "here would keep an old name after a node is renamed."
        ),
    )
    use_case_id: str | None = Field(
        default=None, description="The use case this diagram draws, for sequence diagrams."
    )
    traces: Traces


class UmlArtefact(WireModel):
    use_cases: list[UseCase] = Field(default_factory=list)
    diagrams: list[UmlDiagram] = Field(default_factory=list)

    @model_validator(mode="after")
    def sequence_diagrams_name_a_real_use_case(self) -> "UmlArtefact":
        known = {u.id for u in self.use_cases}
        for diagram in self.diagrams:
            if diagram.use_case_id is not None and diagram.use_case_id not in known:
                raise ValueError(
                    f"diagram {diagram.id} names an unknown use case: {diagram.use_case_id}"
                )
        return self
