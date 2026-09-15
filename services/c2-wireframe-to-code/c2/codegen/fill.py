"""The optional model fill: richer bodies, under a post checked constraint.

The rule generated bodies are complete and are what ships when this pass is
absent or misbehaves. A fill is accepted only when the checks pass: a page
may call only client methods that exist and may not fetch around the client;
a handler must keep to the repository interface. A refused fill is retried
once with the reason; a second refusal keeps the rule body and the manifest
keeps saying `rule`, because "which generator authored this file" must stay
a fact.
"""

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model

from ..agents import MALFORMED_OUTPUT_RETRIES, output_for, settings_for
from ..model_use import records_answers

log = logging.getLogger(__name__)

FILL_ATTEMPTS = 2

_IMPLEMENTS = re.compile(r"^//\s*implements\s+.*$", re.MULTILINE)
_CLIENT_CALL = re.compile(r"\bclient\.(\w+)\s*\(")
_FOREIGN_CALL = re.compile(r"\bfetch\s*\(|\baxios\b|XMLHttpRequest|WebSocket\s*\(")
_REPOSITORY_CALL = re.compile(r"\brepository\.(\w+)\s*\(")
_ROUTE_RECORD = re.compile(r"\buseParams\s*\(")
#: A client call whose first argument is a written-in string, such as `client.getOrdersId("id")`.
_WRITTEN_IN_ID = re.compile(r"\bclient\.(\w+)\s*\(\s*[\"'`]")

REPOSITORY_METHODS = frozenset({"list", "get", "create", "update", "remove"})


class FilledFile(BaseModel):
    """The one thing the fill model may produce: the file's full content."""

    content: str = Field(min_length=1)


def dropped_headers(rule_body: str, filled: str) -> list[str]:
    """Every `implements` header in the rule body has to survive the fill.

    Not a style rule. `validate/agreement.py` reads these lines back to build
    the table of which file implements which endpoint, so a fill that drops one
    does not produce a worse looking file: it produces a file the agreement
    check cannot see. The endpoint reads as unimplemented and the run reports a
    disagreement that is not there, which is the one failure this component
    must not have, because static agreement is the thing it is measuring.

    Both instruction sets have asked for this since the first version. A model
    that ignores an instruction is exactly what a post check is for, and the
    reason to add it now is that a styling pass gives the model much more
    reason to rewrite the top of a file.
    """
    required = {line.strip() for line in _IMPLEMENTS.findall(rule_body)}
    present = {line.strip() for line in _IMPLEMENTS.findall(filled)}
    return [
        f"the header line `{line}` was dropped; the agreement check reads those lines "
        "to decide which endpoints are implemented"
        for line in sorted(required - present)
    ]


def lost_the_record(rule_body: str, filled: str) -> list[str]:
    """A page that reads its record from its address has to go on reading it there.

    The rule page learns which record it shows from its route (`useParams`)
    and passes that id to the client. A rewrite that dropped the read, or passed
    a written-in id instead, asks the API for `/orders/id` and shows a 404 on
    every record, which is what the rule pages themselves did until the route
    carried the id.
    """
    problems: list[str] = []
    if _ROUTE_RECORD.search(rule_body) and not _ROUTE_RECORD.search(filled):
        problems.append(
            "the page reads the record it shows from its address with useParams; keep that "
            "read, and pass that id to the client"
        )
    written_in = sorted({match.group(1) for match in _WRITTEN_IN_ID.finditer(filled)})
    problems.extend(
        f"client.{method} is passed a written-in string; pass the id the page reads from its "
        "address instead"
        for method in written_in
    )
    return problems


def check_page_fill(content: str, allowed_methods: set[str]) -> list[str]:
    problems: list[str] = []
    for match in _CLIENT_CALL.finditer(content):
        method = match.group(1)
        if method not in allowed_methods:
            problems.append(
                f"client.{method} does not exist; the client has: "
                + ", ".join(sorted(allowed_methods))
            )
    if _FOREIGN_CALL.search(content):
        problems.append("the page requests outside the generated client, which is forbidden")
    return problems


def check_handler_fill(content: str) -> list[str]:
    problems: list[str] = []
    for match in _REPOSITORY_CALL.finditer(content):
        method = match.group(1)
        if method not in REPOSITORY_METHODS:
            problems.append(
                f"repository.{method} does not exist; the repository has: "
                + ", ".join(sorted(REPOSITORY_METHODS))
            )
    if "require(" in content:
        problems.append("no require: the generated app is ESM TypeScript")
    return problems


PAGE_INSTRUCTIONS = (
    "You turn one generated React page into the screen a person would expect for "
    "what it is for. Rules:\n"
    "1. Keep the exported function's name, the PageHeader's title and every "
    "`// implements` header line exactly as they are.\n"
    "2. Keep its data flow: the client calls it makes and what it does with what "
    "they return. Call only the client methods you are told exist, and never "
    "fetch around the client.\n"
    '3. Build from the app\'s own components, imported from "../ui", and style '
    "with its tokens as class names (bg-canvas, bg-surface, bg-surface-2, text-ink, "
    "text-ink-2, text-muted, border-line, border-line-strong, rounded-panel, "
    "rounded-control, bg-accent, text-accent, text-accent-ink, shadow-panel). No "
    "other library and no inline styles.\n"
    "4. Where the requirements say how something is used, build that: a keypad "
    "and a read-out for a calculator, not a text box.\n"
    "5. It is strict TypeScript, and a draft that does not compile is put back "
    "for the generated page.\n"
    "6. Keep how the page learns which record it shows: an id it reads from its "
    "address with useParams stays, and that id, never a written-in value, is what "
    "it passes to the client.\n"
    "Answer with the complete file content."
)

#: What the page writer may build from, as the components in `src/ui` declare it.
COMPONENTS_GUIDE = """The components in "../ui", with their props:
  PageHeader({ title, description?, actions? })
  Card({ title?, description?, actions?, label?, flush?, className?, children })
  Button({ variant?: "primary" | "secondary" | "ghost" | "danger", busy?, onClick?, className?, children })
  Field({ label, value: string, onChange: (value: string) => void, type?: "text" | "number" | "date" | "email", hint? })
  DataTable<Row>({ rows, columns: { key, label, render: (row) => ReactNode }[], rowKey: (row, index) => string, loading?, empty? })
  EmptyState({ title, description?, action? })
  Notice({ tone?: "positive" | "danger" | "neutral" | "muted", title, children? })
  Spinner({ label?, className? })"""

HANDLER_INSTRUCTIONS = (
    "You improve one generated Express route file. Keep every route path, "
    "method and implements header comment exactly as it is. You may improve "
    "validation and error messages. You may use only the repository methods "
    "list, get, create, update, remove. Answer with the complete file content."
)


def build_page_filler(
    model: str | Model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
):
    return Agent(
        model,
        output_type=output_for(FilledFile, model, thinking=thinking),
        instructions=PAGE_INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def build_handler_filler(
    model: str | Model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
):
    return Agent(
        model,
        output_type=output_for(FilledFile, model, thinking=thinking),
        instructions=HANDLER_INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


@dataclass(frozen=True)
class FillOutcome:
    content: str | None
    attempts: int
    refused_reasons: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.content is not None


def page_prompt(
    rule_body: str, requirements: Sequence[str], allowed_methods: set[str] | None
) -> str:
    """What the page writer is asked, with the client methods left out when None."""
    said = (
        "What this screen is for, from the requirements it serves:\n"
        + "\n".join(f"- {one}" for one in requirements)
        + "\n\n"
        if requirements
        else ""
    )
    methods = (
        f"Client methods that exist: {', '.join(sorted(allowed_methods))}.\n\n"
        if allowed_methods is not None
        else ""
    )
    return (
        "The generated page below is functional. Rewrite it under your rules.\n"
        f"{said}{COMPONENTS_GUIDE}\n\n"
        f"{methods}"
        f"{rule_body}"
    )


def page_digest(
    rule_body: str, requirements: Sequence[str], *, model: str | Model, thinking: str
) -> str:
    """A digest of everything a page rewrite depends on, for reusing it while unchanged.

    The prompt as it is sent, the instructions, the answer's shape, the model,
    its thinking level and settings, and the attempt counts: anything that
    could change what comes back changes the digest. One thing is left out on
    purpose: the client methods the prompt lists are the whole contract's, so a
    story added anywhere would change every page's digest. Which methods this
    page calls is in its rule page already, and a reused rewrite is checked
    against today's methods before it ships (`C2._fill_pages`), as a new one is.
    """
    named = model if isinstance(model, str) else f"{model.system}:{model.model_name}"
    canonical = json.dumps(
        {
            "prompt": page_prompt(rule_body, requirements, None),
            "instructions": PAGE_INSTRUCTIONS,
            "answer": FilledFile.model_json_schema(),
            "model": named,
            "thinking": thinking,
            "settings": settings_for(model, thinking=thinking) or {},
            "attempts": [FILL_ATTEMPTS, MALFORMED_OUTPUT_RETRIES],
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def fill_page(
    agent: Agent[None, FilledFile],
    *,
    rule_body: str,
    allowed_methods: set[str],
    requirements: Sequence[str] = (),
    max_attempts: int = FILL_ATTEMPTS,
) -> FillOutcome:
    """One page, rewritten for what it is for, or refused with the reasons.

    `requirements` is what the page's flow was drawn for, which is what tells a
    calculator from a form: without it the writer saw fields and a button, and
    could only restyle them.
    """
    prompt = page_prompt(rule_body, requirements, allowed_methods)
    refused: list[str] = []
    for attempt in range(1, max_attempts + 1):
        result = await agent.run(prompt)
        problems = check_page_fill(result.output.content, allowed_methods)
        problems += dropped_headers(rule_body, result.output.content)
        problems += lost_the_record(rule_body, result.output.content)
        if not problems:
            return FillOutcome(content=result.output.content, attempts=attempt)
        refused.extend(problems)
        prompt = f"{prompt}\n\nYour previous answer was refused:\n" + "\n".join(
            f"- {problem}" for problem in problems
        )
    log.warning("page fill refused twice; the rule body ships: %s", "; ".join(refused[:3]))
    return FillOutcome(content=None, attempts=max_attempts, refused_reasons=tuple(refused))


async def fill_handler(
    agent: Agent[None, FilledFile],
    *,
    rule_body: str,
    max_attempts: int = FILL_ATTEMPTS,
) -> FillOutcome:
    prompt = (
        f"The generated route file below is functional. Improve it under your rules.\n\n{rule_body}"
    )
    refused: list[str] = []
    for attempt in range(1, max_attempts + 1):
        result = await agent.run(prompt)
        problems = check_handler_fill(result.output.content)
        problems += dropped_headers(rule_body, result.output.content)
        if not problems:
            return FillOutcome(content=result.output.content, attempts=attempt)
        refused.extend(problems)
        prompt = f"{prompt}\n\nYour previous answer was refused:\n" + "\n".join(
            f"- {problem}" for problem in problems
        )
    log.warning("handler fill refused twice; the rule body ships: %s", "; ".join(refused[:3]))
    return FillOutcome(content=None, attempts=max_attempts, refused_reasons=tuple(refused))
