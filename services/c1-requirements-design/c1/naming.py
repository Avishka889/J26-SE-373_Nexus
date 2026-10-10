"""Naming a project from the text it was created with.

Truncating the reader's first sentence at forty eight characters gives "Build a
web application for FOMMP (Farmer Organi...", which is a sentence with its end
cut off rather than a title. Naming is summarisation, so it needs the model.

Deliberately its own agent rather than a field added to the requirements
extraction output. That output is tuned, and widening it risks degrading the
primary task for a benefit as small as a title. A separate agent cannot degrade
extraction at all, and when it fails the run carries on with the name it
already had.
"""

import re

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext

from .agents import MALFORMED_OUTPUT_RETRIES, output_for, settings_for
from .model_use import records_answers

#: Where a title stops, matching the client's name limit so a generated title
#: never needs truncating in the UI.
TITLE_LIMIT = 48

MIN_WORDS = 2
MAX_WORDS = 6

#: How much of the input the title is written from.
#:
#: A title comes from the opening of a brief, not from its appendices, and
#: sending forty thousand characters to name a project would cost more than the
#: six stages that actually produce something.
PROMPT_CHARS = 2_000

#: Words too common to prove a title came from this particular input. A title
#: built only from these has named a category, not a system.
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "app",
        "application",
        "for",
        "of",
        "or",
        "platform",
        "portal",
        "service",
        "software",
        "solution",
        "system",
        "the",
        "to",
        "tool",
        "web",
        "with",
    }
)

INSTRUCTIONS = """
You name a software project, the way a person titles a document.

Write two to six words saying what the system is. Not what it would take to
build it, not a sentence, not a description.

  "Build a web application for FOMMP (Farmer Organizations Management and
   Monitoring Platform) as specified in the attached BRD"   ->  FOMMP Platform
  "Create an inventory API with stock levels and low stock alerts"
                                                            ->  Inventory API
  "Build a simple calculator app"                           ->  Calculator

Rules you must follow:

1. Use the words the text uses. If it names the system, use that name.
2. Never open with a verb like Build, Create, Make or Design. Those describe
   the request, not the system.
3. Never return the opening words of the text. A title is not the first line
   with its end cut off.
4. No trailing punctuation.
""".strip()


class DraftTitle(BaseModel):
    """What the model may produce. Bounded here by length alone, not by content.

    A one word title, or one that shares nothing with the text, still satisfies
    this type; catching those is the output validator's job, not this one's.
    Between the type's bound and the validator's, `name_project` never returns a
    title that failed a rule.
    """

    title: str = Field(min_length=2, max_length=TITLE_LIMIT)


#: Leading quote and heading markers, emphasis, quotes and closing punctuation.
_WRAPPING = re.compile(r"^[\s>#*_\"'`:-]+|[\s.!?*_\"'`:]+$")


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", text.lower())


def _content_words(text: str) -> set[str]:
    return {word for word in _words(text) if word not in _STOP and len(word) > 2}


def prompt_for(text: str) -> str:
    return "Name the system described here.\n\n" + text[:PROMPT_CHARS]


def check_is_a_title(title: str, text: str) -> str:
    """The rules a title has to satisfy, returning the cleaned title.

    A plain function rather than logic buried in the validator, so the rules can
    be tested without a model at all. That is how `check_no_invented_figures`
    works in the architecture explainer, and for the same reason: a rule tested
    through a model is tested slowly and flakily.

    Raises `ValueError` with the reason. The agent's validator turns that into a
    `ModelRetry`, so the model is told what was wrong rather than simply asked
    again.
    """
    # Markdown a model wraps its answer in, and quotes, off both ends: a title
    # came back as "> Community Library Reservation System", quote marker and
    # all, and was the project's name until someone renamed it.
    cleaned = _WRAPPING.sub("", title)
    words = _words(cleaned)

    if not MIN_WORDS <= len(words) <= MAX_WORDS:
        raise ValueError(
            f"A title is {MIN_WORDS} to {MAX_WORDS} words and yours has {len(words)}. "
            "Say what the system is, not what it does."
        )

    if text.strip().lower().startswith(cleaned.lower()):
        raise ValueError(
            "That is the opening of the text, not a title. Say what the system is "
            "in your own words."
        )

    # An intersection, not a subset: one shared content word is enough, and the
    # rest of the title does not have to be grounded. That is enough to catch
    # wholesale invention, a title with no relationship to the input, and a
    # title built only from category words like "Web Application Platform",
    # which has no content words left once stopwords are removed. It does no
    # stemming or synonym matching: "Dispensing" only grounds against
    # "dispensing" appearing in the text, not against "dispense".
    if not _content_words(cleaned) & _content_words(text):
        raise ValueError(
            "The title shares no word with the text it describes. Name what this "
            "system actually is, using the text's own words."
        )

    return cleaned


def build_naming_agent(
    model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[str, DraftTitle]:
    """The naming agent. Build one and keep it; it owns a connection.

    The input text travels as `deps` rather than being re-parsed out of the
    prompt, because the validator needs the whole brief to check grounding while
    the prompt only carries its opening.
    """
    agent = Agent(
        model,
        output_type=output_for(DraftTitle, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        deps_type=str,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )

    @agent.output_validator
    def is_a_title(ctx: RunContext[str], draft: DraftTitle) -> DraftTitle:
        try:
            return DraftTitle(title=check_is_a_title(draft.title, ctx.deps))
        except ValueError as exc:
            raise ModelRetry(str(exc)) from exc

    return agent


async def name_project(text: str, *, agent: Agent[str, DraftTitle]) -> str:
    """A title for this brief, or a raised error if the model would not write one."""
    result = await agent.run(prompt_for(text), deps=text)
    return result.output.title
