"""The tech stack: rules propose, the model explains, the human selects."""

from .catalog import CATALOG, entry_for
from .explain import build_stack_explainer, check_no_invented_figures, prompt_for
from .scoring import StackFacts, gather_stack_facts, score_stacks

__all__ = [
    "CATALOG",
    "StackFacts",
    "build_stack_explainer",
    "check_no_invented_figures",
    "entry_for",
    "gather_stack_facts",
    "prompt_for",
    "score_stacks",
]
