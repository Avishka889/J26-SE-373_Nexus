"""Detection: the three arms, and how a candidate becomes a finding.

The arms are interchangeable at the seam and comparable at the report, which is
the security pillar's whole design. This package holds all three: the scanners, which need no model; the prompted
arm, which needs one and is therefore the one that has to be checked; and the
trained arm, which needs one it owns and runs in its own process. With them
lives the rule table that turns a weakness class into a severity, so that no
arm ever scores its own finding.
"""

from .arm import PROJECT_SCOPE, ScannerArm, tools_for
from .llm import (
    LlmArm,
    ProposedFinding,
    Triaged,
    build_detector,
    build_triager,
    check_no_self_scoring,
    chunks,
    find_quote,
    triage,
)
from .scanners import (
    RULESETS,
    ScanOutput,
    parse_spotbugs,
    run_findsecbugs,
    run_npm_audit,
    run_semgrep,
    semgrep_version,
)
from .severity import ALIASES, BY_CWE, UNKNOWN, factors_for, normalise
from .trained import ModelProcess, TrainedArm, methods_of

__all__ = [
    "ALIASES",
    "BY_CWE",
    "PROJECT_SCOPE",
    "RULESETS",
    "UNKNOWN",
    "LlmArm",
    "ModelProcess",
    "ProposedFinding",
    "ScanOutput",
    "ScannerArm",
    "TrainedArm",
    "Triaged",
    "build_detector",
    "build_triager",
    "check_no_self_scoring",
    "chunks",
    "factors_for",
    "find_quote",
    "methods_of",
    "normalise",
    "parse_spotbugs",
    "run_findsecbugs",
    "run_npm_audit",
    "run_semgrep",
    "semgrep_version",
    "tools_for",
    "triage",
]
