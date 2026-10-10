"""Interactions, written by the model and checked against the graph.

This is the one UML artefact a model earns its place on. A real interaction has a
request, a check, a persist and a response, and none of that can be read off a
single actor-verb-entity triple: the graph knows that a customer makes a payment,
not that the payment service asks the verification service first.

What the model must not do is name anything. Participants are node ids, and any
name inside a message is written as `{a1}` and resolved from the graph when the
diagram is drawn. That is what makes a rename propagate: change the node's label
and every line of every diagram follows, because none of them ever held a copy.

Two validators enforce it. Every participant must be a node that exists, and
every token in every message must resolve. A step naming a participant the graph
does not have would render as a lifeline for a thing that is not in the design.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from sdlc_contracts import NODE_TOKEN, ArchitectureGraph, SequenceStep, UseCase

from ..agents import MALFORMED_OUTPUT_RETRIES, output_for, settings_for
from ..model_use import records_answers

INSTRUCTIONS = """
You write one interaction between the parts of a system, as a sequence of steps.

You are given the parts, each with an id and a name. Refer to every part by its
id, never by its name:

  fromId, toId   the id of the part the step goes from and to
  message        what is being asked or answered
  kind           call for a request, return for an answer, note for an aside

If you need to mention a part inside a message, write its id in braces, like
{e2}. It is replaced with the current name when the diagram is drawn, so a part
that is renamed later stays correct. Never type a part's name into a message.

Write the interaction as it really happens: the request, the checks it triggers,
what is written down, and the answer that comes back. Six to twelve steps is
usually right. Do not invent parts that are not in the list.
""".strip()


class DraftStep(BaseModel):
    from_id: str = Field(default="", description="The id of the part this step goes from.")
    to_id: str = Field(default="", description="The id of the part this step goes to.")
    message: str = Field(default="", description="What is asked or answered. Use {id} for names.")
    kind: str = Field(default="call", description="call, return, or note.")


class DraftInteraction(BaseModel):
    """One interaction the model wrote."""

    name: str = Field(default="", description="What this interaction is called, in plain words.")
    steps: list[DraftStep] = Field()


@dataclass(frozen=True)
class SequenceReport:
    """What had to be corrected, for the evaluation."""

    steps_returned: int = 0
    unknown_participants: tuple[str, ...] = field(default=())
    unresolved_tokens: tuple[str, ...] = field(default=())
    #: Names the model typed as text and that were turned back into tokens. Not
    #: a failure, but worth counting: it says how often the instruction to use
    #: ids was ignored.
    names_tokenised: tuple[str, ...] = field(default=())


def unknown_participants(interaction: DraftInteraction, known: set[str]) -> list[str]:
    """Participants the graph does not have.

    Blank ones are handled separately rather than swept in here, so the message
    the model gets can say something other than "'' is not a part of this system".
    """
    used = {step.from_id for step in interaction.steps} | {step.to_id for step in interaction.steps}
    return sorted(participant for participant in used if participant and participant not in known)


def blank_participants(interaction: DraftInteraction) -> list[int]:
    """Step numbers where an end of the arrow was left empty.

    Its own check because the obvious way to write the one above skips empty
    strings, which lets a blank through validation and turns it into a raw
    ValidationError at construction: a stack trace instead of a retry the model
    could have acted on. A real Groq run produced exactly that.
    """
    return [
        number
        for number, step in enumerate(interaction.steps, start=1)
        if not step.from_id.strip() or not step.to_id.strip()
    ]


def unresolved_tokens(interaction: DraftInteraction, known: set[str]) -> list[str]:
    """`{id}` tokens in messages that name nothing in the graph.

    An unresolved token is worse than a wrong name: it renders as the literal
    braces, so the reader sees `{e9}` in the middle of a sentence.
    """
    found: set[str] = set()
    for step in interaction.steps:
        for match in NODE_TOKEN.finditer(step.message):
            if match.group(1) not in known:
                found.add(match.group(1))
    return sorted(found)


def names_typed_instead_of_ids(
    interaction: DraftInteraction, graph: ArchitectureGraph
) -> list[str]:
    """Node labels written into a message as text rather than as a token.

    The failure that looks harmless and is not: the diagram reads correctly today
    and keeps saying "Payment Service" after somebody renames that node, because
    this copy was never connected to it.

    Matched case sensitively, and that is a deliberate limit rather than an
    oversight. A node called "Payment" must not make the word "payment"
    unusable: "confirms a payment" is ordinary English, and refusing it would
    force the model into contortions to describe its own domain. A reference to
    the node is capitalised as the node is; incidental prose is not. This misses
    a lowercase reference, and catching that would cost more than it is worth.
    """
    labels = {node.label for node in graph.nodes if len(node.label) > 3}
    offenders: set[str] = set()
    for step in interaction.steps:
        # Tokens are the correct form, so they are removed before looking.
        bare = NODE_TOKEN.sub(" ", step.message)
        for label in labels:
            if label in bare:
                offenders.add(label)

    # "Payment" is a prefix of "Payment Service", so a message naming the service
    # matches both. Reporting the shorter one too would send the model a hint
    # about a node it never mentioned.
    return sorted(
        label
        for label in offenders
        if not any(other != label and label in other for other in offenders)
    )


def tokenise_names(message: str, graph: ArchitectureGraph) -> tuple[str, list[str]]:
    """Turn a typed node name back into the token it should have been.

    Lossless: the rendered sentence is identical today, and correct tomorrow when
    the node is renamed. Longest label first, so "Payment Service" is replaced as
    one thing rather than having its first word swapped out from under it.
    """
    by_length = sorted(
        (node for node in graph.nodes if len(node.label) > 3),
        key=lambda node: -len(node.label),
    )
    replaced: list[str] = []
    out = message
    for node in by_length:
        # Skip anything already inside braces, which is the correct form.
        if node.label in NODE_TOKEN.sub(" ", out):
            out = out.replace(node.label, f"{{{node.id}}}")
            replaced.append(node.label)
    return out, replaced


def build_sequence_agent(
    model: str, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[ArchitectureGraph, DraftInteraction]:
    """The interaction agent, with the participant checks attached.

    Validators rather than checks afterwards, so a bad interaction is sent back
    with the reason instead of being repaired here or reaching a reader.
    """
    agent: Agent[ArchitectureGraph, DraftInteraction] = Agent(
        model,
        output_type=output_for(DraftInteraction, model, thinking=thinking),
        deps_type=ArchitectureGraph,
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )

    @agent.output_validator
    def participants_exist(
        ctx: RunContext[ArchitectureGraph], output: DraftInteraction
    ) -> DraftInteraction:
        known = {node.id for node in ctx.deps.nodes}

        blank = blank_participants(output)
        if blank:
            raise ModelRetry(
                f"Step {', '.join(str(n) for n in blank)} does not say who it is between. "
                f"Every step needs a fromId and a toId, each one of: {', '.join(sorted(known))}."
            )

        missing = unknown_participants(output, known)
        if missing:
            raise ModelRetry(
                f"These are not parts of this system: {', '.join(missing)}. "
                f"Use only these ids: {', '.join(sorted(known))}."
            )

        dangling = unresolved_tokens(output, known)
        if dangling:
            raise ModelRetry(
                f"These braces name nothing: {', '.join('{' + t + '}' for t in dangling)}. "
                f"Use only these ids: {', '.join(sorted(known))}."
            )

        # A typed name is not sent back. It is corrected, below, when the use
        # case is assembled: replacing the exact label with its token is
        # mechanical and loses nothing, and refusing it instead cost two retries
        # and then the whole run when a real model wrote "Payment" for a node
        # called Payment. Reserving retries for what cannot be fixed here.

        if not output.steps:
            raise ModelRetry("An interaction with no steps says nothing. Write the steps.")

        return output

    return agent


def prompt_for(graph: ArchitectureGraph, story: str) -> str:
    """The parts, and the thing that should happen between them."""
    parts = "\n".join(
        f"  {node.id}: {node.label} ({node.kind})"
        for node in graph.nodes
        if node.kind != "constraint"
    )
    return (
        f"The parts of this system:\n{parts}\n\n"
        f"Write the interaction for: {story}\n\n"
        f"Refer to every part by its id."
    )


async def write_interaction(
    graph: ArchitectureGraph,
    story: str,
    *,
    agent: Agent[ArchitectureGraph, DraftInteraction],
    use_case_id: str,
    traces: list[str],
    story_id: str | None = None,
) -> tuple[UseCase, SequenceReport]:
    """Write one interaction and turn it into the contract's use case."""
    result = await agent.run(prompt_for(graph, story), deps=graph)
    interaction = result.output

    known = {node.id for node in graph.nodes}
    steps: list[SequenceStep] = []
    tokenised: list[str] = []
    for step in interaction.steps:
        message, replaced = tokenise_names(step.message.strip(), graph)
        tokenised.extend(replaced)
        steps.append(
            SequenceStep(
                fromId=step.from_id,
                toId=step.to_id,
                message=message,
                kind=step.kind if step.kind in {"call", "return", "note"} else "call",
            )
        )

    use_case = UseCase(
        id=use_case_id,
        name=interaction.name.strip() or story,
        traces=list(traces),
        storyId=story_id,
        steps=steps,
    )
    report = SequenceReport(
        steps_returned=len(steps),
        unknown_participants=tuple(unknown_participants(interaction, known)),
        unresolved_tokens=tuple(unresolved_tokens(interaction, known)),
        names_tokenised=tuple(sorted(set(tokenised))),
    )
    return use_case, report
