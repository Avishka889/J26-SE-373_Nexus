"""The shape a model answers the changelog question in, and the request it is asked.

These are the model's draft claims, before any is checked. What survives the
check becomes a `ChangelogClaim` in the report; what does not becomes a
`RefusedClaim`, with its reason. The kinds are the contract's own, so the forced
tool call's schema already names every kind the rule can rate.
"""

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field
from sdlc_contracts import ClaimKind

from .notes import Section, render


class DraftClaim(BaseModel):
    kind: ClaimKind = Field(
        description=(
            "breaking (the notes say existing use breaks), removal (something is removed), "
            "behavioural (existing behaviour changes without being called breaking), "
            "deprecation, security, fix, feature, or other."
        )
    )
    symbols: list[str] = Field(
        default_factory=list,
        description=(
            "API names the quoted sentence itself contains, copied exactly, such as "
            "Client.connect or app.del. Empty when the sentence names none."
        ),
    )
    quote: str = Field(
        description="The sentence the claim rests on, copied character for character."
    )
    version: str = Field(description="The release heading the quote sits under.")


class ChangelogAnswer(BaseModel):
    claims: list[DraftClaim] = Field(default_factory=list)
    stated_level: Literal["low", "medium", "high"] = Field(
        description="Your own overall reading of this update's risk. Recorded, not used."
    )


def request(
    package: str, ecosystem: str, from_version: str, to_version: str, sections: Iterable[Section]
) -> str:
    """The user message: which update, and every release note inside its window."""
    return (
        f"Package: {package} ({ecosystem}).\n"
        f"Installed version: {from_version}. Target version: {to_version}.\n"
        f"These are the notes of every release after {from_version} up to and including "
        f"{to_version}, each under its version heading.\n\n"
        f"{render(sections)}"
    )
