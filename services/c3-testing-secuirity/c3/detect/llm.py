"""The prompted model as a detector, anchored to code it can be shown to have read.

The second arm. It is the one with the strongest priors in the literature and
the weakest guarantees in practice, so almost everything here is about making
its answers checkable rather than about making them good.

**The quote is the evidence, not the line number.** The model is shown numbered
source and must copy the offending code back exactly. The pipeline then finds
that text in the file, and that is where the finding is. Anchoring on the quote
rather than on the claimed number separates two failures that a line based
check would report as one: a model that invented a vulnerability, and a model
that found a real one and counted lines badly. The first is fabrication and is
refused. The second is arithmetic, is corrected, and is counted as line drift,
which is a fact about the arm worth reporting rather than a reason to throw a
true finding away.

**A quote that is not in the file is a fabrication and is refused.** Not
relocated, not repaired, not silently dropped. The refusal rate per arm is a
result: an arm whose evidence does not resolve is an arm inventing locations,
and this study cannot report that number if the pipeline quietly fixes it.

**The model may not score its own finding.** The output type has no severity and
no confidence field, so it cannot, and the prose is checked as well, because a
sentence calling something critical is a severity by another route. Severity
comes from the CWE table; confidence comes from how many arms agreed.

**It reads slices and says which.** This is the arm that is priced per token,
so it is given an explicit list of files, the same list the other two arms get,
and the tokens it spent are recorded per run beside what it found.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model
from sdlc_contracts import DetectorRun, RefusedFinding

from ..agents import MALFORMED_OUTPUT_RETRIES, model_for, output_for, settings_for
from ..detection import Arm, Candidate, DetectionResult
from ..model_use import records_answers
from .severity import normalise

log = logging.getLogger(__name__)

#: How much source goes into one call. Large enough that a function and its
#: callers usually travel together, small enough that a refusal costs one
#: chunk rather than a whole repository.
CHUNK_CHARACTERS = 12_000

#: The status a provider returns when the quota is spent. A pass that meets it
#: stops, because every call after it will be refused too.
RATE_LIMITED = 429

#: How much code the triager sees on each side of a reported line. Enough for
#: the guard clause above a sink and the sanitiser below it, which is what
#: decides most false positives.
CONTEXT_LINES = 12

#: The refusals this arm can produce, spelled as the contract spells them.
RefusalReason = Literal[
    "file-not-found", "span-out-of-range", "snippet-does-not-match", "malformed-cwe", "no-evidence"
]

#: What the arm will not read at all, whatever it was handed. Minified bundles
#: and lock files are where a token budget goes to die for nothing.
SKIP_SUFFIXES = (".min.js", ".min.css", ".map", ".lock", ".snap")
SKIP_NAMES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml")

INSTRUCTIONS = (
    "You review source code for security weaknesses. You are given files with "
    "line numbers.\n"
    "Report only weaknesses you can point at. For each one, copy the offending "
    "line or lines back exactly as they appear, character for character, "
    "without the line number prefix. That quote is your evidence: a finding "
    "whose quote is not in the file is discarded.\n"
    "Give the CWE identifier in the form CWE-89. Give the file path exactly as "
    "it was shown to you.\n"
    "Do not state a severity, a score, a CVSS vector or a risk rating. Those "
    "are computed from the CWE by a published rule, and a finding that asserts "
    "one is rejected.\n"
    "Finding nothing is a correct answer. This code may be fine, and an "
    "invented weakness costs a reviewer more than a missed one costs you."
)

#: Prose that scores. Checked because the output type cannot carry a severity
#: but a sentence can, and this arm is the one that must not have an opinion
#: about how bad its own finding is.
_SCORING = re.compile(
    r"\b(critical|high[- ]risk|severity|cvss|risk (?:score|rating)|"
    r"score of \d|CVSS:3\.[01])\b",
    re.IGNORECASE,
)


class ProposedFinding(BaseModel):
    """One weakness the model claims, in the only shape it may claim one.

    No severity field and no confidence field, deliberately. An arm that could
    fill either would be an arm scoring its own finding, which is the property
    this component's security pillar is built to prevent.
    """

    cwe: str = Field(description="Like CWE-89.")
    title: str = Field(description="A few words a reader can scan.")
    path: str = Field(description="Exactly as the file was labelled.")
    start_line: int = Field(description="Where you believe the quote starts.")
    end_line: int = Field(default=0, description="Where it ends. Same as the start is fine.")
    quoted_code: str = Field(description="The offending code, copied exactly.")
    explanation: str = Field(default="", description="One or two sentences.")
    remediation: str = Field(default="", description="What to do instead.")


class Reading(BaseModel):
    """One pass over one chunk."""

    findings: list[ProposedFinding] = Field(default_factory=list)


def build_detector(
    model: str | Model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
):
    return Agent(
        model_for(model),
        output_type=output_for(Reading, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def readable(files: list[str]) -> list[str]:
    """The files worth spending tokens on."""
    keep = []
    for path in files:
        name = Path(path).name
        if name in SKIP_NAMES or any(name.endswith(suffix) for suffix in SKIP_SUFFIXES):
            continue
        keep.append(path)
    return keep


@dataclass(frozen=True)
class Block:
    """One request's worth of source, and which files went into it.

    The paths travel with the body because a pass can stop early. An arm that
    reported the files it meant to read rather than the ones it read would put
    a denominator in the study that nothing measured, which is the mistake the
    mutation score and the flagged fraction already refuse to make.
    """

    body: str
    paths: tuple[str, ...]


def chunks(root: str, files: list[str], *, budget: int = CHUNK_CHARACTERS) -> list[Block]:
    """The prompt bodies, numbered, one file per block, batched to a budget.

    Numbered because the model is asked where it is looking, and unnumbered
    source would make every claimed location a guess. A file larger than the
    budget travels alone and whole rather than being cut mid function, since a
    weakness split across two calls is a weakness neither call can see.
    """
    blocks: list[Block] = []
    current: list[str] = []
    paths: list[str] = []
    size = 0
    for path in readable(files):
        try:
            text = (Path(root) / path).read_text(errors="replace")
        except OSError:
            continue
        numbered = "\n".join(
            f"{number:>5} {line}" for number, line in enumerate(text.splitlines(), start=1)
        )
        block = f"--- {path} ---\n{numbered}"
        if current and size + len(block) > budget:
            blocks.append(Block(body="\n\n".join(current), paths=tuple(paths)))
            current, paths, size = [], [], 0
        current.append(block)
        paths.append(path)
        size += len(block)
    if current:
        blocks.append(Block(body="\n\n".join(current), paths=tuple(paths)))
    return blocks


def is_rate_limit(error: Exception) -> bool:
    """Whether the provider refused because the quota is spent.

    Checked on the status code where there is one, and on the text otherwise,
    because the wrappers around an HTTP client vary in what they raise and this
    decides whether the run stops.
    """
    if getattr(error, "status_code", None) == RATE_LIMITED:
        return True
    text = str(error).lower()
    return str(RATE_LIMITED) in text or "rate limit" in text or "quota" in text


@dataclass(frozen=True)
class Located:
    """Where a quote really is, and whether the model said so."""

    start_line: int
    end_line: int
    #: How far the claim was from the truth, in lines. Reported rather than
    #: hidden: it separates a model that cannot count from a model that
    #: invents, and only one of those should cost the arm a finding.
    drift: int


def find_quote(source: str, quote: str, claimed: int) -> Located | None:
    """Where this text actually appears, preferring where the model said.

    Compares with leading and trailing whitespace removed per line, because a
    model that re-indents a copied line has still copied it, and refusing that
    would measure transcription rather than detection.
    """
    wanted = [line.strip() for line in quote.strip().splitlines() if line.strip()]
    if not wanted:
        return None
    lines = [line.strip() for line in source.splitlines()]
    span = len(wanted)
    hits = [
        index + 1
        for index in range(0, max(0, len(lines) - span + 1))
        if lines[index : index + span] == wanted
    ]
    if not hits:
        return None
    best = min(hits, key=lambda line: abs(line - claimed))
    return Located(start_line=best, end_line=best + span - 1, drift=abs(best - claimed))


def check_no_self_scoring(text: str) -> list[str]:
    """Severity claims in prose, which the output type cannot hold but a
    sentence can."""
    return sorted({match.group(0) for match in _SCORING.finditer(text or "")})


@dataclass
class LlmArm:
    """The prompted model, behind the same interface as the other two.

    Carries its own refusal and drift counts because those are results about
    this arm rather than incidents in a log: an arm that has to be corrected
    on half its line numbers, or refused on half its quotes, is telling the
    study something it should report.
    """

    agent: Agent[None, Reading]
    model_id: str
    arm: Arm = "llm"
    #: It needs the network by construction. The trained arm is the one whose
    #: claim is that it does not.
    offline: bool = False
    drifted: int = 0
    scoring_refused: int = 0

    async def scan(self, root: str, files: list[str]) -> DetectionResult:
        started = datetime.now(UTC)
        clock = monotonic()
        prompt_tokens = 0
        completion_tokens = 0
        cost: float | None = None

        proposed: list[ProposedFinding] = []
        failures: list[str] = []
        read: list[str] = []
        blocks = chunks(root, files)
        for index, block in enumerate(blocks, start=1):
            try:
                result = await self.agent.run(block.body)
            except Exception as error:
                # One chunk that failed is not a scan that failed, and it is
                # also not a clean chunk. Both facts survive to the report.
                failures.append(f"chunk {index} of {len(blocks)}: {type(error).__name__}: {error}")
                if is_rate_limit(error):
                    # The standing rule on this project, and the reason for it:
                    # the quota is spent, every remaining call will be refused
                    # too, and a pass that ploughs on turns one refusal into a
                    # hundred while still measuring nothing. The first live
                    # three arm run did exactly that, 69 chunks of it.
                    failures.append(
                        f"stopped after chunk {index} of {len(blocks)}: the provider refused "
                        f"with a rate limit and this run does not retry. "
                        f"{len(blocks) - index} chunks were never attempted"
                    )
                    break
                continue
            read.extend(block.paths)
            usage = result.usage
            prompt_tokens += usage.input_tokens or 0
            completion_tokens += usage.output_tokens or 0
            if usage.cost is not None:
                cost = (cost or 0.0) + float(usage.cost)
            proposed.extend(result.output.findings)

        candidates, refused = self.verify(root, files, proposed)
        return DetectionResult(
            candidates=candidates,
            refused=refused,
            failures=failures,
            run=DetectorRun(
                arm="llm",
                model_id=self.model_id,
                started_at=started,
                duration_seconds=round(monotonic() - clock, 3),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                # List price for these tokens, computed by pydantic-ai from
                # its bundled price table. Not a bill: the Gemini API returns
                # token counts and no cost, and a free tier is charged nothing
                # whatever this says. Null only when the model is unpriced.
                # Not zero, because zero is what an arm that made no call
                # reports and the two must stay distinguishable.
                cost_usd=cost,
                offline=self.offline,
                # What it read, not what it meant to read. A pass stopped by a
                # quota covers fewer files, and a denominator nothing measured
                # is how a partial pass comes to look like a poor one.
                files_scanned=len(read),
            ),
        )

    def verify(
        self, root: str, files: list[str], proposed: list[ProposedFinding]
    ) -> tuple[list[Candidate], list[RefusedFinding]]:
        """Every claim checked against the file it names, before it is a finding."""
        allowed = set(files)
        candidates: list[Candidate] = []
        refused: list[RefusedFinding] = []
        self.drifted = 0
        self.scoring_refused = 0
        for finding in proposed:
            cwe = normalise(finding.cwe)
            path = finding.path.strip()
            if not cwe:
                refused.append(_refusal(finding, "malformed-cwe", f"gave {finding.cwe!r}"))
                continue
            if not path or (allowed and path not in allowed):
                refused.append(_refusal(finding, "file-not-found", "named a file it was not given"))
                continue
            try:
                source = (Path(root) / path).read_text(errors="replace")
            except OSError:
                refused.append(_refusal(finding, "file-not-found", "the file is not there"))
                continue
            if not finding.quoted_code.strip():
                refused.append(_refusal(finding, "no-evidence", "quoted nothing"))
                continue
            located = find_quote(source, finding.quoted_code, max(1, finding.start_line))
            if located is None:
                refused.append(
                    _refusal(
                        finding,
                        "snippet-does-not-match",
                        "quoted code that is not in the file",
                    )
                )
                continue
            scoring = check_no_self_scoring(f"{finding.title} {finding.explanation}")
            if scoring:
                # The finding survives; its prose does not. Throwing away a
                # real weakness because its sentence was badly worded would
                # cost recall to enforce a rule about wording.
                self.scoring_refused += 1
                log.info("c3 llm arm dropped a severity claim from its prose: %s", scoring)
            if located.drift:
                self.drifted += 1
            candidates.append(
                Candidate(
                    cwe=cwe,
                    title=finding.title.strip() or cwe,
                    path=path,
                    start_line=located.start_line,
                    end_line=located.end_line,
                    message=_prose(finding, scoring),
                    extra={
                        "claimedStartLine": finding.start_line,
                        "lineDrift": located.drift,
                        "remediation": _strip_scoring(finding.remediation, scoring),
                        "droppedSeverityClaims": scoring,
                    },
                )
            )
        return candidates, refused


def _prose(finding: ProposedFinding, scoring: list[str]) -> str:
    return _strip_scoring(finding.explanation.strip(), scoring)


def _strip_scoring(text: str, scoring: list[str]) -> str:
    """The model's words with its severity claims removed.

    Removed rather than rewritten. This component's report says what the model
    said, minus the part it is not allowed to say, and a paraphrase would be
    the pipeline putting words in the arm's mouth.
    """
    cleaned = text
    for phrase in scoring:
        cleaned = cleaned.replace(phrase, "[severity claim removed]")
    return cleaned


def _refusal(finding: ProposedFinding, reason: RefusalReason, detail: str) -> RefusedFinding:
    return RefusedFinding(
        origin="llm",
        cwe=normalise(finding.cwe),
        reason=reason,
        claimed_path=finding.path.strip(),
        claimed_start_line=finding.start_line if finding.start_line >= 1 else None,
        detail=detail,
    )


TRIAGE_INSTRUCTIONS = (
    "A static analysis tool reported a possible weakness. You are given the "
    "code around it. Say whether the tool is right.\n"
    "Answer `true-positive` only when the code you were shown demonstrates the "
    "weakness, `false-positive` when it demonstrably does not, and `unsure` "
    "when what you were shown does not settle it.\n"
    "Quote, exactly, the line from the code you were shown that decided it. A "
    "verdict quoting anything else is discarded.\n"
    "`unsure` is a correct answer. A wrong `false-positive` deletes a real "
    "weakness from the report, which is the one outcome nobody recovers from."
)


class TriageAnswer(BaseModel):
    """What the model thinks of somebody else's finding."""

    verdict: Literal["true-positive", "false-positive", "unsure"]
    cited_line: str = Field(description="One line from the code shown, copied exactly.")
    reasoning: str = Field(default="", description="One sentence.")


@dataclass(frozen=True)
class Triaged:
    """One scanner finding, and what the model made of it."""

    candidate: Candidate
    verdict: Literal["true-positive", "false-positive", "unsure"]
    reasoning: str = ""
    cited_line: str = ""

    @property
    def dismissed(self) -> bool:
        return self.verdict == "false-positive"


def build_triager(
    model: str | Model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
):
    return Agent(
        model_for(model),
        output_type=output_for(TriageAnswer, model, thinking=thinking),
        instructions=TRIAGE_INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def context_for(root: str, candidate: Candidate, *, around: int = CONTEXT_LINES) -> str:
    """The code the triager judges, numbered, with room on both sides."""
    try:
        lines = (Path(root) / candidate.path).read_text(errors="replace").splitlines()
    except OSError:
        return ""
    first = max(1, candidate.start_line - around)
    last = min(len(lines), candidate.end_line + around)
    body = "\n".join(f"{number:>5} {lines[number - 1]}" for number in range(first, last + 1))
    return (
        f"The tool reported {candidate.cwe} ({candidate.title}) at "
        f"{candidate.path}:{candidate.start_line}.\n"
        f"Its message: {candidate.message or 'none given'}\n\n"
        f"--- {candidate.path} ---\n{body}"
    )


async def triage(
    agent: Agent[None, TriageAnswer], root: str, candidates: list[Candidate]
) -> list[Triaged]:
    """Ask the model whether the scanners were right, one finding at a time.

    A separate capability, reported separately, and it is worth saying why: a
    model that is good at judging someone else's finding and bad at finding
    anything itself is a real and useful thing, and folding the two into one
    number would hide it in both directions.

    Nothing is deleted here. A dismissal is a label on a finding that stays in
    the report, because the study measures how often the triager was right,
    which it cannot do if the triager's mistakes are thrown away.
    """
    judged: list[Triaged] = []
    for candidate in candidates:
        context = context_for(root, candidate)
        if not context:
            judged.append(
                Triaged(
                    candidate=candidate, verdict="unsure", reasoning="the file could not be read"
                )
            )
            continue
        try:
            answer = (await agent.run(context)).output
        except Exception as error:
            judged.append(
                Triaged(
                    candidate=candidate,
                    verdict="unsure",
                    reasoning=f"the triager did not answer: {type(error).__name__}",
                )
            )
            continue
        quoted = answer.cited_line.strip()
        shown = {line.strip() for line in context.splitlines()}
        # The same discipline as the referee: a verdict that cites something it
        # was not shown is a verdict about nothing, and dismissing a real
        # weakness on one is the outcome nobody recovers from.
        cited_something_real = any(quoted and quoted in line for line in shown)
        if not cited_something_real:
            judged.append(
                Triaged(
                    candidate=candidate,
                    verdict="unsure",
                    reasoning=f"cited a line it was not shown: {quoted[:80]!r}",
                )
            )
            continue
        judged.append(
            Triaged(
                candidate=candidate,
                verdict=answer.verdict,
                reasoning=answer.reasoning.strip(),
                cited_line=quoted,
            )
        )
    return judged
