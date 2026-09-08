"""The rule layer: everything C1 decides without a language model.

The model builds; the rules validate, classify and score. That split is what
makes the component's claims checkable, so it is a package boundary rather than a
convention.
"""

from .classify import Classification, classify
from .confidence import CEILING, LOW_CONFIDENCE_BELOW, ConfidenceScore, Deduction, score
from .extract import Extraction, ScoredRequirement, apply_budget, extract
from .measure import InputMeasurement, budget_for, measure
from .slots import MAX_QUESTIONS, SLOTS, Slot, SlotFinding, unfilled_slots
from .spans import SpanCheck, find_span, verify_span

__all__ = [
    "CEILING",
    "LOW_CONFIDENCE_BELOW",
    "MAX_QUESTIONS",
    "SLOTS",
    "Classification",
    "ConfidenceScore",
    "Deduction",
    "Extraction",
    "InputMeasurement",
    "ScoredRequirement",
    "Slot",
    "SlotFinding",
    "SpanCheck",
    "apply_budget",
    "budget_for",
    "classify",
    "extract",
    "find_span",
    "measure",
    "score",
    "unfilled_slots",
    "verify_span",
]
