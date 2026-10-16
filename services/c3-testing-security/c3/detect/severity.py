"""How a weakness class becomes a severity, by rule and not by opinion.

The component's flat claim is that no model scores its own finding. That claim
needs something to score by, and this is it: one table from CWE to the CVSS
v3.1 base metrics, applied by lookup, with the arithmetic living in the
contracts package where it is checked against published CVEs.

**Why a table and not a judgement.** The alternative is asking a model, and the
one number available on that says language models are around sixty percent
accurate on CVSS and tend to underestimate. A lookup is worse than an expert
and better than a guess, and unlike either it is the same answer every time,
which is what makes two runs comparable.

**What the table is and is not.** It is a default severity for a weakness class
in the worst reasonable case for that class, which is what CWE level scoring
can honestly offer. It is not an assessment of a particular finding: whether
this SQL injection is reachable from the internet is a property of the
application, not of CWE-89, and nothing here pretends to know it. The report
carries the vector, so a reader who knows better can say so and be specific.

Every row cites the reasoning that produced it in one line, because a severity
nobody can argue with is a severity nobody can check.
"""

from sdlc_contracts import CvssFactors

#: What a weakness class scores when nothing more specific is known.
#:
#: Read as: an attacker who can reach the affected feature at all. The vectors
#: are deliberately conservative about reachability (`AV:N` only where the
#: weakness class is characteristically remote) and deliberately blunt about
#: impact, because impact is the part CWE level scoring can actually speak to.
BY_CWE: dict[str, tuple[CvssFactors, str]] = {
    "CWE-89": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="H",
            availability="H",
        ),
        "SQL injection reaches the database with the application's own rights, "
        "so all three impacts are high; scored as the unauthenticated case, "
        "which is the one that matters",
    ),
    "CWE-78": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="H",
            availability="H",
        ),
        "command injection is arbitrary execution as the service account, "
        "which is the same three high impacts by a shorter route",
    ),
    "CWE-22": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="N",
            availability="N",
        ),
        "path traversal reads what the process can read; writing through one is "
        "a separate weakness and is not assumed here",
    ),
    "CWE-79": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="R",
            scope="C",
            confidentiality="L",
            integrity="L",
            availability="N",
        ),
        "reflected cross site scripting needs a victim to act and crosses into "
        "their browser, which is the scope change; the published examples score "
        "6.1 on exactly this vector",
    ),
    "CWE-327": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="H",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="N",
            availability="N",
        ),
        "a broken algorithm exposes what it was protecting, but exploiting it "
        "takes work the attacker does not control, so the complexity is high",
    ),
    "CWE-328": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="H",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="N",
            availability="N",
        ),
        "a weak hash is the same argument as a broken algorithm; the two CWEs "
        "are reported by different scanners for the same finding",
    ),
    "CWE-916": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="H",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="N",
            availability="N",
        ),
        "a password hash without work factor is broken offline, which is "
        "effort the defender cannot see and the attacker can afford",
    ),
    "CWE-798": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="H",
            availability="N",
        ),
        "a credential in the source is a credential in every clone and every "
        "build cache; whoever has the repository has the account",
    ),
    "CWE-1321": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="N",
            integrity="H",
            availability="H",
        ),
        "prototype pollution corrupts objects the program trusts, so integrity "
        "and availability rather than disclosure",
    ),
    "CWE-94": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="H",
            availability="H",
        ),
        "code injection runs the attacker's code in the application's own "
        "process, which is every impact at once",
    ),
    "CWE-502": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="H",
            availability="H",
        ),
        "deserialising untrusted data is execution in the process that does it",
    ),
    "CWE-611": (
        CvssFactors(
            attack_vector="N",
            attack_complexity="L",
            privileges_required="N",
            user_interaction="N",
            scope="U",
            confidentiality="H",
            integrity="N",
            availability="L",
        ),
        "an external entity reads local files and can be pointed at services that answer slowly",
    ),
}

#: Children of a class the table scores, scored as their parent.
#:
#: Found by measurement rather than by reading the CWE tree: Juliet Java labels
#: its path traversal cases CWE-23 and CWE-36 and its cross site scripting
#: cases CWE-80, CWE-81 and CWE-83, while the scanners report the parents,
#: CWE-22 and CWE-79. Both are correct and they are the same weakness at
#: different depths of the same tree. Without this, the trained arm's findings
#: would score as unknown while the scanner arm's identical findings scored as
#: high, and the comparison would be measuring which vocabulary each arm
#: happened to use.
#:
#: One way only: a parent is never scored as a child, because the child is the
#: more specific claim and nothing here is entitled to make it.
ALIASES: dict[str, str] = {
    "CWE-23": "CWE-22",
    "CWE-36": "CWE-22",
    "CWE-80": "CWE-79",
    "CWE-81": "CWE-79",
    "CWE-83": "CWE-79",
    "CWE-759": "CWE-916",
    "CWE-760": "CWE-916",
    # Weak hash under broken algorithm. The table already scores the two the
    # same and says why; this is the same argument applied to matching, so a
    # scanner that says MD5 and a benchmark that says broken crypto are talking
    # about one finding rather than about two the arm got wrong.
    "CWE-328": "CWE-327",
}

#: What anything not in the table scores.
#:
#: Deliberately not zero and deliberately not high. A weakness a scanner
#: reported and this table has never heard of is worth a reader's attention and
#: is not worth an alarm, and the report says the score came from here rather
#: than from a rule written for that class.
UNKNOWN = (
    CvssFactors(
        attack_vector="N",
        attack_complexity="H",
        privileges_required="L",
        user_interaction="N",
        scope="U",
        confidentiality="L",
        integrity="L",
        availability="N",
    ),
    "no rule for this weakness class, so a deliberately unremarkable default "
    "that asks for a look rather than an alarm",
)


def normalise(cwe: str) -> str:
    """`CWE-89: Improper Neutralization...` as `CWE-89`.

    Semgrep reports the class and its full title in one string, npm audit
    reports the bare id, FindSecBugs reports a bare number, and CWE-Bench-Java
    zero pads to three digits. One spelling reaches the report.

    The zero padding is worth naming, because it was a silent failure rather
    than a loud one: `CWE-022` parses, looks like a weakness class, matches
    nothing in the table, and scores as unknown. Every path traversal in a
    whole benchmark would have been graded against a different class from the
    one the scanners report, and nothing would have looked wrong.
    """
    text = (cwe or "").strip()
    head = text.split(":", 1)[0].strip().upper()
    digits = head[4:] if head.startswith("CWE-") else head
    digits = "".join(character for character in digits if character.isdigit())
    return f"CWE-{int(digits)}" if digits else ""


def factors_for(cwe: str) -> tuple[CvssFactors, str]:
    """The metrics this weakness class scores at, and why.

    Returns the reasoning beside the metrics so the report can carry it. A
    severity a reader cannot argue with is a severity nobody can check.

    A class that is a more specific child of one the table scores is scored as
    the parent, and the reasoning says so: an arm that reported CWE-36 and an
    arm that reported CWE-22 found the same thing, and a severity that moved
    between them would be a severity about vocabulary.
    """
    key = normalise(cwe)
    if key in BY_CWE:
        return BY_CWE[key]
    parent = ALIASES.get(key)
    if parent and parent in BY_CWE:
        factors, why = BY_CWE[parent]
        return factors, f"{why}; scored as {parent}, of which {key} is a more specific case"
    return UNKNOWN
