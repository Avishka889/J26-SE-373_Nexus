"""The honesty guarded self healing loop.

The component's headline claim lives here: a repaired test is accepted only if
it changes test code only, still passes the unchanged production code, and
still kills an injected mutant. Weakening an assertion and deleting a test both
pass the first two and fail the third, which is the point.

`mutants` is the mechanism, and it is shared. The guard asks whether a repaired
test still notices a fault; the weak fill gate asks the same question of a test
the model has just written for the first time. One injection, one test run,
seconds, and no requirement that the rest of the suite be green.
"""

from .classify import Verdict, classify, summarise
from .guard import (
    kills_a_mutant_check,
    passes_unchanged_code,
    production_files,
    refusal_for,
    touched_only_test_code,
)
from .kill_check import KillCheck, kills_a_mutant
from .mutants import MAX_ATTEMPTS, Mutant, candidates, inject
from .referee import RefereeAnswer, build_referee, referee
from .repair import RepairOutcome, build_repairer, repair, repair_problems, unified

__all__ = [
    "MAX_ATTEMPTS",
    "KillCheck",
    "Mutant",
    "RefereeAnswer",
    "RepairOutcome",
    "Verdict",
    "build_referee",
    "build_repairer",
    "candidates",
    "classify",
    "inject",
    "kills_a_mutant",
    "kills_a_mutant_check",
    "passes_unchanged_code",
    "production_files",
    "referee",
    "refusal_for",
    "repair",
    "repair_problems",
    "summarise",
    "touched_only_test_code",
    "unified",
]
