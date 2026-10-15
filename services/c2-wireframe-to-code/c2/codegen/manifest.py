"""Generated files, and the manifest that makes them attributable.

Every generated file passes through here: path, content, which stage wrote
it, which generator authored it (a checked in template, the rule generator,
or a model filled body), which contract arm the run had chosen, and what it
implements. "Which arm wrote this file" is a stored fact, never an inference.
"""

from dataclasses import dataclass, field

from sdlc_contracts import ManifestRow


@dataclass(frozen=True)
class GeneratedFile:
    path: str
    content: str
    stage: str
    generator: str  # static | rule | model
    implements: tuple[str, ...] = ()
    summary: str = ""
    #: What a page's rewrite depended on (`fill.page_digest`), set on every page
    #: the model was asked to rewrite, whether its rewrite shipped or not.
    written_from: str = ""
    #: The code version whose page this one reuses unchanged; 0 when written now.
    reused_from_version: int = 0


@dataclass
class FileSet:
    """An ordered, collision refusing collection of generated files."""

    files: list[GeneratedFile] = field(default_factory=list)

    def add(self, generated: GeneratedFile) -> None:
        if any(existing.path == generated.path for existing in self.files):
            raise ValueError(f"two generators wrote {generated.path}")
        self.files.append(generated)

    def extend(self, others: "FileSet") -> None:
        for generated in others.files:
            self.add(generated)

    def content_of(self, path: str) -> str:
        for generated in self.files:
            if generated.path == path:
                return generated.content
        raise KeyError(path)

    def manifest(self, arm: str) -> list[ManifestRow]:
        return [
            ManifestRow(
                path=generated.path,
                stage=generated.stage,
                generator=generated.generator,  # type: ignore[arg-type]
                arm=arm,  # type: ignore[arg-type]
                implements=list(generated.implements),
                summary=generated.summary,
                written_from=generated.written_from,
                reused_from_version=generated.reused_from_version,
            )
            for generated in self.files
        ]
