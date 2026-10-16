"""Asking a model for a fix, in a shape that can be checked before anybody reads it.

The same lesson as the repair loop, applied one component over. Epoch 1 recorded
a free model answering a whole file repair with a single import line, so the
repair request was reshaped to ask for one body and splice it in. A security fix
is the same task with higher stakes: the model is asked for the replacement
lines, and this module puts them where the old ones were.

**Why the replacement lines and not a diff.** A model asked for a unified diff
has to count context lines and get the hunk header arithmetic right, and when it
gets that wrong the patch does not apply, which is indistinguishable from the
model having nothing useful to say. Asking for the new text of a known line span
removes the arithmetic from the model's job and leaves it the part it is
actually good at.

**The span comes from the finding, which came from a tool.** Every finding in
this component carries evidence that resolved against the repository, so the
lines to replace are known before the model is asked. It is not being trusted to
locate anything.

**What this module does not decide.** Whether the fix is correct. The guard says
whether it is the kind of thing that could be a fix, the risk assessment says
how much is at stake, re-verification says whether it worked, and a human says
whether to apply it. This produces a candidate.
"""

import difflib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model
from sdlc_contracts import PatchHunk, SecurityFinding

from ..agents import MALFORMED_OUTPUT_RETRIES, log_rejected, model_for, output_for, settings_for
from ..model_use import records_answers
from .guard import Refusal, refusal_for

log = logging.getLogger(__name__)

#: One retry with the reason, then the finding stays open and the refusal is
#: reported. The same number as the fill, the referee and the repair, for the
#: same reason: a second refusal is a model that cannot satisfy the rule.
PATCH_ATTEMPTS = 2

#: How much of the file the model is shown around the weakness. Enough for the
#: imports at the top of a small file and the method the finding sits in.
CONTEXT_LINES = 40

INSTRUCTIONS = (
    "You fix one security weakness in one file. You are given the file with "
    "line numbers and the exact lines to replace.\n"
    "Answer with the replacement text for those lines only: not the whole "
    "file, not a diff, not an explanation around it. Your answer is put in "
    "place of the lines you were given.\n"
    "Rules:\n"
    "1. Fix the weakness. Do not silence the tool that found it. A comment such "
    "as nosemgrep, nosec, NOSONAR, SuppressWarnings or eslint-disable is "
    "rejected, and so is a fix that includes one.\n"
    "2. Keep the surrounding code working: the same method signature, the same "
    "return type, the same names used elsewhere.\n"
    "3. Change nothing else. You are writing the replacement for a span, not "
    "editing a file.\n"
    "4. If the span you were given cannot be fixed without changing code "
    "outside it, say so in `cannot_fix` and leave `replacement` empty. That is "
    "a useful answer and a wrong fix is not."
)


class ProposedFix(BaseModel):
    """The only shape the patch model may produce.

    No severity field and no confidence field, for the same reason the
    detection arm has none: the arm that produced a finding does not get to
    say how serious it is or how sure it is.
    """

    replacement: str = Field(default="", description="The new text for the span, or empty.")
    explanation: str = Field(default="", description="One or two sentences for the reviewer.")
    cannot_fix: str = Field(
        default="", description="Why this span cannot be fixed on its own, if it cannot."
    )


@dataclass
class PatchOutcome:
    """What the loop produced, and everything it looked at on the way."""

    hunks: list[PatchHunk] = field(default_factory=list)
    explanation: str = ""
    attempts: int = 0
    #: Refused drafts, kept. How often a model answers a security fix with a
    #: suppression is a result about that model, and dropping those quietly
    #: would flatter it in exactly the comparison this component runs.
    refusals: list[Refusal] = field(default_factory=list)
    #: Set when nothing usable came back, so a caller has a reason rather than
    #: having to infer one from an absence.
    gave_up: str = ""

    @property
    def patched(self) -> bool:
        return bool(self.hunks)


def build_patcher(
    model: str | Model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
):
    return Agent(
        model_for(model),
        output_type=output_for(ProposedFix, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def numbered(source: str, start: int, end: int, *, around: int = CONTEXT_LINES) -> str:
    """The file around the weakness, numbered, with the span marked.

    Numbered because the model is told which lines it is replacing, and marked
    because a span named only in prose is a span a model has to find again.
    """
    lines = source.splitlines()
    first = max(1, start - around)
    last = min(len(lines), end + around)
    shown = []
    for number in range(first, last + 1):
        marker = ">>" if start <= number <= end else "  "
        shown.append(f"{marker} {number:>5} {lines[number - 1]}")
    return "\n".join(shown)


def splice(source: str, start: int, end: int, replacement: str) -> str:
    """The file with one line span replaced.

    The indentation of the first replaced line is applied to the replacement
    when the model did not indent it itself, because a fix that is correct and
    unreadable will be rejected by a reviewer for the wrong reason.
    """
    lines = source.splitlines(keepends=True)
    if not 1 <= start <= end <= len(lines):
        return ""
    original = lines[start - 1]
    indent = original[: len(original) - len(original.lstrip())]
    written = replacement.strip("\n")
    if written and not written.startswith((" ", "\t")):
        written = "\n".join(
            f"{indent}{line.lstrip()}" if line.strip() else "" for line in written.splitlines()
        )
    return "".join(lines[: start - 1]) + written + "\n" + "".join(lines[end:])


def unified(path: str, before: str, after: str) -> str:
    """The change as a diff a person can read and a machine can apply.

    Every line is terminated, which difflib does not guarantee: a file whose
    last line has no newline yields a diff line without one, and joining those
    runs `-b` into `+B` as a single line `-b+B`. The diff then reads fine to a
    human and parses to nonsense, which is the worst combination available. The
    trailing newline of the file itself is not this diff's business: the
    applier preserves whatever the file had.
    """
    return "".join(
        line if line.endswith("\n") else line + "\n"
        for line in difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )


def prompt_for(finding: SecurityFinding, source: str) -> str:
    span = finding.evidence
    lines = [
        f"The weakness: {finding.cwe} ({finding.title})",
        f"Where: {span.path}, lines {span.start_line} to {span.end_line}",
        f"Why it is a weakness: {finding.severity_reasoning or 'see the class'}",
    ]
    if finding.explanation:
        lines.append(f"What the detector said: {finding.explanation}")
    lines.extend(
        [
            "",
            "The file, with the lines to replace marked >>:",
            numbered(source, span.start_line, span.end_line),
            "",
            "Answer with the replacement for the marked lines only.",
        ]
    )
    return "\n".join(lines)


async def propose_patch(
    agent: Agent[None, ProposedFix],
    finding: SecurityFinding,
    *,
    source: str,
    attempts: int = PATCH_ATTEMPTS,
) -> PatchOutcome:
    """One finding, one candidate patch, or a refusal that says why.

    A refusal leaves the file exactly as it was and the finding open, which is
    the honest outcome. An open finding a human can see beats a closed one
    nobody can trust.
    """
    outcome = PatchOutcome()
    span = finding.evidence
    prompt = prompt_for(finding, source)

    for attempt in range(1, attempts + 1):
        outcome.attempts = attempt
        try:
            answer = (await agent.run(prompt)).output
        except Exception as error:
            outcome.gave_up = f"the model did not answer: {type(error).__name__}: {error}"
            return outcome

        if answer.cannot_fix.strip() and not answer.replacement.strip():
            # A model saying the span cannot be fixed alone is giving a useful
            # answer, not failing. The finding stays open with its reason.
            outcome.gave_up = f"the model declined: {answer.cannot_fix.strip()}"
            return outcome

        patched = splice(source, span.start_line, span.end_line, answer.replacement)
        if not patched or patched == source:
            refusal = Refusal("no-change", "the answer left the file exactly as it was")
            outcome.refusals.append(refusal)
            log_rejected("remediation", attempt, [str(refusal)])
            prompt = f"{prompt}\n\nYour previous answer was refused: {refusal.detail}"
            continue

        hunks = [PatchHunk(path=span.path, diff=unified(span.path, source, patched))]
        refusal = refusal_for(hunks, finding_path=span.path)
        if refusal is None:
            outcome.hunks = hunks
            outcome.explanation = answer.explanation.strip()
            return outcome

        outcome.refusals.append(refusal)
        log_rejected("remediation", attempt, [str(refusal)])
        prompt = f"{prompt}\n\nYour previous answer was refused: {refusal.detail}"

    outcome.gave_up = (
        outcome.refusals[-1].reason if outcome.refusals else "no usable patch was produced"
    )
    return outcome


def read_source(root: str, path: str) -> str | None:
    try:
        return (Path(root) / path).read_text(errors="replace")
    except OSError:
        return None
