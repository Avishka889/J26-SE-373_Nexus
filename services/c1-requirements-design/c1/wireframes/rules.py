"""The twelve checks a flow has to pass, most of them about the link graph.

A clickable prototype is a graph, and the reason to generate one at design time
is to find out where the graph is broken before anyone writes the screens. So the
checks that matter here are not "does this screen look plausible" but "can a
person actually get to it, and can they get anywhere from it".

Three of those are treated differently, and the difference is the point.

A link to a screen that does not exist is an error. Nobody meant it, the button
does nothing, and there is no reading of the flow where it is correct.

A screen nothing reaches is an error, and reachability is checked from the entry
screen rather than by counting inbound links. Two screens that link to each other
and nowhere else each have an inbound link and are still unreachable, so counting
would pass a flow no user can enter.

A screen with no way out is a warning. Some screens are supposed to end the
journey: a confirmation, a receipt, an error page. An absolute rule would fire on
every one of them and teach the reader to ignore it. So a screen whose name reads
like an ending is exempt, and everything else is surfaced as a finding a person
can judge. This is the same treatment requirement coverage gets in the graph
rules, and for the same reason: a real gap is worth showing, not worth refusing
the artefact over.

The exemption is decided here, from the screen's name, and never by the model.
`terminal` is the flag that silences this warning, so a model able to set it would
set it.
"""

from collections.abc import Callable

from ..rules.findings import Finding, Report
from .schema import DraftFlow, DraftScreen

BLOCK_KINDS = frozenset({"field", "row", "summary", "banner", "text", "list", "button", "display"})
LINK_VARIANTS = frozenset({"primary", "secondary", "row", "text"})
TONES = frozenset({"neutral", "positive", "muted"})

#: Words that mean a journey has finished. Kept tight on purpose: a word that
#: also appears mid-journey would exempt a screen that really is a dead end, and
#: a missed ending only costs a warning somebody can read and dismiss. So
#: "confirmed" is here and "confirm" is not, because "Confirm Payment" is a
#: screen you act on and "Payment Confirmed" is a screen you leave.
TERMINAL_WORDS = frozenset(
    {
        "confirmation",
        "confirmed",
        "success",
        "successful",
        "receipt",
        "complete",
        "completed",
        "done",
        "thanks",
        "thank",
        "error",
        "failed",
        "failure",
        "denied",
        "rejected",
        "expired",
        "sent",
        "submitted",
        "cancelled",
        "canceled",
    }
)

#: Endings that only read as endings as a pair of words.
TERMINAL_PHRASES = ("not found", "no results", "try again later")


def reads_as_an_ending(name: str) -> bool:
    """Whether this screen's name says the journey stops here.

    The single place terminality is decided, used both by the dead end rule and
    by promotion, so the flag on the artefact and the warning about the artefact
    can never disagree.
    """
    lowered = name.lower()
    if any(phrase in lowered for phrase in TERMINAL_PHRASES):
        return True
    words = {word.strip(".,;:!?()'\"") for word in lowered.split()}
    return bool(words & TERMINAL_WORDS)


def _name(screen: DraftScreen) -> str:
    return screen.name or screen.id or "an unnamed screen"


Rule = Callable[[DraftFlow, frozenset[str]], list[Finding]]


def validate_flow(flow: DraftFlow, *, requirement_ids: frozenset[str]) -> Report:
    """Run every rule over one flow, in catalogue order."""
    findings: list[Finding] = []
    for rule in ALL_RULES:
        findings.extend(rule(flow, requirement_ids))
    return Report(findings=tuple(findings))


def unique_screen_ids(flow: DraftFlow, _ids: frozenset[str]) -> list[Finding]:
    """1. No two screens share an id."""
    seen = [screen.id for screen in flow.screens if screen.id]
    duplicates = sorted({i for i in seen if seen.count(i) > 1})
    return [
        Finding(
            rule_id="unique-screen-ids",
            severity="error",
            reason=f"Two screens are both called {duplicate}, so a link to it is ambiguous.",
            hint=(
                f"The screen id {duplicate} is used more than once. Give every screen "
                f"its own id and point the links at the right one."
            ),
            subject=duplicate,
        )
        for duplicate in duplicates
    ]


def unique_link_ids(flow: DraftFlow, _ids: frozenset[str]) -> list[Finding]:
    """2. No two links on one screen share an id.

    Scoped per screen rather than per flow, because a block names the link it
    activates by id and only ever looks on its own screen.
    """
    findings: list[Finding] = []
    for screen in flow.screens:
        seen = [link.id for link in screen.links if link.id]
        for duplicate in sorted({i for i in seen if seen.count(i) > 1}):
            findings.append(
                Finding(
                    rule_id="unique-link-ids",
                    severity="error",
                    reason=(
                        f"{_name(screen)} has two links called {duplicate}, so a line "
                        f"pointing at that id could activate either."
                    ),
                    hint=(
                        f"Screen {screen.id} uses the link id {duplicate} twice. "
                        f"Give each link on a screen its own id."
                    ),
                    subject=screen.id,
                    traces=tuple(screen.traces),
                )
            )
    return findings


def names_are_present(flow: DraftFlow, _ids: frozenset[str]) -> list[Finding]:
    """3. Nothing a reader sees, and no id anything points at, is blank.

    Caught here rather than at promotion so that an empty label comes back as a
    sentence the model can act on instead of a validation error nobody can read.
    """
    findings: list[Finding] = []

    def complain(what: str, hint: str, subject: str | None, traces: tuple[str, ...] = ()) -> None:
        findings.append(
            Finding(
                rule_id="names-are-present",
                severity="error",
                reason=what,
                hint=hint,
                subject=subject,
                traces=traces,
            )
        )

    if not flow.name.strip():
        complain(
            "This journey has no name.",
            "Give the flow a name saying what journey it is, in plain words.",
            None,
        )

    for index, screen in enumerate(flow.screens):
        traces = tuple(screen.traces)
        if not screen.id.strip():
            complain(
                f"The screen at position {index + 1} has no id, so nothing can link to it.",
                f"Give the screen at position {index + 1} a short unique id, such as s{index + 1}.",
                None,
                traces,
            )
        if not screen.name.strip():
            complain(
                f"Screen {screen.id or index + 1} has no name.",
                f"Give screen {screen.id or index + 1} a name saying what the reader is looking at.",
                screen.id or None,
                traces,
            )
        for block in screen.blocks:
            if not block.id.strip() or not block.label.strip():
                complain(
                    f"A line on {_name(screen)} has no label, so it would render blank.",
                    f"Every block on screen {screen.id} needs an id and a label.",
                    screen.id or None,
                    traces,
                )
        for link in screen.links:
            if not link.id.strip() or not link.label.strip() or not link.target_id.strip():
                complain(
                    f"A control on {_name(screen)} is missing its wording or its destination.",
                    f"Every link on screen {screen.id} needs an id, a label and a targetId.",
                    screen.id or None,
                    traces,
                )
    return findings


def kinds_are_known(flow: DraftFlow, _ids: frozenset[str]) -> list[Finding]:
    """4. Every kind, variant and tone is one the renderer knows."""
    findings: list[Finding] = []
    for screen in flow.screens:
        traces = tuple(screen.traces)
        for block in screen.blocks:
            if block.kind not in BLOCK_KINDS:
                findings.append(
                    Finding(
                        rule_id="kinds-are-known",
                        severity="error",
                        reason=(
                            f"{_name(screen)} has a line of an unknown kind "
                            f"({block.kind or 'blank'}), which nothing can draw."
                        ),
                        hint=(
                            f"Block {block.id} on screen {screen.id} has kind "
                            f"'{block.kind}'. Use one of: {', '.join(sorted(BLOCK_KINDS))}."
                        ),
                        subject=screen.id or None,
                        traces=traces,
                    )
                )
            if block.tone and block.tone not in TONES:
                findings.append(
                    Finding(
                        rule_id="kinds-are-known",
                        severity="error",
                        reason=f"{_name(screen)} asks for a tone that does not exist.",
                        hint=(
                            f"Block {block.id} on screen {screen.id} has tone "
                            f"'{block.tone}'. Use one of: {', '.join(sorted(TONES))}, or leave it out."
                        ),
                        subject=screen.id or None,
                        traces=traces,
                    )
                )
        for link in screen.links:
            if link.variant not in LINK_VARIANTS:
                findings.append(
                    Finding(
                        rule_id="kinds-are-known",
                        severity="error",
                        reason=f"A control on {_name(screen)} has no drawable style.",
                        hint=(
                            f"Link {link.id} on screen {screen.id} has variant "
                            f"'{link.variant}'. Use one of: {', '.join(sorted(LINK_VARIANTS))}."
                        ),
                        subject=screen.id or None,
                        traces=traces,
                    )
                )
    return findings


def link_target_exists(flow: DraftFlow, _ids: frozenset[str]) -> list[Finding]:
    """5. No link goes to a screen that is not in this flow.

    The plain broken button. There is no reading of the flow where this is
    intended, so it is an error rather than something to show a reader.
    """
    known = {screen.id for screen in flow.screens if screen.id}
    findings: list[Finding] = []
    for screen in flow.screens:
        for link in screen.links:
            if link.target_id and link.target_id not in known:
                findings.append(
                    Finding(
                        rule_id="link-target-exists",
                        severity="error",
                        reason=(
                            f"'{link.label or link.id}' on {_name(screen)} leads nowhere: "
                            f"there is no screen {link.target_id} in this journey."
                        ),
                        hint=(
                            f"Link {link.id} on screen {screen.id} targets "
                            f"{link.target_id}, which is not a screen here. Point it at one of: "
                            f"{', '.join(sorted(known))}, or add the screen."
                        ),
                        subject=screen.id or None,
                        traces=tuple(screen.traces),
                    )
                )
    return findings


def no_self_link(flow: DraftFlow, _ids: frozenset[str]) -> list[Finding]:
    """6. No screen links to itself.

    A control that returns the reader to where they already are. It is always a
    mistake rather than a choice, and it hides a missing destination.
    """
    findings: list[Finding] = []
    for screen in flow.screens:
        for link in screen.links:
            if link.target_id and link.target_id == screen.id:
                findings.append(
                    Finding(
                        rule_id="no-self-link",
                        severity="error",
                        reason=(
                            f"'{link.label or link.id}' on {_name(screen)} leads back to the "
                            f"same screen, so pressing it does nothing."
                        ),
                        hint=(
                            f"Link {link.id} on screen {screen.id} targets its own screen. "
                            f"Point it at the screen the reader should see next, or remove it."
                        ),
                        subject=screen.id or None,
                        traces=tuple(screen.traces),
                    )
                )
    return findings


def reachable_from_the_entry(flow: DraftFlow, _ids: frozenset[str]) -> list[Finding]:
    """7. Every screen can be reached from the first one.

    Reachability, not inbound link count. Two screens linking only to each other
    both have an inbound link and neither can be opened, and a flow that ships
    with a section no user can enter is the failure a clickable prototype exists
    to catch.
    """
    if not flow.screens:
        return []

    by_id = {screen.id: screen for screen in flow.screens if screen.id}
    entry = flow.screens[0]
    if not entry.id:
        # The entry has no id, which names-are-present already reported. There
        # is no fixed point to walk from, so saying every other screen is
        # unreachable would be a page of findings with one real cause.
        return []

    seen = {entry.id}
    queue = [entry.id]
    while queue:
        current = by_id.get(queue.pop())
        if current is None:
            continue
        for link in current.links:
            if link.target_id in by_id and link.target_id not in seen:
                seen.add(link.target_id)
                queue.append(link.target_id)

    return [
        Finding(
            rule_id="reachable-from-the-entry",
            severity="error",
            reason=(
                f"Nothing leads to {_name(screen)}. A reader starting at "
                f"{_name(entry)} can never open it."
            ),
            hint=(
                f"Screen {screen.id} cannot be reached from the entry screen {entry.id}. "
                f"Add a link to it from a screen that can, or remove it."
            ),
            subject=screen.id,
            traces=tuple(screen.traces),
        )
        for screen in flow.screens
        if screen.id and screen.id not in seen
    ]


def no_unmarked_dead_end(flow: DraftFlow, _ids: frozenset[str]) -> list[Finding]:
    """8. A screen with no way out is reported, unless it reads as an ending.

    A warning, not an error, and that is the whole design of this rule. Endings
    are real: a confirmation and an error page are supposed to stop. An absolute
    rule would fire on every one of them, and a check that is usually wrong is a
    check people learn to skip past. So the name decides, and anything the name
    does not excuse is put in front of a reader to judge.
    """
    return [
        Finding(
            rule_id="no-unmarked-dead-end",
            severity="warning",
            reason=(
                f"{_name(screen)} has no way out, and its name does not say the journey "
                f"ends there. A reader who opens it is stuck."
            ),
            hint=(
                f"Screen {screen.id} has no links. Add the control that carries the "
                f"reader onward or back, or rename it to say it is the end of the journey."
            ),
            subject=screen.id or None,
            traces=tuple(screen.traces),
        )
        for screen in flow.screens
        if not screen.links and not reads_as_an_ending(screen.name)
    ]


def block_activates_a_real_link(flow: DraftFlow, _ids: frozenset[str]) -> list[Finding]:
    """9. A line that claims to be pressable names a link on its own screen."""
    findings: list[Finding] = []
    for screen in flow.screens:
        known = {link.id for link in screen.links if link.id}
        for block in screen.blocks:
            if block.link_id and block.link_id not in known:
                findings.append(
                    Finding(
                        rule_id="block-activates-a-real-link",
                        severity="error",
                        reason=(
                            f"'{block.label or block.id}' on {_name(screen)} looks pressable "
                            f"but is wired to nothing."
                        ),
                        hint=(
                            f"Block {block.id} on screen {screen.id} activates "
                            f"{block.link_id}, which is not a link on that screen. Use one of: "
                            f"{', '.join(sorted(known)) or 'none, so remove the linkId'}."
                        ),
                        subject=screen.id or None,
                        traces=tuple(screen.traces),
                    )
                )
    return findings


def screen_is_traced(flow: DraftFlow, _ids: frozenset[str]) -> list[Finding]:
    """10. Every screen says which requirements it serves.

    A screen nothing asked for is a screen somebody invented, and it is the
    cheapest place for scope to grow without anyone noticing.
    """
    return [
        Finding(
            rule_id="screen-is-traced",
            severity="error",
            reason=(
                f"{_name(screen)} does not say which requirement it serves, so there is "
                f"no way to tell whether it was asked for."
            ),
            hint=(
                f"Screen {screen.id} has no traces. Add the requirement ids it comes from, "
                f"or remove the screen if nothing asked for it."
            ),
            subject=screen.id or None,
        )
        for screen in flow.screens
        if not screen.traces
    ]


def traces_resolve(flow: DraftFlow, requirement_ids: frozenset[str]) -> list[Finding]:
    """11. Every trace names a requirement that exists.

    An invented requirement id is worse than a missing one: it looks like
    traceability and links to nothing.
    """
    findings: list[Finding] = []
    for screen in flow.screens:
        unknown = sorted(t for t in screen.traces if t not in requirement_ids)
        if unknown:
            findings.append(
                Finding(
                    rule_id="traces-resolve",
                    severity="error",
                    reason=(
                        f"{_name(screen)} traces to {', '.join(unknown)}, which "
                        f"{'is not a requirement' if len(unknown) == 1 else 'are not requirements'} "
                        f"of this project."
                    ),
                    hint=(
                        f"Screen {screen.id} names requirement ids that do not exist: "
                        f"{', '.join(unknown)}. Use only ids from the list you were given."
                    ),
                    subject=screen.id or None,
                )
            )
    return findings


def screen_has_content(flow: DraftFlow, _ids: frozenset[str]) -> list[Finding]:
    """12. No screen is empty.

    A screen with no blocks renders as an empty rectangle. It counts towards
    coverage while showing the reader nothing, which is the quietest way for a
    flow to look more complete than it is.

    The hint names the ending case explicitly because that is where a real model
    actually fails: asked for a confirmation screen it returns the name and
    nothing else, having treated the ending as a label rather than as a screen
    somebody reads.
    """
    return [
        Finding(
            rule_id="screen-has-content",
            severity="error",
            reason=f"{_name(screen)} has nothing on it, so it would draw as an empty box.",
            hint=(
                f"Screen {screen.id} has no blocks. Add the lines the reader sees: the "
                f"fields they fill in, the rows they choose from, or the message they read. "
                f"If the journey ends here, a banner saying what happened plus the facts "
                f"they came for is what belongs on it."
            ),
            subject=screen.id or None,
            traces=tuple(screen.traces),
        )
        for screen in flow.screens
        if not screen.blocks
    ]


#: All twelve, in the order they are reported. Structural first, because a flow
#: that does not hold together makes the link graph findings noise.
ALL_RULES: tuple[Rule, ...] = (
    unique_screen_ids,
    unique_link_ids,
    names_are_present,
    kinds_are_known,
    screen_has_content,
    link_target_exists,
    no_self_link,
    reachable_from_the_entry,
    no_unmarked_dead_end,
    block_activates_a_real_link,
    screen_is_traced,
    traces_resolve,
)

#: The names, for the evaluation and for the test that pins the catalogue.
RULE_IDS = (
    "unique-screen-ids",
    "unique-link-ids",
    "names-are-present",
    "kinds-are-known",
    "screen-has-content",
    "link-target-exists",
    "no-self-link",
    "reachable-from-the-entry",
    "no-unmarked-dead-end",
    "block-activates-a-real-link",
    "screen-is-traced",
    "traces-resolve",
)
