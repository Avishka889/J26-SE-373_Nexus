"""The run harness: what actually executes tests and counts what happened.

Rules only. Nothing in this package calls a model, which is the point: the
numbers the dissertation reports about coverage, mutation and pass rates come
from tools, and the parts a model touches (writing a test, refereeing a
failure, proposing a fix) sit outside it and are measured by it.
"""

from .report import Authored, LaneRun, origin_of
from .sandbox import (
    ISOLATION,
    PER_STEP_TIMEOUT_SECONDS,
    Sandbox,
    Step,
    StepResult,
    not_run,
    toolchain,
)
from .targets import (
    Stack,
    TargetKind,
    TargetLike,
    TargetRepo,
    UnusableTarget,
    resolve,
    sample_root,
    samples,
    stage_copy,
)

__all__ = [
    "ISOLATION",
    "PER_STEP_TIMEOUT_SECONDS",
    "Authored",
    "LaneRun",
    "Sandbox",
    "Stack",
    "Step",
    "StepResult",
    "TargetKind",
    "TargetLike",
    "TargetRepo",
    "UnusableTarget",
    "not_run",
    "origin_of",
    "resolve",
    "sample_root",
    "samples",
    "stage_copy",
    "toolchain",
]
