"""The CI/CD pipeline and deployment configuration C4 generated, and how each file was checked.

FR12 to FR14 and NFR5. The files come from validated templates per supported
stack, filled with the project's own values; a stack without templates is
reported as unsupported and nothing is generated for it, rather than an
unverified configuration being offered as if it were one (FR14).

**Valid means checked, on the first generation.** NFR5 asks for configuration
that is valid with no manual correction, so there is no repair loop: each file
records every validator that applies to it, with its verdict, and `valid` is
computed from those records. Every one must have run and passed: a check that
could not run (a linter with no Docker to run in) leaves the file unverified,
not valid, however many other checks passed.

**The layout is recorded with the evidence that decided it.** Generating a
pipeline is not novel; choosing it by the project's architectural layout is the
one increment claimed, so the layout detected and the facts it rests on are part
of the artefact.
"""

from typing import Literal

from pydantic import Field, computed_field, model_validator

from .wire import WireDatetime, WireModel

ValidatorName = Literal[
    "json-schema",
    "yaml-parse",
    "actionlint",
    "hadolint",
    "kubeconform",
    "secret-scan",
]

ValidationOutcome = Literal["passed", "failed", "not-run"]

#: `one-process`: the backend serves the built frontend, as the generated MERN
#: projects do. `split`: two deployable parts that find each other by address.
LayoutKind = Literal["one-process", "split", "backend-only", "frontend-only"]

FilePurpose = Literal[
    "workflow",
    "container",
    "hosting",
    "orchestration",
    "ignore",
    "lockfile",
    "fingerprint",
]


class FileValidation(WireModel):
    """One validator's verdict on one file."""

    validator: ValidatorName
    #: The tool and its version, or the schema's name.
    tool: str = ""
    schema_url: str = ""
    #: When the vendored schema was retrieved, so a verdict can be dated.
    schema_retrieved: str = ""
    outcome: ValidationOutcome
    findings: list[str] = Field(default_factory=list)
    #: Why the validator did not run, when it did not.
    reason: str = ""

    @model_validator(mode="after")
    def a_verdict_says_why(self) -> "FileValidation":
        if self.outcome == "failed" and not self.findings:
            raise ValueError(f"{self.validator} failed without saying what it found")
        if self.outcome == "not-run" and not self.reason.strip():
            raise ValueError(f"{self.validator} did not run and did not say why")
        return self


class PipelineFile(WireModel):
    """One generated file."""

    path: str = Field(min_length=1)
    purpose: FilePurpose
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    #: The template and its version, `mern/deploy.yml@1`.
    template_id: str = Field(min_length=1)
    #: Secret names the file refers to, never values (NFR8).
    secrets_referenced: list[str] = Field(default_factory=list)
    validations: list[FileValidation] = Field(default_factory=list)

    @computed_field
    @property
    def valid(self) -> bool:
        """Every validator that applies to it ran, and passed."""
        return bool(self.validations) and all(
            check.outcome == "passed" for check in self.validations
        )


class ArchitecturalLayout(WireModel):
    """How the project is laid out, and the facts that decided it."""

    kind: LayoutKind
    frontend_dir: str | None = None
    backend_dir: str | None = None
    shared_dirs: list[str] = Field(default_factory=list)
    serves_frontend_from_backend: bool
    evidence: list[str] = Field(min_length=1)


class StackSupport(WireModel):
    """Whether this stack has validated templates, and if not, why (FR14)."""

    stack_id: str = Field(min_length=1)
    supported: bool
    reason: str = ""
    layout: ArchitecturalLayout | None = None

    @model_validator(mode="after")
    def unsupported_says_why(self) -> "StackSupport":
        if not self.supported and not self.reason.strip():
            raise ValueError(f"stack {self.stack_id} is unsupported without a reason")
        if self.supported and self.layout is None:
            raise ValueError(f"stack {self.stack_id} is supported but no layout was detected")
        return self


class PipelineConfig(WireModel):
    """The `pipeline-config` artefact."""

    version: int = Field(ge=1)
    generated_at: WireDatetime
    code_version: int = Field(ge=1)
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    stack: StackSupport
    files: list[PipelineFile] = Field(default_factory=list)
    kubernetes: Literal["generated", "skipped"]
    kubernetes_reason: str = ""

    @model_validator(mode="after")
    def an_unsupported_stack_gets_no_files(self) -> "PipelineConfig":
        if not self.stack.supported and self.files:
            raise ValueError(
                "files were generated for an unsupported stack; FR14 reports it instead"
            )
        if self.kubernetes == "skipped" and not self.kubernetes_reason.strip():
            raise ValueError("the Kubernetes manifests were skipped without a reason")
        return self

    @computed_field
    @property
    def valid(self) -> bool:
        """NFR5: a supported stack whose every generated file is valid."""
        return self.stack.supported and bool(self.files) and all(f.valid for f in self.files)
