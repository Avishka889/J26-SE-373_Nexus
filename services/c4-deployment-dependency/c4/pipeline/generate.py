"""Pipeline generation (FR12 to FR14): the deployment layer for the stack C2 chose.

One pass, no repair loop (NFR5). The stack is supported only where validated
templates exist and the project's layout is one they were written for;
otherwise the stack is reported unsupported with the reason, and no file is
generated (FR14). For a supported stack the steps are, in order:

1. **The layout** is read from the project (`layout.py`), with its evidence.
2. **The candidate's dependencies**: the included updates applied to the
   baseline pin (`candidate.py`).
3. **The templates** are filled with values read from the project and the
   settings, each checked for its shape first. Kubernetes manifests are
   optional (FR13) and generated only when asked for.
4. **The candidate hash** is taken over the code, the lockfile, the changed
   manifests and every generated file, and written into `release.json`, the
   fingerprint the built frontend serves.
5. **Every file is validated** where it was generated (`validate.py`), and the
   verdicts are recorded on it. Nothing is regenerated after a failure: NFR5
   asks for validity on the first generation, so a failure is a result.

**Where the values come from.** The Node image is the one staging and the study
lane run on, pinned by digest, so what is verified is what ships. The actions a
workflow uses are pinned by commit, with the release they are named beside.
Origins come from the settings; before a first cloud release they are Render's
and Vercel's default addresses for the names chosen here, and the notes say they
were predicted. The deploy workflow's `environment:` key is written only where
GitHub can enforce it, which the settings' `github_protection` says.
"""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sdlc_contracts import (
    ApiContract,
    DependencyUpdates,
    FileValidation,
    GithubProtection,
    PipelineConfig,
    PipelineFile,
    StackSupport,
)

from ..harness.container import IMAGE
from ..harness.steps import smoke_paths as client_smoke_paths
from . import render
from .candidate import (
    Resolution,
    Resolver,
    candidate_hash,
    fingerprint_path,
    image_tag,
    resolve,
)
from .layout import Detected, Undetectable, detect
from .validate import validate as validate_files

#: The one stack with validated templates, and the one layout they were written for.
SUPPORTED_STACK = "mern"
SUPPORTED_LAYOUT = "one-process"

#: Pinned by commit and checked against the release named beside it on 2026-09-27.
CHECKOUT = ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1")
SETUP_NODE = ("820762786026740c76f36085b0efc47a31fe5020", "v7.0.0")
VERCEL_CLI = "60.1.3"

#: Names the platform sets on every host, so they are never declared as secrets.
_PLATFORM_SET = frozenset({"PORT", "HOST", "NODE_ENV"})

_SECRET_USE = re.compile(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}")
_ENV_NAME = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)
_SMOKE_PATH = re.compile(r"^/[A-Za-z0-9._~/-]*$")
_SHELL = re.compile(r"[&|;<>$`\\\"']")

#: What the files are checked with: path to (purpose, text) in, verdicts by path out.
Validator = Callable[[dict[str, tuple[str, str]]], dict[str, list[FileValidation]]]


class PipelineSettings(BaseModel):
    """What the orchestrator knows that the files do not."""

    model_config = ConfigDict(extra="ignore")

    project_slug: str = Field(default="app", pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")
    backend_origin: str | None = Field(default=None, pattern=r"^https://[a-z0-9.-]+$")
    frontend_origin: str | None = Field(default=None, pattern=r"^https://[a-z0-9.-]+$")
    github_protection: GithubProtection | None = None
    kubernetes: bool = False


@dataclass(frozen=True)
class Generated:
    config: PipelineConfig
    #: Every file the candidate adds or replaces: the generated files, the
    #: lockfile and the manifests the updates changed.
    layer: dict[str, str]
    summary: str
    notes: dict[str, Any] = field(default_factory=dict)
    detected: Detected | None = None
    resolution: Resolution | None = None


def node_major(image: str = IMAGE) -> str:
    """The Node major the pinned image runs, for the workflows' setup step."""
    match = re.match(r"node:(\d+)", image)
    if not match:
        raise ValueError(f"the pinned image {image} names no Node major")
    return match.group(1)


def smoke_paths(files: dict[str, str], contract: ApiContract | None) -> list[str]:
    """The GET endpoints a smoke request can make without inventing an id.

    Read from the generated client's `implements` headers, as staging and the
    study read them, so the release checks what staging checked; from the
    contract only when the code declares none. Each is safe as a shell word.
    """
    paths = client_smoke_paths(files)
    if not paths and contract is not None:
        paths = sorted(
            {
                endpoint.path
                for endpoint in contract.endpoints
                if endpoint.method.upper() == "GET" and "{" not in endpoint.path
            }
        )
    return [path for path in paths if _SMOKE_PATH.match(path)]


def secret_names(files: dict[str, str], backend_dir: str) -> list[str]:
    """The names the backend's `.env.example` declares, less those every host sets itself."""
    example = files.get(f"{backend_dir}/.env.example", "")
    return sorted({name for name in _ENV_NAME.findall(example) if name not in _PLATFORM_SET})


def _unsupported(
    stack_id: str,
    reason: str,
    files: dict[str, str],
    *,
    version: int,
    code_version: int,
    now: datetime,
) -> Generated:
    config = PipelineConfig(
        version=version,
        generated_at=now,
        code_version=code_version,
        candidate_hash=candidate_hash(files, fingerprint=""),
        stack=StackSupport(stack_id=stack_id, supported=False, reason=reason),
        files=[],
        kubernetes="skipped",
        kubernetes_reason="the stack is unsupported, so nothing was generated",
    )
    return Generated(
        config=config,
        layer={},
        summary=f"{stack_id} is not supported: {reason}",
        notes={"supported": False},
    )


#: Each stack as a reader knows it; the ids are C2's catalogue keys.
_STACK_NAMES = {
    "mern": "the MERN stack (MongoDB, Express, React, Node)",
    "react-spring-postgres": "React with Spring Boot and PostgreSQL",
}


def _stack_name(stack_id: str) -> str:
    return _STACK_NAMES.get(stack_id, stack_id)


def generate(
    files: dict[str, str],
    updates: DependencyUpdates,
    *,
    stack_id: str,
    contract: ApiContract | None,
    included: list[str],
    settings: dict[str, Any],
    version: int,
    code_version: int,
    now: datetime | None = None,
    resolver: Resolver = resolve,
    validate: Validator = validate_files,
) -> Generated:
    now = now or datetime.now(UTC)
    chosen = PipelineSettings.model_validate(settings)
    if stack_id != SUPPORTED_STACK:
        return _unsupported(
            stack_id,
            f"validated templates exist for {_stack_name(SUPPORTED_STACK)} only; "
            f"{_stack_name(stack_id)} is reported rather than given a configuration "
            "nobody has validated",
            files,
            version=version,
            code_version=code_version,
            now=now,
        )
    try:
        detected = detect(files)
    except Undetectable as unreadable:
        return _unsupported(
            stack_id,
            f"the project's layout could not be read: {unreadable}",
            files,
            version=version,
            code_version=code_version,
            now=now,
        )
    layout, runtime = detected.layout, detected.runtime
    if layout.kind != SUPPORTED_LAYOUT or runtime is None or layout.frontend_dir is None:
        return _unsupported(
            stack_id,
            f"the templates are written for the {SUPPORTED_LAYOUT} layout, and this project is "
            f"{layout.kind}",
            files,
            version=version,
            code_version=code_version,
            now=now,
        )
    if runtime.port is None:
        return _unsupported(
            stack_id,
            f"{runtime.entry} does not read PORT, which Render sets for the process to listen on",
            files,
            version=version,
            code_version=code_version,
            now=now,
        )
    if _SHELL.search(runtime.start_script):
        return _unsupported(
            stack_id,
            f"the backend's start script {runtime.start_script!r} is shell, and the image runs "
            "one command",
            files,
            version=version,
            code_version=code_version,
            now=now,
        )

    wanted = {update.id for update in updates.updates if update.id in set(included)}
    resolution = resolver(files, [u for u in updates.updates if u.id in wanted])

    service = f"{chosen.project_slug}-api"
    backend_origin = chosen.backend_origin or f"https://{service}.onrender.com"
    frontend_origin = chosen.frontend_origin or f"https://{chosen.project_slug}.vercel.app"
    protection = chosen.github_protection
    secrets = secret_names(files, layout.backend_dir or "")
    smoke = smoke_paths(files, contract)
    env_block = (
        "    envVars:\n"
        + "".join(f"      - key: {name}\n        sync: false\n" for name in secrets)
        if secrets
        else ""
    )
    templates = [
        template
        for template in render.track(SUPPORTED_STACK)
        if template.id != "mern/release.json@1"
        and (chosen.kubernetes or template.purpose != "orchestration")
    ]
    values = {
        "node_image": IMAGE,
        "node_version": node_major(),
        "workspace_manifests": "\n".join(
            f"COPY {directory}/package.json {directory}/" for directory in detected.workspaces
        ),
        "backend_dir": layout.backend_dir or "",
        "frontend_dir": layout.frontend_dir,
        "frontend_output": detected.frontend_output or "",
        "port": str(runtime.port),
        "command": json.dumps(runtime.start_script.split()),
        "service_name": service,
        "health_path": "/release.json",
        "env_vars": env_block,
        "backend_origin": backend_origin,
        "frontend_origin": frontend_origin,
        "checkout_sha": CHECKOUT[0],
        "checkout_version": CHECKOUT[1],
        "setup_node_sha": SETUP_NODE[0],
        "setup_node_version": SETUP_NODE[1],
        "vercel_version": VERCEL_CLI,
        "fingerprint_path": fingerprint_path(layout.frontend_dir),
        "environment": "    environment: production\n" if protection == "configured" else "",
        "smoke_paths": " ".join(smoke),
    }
    if chosen.kubernetes:
        values["image"] = image_tag(chosen.project_slug, version)
    filled = {
        path: (template, text.rstrip("\n") + "\n")
        for path, (template, text) in render.fill_all(templates, values).items()
    }

    tree = {
        **files,
        **resolution.manifests,
        "package-lock.json": resolution.lockfile,
        **{path: text for path, (_, text) in filled.items()},
    }
    fingerprint = fingerprint_path(layout.frontend_dir)
    digest = candidate_hash(tree, fingerprint=fingerprint)
    lockfile_sha = hashlib.sha256(resolution.lockfile.encode("utf-8")).hexdigest()
    release = render.load("mern/release.json@1")
    path, text = render.fill(
        release,
        {
            "frontend_dir": layout.frontend_dir,
            "candidate_hash": digest,
            "deploy_version": str(version),
            "code_version": str(code_version),
            "lockfile_sha256": lockfile_sha,
        },
    )
    filled[path] = (release, text.rstrip("\n") + "\n")

    verdicts = validate(
        {path: (template.purpose, text) for path, (template, text) in filled.items()}
    )
    generated: list[PipelineFile] = []
    for path, (template, text) in filled.items():
        named = (
            secrets
            if template.id == "mern/render.yaml@1"
            else sorted(set(_SECRET_USE.findall(text)))
        )
        generated.append(
            PipelineFile(
                path=path,
                purpose=template.purpose,
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                bytes=len(text.encode("utf-8")),
                template_id=template.id,
                secrets_referenced=named,
                validations=verdicts.get(path, []),
            )
        )
    config = PipelineConfig(
        version=version,
        generated_at=now,
        code_version=code_version,
        candidate_hash=digest,
        stack=StackSupport(stack_id=stack_id, supported=True, layout=layout),
        files=generated,
        kubernetes="generated" if chosen.kubernetes else "skipped",
        kubernetes_reason=(
            ""
            if chosen.kubernetes
            else "optional, and not asked for: the release path is Vercel and Render"
        ),
    )
    layer = {
        **resolution.manifests,
        "package-lock.json": resolution.lockfile,
        **{path: text for path, (_, text) in filled.items()},
    }
    predicted = [
        name
        for name, given in (
            ("backend", chosen.backend_origin),
            ("frontend", chosen.frontend_origin),
        )
        if given is None
    ]
    valid_files = sum(1 for item in generated if item.valid)
    summary = (
        f"{len(generated)} files for the {layout.kind} MERN layout, {valid_files} valid on "
        f"first generation; {len(resolution.applied)} of {len(wanted)} included updates in the "
        "lockfile"
    )
    return Generated(
        config=config,
        layer=layer,
        summary=summary,
        notes={
            "supported": True,
            "image": image_tag(chosen.project_slug, version),
            "layout": layout.kind,
            "applied": resolution.applied,
            "refused": resolution.refused,
            "resolved_by": resolution.resolved_by,
            "backend_origin": backend_origin,
            "frontend_origin": frontend_origin,
            "origins_predicted": predicted,
            "github_protection": protection or "not given",
        },
        detected=detected,
        resolution=resolution,
    )
