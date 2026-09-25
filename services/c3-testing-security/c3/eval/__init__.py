"""The study: how the three arms are scored, and by what rule.

Every number destined for the dissertation is computed here, from predictions
the arms wrote down, rather than inside whichever notebook or sandbox produced
them. Predictions are data and are kept; scores are derived and are recomputed
whenever the rule for what counts as a match is examined.
"""

from .benchmarks import Benchmark, decoys_hit, owasp
from .cwe_bench import fetch_project, project, project_slugs
from .healing import Convergence, HealingStudy
from .healing import combine as combine_healing
from .healing import study as healing_study
from .predictions import detection, per_class, report
from .scoring import ClassScore, Scorecard, Span, aligned, score
from .study import ArmResult, Epoch, Study, run_study, spans_of

__all__ = [
    "ArmResult",
    "Benchmark",
    "ClassScore",
    "Convergence",
    "Epoch",
    "HealingStudy",
    "Scorecard",
    "Span",
    "Study",
    "aligned",
    "combine_healing",
    "decoys_hit",
    "detection",
    "fetch_project",
    "healing_study",
    "owasp",
    "per_class",
    "project",
    "project_slugs",
    "report",
    "run_study",
    "score",
    "spans_of",
]
