"""Table 6, part one: are the generated deployment files valid on their first generation (NFR5)?

    uv run python -m c4.eval.pipeline_study --commit SHA --out studies/epochs \\
        studies/clients/task-tracker studies/clients/c2-rule/*

Every project is generated once for each setting that changes what is
generated, and nothing is ever regenerated after a failure:

- **private**: a private repository, where GitHub has no environments, so the
  deploy workflow carries no `environment:` key;
- **public**: a public repository, where it does;
- **kubernetes**: the optional manifests asked for (FR13).

Each generated file is checked by every check that applies to it, exactly as the
pipeline stage checks it, and the record keeps every verdict. The counts are
taken per validator (checked, passed, failed, not run) and per project, and a
generation is valid only when every one of its files is.

**What this measures and what it does not.** Validity of the files, on the
first generation, by the schemas and linters named in the header. It does not
build or deploy anything: the candidate's lockfile is not resolved here (the
checks do not read it), and whether a candidate builds and boots is staging's
question, answered per run. The projects are the platform's own generated apps:
the task tracker a live C2 run produced, and the four C2's rule arm generates
from its corpus designs.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from sdlc_contracts import DependencyUpdates

from ..pipeline import render
from ..pipeline.candidate import Resolution
from ..pipeline.generate import generate
from ..pipeline.validate import SCHEMAS, validate
from .loaders.clients import files_sha256, read_client

VARIANTS: dict[str, dict] = {
    "private": {"github_protection": "unavailable-private-repo"},
    "public": {"github_protection": "configured"},
    "kubernetes": {"github_protection": "unavailable-private-repo", "kubernetes": True},
}

VALIDATORS = ("yaml-parse", "json-schema", "actionlint", "hadolint", "kubeconform", "secret-scan")


def _unresolved(files: dict[str, str], updates) -> Resolution:
    """No update is applied: the study measures the files, which never read the lockfile."""
    return Resolution(lockfile=files.get("package-lock.json", ""), resolved_by="not resolved")


def generation(project: str, files: dict[str, str], variant: str, *, validator, now) -> dict:
    """One project generated once under one variant, with every verdict kept."""
    generated = generate(
        files,
        DependencyUpdates(
            version=1, generated_at=now, code_version=1, test_version=1, target="study"
        ),
        stack_id="mern",
        contract=None,
        included=[],
        settings={"project_slug": project, **VARIANTS[variant]},
        version=1,
        code_version=1,
        now=now,
        resolver=_unresolved,
        validate=validator,
    )
    config = generated.config
    return {
        "project": project,
        "variant": variant,
        "supported": config.stack.supported,
        "reason": config.stack.reason,
        "valid": config.valid,
        "files": [
            {
                "path": item.path,
                "templateId": item.template_id,
                "valid": item.valid,
                "validations": [
                    {
                        "validator": check.validator,
                        "tool": check.tool,
                        "outcome": check.outcome,
                        "findings": check.findings,
                        "reason": check.reason,
                    }
                    for check in item.validations
                ],
            }
            for item in config.files
        ],
    }


def tally(generations: list[dict]) -> dict:
    """The counts a table is built from: per validator, per project, and overall."""
    by_validator = {
        name: {"checked": 0, "passed": 0, "failed": 0, "notRun": 0} for name in VALIDATORS
    }
    by_project: dict[str, dict[str, int]] = {}
    for item in generations:
        project = by_project.setdefault(
            item["project"], {"generations": 0, "valid": 0, "files": 0, "validFiles": 0}
        )
        project["generations"] += 1
        project["valid"] += int(item["valid"])
        for generated in item["files"]:
            project["files"] += 1
            project["validFiles"] += int(generated["valid"])
            for check in generated["validations"]:
                counts = by_validator[check["validator"]]
                counts["checked"] += 1
                key = {"passed": "passed", "failed": "failed", "not-run": "notRun"}[
                    check["outcome"]
                ]
                counts[key] += 1
    overall = {
        key: sum(project[key] for project in by_project.values())
        for key in ("generations", "valid", "files", "validFiles")
    }
    return {"byValidator": by_validator, "byProject": by_project, "overall": overall}


def header(commit: str, projects: dict[str, str], tools: list[str], *, today: date) -> dict:
    """Everything a verdict depends on: the templates, the schemas, the tools, the projects."""
    return {
        "label": "Table 6, part one: first-generation validity",
        "date": today.isoformat(),
        "commit": commit,
        "templates": {tid: entry["sha256"] for tid, entry in render.manifest().items()},
        "schemas": {
            path.relative_to(SCHEMAS).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(SCHEMAS.rglob("*.json"))
        },
        "tools": tools,
        "variants": VARIANTS,
        "projects": projects,
    }


def run(
    clients: list[Path], *, commit: str, validator=validate, now: datetime | None = None
) -> dict:
    now = now or datetime.now(UTC)
    generations = []
    projects: dict[str, str] = {}
    for directory in clients:
        files = read_client(directory)
        project = directory.name
        projects[project] = files_sha256(files)
        for variant in VARIANTS:
            generations.append(generation(project, files, variant, validator=validator, now=now))
    tools = sorted(
        {
            check["tool"]
            for item in generations
            for generated in item["files"]
            for check in generated["validations"]
        }
    )
    record = {
        "study": header(commit, projects, tools, today=now.date()),
        "generations": generations,
    }
    record.update(tally(generations))
    return record


def render_table(record: dict) -> str:
    study = record["study"]
    lines = [
        f"### {study['label']}, {study['date']}",
        "",
        f"Commit `{study['commit']}`. {len(study['projects'])} projects, "
        f"{len(study['variants'])} variants each ({', '.join(study['variants'])}). "
        f"Tools: {'; '.join(study['tools'])}.",
        "",
        "| validator | checked | passed | failed | not run |",
        "|---|---|---|---|---|",
    ]
    for name, counts in record["byValidator"].items():
        lines.append(
            f"| {name} | {counts['checked']} | {counts['passed']} | {counts['failed']} | "
            f"{counts['notRun']} |"
        )
    lines += [
        "",
        "| project | generations valid | files valid |",
        "|---|---|---|",
    ]
    for project, counts in record["byProject"].items():
        lines.append(
            f"| {project} | {counts['valid']} of {counts['generations']} | "
            f"{counts['validFiles']} of {counts['files']} |"
        )
    overall = record["overall"]
    lines += [
        "",
        f"Overall: {overall['valid']} of {overall['generations']} generations valid on their first "
        f"generation, {overall['validFiles']} of {overall['files']} files.",
    ]
    return "\n".join(lines) + "\n"


def _commit() -> str:
    done = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m c4.eval.pipeline_study", description=__doc__)
    parser.add_argument("clients", nargs="+", type=Path)
    parser.add_argument("--commit", default=None)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    record = run(args.clients, commit=args.commit or _commit())
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / "table-6-part-one-first-generation-validity.json"
        target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(f"wrote {target}")
    print(render_table(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
