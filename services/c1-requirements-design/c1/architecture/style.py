"""Which code organisation style suits the design, chosen by rule.

A style and a topology are different axes and the project settled that early:
Layered, Clean and Modular are ways to organise code inside whichever deployment
shape is picked, so scoring them against Microservices would produce "Clean
Architecture 71 versus Microservices 68", a comparison of two things that are not
alternatives.

So there is no score here and there are no candidates. One style is chosen from
the same counted facts the topologies are scored on, and the note says which fact
chose it. That is the whole claim: a reader can disagree with the rule, and to do
that they have to be able to see it.

The order matters and is not arbitrary. Something the design does not control,
an external system or a rule it must satisfy, is the strongest signal, because
that is the problem Clean Architecture exists to solve and the one that is
expensive to retrofit. Size comes next. Everything else is Layered, which is the
honest default for a small system rather than a consolation prize.
"""

from sdlc_contracts import ArchitectureStyleNote

from .scoring import ScoringFacts

#: Entities at which organising by feature starts to beat organising by layer.
#: A judgement, stated here rather than buried in a condition, so it can be
#: argued with.
MODULAR_ENTITY_THRESHOLD = 5


def choose_style(facts: ScoringFacts) -> ArchitectureStyleNote:
    """One style, and the counted reason it was chosen."""
    if facts.n_external > 0 or facts.compliance_signal:
        reasons = []
        if facts.n_external:
            reasons.append(f"{facts.n_external} external system(s) this design does not control")
        if facts.compliance_signal:
            reasons.append("a rule the design has to satisfy")
        return ArchitectureStyleNote(
            id="clean",
            name="Clean Architecture",
            note=(
                f"Chosen because the design has {' and '.join(reasons)}. Keeping the domain "
                f"behind ports means the part that has to be correct does not change when "
                f"somebody else's system or the rule around it does."
            ),
        )

    if facts.n_entities >= MODULAR_ENTITY_THRESHOLD and facts.n_services > 1:
        return ArchitectureStyleNote(
            id="modular",
            name="Modular by feature",
            note=(
                f"Chosen because {facts.n_entities} entities across {facts.n_services} services "
                f"is enough that organising by layer would spread one feature across every "
                f"folder. Grouping by feature keeps a change in one place, and it is also the "
                f"seam to split along later if the shape ever needs to change."
            ),
        )

    return ArchitectureStyleNote(
        id="layered",
        name="Layered",
        note=(
            f"Chosen because {facts.n_entities} entities and {facts.n_services} service(s) is "
            f"small enough that layers stay readable, and nothing here is outside the "
            f"design's control. The plain option, because a small system does not need more."
        ),
    )
