"""What a project says it depends on, read from its manifests.

Two ecosystems, read as each ecosystem reads itself. npm: every `package.json`
the root's `workspaces` names, plus the root, with the four dependency sections
kept apart. Maven: `pom.xml`, with `${property}` versions resolved from the
POM's own properties and the scope Maven would apply (compile when none is
given), plus the plugins a build runs.

**A workspace reference is not a registry dependency.** The generated monorepo
depends on its own `@app/contract` package with `"*"`, and asking the npm
registry about it would either fail or, worse, find an unrelated public package
of the same name. Such a dependency is read, marked, and later rejected with a
reason rather than analysed (FR3).

Line numbers are found in the raw text, because a JSON or XML parser discards
them and a reader who is told a dependency is risky wants to see where it is
declared.
"""

import json
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Literal

Ecosystem = Literal["npm", "maven"]

#: npm's dependency sections, and the scope each maps to.
NPM_SECTIONS = {
    "dependencies": "prod",
    "devDependencies": "dev",
    "peerDependencies": "peer",
    "optionalDependencies": "optional",
}

#: Ranges that point somewhere other than the registry.
_NOT_THE_REGISTRY = ("workspace:", "file:", "link:", "portal:", "git+", "git:", "github:")

#: Tags are read without a namespace: `_parse` strips it, so a POM that declares
#: the usual `http://maven.apache.org/POM/4.0.0` and one that declares none are
#: read the same way.
_POM = ""


def _parse(text: str) -> ElementTree.Element:
    root = ElementTree.fromstring(text)
    for element in root.iter():
        if isinstance(element.tag, str) and element.tag.startswith("{"):
            element.tag = element.tag.split("}", 1)[1]
    return root


@dataclass(frozen=True)
class Declared:
    """One dependency as a manifest declares it."""

    ecosystem: Ecosystem
    #: The npm name, or `groupId:artifactId`.
    package: str
    #: The range or version exactly as written.
    declared: str
    scope: str
    manifest_path: str
    line: int | None
    #: Why this is not something a registry can answer about, when it is not.
    not_registry: str = ""


def _line_of(text: str, needle: str, after: int = 0) -> int | None:
    """The one-based line a needle first appears on, at or after an offset."""
    found = text.find(needle, after)
    return text.count("\n", 0, found) + 1 if found >= 0 else None


def _npm_manifests(files: dict[str, str]) -> list[str]:
    """The root manifest and every workspace manifest it names, root first."""
    if "package.json" not in files:
        return sorted(path for path in files if path.endswith("package.json"))[:1]
    try:
        root = json.loads(files["package.json"])
    except json.JSONDecodeError:
        return ["package.json"]
    patterns = root.get("workspaces") or []
    if isinstance(patterns, dict):
        patterns = patterns.get("packages") or []
    members = sorted(
        path
        for path in files
        if path.endswith("/package.json")
        and "node_modules/" not in path
        and any(fnmatch(path.removesuffix("/package.json"), pattern) for pattern in patterns)
    )
    return ["package.json", *members]


def npm_dependencies(files: dict[str, str]) -> list[Declared]:
    manifests = _npm_manifests(files)
    parsed: dict[str, dict] = {}
    for path in manifests:
        try:
            parsed[path] = json.loads(files[path])
        except (json.JSONDecodeError, KeyError):
            continue
    workspace_names = {body.get("name") for body in parsed.values() if body.get("name")}

    found: list[Declared] = []
    for path, body in parsed.items():
        text = files[path]
        for section, scope in NPM_SECTIONS.items():
            entries = body.get(section) or {}
            section_at = text.find(f'"{section}"')
            for name, declared in entries.items():
                declared = str(declared)
                reason = ""
                if name in workspace_names:
                    reason = f"{name} is a package in this repository, not in the registry"
                elif declared.startswith(_NOT_THE_REGISTRY) or "://" in declared:
                    reason = (
                        f"{name} is declared as {declared!r}, which points outside the registry"
                    )
                elif declared.startswith("npm:"):
                    reason = f"{name} is an alias for another package, {declared!r}"
                found.append(
                    Declared(
                        ecosystem="npm",
                        package=name,
                        declared=declared,
                        scope=scope,
                        manifest_path=path,
                        line=_line_of(text, f'"{name}"', max(section_at, 0)),
                        not_registry=reason,
                    )
                )
    return found


def _text(element: ElementTree.Element | None, tag: str) -> str:
    child = element.find(f"{_POM}{tag}") if element is not None else None
    return (child.text or "").strip() if child is not None else ""


def _resolve(value: str, properties: dict[str, str]) -> str:
    """`${name}` replaced from the POM's properties, as Maven would."""

    def one(match: re.Match[str]) -> str:
        return properties.get(match.group(1), match.group(0))

    for _ in range(5):
        resolved = re.sub(r"\$\{([^}]+)\}", one, value)
        if resolved == value:
            break
        value = resolved
    return value


def _declared_in(
    container: ElementTree.Element | None,
    tag: str,
    default_scope: str,
    *,
    path: str,
    text: str,
    properties: dict[str, str],
) -> list[Declared]:
    """Every dependency or plugin under one POM element, versions resolved."""
    if container is None:
        return []
    found: list[Declared] = []
    for element in container.findall(f"{_POM}{tag}"):
        group = _text(element, "groupId") or ("org.apache.maven.plugins" if tag == "plugin" else "")
        artifact = _text(element, "artifactId")
        if not artifact:
            continue
        raw = _text(element, "version")
        version = _resolve(raw, properties)
        scope = default_scope if tag == "plugin" else (_text(element, "scope") or default_scope)
        reason = ""
        if not raw:
            reason = (
                f"{group}:{artifact} has no version here; it is managed by a parent or a "
                "bill of materials this analysis does not resolve"
            )
        elif "${" in version:
            reason = f"{group}:{artifact} uses {raw}, which this POM does not define"
        found.append(
            Declared(
                ecosystem="maven",
                package=f"{group}:{artifact}",
                declared=version or raw,
                scope=scope,
                manifest_path=path,
                line=_line_of(text, f"<artifactId>{artifact}</artifactId>"),
                not_registry=reason,
            )
        )
    return found


def maven_dependencies(files: dict[str, str]) -> list[Declared]:
    found: list[Declared] = []
    for path in sorted(p for p in files if p == "pom.xml" or p.endswith("/pom.xml")):
        text = files[path]
        try:
            root = _parse(text)
        except ElementTree.ParseError:
            continue
        # Explicit None checks throughout: an element with no children is falsy,
        # and testing one's truth is deprecated, which this suite treats as an error.
        holder = root.find(f"{_POM}properties")
        properties = {
            child.tag.removeprefix(_POM): (child.text or "").strip()
            for child in (list(holder) if holder is not None else [])
        }
        project_version = _text(root, "version") or _text(root.find(f"{_POM}parent"), "version")
        properties.update({"project.version": project_version, "version": project_version})
        where = {"path": path, "text": text, "properties": properties}

        found += _declared_in(root.find(f"{_POM}dependencies"), "dependency", "compile", **where)
        management = root.find(f"{_POM}dependencyManagement")
        managed = management.find(f"{_POM}dependencies") if management is not None else None
        if managed is not None:
            imports = ElementTree.Element("imports")
            for dependency in list(managed):
                if _text(dependency, "scope") == "import":
                    imports.append(dependency)
            found += _declared_in(imports, "dependency", "import", **where)
        build = root.find(f"{_POM}build")
        plugins = build.find(f"{_POM}plugins") if build is not None else None
        found += _declared_in(plugins, "plugin", "plugin", **where)
    return found


def declared_dependencies(files: dict[str, str]) -> list[Declared]:
    """Everything the project's manifests declare, npm first, in manifest order."""
    return npm_dependencies(files) + maven_dependencies(files)
