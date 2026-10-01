"""Maven updates observed on a client of our own, where BUMP has only breaks.

BUMP is all positives: every record is an update that broke a build. The Maven
side of the study needs updates that did not break anything too, observed the
same way, or its accuracy is only its High recall. The client is `java-records`,
C3's Java sample reduced to one class and its suite, and it is crossed with the
patch, minor and major updates of the JUnit BOM its POM imports
(`crossings.targets`).

Maven has no lockfile, so the control and the candidate are the same files with
the version property set to the installed and the target version. Each runs in
a fresh container of a Maven image pinned by digest, which downloads what the
POM names from Maven Central; nothing on the host is read or written.
"""

import re

from ...harness.container import Lane, StepSpec
from ...harness.reproduce import Reproduction, compare
from ..cases import CaseClient, CaseUpdate, LabelledCase, Observed
from .clients import files_sha256
from .crossings import CrossingKind

#: Maven 3.9 on Eclipse Temurin 21, the JDK the client compiles for. Pinned by
#: digest, so a rerun of the study builds with exactly this toolchain: Maven
#: 3.9.16 and Java 21.0.12.1, pulled 2026-09-27.
MAVEN_IMAGE = "maven:3.9-eclipse-temurin-21@sha256:99e61abcff91a9b1333463bd8451fb18495d6eba9250ac66a338b518f8278320"

#: The dependency the client's POM imports, and the property that holds its version.
PACKAGE = "org.junit:junit-bom"
PROPERTY = "junit.version"

#: Every Maven goal can download a plugin it has not used yet, so both steps do.
STEPS = [
    StepSpec("compile", "mvn -B -ntp -q test-compile", timeout=900, downloads=True),
    StepSpec("test", "mvn -B -ntp test", timeout=900, downloads=True),
]


def installed_version(files: dict[str, str]) -> str:
    found = re.search(rf"<{re.escape(PROPERTY)}>([^<]+)</{re.escape(PROPERTY)}>", files["pom.xml"])
    if found is None:
        raise ValueError(f"the client's pom.xml sets no {PROPERTY}")
    return found.group(1).strip()


def with_version(files: dict[str, str], version: str) -> dict[str, str]:
    """The client with its JUnit version property set to `version`, and nothing else changed."""
    pom, count = re.subn(
        rf"<{re.escape(PROPERTY)}>[^<]+</{re.escape(PROPERTY)}>",
        f"<{PROPERTY}>{version}</{PROPERTY}>",
        files["pom.xml"],
    )
    if count != 1:
        raise ValueError(f"expected one {PROPERTY} in the client's pom.xml, found {count}")
    return {**files, "pom.xml": pom}


def observe(lane: Lane, files: dict[str, str], old: str, new: str) -> Reproduction:
    return compare(
        lane,
        (with_version(files, old), STEPS),
        (with_version(files, new), STEPS),
        package=PACKAGE,
    )


def case_id(old: str, new: str) -> str:
    slug = re.sub(r"[^a-z0-9.]+", "-", f"junit-bom-{old}-{new}")
    return f"maven-records-{slug}"


def case_for(
    kind: CrossingKind,
    old: str,
    new: str,
    reproduction: Reproduction,
    *,
    files: dict[str, str],
    toolchain: str,
    captured_at: str,
) -> LabelledCase:
    return LabelledCase(
        case_id=case_id(old, new),
        source="maven-negative",
        client=CaseClient(
            kind="seeded",
            snapshot="studies/clients/java-records",
            snapshot_sha256=files_sha256(files),
        ),
        update=CaseUpdate(
            ecosystem="maven",
            package=PACKAGE,
            from_version=old,
            to_version=new,
            manifest_paths=["pom.xml"],
            scope="import",
        ),
        source_change=kind,
        observed=Observed(
            method="container-reproduction",
            captured_at=captured_at,
            toolchain=toolchain,
            baseline=reproduction.baseline,
            candidate=reproduction.candidate,
            warnings=reproduction.warnings,
        ),
        provenance=(
            "maven_negatives loader: the client java-records, its JUnit BOM crossed with the "
            f"{kind} update Maven Central listed at capture"
        ),
    )
