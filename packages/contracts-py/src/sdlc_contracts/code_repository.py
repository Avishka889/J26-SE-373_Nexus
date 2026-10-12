"""The generated repository: manifest, build report, and the pointer.

Three rules this shape enforces in words and validators:

- Every generated file is on the manifest with its stage and its generator, so
  "which arm wrote this" is a stored fact rather than an inference.
- A build step that did not run says `not-run`; one that hit its cap says
  `timed-out`. Neither is ever `passed`.
- The repository pointer exists only when a push actually happened; otherwise
  `not_pushed_reason` says why in plain words, and no URL is invented.
"""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .wire import WireModel

Generator = Literal["static", "rule", "model"]
StepOutcome = Literal["passed", "failed", "not-run", "timed-out"]


class ManifestRow(WireModel):
    path: str = Field(min_length=1)
    #: The stage that wrote it: frontend-code, backend-code, or build.
    stage: str = Field(min_length=1)
    #: Who authored the content: a checked in template, the rule generator, or
    #: a model filled body.
    generator: Generator
    #: The contract arm the generating run had chosen, recorded per file so a
    #: mixed history stays attributable.
    arm: Literal["rule", "llm", "merged"] = "rule"
    #: Endpoint ids, screen ids and entity names this file implements.
    implements: list[str] = Field(default_factory=list)
    summary: str = ""
    #: For a page the model was asked to rewrite: a digest of everything the
    #: rewrite depended on, so the next generation can tell an unchanged page
    #: from a changed one. Empty for every other file.
    written_from: str = ""
    #: The code version whose page this one reuses unchanged, its inputs being
    #: the same; 0 when this generation wrote it. A reviewer reads it as "no
    #: change since version N".
    reused_from_version: int = Field(default=0, ge=0)
    #: The code versions whose applied security fix was carried into this file
    #: when the code was generated again, oldest first. A reviewer reads each as
    #: "includes the fix applied as version N".
    carried_fixes: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list)


class EarlierPage(WireModel):
    """A page as an earlier generation left it, for the next one to reuse when unchanged.

    The model's rewrite or, where the rewrite was refused, the rule page that
    shipped instead: reusing the refusal as well keeps an unchanged page from
    flipping between the two from one generation to the next.
    """

    path: str = Field(min_length=1)
    written_from: str = Field(min_length=1)
    generator: Literal["rule", "model"]
    #: The file as it shipped, byte for byte: the wire models strip strings,
    #: and a page that lost its last newline would read as changed.
    content: Annotated[str, StringConstraints(strip_whitespace=False)]
    version: int = Field(ge=1)


class BuildStepReport(WireModel):
    name: str = Field(min_length=1)
    command: str = Field(min_length=1)
    outcome: StepOutcome
    duration_seconds: float | None = Field(default=None, ge=0)
    #: The real tail of the real output, capped by the sandbox. Empty only for
    #: a step that never ran.
    log_tail: str = ""

    @model_validator(mode="after")
    def outcomes_are_honest(self) -> "BuildStepReport":
        if self.outcome == "not-run" and self.duration_seconds is not None:
            raise ValueError(f"step {self.name} did not run but carries a duration")
        return self


class BuildReport(WireModel):
    #: What actually ran the build: "node 22.17.0 / npm 10.9.2".
    toolchain: str = Field(min_length=1)
    #: The isolation mechanism in words, including what it does not guarantee.
    isolation: str = Field(min_length=1)
    steps: list[BuildStepReport] = Field(min_length=1)

    @property
    def passed(self) -> bool:
        return all(step.outcome == "passed" for step in self.steps)


class RepositoryPointer(WireModel):
    provider: Literal["github"] = "github"
    owner: str = Field(min_length=1)
    name: str = Field(min_length=1)
    default_branch: str = Field(min_length=1)
    commit_sha: str = Field(min_length=1)
    url: str = Field(min_length=1)
    #: The branch this version's commit is on: its own (`code/v3`), and the
    #: default branch moves to it when the code review approves it. Empty for
    #: a version pushed to the default branch itself, as every version was
    #: before 2026-10-04, unreviewed or failing ones included.
    branch: str = ""
    #: The pull request that proposes this version's branch into the default
    #: branch, for the review to open. Empty where none was opened: a version on
    #: the default branch itself, or GitHub refusing one (review item C2-8).
    pull_request_url: str = ""
    pull_request_number: int | None = Field(default=None, ge=1)


class CodeRepository(WireModel):
    version: int = Field(ge=1)
    manifest: list[ManifestRow] = Field(default_factory=list)
    #: None until the build stage has run.
    build: BuildReport | None = None
    repository: RepositoryPointer | None = None
    not_pushed_reason: str | None = None

    @model_validator(mode="after")
    def the_pointer_and_the_reason_are_exclusive(self) -> "CodeRepository":
        if self.repository is not None and self.not_pushed_reason:
            raise ValueError("a pushed repository cannot also carry a not pushed reason")
        return self
