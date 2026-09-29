"""Signal two (FR5): what the release notes say changed, checked claim by claim.

**The model extracts; a rule rates** (decision 6). For each update the model is
shown the stored notes of every release in its window and returns claims: a
kind, the symbols the sentence names, the sentence itself, and the release it
sits under. Code then checks every claim against the stored text, and
`changelog-rule/1` turns the claims that hold into the signal's level. The
model's own reading of the level is recorded and used by nothing, so a model
that states "medium" over a verified removal still yields High.

**The check.** A claim is refused, and counted, for exactly one reason:

- `empty-quote`: it quotes nothing;
- `quote-not-found`: no release's notes contain the sentence, character for
  character up to whitespace (`notes.locate`), so it was invented or paraphrased;
- `no-such-source`: the sentence is in what the model was shown, but in none of
  its releases' notes (the request's own framing, for instance), so it is
  evidence about no release;
- `outside-version-window`: the sentence sits only under a release outside the
  window, which a release body can carry as a nested heading;
- `symbol-not-in-quote`: it names a symbol its own sentence does not contain.

A verified claim takes the release the check found its sentence under, not the
one the model named: the model's label is not evidence.

**Only the text that was read can be quoted from.** Each stored note text is
checked against the hash recorded when it was fetched before it is shown, and a
text that is missing or has changed is not shown at all.

**Who abstains, and why.** No notes, no usable notes, a model that did not
answer, and every claim refused all leave the signal without a vote, each with
its own reason; none of them is reported as a quiet release. A rate limit that
surfaces stops the stage: that update and every later one abstain as
`rate-limited`, and nothing is retried here (DeepSeek's client keeps its own
default retries, by decision). An answer cut off at the output ceiling is not
asked for again either, because at the same ceiling it would be cut off again.

**What a call cost is recorded whatever came of it**: the requests it made and
the tokens the provider billed for them, read from the answers themselves, so a
call that failed after answering is not recorded as free.
"""

import hashlib
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic_ai import Agent, AgentRunResult, capture_run_messages
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models import Model
from sdlc_contracts import (
    CHANGELOG_RULE,
    ChangelogAnalysis,
    ChangelogClaim,
    ChangelogReport,
    DependencyUpdate,
    DependencyUpdates,
    ModelCall,
    ModelCallSettings,
    RefusedClaim,
    ReleaseNoteRef,
    SignalVote,
    changelog_level,
)

from .. import prompts
from ..agents import (
    MALFORMED_OUTPUT_RETRIES,
    model_for,
    output_for,
    recorded_settings,
    settings_for,
)
from ..intake.releases import in_window, oldest_first
from ..model_use import records_answers
from .claims import ChangelogAnswer, DraftClaim, request
from .notes import Section, normalise, split_changelog

PROMPT_ID = "changelog-extract/1"

#: The kinds that decide a High and a Medium, named in a rationale in this order.
_SEVERITY = ("breaking", "removal", "behavioural", "deprecation")


def changelog_agent(
    model: str | Model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[None, ChangelogAnswer]:
    """The agent the signal and the probe both ask: one forced tool call, temperature zero."""
    return Agent(
        model_for(model),
        output_type=output_for(ChangelogAnswer, model, thinking=thinking),
        instructions=prompts.load(PROMPT_ID).text,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


@dataclass(frozen=True)
class Source:
    """One stored note text the model is shown, split into its releases."""

    ref: ReleaseNoteRef
    sections: list[Section]


def sources_for(update: DependencyUpdate, texts: dict[str, str]) -> tuple[list[Source], list[str]]:
    """The stored notes an update names, each checked against its recorded hash.

    Returns the usable ones and a sentence for every one that is not: a text the
    stage was not given, or one whose bytes are not the ones that were fetched.
    """
    usable: list[Source] = []
    problems: list[str] = []
    for ref in update.notes:
        text = texts.get(ref.path)
        if text is None:
            problems.append(f"the stored notes at {ref.path} were not passed to this stage")
            continue
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != ref.sha256:
            problems.append(f"the notes at {ref.path} are not the text that was fetched")
            continue
        usable.append(Source(ref, split_changelog(text)))
    return usable, problems


def _refuse(draft: DraftClaim, reason, detail: str) -> RefusedClaim:
    return RefusedClaim(
        kind=draft.kind,
        quote=draft.quote,
        version=draft.version,
        symbols=list(draft.symbols),
        reason=reason,
        detail=detail,
    )


def verify(
    draft: DraftClaim,
    sources: Sequence[Source],
    shown: str,
    *,
    update: DependencyUpdate,
    claim_id: str,
) -> ChangelogClaim | RefusedClaim:
    """One claim against the notes the model was shown: kept with its release, or refused."""
    wanted = normalise(draft.quote)
    if not wanted:
        return _refuse(draft, "empty-quote", "the claim quotes nothing")
    homes = [
        (source, section)
        for source in sources
        for section in source.sections
        if wanted in normalise(section.text)
    ]
    if not homes:
        if wanted in normalise(shown):
            return _refuse(
                draft,
                "no-such-source",
                "the sentence is in what the model was shown, but in no release's notes",
            )
        return _refuse(
            draft,
            "quote-not-found",
            "no release in the window has this sentence, character for character",
        )
    inside = [
        (source, section)
        for source, section in homes
        if in_window(update.ecosystem, section.version, update.from_version, update.to_version)
    ]
    if not inside:
        found = ", ".join(sorted({section.version for _, section in homes}))
        return _refuse(
            draft,
            "outside-version-window",
            f"the sentence is under {found}, outside the releases after "
            f"{update.from_version} up to {update.to_version}",
        )
    missing = [symbol for symbol in draft.symbols if symbol not in draft.quote]
    if missing:
        return _refuse(
            draft, "symbol-not-in-quote", f"the sentence does not contain {', '.join(missing)}"
        )
    source, section = inside[0]
    return ChangelogClaim(
        id=claim_id,
        kind=draft.kind,
        symbols=list(draft.symbols),
        quote=draft.quote,
        source_url=source.ref.url,
        version=section.version,
    )


def spent(exchanged: list[ModelMessage]) -> dict[str, int]:
    """What the provider billed for the answers it gave, read or not.

    A call that fails after an answer arrived (cut off at the output ceiling, or
    never in the required shape) was still paid for, and the answer carries its
    usage even when the run raises, so a failed call records its spend rather
    than nothing.
    """
    answers = [message for message in exchanged if isinstance(message, ModelResponse)]
    return {
        "requests": len(answers),
        "prompt_tokens": sum(answer.usage.input_tokens or 0 for answer in answers),
        "completion_tokens": sum(answer.usage.output_tokens or 0 for answer in answers),
    }


class _CutOff(Exception):
    """An answer that stopped at the output ceiling before its claims were complete."""


def _cut_off(answer: ModelResponse) -> bool:
    """Whether the answer ran out of room before its tool call was whole.

    The same test pydantic-ai applies before it names a token limit, made on the
    first answer instead of after the output retries are spent.
    """
    if answer.finish_reason != "length":
        return False
    last = answer.parts[-1] if answer.parts else None
    if not isinstance(last, ToolCallPart):
        return True
    try:
        last.args_as_dict(raise_if_invalid=True)
    except Exception:
        return True
    return False


async def _run(runner: Agent[None, ChangelogAnswer], shown: str) -> AgentRunResult:
    """The run, stopped at the first answer cut off at the output ceiling.

    pydantic-ai reads a cut off tool call as malformed output and asks again, up
    to the output retries. At the same ceiling the answer is cut off again: on the
    seed set's first live pass all three such answers were, four requests each,
    so asking again is spend with nothing to show for it, and it is not asked.
    """
    async with runner.iter(shown) as run:
        async for node in run:
            if Agent.is_call_tools_node(node) and _cut_off(node.model_response):
                raise _CutOff
    if run.result is None:  # pragma: no cover - the loop ends only at a result
        raise UnexpectedModelBehavior("the run ended without a result")
    return run.result


def _vote(level, reason: str, rationale: str, evidence: list[str]) -> SignalVote:
    return SignalVote(
        signal="changelog",
        level=level,
        abstained_reason="" if level else reason,
        rule_id=CHANGELOG_RULE,
        rationale=rationale,
        evidence_ids=evidence,
    )


def _abstaining(
    update: DependencyUpdate,
    *,
    notes_found: bool,
    windows: list[str],
    reason: str,
    model: ModelCall | None = None,
) -> ChangelogAnalysis:
    return ChangelogAnalysis(
        update_id=update.id,
        windows=windows,
        notes_found=notes_found,
        vote=_vote(None, reason, f"The changelog signal abstains: {reason}.", []),
        model=model,
    )


def _rationale(level: str, claims: list[ChangelogClaim], refused: int) -> str:
    """Written by code from the verified claims, never by the model."""
    refusals = f"; {refused} refused" if refused else ""
    if level == "low":
        kinds = sorted({claim.kind for claim in claims})
        stated = f" ({', '.join(kinds)})" if kinds else ""
        return (
            f"The notes were read and state nothing {CHANGELOG_RULE} rates above Low: "
            f"{len(claims)} verified claim{'s' if len(claims) != 1 else ''}{stated}{refusals}."
        )
    decisive = next(claim for kind in _SEVERITY for claim in claims if claim.kind == kind)
    named = f" of {', '.join(decisive.symbols)}" if decisive.symbols else ""
    return (
        f"The notes state a {decisive.kind}{named} in {decisive.version}, which "
        f"{CHANGELOG_RULE} rates {level.capitalize()}: {len(claims)} verified "
        f"claim{'s' if len(claims) != 1 else ''}{refusals}."
    )


class _RateLimited(Exception):
    def __init__(self, analysis: ChangelogAnalysis, reason: str) -> None:
        super().__init__(reason)
        self.analysis = analysis
        self.reason = reason


async def analyse_update(
    update: DependencyUpdate,
    texts: dict[str, str],
    *,
    agent: Callable[[], Awaitable[Agent[None, ChangelogAnswer]]],
    model_id: str,
    thinking: str = "off",
) -> ChangelogAnalysis:
    """The changelog signal for one update. Raises `_RateLimited` carrying its analysis.

    `agent` is asked for only once there are notes to show, so an update with
    none never needs a model, or a key for one.
    """
    sources, problems = sources_for(update, texts)
    windows = oldest_first(
        update.ecosystem, [section.version for source in sources for section in source.sections]
    )
    if not update.notes:
        return _abstaining(
            update,
            notes_found=False,
            windows=[],
            reason=update.notes_unavailable
            or (
                f"no release notes were found for the releases after {update.from_version} "
                f"up to {update.to_version}"
            ),
        )
    if not sources:
        return _abstaining(update, notes_found=False, windows=[], reason="; ".join(problems))

    prompt = prompts.load(PROMPT_ID)
    sections = [section for source in sources for section in source.sections]
    shown = request(
        update.package, update.ecosystem, update.from_version, update.to_version, sections
    )
    settings = ModelCallSettings.model_validate(recorded_settings(model_id, thinking=thinking))

    def call(outcome, *, seconds: float, error: str = "", **extra) -> ModelCall:
        return ModelCall(
            model_id=model_id,
            prompt_id=PROMPT_ID,
            prompt_sha256=prompt.sha256,
            settings=settings,
            outcome=outcome,
            duration_seconds=round(seconds, 3),
            error=error[:500],
            **extra,
        )

    runner = await agent()
    started = time.monotonic()
    with capture_run_messages() as exchanged:
        try:
            result = await _run(runner, shown)
        except _CutOff:
            ceiling = settings.max_tokens or "the provider's default"
            return _abstaining(
                update,
                notes_found=True,
                windows=windows,
                reason=f"the model's answer was cut off at the output ceiling ({ceiling} tokens)",
                model=call(
                    "cut-off",
                    seconds=time.monotonic() - started,
                    error=(
                        f"the answer reached the output ceiling ({ceiling} tokens) before its "
                        "claims were complete, and was not asked for again"
                    ),
                    **spent(exchanged),
                ),
            )
        except ModelHTTPError as error:
            seconds = time.monotonic() - started
            if error.status_code == 429:
                reason = f"the model was rate limited on {update.package}, and the stage stops"
                analysis = _abstaining(
                    update,
                    notes_found=True,
                    windows=windows,
                    reason="rate-limited: " + reason,
                    model=call(
                        "rate-limited",
                        seconds=seconds,
                        error=f"HTTP 429: {error.body}",
                        **spent(exchanged),
                    ),
                )
                raise _RateLimited(analysis, reason) from error
            return _abstaining(
                update,
                notes_found=True,
                windows=windows,
                reason=f"the model provider answered HTTP {error.status_code}",
                model=call(
                    "provider-error",
                    seconds=seconds,
                    error=f"HTTP {error.status_code}: {error.body}",
                    **spent(exchanged),
                ),
            )
        except UnexpectedModelBehavior as error:
            return _abstaining(
                update,
                notes_found=True,
                windows=windows,
                reason="the model never answered in the required shape",
                model=call(
                    "malformed",
                    seconds=time.monotonic() - started,
                    error=str(error),
                    **spent(exchanged),
                ),
            )
        except ModelAPIError as error:
            return _abstaining(
                update,
                notes_found=True,
                windows=windows,
                reason="the model provider could not be reached",
                model=call(
                    "provider-error",
                    seconds=time.monotonic() - started,
                    error=str(error),
                    **spent(exchanged),
                ),
            )

    answer = result.output
    usage = result.usage
    claims: list[ChangelogClaim] = []
    refused: list[RefusedClaim] = []
    for draft in answer.claims:
        checked = verify(
            draft, sources, shown, update=update, claim_id=f"{update.id}-c{len(claims) + 1}"
        )
        if isinstance(checked, ChangelogClaim):
            claims.append(checked)
        else:
            refused.append(checked)

    level = changelog_level(
        [claim.kind for claim in claims], notes_found=True, refused=len(refused)
    )
    model = call(
        "answered",
        seconds=time.monotonic() - started,
        requests=usage.requests,
        prompt_tokens=usage.input_tokens or 0,
        completion_tokens=usage.output_tokens or 0,
        stated_level=answer.stated_level,
    )
    if level is None:
        reason = f"every claim the model made was refused ({len(refused)})"
        vote = _vote(None, reason, f"The changelog signal abstains: {reason}.", [])
    else:
        vote = _vote(
            level,
            "",
            _rationale(level, claims, len(refused)),
            [claim.id for claim in claims],
        )
    return ChangelogAnalysis(
        update_id=update.id,
        windows=windows,
        notes_found=True,
        claims=claims,
        refused=refused,
        vote=vote,
        model=model,
    )


async def analyse(
    updates: DependencyUpdates,
    texts: dict[str, str],
    *,
    model: str,
    version: int,
    agent_model: Model | None = None,
    now: datetime | None = None,
    thinking: str = "off",
) -> ChangelogReport:
    """The `changelog-report` for every update: one model call per update with notes."""
    analyses: list[ChangelogAnalysis] = []
    stopped = ""
    async with AsyncExitStack() as stack:
        built: list[Agent[None, ChangelogAnswer]] = []

        async def agent() -> Agent[None, ChangelogAnswer]:
            if not built:
                made = changelog_agent(agent_model or model, thinking=thinking)
                built.append(await stack.enter_async_context(made))
            return built[0]

        for update in updates.updates:
            if stopped and update.notes:
                analyses.append(
                    _abstaining(
                        update,
                        notes_found=True,
                        windows=[],
                        reason=f"rate-limited: not asked, because {stopped}",
                    )
                )
                continue
            try:
                analyses.append(
                    await analyse_update(
                        update, texts, agent=agent, model_id=model, thinking=thinking
                    )
                )
            except _RateLimited as limited:
                analyses.append(limited.analysis)
                stopped = limited.reason
    return ChangelogReport(
        version=version,
        generated_at=now or datetime.now(UTC),
        model_id=model,
        prompt_id=PROMPT_ID,
        prompt_sha256=prompts.load(PROMPT_ID).sha256,
        per_update=analyses,
        stopped_on_rate_limit=bool(stopped),
        stop_reason=stopped,
    )
