"""Every generated file checked on its first generation (NFR5), and never repaired.

Each file gets every check that applies to it, and each check's verdict is kept
on the file: `valid` is computed from them in the contract, and a check that
could not run leaves the file unverified rather than valid.

| Purpose | Checks |
|---|---|
| workflow | YAML parse, SchemaStore's GitHub workflow schema, actionlint (with shellcheck) |
| container | hadolint, at its default threshold |
| hosting | YAML or JSON parse and Render's or Vercel's own schema |
| fingerprint | the fingerprint's own schema |
| orchestration | YAML parse, kubeconform (strict) against Kubernetes 1.37.1's schemas |
| every file | the secret scan (NFR8) |

**The schemas are kept here** (`schemas/`, with `SOURCES.md` saying where each
came from, when and at what hash), so a verdict never depends on a network or on
a schema that has changed since. **The linters are images pinned by digest**,
run with no network and the file mounted read only; kubeconform reads the kept
schemas, so it cannot quietly fetch others. Without a Docker daemon each linter
is recorded as not run, with the reason.

**YAML is read as the hosts read it.** PyYAML reads YAML 1.1, where `on`, `off`,
`yes` and `no` are booleans; GitHub, Render and Kubernetes read YAML 1.2, where
only `true` and `false` are. A workflow's `on:` key would otherwise fail its
schema as the boolean `true`. A key written twice in one mapping is refused,
where PyYAML would keep the second silently.

**The secret scan** looks for the credentials this platform handles and the
shapes secrets are commonly pasted in: GitHub, Render and AWS keys, a Render
deploy hook with its key, a private key, a URL with a password in it, a JSON web
token, and a value assigned to a name that says it is a secret. A reference
through the host's secret store (`${{ secrets.NAME }}`, `sync: false`) is not a
value. A finding names the rule and the line, never the text it matched, so the
record of a leak does not repeat it.
"""

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import jsonschema
import yaml
from sdlc_contracts import FileValidation

from ..harness.container import docker_unavailable

SCHEMAS = Path(__file__).resolve().parent / "schemas"
RETRIEVED = "2026-09-27"

_JSONSCHEMA = f"jsonschema {version('jsonschema')}"
_PYYAML = f"PyYAML {version('PyYAML')}, read as YAML 1.2"

ACTIONLINT = "rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667"
HADOLINT = "hadolint/hadolint:v2.15.1@sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d"
KUBECONFORM = (
    "ghcr.io/yannh/kubeconform:v0.8.0"
    "@sha256:faffaf43f95aa6425306e1ab8d6fcad72acb9049158f38e574c085ea1ec0f64e"
)
KUBERNETES = "1.37.1"
TOOL_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class Schema:
    file: str
    url: str
    name: str


WORKFLOW = Schema(
    "github-workflow.json", "https://www.schemastore.org/github-workflow.json", "GitHub workflow"
)
RENDER = Schema(
    "render.yaml.json", "https://render.com/schema/render.yaml.json", "Render Blueprint"
)
VERCEL = Schema("vercel.json", "https://openapi.vercel.sh/vercel.json", "Vercel project")
RELEASE = Schema("release.json.schema.json", "", "release.json fingerprint")


class _Yaml12(yaml.SafeLoader):
    """YAML as the hosts read it: only true and false are booleans, and no key twice."""


_Yaml12.yaml_implicit_resolvers = {
    first: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Yaml12.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _mapping(loader: _Yaml12, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set[object] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"the key {key!r} is written twice", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_Yaml12.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def parse_yaml(text: str) -> object:
    return yaml.load(text, Loader=_Yaml12)


#: Rule name, then the pattern. A match is reported by rule and line only.
SECRET_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b")),
    ("a GitHub fine grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("a Render API key", re.compile(r"\brnd_[A-Za-z0-9]{20,}\b")),
    (
        "a Render deploy hook with its key",
        re.compile(r"api\.render\.com/deploy/srv-[A-Za-z0-9]+\?key=[A-Za-z0-9_-]+"),
    ),
    ("an AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a URL with a password in it", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@$]+@")),
    (
        "a JSON web token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ),
    (
        "a value assigned to a name that says it is a secret",
        re.compile(
            r"(?i)[A-Za-z0-9_]*(?:password|passwd|secret|token|api_?key|access_?key)[\"']?\s*[:=]\s*"
            r"[\"']?(?!\$\{\{)[A-Za-z0-9/+_\-]{12,}"
        ),
    ),
)


def secret_scan(text: str) -> FileValidation:
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in SECRET_RULES:
            if pattern.search(line):
                findings.append(f"line {number}: {rule}")
    return FileValidation(
        validator="secret-scan",
        tool=f"c4 secret scan, {len(SECRET_RULES)} rules",
        outcome="failed" if findings else "passed",
        findings=findings,
    )


def _yaml_check(text: str) -> tuple[FileValidation, object | None]:
    try:
        body = parse_yaml(text)
    except yaml.YAMLError as error:
        return (
            FileValidation(
                validator="yaml-parse",
                tool=_PYYAML,
                outcome="failed",
                findings=[str(error).replace("\n", " ")[:300]],
            ),
            None,
        )
    return (
        FileValidation(
            validator="yaml-parse",
            tool=_PYYAML,
            outcome="passed",
        ),
        body,
    )


def _closest(error: jsonschema.ValidationError) -> list[jsonschema.ValidationError]:
    """The errors that say what is wrong, not that nothing matched.

    A schema with alternatives (Render's services are a `oneOf` over service
    types) reports only that no alternative matched, with the whole value as the
    message. Its context holds each alternative's own errors; the alternative
    with the fewest is the one the value nearly is, and its errors name the field.
    """
    if error.validator not in ("oneOf", "anyOf") or not error.context:
        return [error]
    branches: dict[object, list[jsonschema.ValidationError]] = {}
    for sub in error.context:
        branches.setdefault(sub.relative_schema_path[0], []).append(sub)
    nearest = min(branches.values(), key=len)
    return [found for sub in nearest for found in _closest(sub)]


def schema_check(body: object, schema: Schema) -> FileValidation:
    document = json.loads((SCHEMAS / schema.file).read_text(encoding="utf-8"))
    checker = jsonschema.validators.validator_for(document)(document)
    errors = sorted(
        (found for error in checker.iter_errors(body) for found in _closest(error)),
        key=lambda error: list(error.absolute_path),
    )
    return FileValidation(
        validator="json-schema",
        tool=f"{_JSONSCHEMA}, {schema.name} schema",
        schema_url=schema.url,
        schema_retrieved=RETRIEVED if schema.url else "",
        outcome="failed" if errors else "passed",
        findings=[
            f"{'/'.join(str(part) for part in error.absolute_path) or '(root)'}: "
            f"{error.message[:200]}"
            for error in errors[:20]
        ],
    )


def _json_check(text: str, schema: Schema) -> FileValidation:
    try:
        body = json.loads(text)
    except json.JSONDecodeError as error:
        return FileValidation(
            validator="json-schema",
            tool=f"{_JSONSCHEMA}, {schema.name} schema",
            schema_url=schema.url,
            outcome="failed",
            findings=[f"not JSON: {error}"],
        )
    return schema_check(body, schema)


def _not_run(validator: str, tool: str, reason: str) -> FileValidation:
    return FileValidation(validator=validator, tool=tool, outcome="not-run", reason=reason)  # type: ignore[arg-type]


def _docker(
    image: str,
    args: list[str],
    *,
    mounts: dict[Path, str],
    stdin: str | None = None,
    workdir: str | None = None,
):
    volumes = [part for host, inside in mounts.items() for part in ("-v", f"{host}:{inside}:ro")]
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            *(["-i"] if stdin else []),
            *(["-w", workdir] if workdir else []),
            *volumes,
            image,
            *args,
        ],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT_SECONDS,
        check=False,
    )


def _actionlint(workflows: dict[str, str], scratch: Path) -> dict[str, FileValidation]:
    tool = "actionlint 1.7.12, with shellcheck"
    for path, text in workflows.items():
        target = scratch / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    done = _docker(
        ACTIONLINT,
        ["-format", "{{json .}}", *sorted(workflows)],
        mounts={scratch: "/repo"},
        workdir="/repo",
    )
    if done.returncode not in (0, 1):
        reason = (
            f"actionlint exited {done.returncode}: {(done.stderr or done.stdout).strip()[:200]}"
        )
        return {path: _not_run("actionlint", tool, reason) for path in workflows}
    findings: dict[str, list[str]] = {path: [] for path in workflows}
    for error in json.loads(done.stdout or "[]"):
        path = str(error.get("filepath", "")).removeprefix("./")
        findings.setdefault(path, []).append(
            f"line {error.get('line')}: {error.get('message')} [{error.get('kind')}]"
        )
    return {
        path: FileValidation(
            validator="actionlint",
            tool=tool,
            outcome="failed" if findings[path] else "passed",
            findings=findings[path],
        )
        for path in workflows
    }


def _hadolint(text: str) -> FileValidation:
    tool = "hadolint 2.15.1, default threshold"
    done = _docker(HADOLINT, ["hadolint", "--format", "json", "-"], mounts={}, stdin=text)
    try:
        found = json.loads(done.stdout or "[]")
    except json.JSONDecodeError:
        return _not_run(
            "hadolint", tool, f"hadolint answered no report: {(done.stderr or '').strip()[:200]}"
        )
    return FileValidation(
        validator="hadolint",
        tool=tool,
        outcome="failed" if found else "passed",
        findings=[
            f"line {item.get('line')}: {item.get('code')} ({item.get('level')}) {item.get('message')}"
            for item in found
        ],
    )


def _kubeconform(manifests: dict[str, str], scratch: Path) -> dict[str, FileValidation]:
    tool = f"kubeconform 0.8.0, strict, Kubernetes {KUBERNETES} schemas"
    for path, text in manifests.items():
        target = scratch / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    done = _docker(
        KUBECONFORM,
        [
            "-strict",
            "-verbose",
            "-output",
            "json",
            "-kubernetes-version",
            KUBERNETES,
            "-schema-location",
            "/schemas/{{ .NormalizedKubernetesVersion }}-standalone{{ .StrictSuffix }}/"
            "{{ .ResourceKind }}{{ .KindSuffix }}.json",
            *(f"/work/{path}" for path in sorted(manifests)),
        ],
        mounts={scratch: "/work", SCHEMAS / "kubernetes": "/schemas"},
    )
    try:
        report = json.loads(done.stdout or "{}")
    except json.JSONDecodeError:
        reason = f"kubeconform answered no report: {(done.stderr or '').strip()[:200]}"
        return {path: _not_run("kubeconform", tool, reason) for path in manifests}
    # Verbose, so every resource is listed: a file passes only when kubeconform
    # names a valid resource in it and nothing else, never because it was silent.
    findings: dict[str, list[str]] = {path: [] for path in manifests}
    valid: set[str] = set()
    for resource in report.get("resources") or []:
        path = str(resource.get("filename", "")).removeprefix("/work/")
        if resource.get("status") == "statusValid":
            valid.add(path)
        else:
            findings.setdefault(path, []).append(
                f"{resource.get('kind')} {resource.get('name')}: {resource.get('status')}, "
                f"{str(resource.get('msg'))[:300]}"
            )
    for path in manifests:
        if path not in valid and not findings[path]:
            findings[path].append(f"kubeconform named no resource in it (exit {done.returncode})")
    return {
        path: FileValidation(
            validator="kubeconform",
            tool=tool,
            outcome="failed" if findings[path] else "passed",
            findings=findings[path],
        )
        for path in manifests
    }


def validate(
    generated: dict[str, tuple[str, str]], *, docker_reason: str | bool | None = True
) -> dict[str, list[FileValidation]]:
    """Every check that applies, on every file, by path. `generated` is path to
    (purpose, text). `docker_reason` is why Docker cannot run, `None` when it can,
    or `True` to ask the machine."""
    reason = docker_unavailable() if docker_reason is True else docker_reason
    verdicts: dict[str, list[FileValidation]] = {path: [] for path in generated}

    for path, (purpose, text) in generated.items():
        if purpose in ("workflow", "orchestration") or path.endswith((".yaml", ".yml")):
            check, body = _yaml_check(text)
            verdicts[path].append(check)
            if body is not None and purpose == "workflow":
                verdicts[path].append(schema_check(body, WORKFLOW))
            elif body is not None and path.endswith("render.yaml"):
                verdicts[path].append(schema_check(body, RENDER))
        elif path.endswith("vercel.json"):
            verdicts[path].append(_json_check(text, VERCEL))
        elif purpose == "fingerprint":
            verdicts[path].append(_json_check(text, RELEASE))

    workflows = {p: t for p, (purpose, t) in generated.items() if purpose == "workflow"}
    dockerfiles = {p: t for p, (purpose, t) in generated.items() if purpose == "container"}
    manifests = {p: t for p, (purpose, t) in generated.items() if purpose == "orchestration"}
    if reason:
        why = f"no Docker daemon to run it in: {reason}"
        for path in workflows:
            verdicts[path].append(_not_run("actionlint", "actionlint 1.7.12", why))
        for path in dockerfiles:
            verdicts[path].append(_not_run("hadolint", "hadolint 2.15.1", why))
        for path in manifests:
            verdicts[path].append(_not_run("kubeconform", "kubeconform 0.8.0", why))
    else:
        with tempfile.TemporaryDirectory(prefix="c4-validate-") as scratch:
            root = Path(scratch)
            if workflows:
                for path, verdict in _actionlint(workflows, root / "actionlint").items():
                    verdicts[path].append(verdict)
            for path, text in dockerfiles.items():
                verdicts[path].append(_hadolint(text))
            if manifests:
                for path, verdict in _kubeconform(manifests, root / "kubeconform").items():
                    verdicts[path].append(verdict)

    for path, (_, text) in generated.items():
        verdicts[path].append(secret_scan(text))
    return verdicts
