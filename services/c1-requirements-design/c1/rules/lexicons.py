"""The word lists every rule reads from.

Kept in one module because they are data, not logic, and because the evaluation
has to be able to say exactly which lexicon a classification came from. A rule
that consults a list defined next to it is a rule nobody can audit.

These are deliberately small and English-only. The claim this component makes is
not that the lexicons are complete; it is that classification is done by a rule
whose inputs can be inspected, rather than by a model reporting a label nobody
can check. A miss shows up as a lower confidence score and a flagged
requirement, which is the honest failure mode.
"""

from typing import Final

#: RFC 2119 style modality, mapped to the priority the requirement carries.
#:
#: Order matters within a tier only for reporting; the tiers themselves are what
#: the rule uses. "shall" and "must" are the strong forms in requirements prose,
#: "should" is the recommendation tier, and "may" and "can" describe an option.
MUST_WORDS: Final[frozenset[str]] = frozenset(
    {"must", "shall", "will", "required", "requires", "mandatory", "has to", "have to", "needs to"}
)
SHOULD_WORDS: Final[frozenset[str]] = frozenset(
    {"should", "recommended", "ought", "preferably", "expected to"}
)
COULD_WORDS: Final[frozenset[str]] = frozenset(
    {"may", "can", "could", "might", "optionally", "optional", "nice to have"}
)

#: Every modal, for the confidence rule that asks whether the sentence had one at
#: all. A requirement with no modality was written as a description, and the
#: priority assigned to it is therefore a default rather than a reading.
ALL_MODALS: Final[frozenset[str]] = MUST_WORDS | SHOULD_WORDS | COULD_WORDS

#: Quality attributes, and the words that signal each one.
#:
#: Restricted to the four the contract allows. A signal here only decides the
#: attribute; whether the requirement is a quality requirement at all is decided
#: by `QUALITY_MARKERS` below, so "the system stores passwords" is functional
#: even though it contains a security word.
QUALITY_SIGNALS: Final[dict[str, frozenset[str]]] = {
    "performance": frozenset(
        {
            "performance",
            "latency",
            "throughput",
            "response time",
            "fast",
            "quickly",
            "within",
            "concurrent",
            "concurrently",
            "load",
            "scale",
            "scalable",
            "seconds",
            "second",
            "milliseconds",
            "ms",
            "per second",
            "requests",
        }
    ),
    "security": frozenset(
        {
            "security",
            "secure",
            "securely",
            "encrypt",
            "encrypted",
            "encryption",
            "authenticate",
            "authentication",
            "authorised",
            "authorized",
            "authorisation",
            "authorization",
            "permission",
            "permissions",
            "role",
            "roles",
            "confidential",
            "private",
            "isolated",
            "isolation",
            "leak",
            "audit trail",
            "tamper",
        }
    ),
    "usability": frozenset(
        {
            "usability",
            "usable",
            "accessible",
            "accessibility",
            "intuitive",
            "easy to use",
            "screen reader",
            "keyboard",
            "wcag",
            "readable",
            "learnable",
        }
    ),
    "reliability": frozenset(
        {
            "reliability",
            "reliable",
            "available",
            "availability",
            "uptime",
            "resilient",
            "fault",
            "failover",
            "recover",
            "recovery",
            "retry",
            "retries",
            "durable",
            "consistent",
            "at most once",
            "at least once",
            "exactly once",
            "never lose",
        }
    ),
}

#: What makes a sentence a quality requirement rather than a functional one.
#:
#: A quality requirement constrains how well the system does something, so it
#: carries either a measurable threshold or an explicit quality word. Without one
#: of these a security-flavoured sentence is still a description of behaviour.
QUALITY_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "within",
        "under",
        "less than",
        "no more than",
        "at least",
        "at most",
        "percent",
        "%",
        "uptime",
        "availability",
        "latency",
        "throughput",
        "performance",
        "usability",
        "reliability",
        "security",
        "accessible",
        "concurrent",
        "per second",
        "response time",
        "never",
        "always",
        # The adjective forms, which is how people usually write these. Without
        # them "the system must be fast" reads as a functional requirement.
        "fast",
        "quickly",
        "slow",
        "responsive",
        "reliable",
        "secure",
        "usable",
        "available",
        "scalable",
        "resilient",
        "durable",
    }
)

#: What makes a sentence a constraint: a prohibition, or a named standard the
#: design has to obey. A constraint restricts the solution space rather than
#: describing something the system does.
CONSTRAINT_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "must not",
        "shall not",
        "cannot",
        "can not",
        "never",
        "no ",
        "without",
        "only",
        "restricted",
        "prohibited",
        "forbidden",
        "comply",
        "compliance",
        "conform",
        "standard",
        "regulation",
        "policy",
        "gdpr",
        "pci",
        "hipaa",
        "iso",
        "soc 2",
        "wcag",
        "hl7",
        "fhir",
    }
)

#: Verbs that carry a domain action. Used to count evidence in the input, and to
#: notice a requirement whose sentence never says what happens.
ACTION_VERBS: Final[frozenset[str]] = frozenset(
    {
        "accept",
        "add",
        "allow",
        "apply",
        "approve",
        "assign",
        "audit",
        "authenticate",
        "authorise",
        "authorize",
        "browse",
        "build",
        "calculate",
        "cancel",
        "capture",
        "charge",
        "check",
        "compare",
        "compute",
        "configure",
        "confirm",
        "connect",
        "create",
        "delete",
        "deliver",
        "deploy",
        "display",
        "download",
        "edit",
        "enable",
        "encrypt",
        "enter",
        "execute",
        "export",
        "filter",
        "generate",
        "grant",
        "handle",
        "hold",
        "import",
        "integrate",
        "issue",
        "keep",
        "list",
        "load",
        "log",
        "look",
        "maintain",
        "make",
        "manage",
        "monitor",
        "notify",
        "offer",
        "open",
        "order",
        "pay",
        "perform",
        "persist",
        "place",
        "plan",
        "predict",
        "present",
        "process",
        "provide",
        "publish",
        "read",
        "receive",
        "record",
        "refund",
        "register",
        "reject",
        "remove",
        "render",
        "report",
        "request",
        "require",
        "reset",
        "resolve",
        "retry",
        "return",
        "review",
        "run",
        "save",
        "schedule",
        "search",
        "select",
        "send",
        "share",
        "show",
        "sign",
        "sort",
        "specify",
        "store",
        "submit",
        "support",
        "sync",
        "synchronise",
        "synchronize",
        "throw",
        "track",
        "transfer",
        "update",
        "upload",
        "validate",
        "verify",
        "view",
        "write",
    }
)


#: Verb forms that appear in prose. Mapping them back to the stem keeps the
#: lexicon small and the matching honest: "processing" and "processes" are the
#: same verb, and counting them as two would inflate the evidence measure.
def verb_stem(token: str) -> str:
    """The lexicon form of a verb token, or the token unchanged."""
    word = token.lower()
    if word in ACTION_VERBS:
        return word
    for suffix, replacement in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if not word.endswith(suffix):
            continue
        stem = word[: len(word) - len(suffix)] + replacement
        if stem in ACTION_VERBS:
            return stem
        # "storing" -> "stor" -> "store", "issued" -> "issu" -> "issue"
        if f"{stem}e" in ACTION_VERBS:
            return f"{stem}e"
        # "shipping" -> "shipp" -> "ship"
        if len(stem) > 3 and stem[-1] == stem[-2] and stem[:-1] in ACTION_VERBS:
            return stem[:-1]
    return word


#: Words that are never the subject or object of a requirement. Used when
#: checking whether a requirement's head nouns actually appear in the input.
NOISE_WORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "than",
        "that",
        "this",
        "these",
        "those",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "from",
        "into",
        "over",
        "under",
        "about",
        "as",
        "is",
        "are",
        "be",
        "been",
        "being",
        "was",
        "were",
        "it",
        "its",
        "their",
        "them",
        "they",
        "we",
        "our",
        "you",
        "your",
        "system",
        "app",
        "application",
        "platform",
        "service",
        "user",
        "users",
        "shall",
        "must",
        "should",
        "will",
        "can",
        "may",
        "each",
        "any",
        "all",
        "every",
        "when",
        "where",
        "which",
        "who",
        "while",
        "also",
        "not",
    }
)
