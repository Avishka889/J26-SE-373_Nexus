"""Model prose reaches the page without em or en dashes; quotes and people's words as written.

Seven of Book Tracker's architecture options carried an em dash from the model,
and the platform's own copy never uses one. The contracts normalise model prose
where every artefact passes, so text stored before this reads the same.
"""

import pytest
from sdlc_contracts import Assumption, ParsedRequirement, TopologyCandidate
from sdlc_contracts.wire import plain_dashes

EM, EN = "\u2014", "\u2013"


@pytest.mark.parametrize(
    ("written", "shown"),
    [
        (f"Simple {EM} one deploy", "Simple, one deploy"),
        (f"Simple{EM}one deploy", "Simple, one deploy"),
        (f"Handles 5{EN}10 services", "Handles 5-10 services"),
        (f"{EM} Leading dash", "Leading dash"),
        (f"Trailing dash {EM}", "Trailing dash"),
        (f"A pause {EM}.", "A pause."),
        ("No dash at all, as most prose is.", "No dash at all, as most prose is."),
    ],
)
def test_a_dash_becomes_a_comma_and_a_range_a_hyphen(written: str, shown: str) -> None:
    assert plain_dashes(written) == shown


def test_an_architecture_option_reads_without_the_models_dashes() -> None:
    option = TopologyCandidate(
        id="monolith",
        name="Modular monolith",
        score=80,
        rationale=f"One deploy {EM} one database",
        pros=[f"Fast {EM} to change"],
        cons=[f"One scale {EM} for all", "One failure domain"],
    )
    assert option.rationale == "One deploy, one database"
    assert option.pros == ["Fast, to change"]
    assert option.cons[0] == "One scale, for all"


def test_a_persons_correction_and_a_verbatim_quote_stay_as_written() -> None:
    quote = f"Books {EM} with their authors {EM} are listed"
    read = ParsedRequirement(
        id="R-1",
        text=f"The system shall list books {EM} with authors",
        type="functional",
        priority="must",
        confidence=80,
        source_quote=quote,
    )
    corrected = read.model_copy(update={"text": f"List books {EM} quickly", "adjusted": True})
    corrected = ParsedRequirement.model_validate(corrected.model_dump())

    assert read.text == "The system shall list books, with authors"
    assert read.source_quote == quote, "a quote is checked against its source letter for letter"
    assert corrected.text == f"List books {EM} quickly", "a person's words are theirs"

    edited = Assumption(id="A-1", text=f"Users {EM} log in", traces=["R-1"], edited=True)
    assert edited.text == f"Users {EM} log in"
