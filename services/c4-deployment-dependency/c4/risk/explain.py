"""The explanation a developer reads (B7): written by a model, checked by code.

The level is decided before any prose is written, by rules, and the prose can
only describe it. A model is shown the assessment as data (the final level, each
signal's vote and the reason code wrote for it, the advisory, the strategy and
the evidence) and never the project's code: a reference is shown as the symbol
and where it is used, not the line itself. It answers with the level it is
explaining and two to four sentences. Its answer is used only if it passes four
checks, each of which is a way prose can mislead a reader about a decision it
did not make:

- **the level it states is the final level**;
- **every level it names** is the final level or one some signal actually voted,
  so a "Medium" the rules never produced cannot appear;
- **everything it quotes**, in backticks or double quotes, is in what it was shown;
- **every file it names** is in the evidence.

A refused answer is replaced by a summary code writes from the same data, and
the refusal is kept on the assessment with its reason, so the study can count
how often the model's prose could not be used. A model that cannot be built or
does not answer leaves the rule written summary, with that as the reason. A rate
limit stops the explanations; the rest are rule written. Nothing is retried here.

**What a developer reads has no em or en dashes.** The prompt (explain/2) asks
for none, and any the model writes anyway are replaced once the answer has
passed the check: a pair around a phrase becomes parentheses, one before a
joining word a comma, one between two numbers "to", and any other a colon, or a
semicolon where the sentence already has one. A quote is never changed, because
it is someone else's words and the check proved it verbatim. How many were
replaced is kept on the assessment, so how often the prompt's rule was not kept
is a result rather than something the clean-up hides.

**Every call is recorded**, whatever came of it: the requests it made and the
tokens they cost, retries included, beside the model and the prompt (NFR13).
"""

import re
import time
from contextlib import AsyncExitStack
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from sdlc_contracts import (
    ModelCall,
    ModelCallSettings,
    ModelOutcome,
    RiskReport,
    UpdateAssessment,
)

from .. import prompts
from ..agents import (
    MALFORMED_OUTPUT_RETRIES,
    model_for,
    output_for,
    recorded_settings,
    settings_for,
)
from ..model_use import records_answers
from .changelog import spent
from .notes import normalise

PROMPT_ID = "explain-assessment/2"

_LEVEL = re.compile(r"\b(low|medium|high)\b", re.IGNORECASE)
_QUOTED = re.compile(r"`([^`]+)`|\"([^\"]+)\"|“([^”]+)”")
_FILE = re.compile(r"[\w./-]+\.(?:java|kt|ts|tsx|js|jsx|mjs|cjs|json|css|xml)\b")

_DASHES = ("\u2013", "\u2014")
_RANGE = re.compile(r"(?<=\d)\s*\u2013\s*(?=\d)")
#: A phrase set off by a pair of dashes inside one sentence. A full stop that is
#: not followed by a space (a version, a file name) does not end the sentence.
_PAIR = re.compile(
    r"\s*[\u2013\u2014]\s*((?:[^\u2013\u2014.!?]|[.!?](?=\S))+?)\s*[\u2013\u2014]\s*"
)
_DASH = re.compile(r"\s*[\u2013\u2014]\s*")
_SENTENCE_END = re.compile(r"[.!?]\s")
_JOINING = frozenset({"and", "but", "or", "so", "yet", "which", "while", "because", "though"})
_CLOSING = ",.;:!?)"


class ExplanationAnswer(BaseModel):
    level: Literal["low", "medium", "high"] = Field(
        description="The final level you were given, exactly."
    )
    text: str = Field(description="Two to four sentences for the developer.")


def explanation_agent(
    model: str | Model, *, thinking: str = "off"
) -> Agent[None, ExplanationAnswer]:
    return Agent(
        model_for(model),
        output_type=output_for(ExplanationAnswer, model, thinking=thinking),
        instructions=prompts.load(PROMPT_ID).text,
        retries=MALFORMED_OUTPUT_RETRIES,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def _evidence_line(summary: str, kind: str) -> str:
    """A reference without its line of code: the model never sees the project's code."""
    if kind == "reference":
        return summary.split(": ", 1)[0]
    return summary


def shown(assessment: UpdateAssessment) -> str:
    """The assessment as the model is shown it: data, and no code."""
    votes = "\n".join(
        f"- {vote.signal}: {vote.level.capitalize() if vote.level else 'no vote'}. {vote.rationale}"
        for vote in assessment.votes
    )
    evidence = "\n".join(
        f"- [{item.id}] {item.kind}: {_evidence_line(item.summary, item.kind)}"
        for item in assessment.evidence
    )
    strategy = assessment.strategy
    return (
        f"Update: {assessment.package} {assessment.from_version} to {assessment.to_version} "
        f"({assessment.ecosystem}, {assessment.change}).\n"
        f"Final level: {assessment.arbitration.final.capitalize()}, by "
        f"{assessment.arbitration.rule_id}, decided by "
        f"{', '.join(assessment.arbitration.decided_by) or 'no signal'}.\n"
        f"Votes:\n{votes}\n"
        + (
            f"Advisory: {assessment.arbitration.advisory}\n"
            if assessment.arbitration.advisory
            else ""
        )
        + f"Strategy: {strategy.deploy}"
        + ("; manual review" if strategy.manual_review_required else "")
        + ("; rollback prepared" if strategy.rollback_required else "")
        + f".\nEvidence:\n{evidence}\n"
    )


def check(answer: ExplanationAnswer, assessment: UpdateAssessment, request: str) -> str:
    """Why this answer cannot be shown, or "" when it can."""
    final = assessment.arbitration.final
    if answer.level != final:
        return f"it states {answer.level}, and the final level is {final}"
    voted = {vote.level for vote in assessment.votes if vote.level}
    for word in _LEVEL.findall(answer.text):
        if word.lower() != final and word.lower() not in voted:
            return f"it names {word.lower()}, which no signal voted and is not the final level"
    haystack = normalise(request)
    for match in _QUOTED.finditer(answer.text):
        quoted = next(group for group in match.groups() if group is not None)
        if normalise(quoted) not in haystack:
            return f"it quotes {quoted[:80]!r}, which is not in what it was shown"
    files = set(assessment.affected_files) | {
        path
        for item in assessment.evidence
        for path in _FILE.findall(_evidence_line(item.summary, item.kind))
    }
    for path in _FILE.findall(answer.text):
        if not any(path == known or known.endswith("/" + path) for known in files):
            return f"it names {path}, which the evidence does not"
    return ""


def _prose(segment: str, *, opens: bool, closes: bool) -> str:
    """One stretch of the model's own words with its dashes replaced."""

    def followed_by_punctuation(match: re.Match[str]) -> bool:
        return match.string[match.end() : match.end() + 1] in tuple(_CLOSING)

    def parenthesised(match: re.Match[str]) -> str:
        return f" ({match.group(1).strip()})" + ("" if followed_by_punctuation(match) else " ")

    def single(match: re.Match[str]) -> str:
        text = match.string
        if (opens and match.start() == 0) or (closes and match.end() == len(text)):
            return ""
        if followed_by_punctuation(match):
            # The punctuation that follows already does the dash's work.
            return ""
        following = text[match.end() :].split(maxsplit=1)
        if following and following[0].lower().strip(_CLOSING) in _JOINING:
            return ", "
        sentence = _SENTENCE_END.split(text[: match.start()])[-1]
        return "; " if ":" in sentence else ": "

    segment = _RANGE.sub(" to ", segment)
    segment = _PAIR.sub(parenthesised, segment)
    return _DASH.sub(single, segment)


def plain(text: str) -> tuple[str, int]:
    """The model's prose without em or en dashes, and how many were replaced.

    Only the model's own words are changed. What it put in backticks or double
    quotes is kept as it was, dashes and all: the check proved it verbatim, and a
    quote changed after that would no longer be what the evidence says.
    """
    pieces: list[str] = []
    replaced = 0
    at = 0
    quotes = [(match.start(), match.end()) for match in _QUOTED.finditer(text)]
    for start, end in [*quotes, (len(text), len(text))]:
        prose = text[at:start]
        replaced += sum(prose.count(dash) for dash in _DASHES)
        pieces.append(_prose(prose, opens=at == 0, closes=start == len(text)))
        pieces.append(text[start:end])
        at = end
    return "".join(pieces).strip(), replaced


def summary(assessment: UpdateAssessment) -> str:
    """The explanation code writes when the model's cannot be used."""
    final = assessment.arbitration.final.capitalize()
    deciders = ", ".join(assessment.arbitration.decided_by) or "no signal"
    said = "; ".join(
        f"{vote.signal}: {vote.level.capitalize() if vote.level else 'no vote'}"
        for vote in assessment.votes
    )
    strategy = assessment.strategy
    action = {
        "automatic": "It can ship automatically.",
        "approval": "It ships once a developer approves it.",
        "approval-with-rollback": (
            "It ships only after a developer reviews and approves it, with a rollback prepared."
        ),
    }[strategy.deploy]
    where = (
        f" It reaches {', '.join(assessment.affected_files[:3])}"
        + (" and more" if len(assessment.affected_files) > 3 else "")
        + "."
        if assessment.affected_files
        else ""
    )
    return f"{final}, decided by {deciders} ({said}).{where} {action}"


def _call(
    model: str,
    prompt: prompts.Prompt,
    settings: ModelCallSettings,
    outcome: ModelOutcome,
    *,
    started: float,
    error: str = "",
    **counts,
) -> ModelCall:
    return ModelCall(
        model_id=model,
        prompt_id=prompt.id,
        prompt_sha256=prompt.sha256,
        settings=settings,
        outcome=outcome,
        duration_seconds=round(time.monotonic() - started, 3),
        error=error[:500],
        **counts,
    )


async def explain(
    risk: RiskReport, *, model: str, agent_model: Model | None = None, thinking: str = "off"
) -> RiskReport:
    """Every assessment with an explanation, the model's where it passes, code's where not."""
    prompt = prompts.load(PROMPT_ID)
    settings = ModelCallSettings.model_validate(recorded_settings(model, thinking=thinking))
    explained: list[UpdateAssessment] = []
    stopped = ""
    unbuildable = ""
    built: Agent[None, ExplanationAnswer] | None = None
    async with AsyncExitStack() as stack:
        for assessment in risk.assessments:
            refusal = unavailable = text = ""
            replaced = 0
            call: ModelCall | None = None
            if stopped:
                unavailable = f"not asked: {stopped}"
            elif unbuildable:
                unavailable = unbuildable
            else:
                if built is None:
                    try:
                        built = await stack.enter_async_context(
                            explanation_agent(agent_model or model, thinking=thinking)
                        )
                    except Exception as error:
                        # Recorded as the reason, never raised: an explanation is
                        # prose about a decision already made, not the decision.
                        unbuildable = f"no model could be built: {type(error).__name__}: {error}"
                        unavailable = unbuildable
                if built is not None:
                    request = shown(assessment)
                    started = time.monotonic()
                    with capture_run_messages() as exchanged:
                        try:
                            result = await built.run(request)
                        except ModelHTTPError as error:
                            if error.status_code == 429:
                                stopped = "the model was rate limited, and explanations stopped"
                                unavailable = f"rate-limited: {stopped}"
                                outcome: ModelOutcome = "rate-limited"
                            else:
                                unavailable = (
                                    f"the model provider answered HTTP {error.status_code}"
                                )
                                outcome = "provider-error"
                            call = _call(
                                model,
                                prompt,
                                settings,
                                outcome,
                                started=started,
                                error=f"HTTP {error.status_code}: {error.body}",
                                **spent(exchanged),
                            )
                        except UnexpectedModelBehavior as error:
                            unavailable = "the model never answered in the required shape"
                            call = _call(
                                model,
                                prompt,
                                settings,
                                "malformed",
                                started=started,
                                error=str(error),
                                **spent(exchanged),
                            )
                        except Exception as error:
                            unavailable = f"the model did not answer: {type(error).__name__}"
                            call = _call(
                                model,
                                prompt,
                                settings,
                                "provider-error",
                                started=started,
                                error=f"{type(error).__name__}: {error}",
                                **spent(exchanged),
                            )
                        else:
                            usage = result.usage
                            call = _call(
                                model,
                                prompt,
                                settings,
                                "answered",
                                started=started,
                                requests=usage.requests,
                                prompt_tokens=usage.input_tokens or 0,
                                completion_tokens=usage.output_tokens or 0,
                                stated_level=result.output.level,
                            )
                            refusal = check(result.output, assessment, request)
                            if not refusal:
                                text, replaced = plain(result.output.text.strip())
            explained.append(
                assessment.model_copy(
                    update={
                        "explanation": text or summary(assessment),
                        "explanation_source": "model" if text else "rule",
                        "explanation_refusal": refusal,
                        "explanation_unavailable": unavailable,
                        "explanation_call": call,
                        "explanation_dashes_replaced": replaced,
                    }
                )
            )
    return risk.model_copy(
        update={
            "assessments": explained,
            "explanation_model_id": model,
            "explanation_prompt_id": PROMPT_ID,
            "explanation_prompt_sha256": prompt.sha256,
        }
    )
