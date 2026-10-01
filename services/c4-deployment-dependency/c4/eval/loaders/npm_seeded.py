"""Small clients written for the study, each over one real release of one package.

A generated project uses a package the way the generator does, so some shapes of
use never appear in it: an alias a major removed, a shortcut a minor deprecated,
code a stricter compiler now refuses, a package the client barely touches. Each
seeded client is a few lines that use one package in one such way, frozen under
`studies/clients/seeded/`, and each is paired with one update of that package.

What a seeded client was written to show is recorded as `intent`, and it is not
the label. The label comes from the container, like every other case's: if the
release did not do what the client was written around, the case says so.
"""

from dataclasses import dataclass

from ...harness.container import Lane, StepSpec
from ...harness.reproduce import Reproduction, reproduce
from ...intake.lockfile import LOCKFILE, Pin
from ..cases import CaseClient, CaseUpdate, LabelledCase, Observed
from .clients import files_sha256, text_sha256

TEST = StepSpec("test", "npm test", timeout=300)
TYPECHECK = StepSpec("typecheck", "npm run typecheck", timeout=300)


@dataclass(frozen=True)
class Seeded:
    client: str
    package: str
    from_version: str
    to_version: str
    scope: str
    steps: tuple[StepSpec, ...]
    #: What the client was written to show, in one sentence. Not the label.
    intent: str

    @property
    def case_id(self) -> str:
        return f"seeded-{self.client}"


SEEDED = (
    Seeded(
        client="express-del",
        package="express",
        from_version="4.21.2",
        to_version="5.1.0",
        scope="prod",
        steps=(TEST,),
        intent="a route registered with app.del, which Express 5 removed",
    ),
    Seeded(
        client="uuid-v4",
        package="uuid",
        from_version="9.0.1",
        to_version="14.0.2",
        scope="prod",
        steps=(TEST,),
        intent="five majors of a package whose one used function, v4, did not change",
    ),
    Seeded(
        client="express-redirect-back",
        package="express",
        from_version="4.20.0",
        to_version="4.21.0",
        scope="prod",
        steps=(TEST,),
        intent='res.redirect("back"), which Express 4.21 deprecated without removing',
    ),
    Seeded(
        client="ts-nullish",
        package="typescript",
        from_version="5.5.4",
        to_version="5.6.3",
        scope="dev",
        steps=(TYPECHECK,),
        intent="a never-nullish ?? and an always-truthy condition, which TypeScript 5.6 reports",
    ),
)


def observe(lane: Lane, files: dict[str, str], seeded: Seeded) -> Reproduction:
    return reproduce(
        lane,
        files,
        package=seeded.package,
        old=seeded.from_version,
        new=seeded.to_version,
        steps=list(seeded.steps),
    )


def case_for(
    seeded: Seeded,
    reproduction: Reproduction,
    *,
    files: dict[str, str],
    pinned: Pin,
    pin_path: str,
    toolchain: str,
    captured_at: str,
) -> LabelledCase:
    return LabelledCase(
        case_id=seeded.case_id,
        source="npm-seeded",
        client=CaseClient(
            kind="seeded",
            snapshot=f"studies/clients/seeded/{seeded.client}",
            snapshot_sha256=files_sha256({p: t for p, t in files.items() if p != LOCKFILE}),
        ),
        update=CaseUpdate(
            ecosystem="npm",
            package=seeded.package,
            from_version=seeded.from_version,
            to_version=seeded.to_version,
            manifest_paths=["package.json"],
            scope=seeded.scope,
        ),
        observed=Observed(
            method="container-reproduction",
            captured_at=captured_at,
            toolchain=toolchain,
            baseline=reproduction.baseline,
            candidate=reproduction.candidate,
            warnings=reproduction.warnings,
        ),
        frozen_inputs={pin_path: text_sha256(files[LOCKFILE])},
        provenance=(
            f"npm_seeded loader: the client seeded/{seeded.client}, written for the study to "
            f"show {seeded.intent}; its tree pinned by {pinned.record.resolved_by}"
        ),
    )
