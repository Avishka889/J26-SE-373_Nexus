"""The architectural layout a pipeline is chosen by, read from the project's own files.

Generating a Dockerfile or a workflow is not novel. Choosing them by how the
project is actually laid out is the one increment claimed for this pillar:
which workspace is the frontend, which is the backend, what they share, and
whether the backend serves the built frontend itself (one process) or the two
find each other by address (split). Nothing is assumed from the stack's name:
each fact that decided the layout is read from a manifest, a script or the
backend's entry file, and recorded as evidence a reader can check.

**What is read.**

- **Workspaces**: the root manifest's `workspaces` globs, matched against the
  directories that hold a `package.json`.
- **The frontend**: a workspace that builds with `vite build`. Its output is
  Vite's default `dist` unless its config names another `outDir`.
- **The backend**: a workspace that depends on `express` and has a `start`
  script. The entry file is the script's first file argument to `node`, and the
  flags before it say what the runtime must support: `--experimental-strip-types`
  runs TypeScript directly, which needs Node 22.6 or later.
- **One process or split**: whether the entry file passes the frontend's
  output directory to `express.static`, resolved from the entry's own
  directory. The port is the entry's `process.env.PORT` default.

A layout that cannot be read says why, and the stack is then unsupported with
that reason (FR14), rather than given a pipeline built on a guess.
"""

import json
import posixpath
import re
from dataclasses import dataclass, field
from fnmatch import fnmatch

from sdlc_contracts import ArchitecturalLayout

#: The Node version that first ran TypeScript with `--experimental-strip-types`.
STRIP_TYPES_NODE = "22.6"

_STATIC = re.compile(r"express\.static\(")
_DIST_PATH = re.compile(
    r"path\.(?:resolve|join)\(\s*(?:import\.meta\.dirname|__dirname)\s*,\s*[\"']([^\"']+)[\"']\s*\)"
)
_PORT = re.compile(r"process\.env\.PORT\s*(?:\?\?|\|\|)\s*(\d{2,5})")
_OUT_DIR = re.compile(r"outDir\s*:\s*[\"']([^\"']+)[\"']")
_VITE_CONFIGS = ("vite.config.ts", "vite.config.mts", "vite.config.js", "vite.config.mjs")


@dataclass(frozen=True)
class Runtime:
    """What the backend needs to run, read from its start script and entry file."""

    entry: str
    start_script: str
    node_minimum: str | None
    port: int | None


@dataclass(frozen=True)
class Detected:
    layout: ArchitecturalLayout
    runtime: Runtime | None
    #: The frontend's build output, relative to the project root.
    frontend_output: str | None
    workspaces: list[str] = field(default_factory=list)


class Undetectable(ValueError):
    """The files do not say enough to name a layout, and this is why."""


def _manifest(files: dict[str, str], path: str) -> dict:
    try:
        body = json.loads(files[path])
    except (KeyError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def workspaces(files: dict[str, str]) -> list[str]:
    """Every workspace directory the root manifest's globs match, in path order."""
    declared = _manifest(files, "package.json").get("workspaces") or []
    if isinstance(declared, dict):  # the older `{"packages": [...]}` form
        declared = declared.get("packages") or []
    directories = sorted(
        path.removesuffix("/package.json")
        for path in files
        if path.endswith("/package.json") and "node_modules/" not in path
    )
    return [d for d in directories if any(fnmatch(d, str(glob)) for glob in declared)]


def _dependencies(manifest: dict) -> set[str]:
    return set(manifest.get("dependencies") or {}) | set(manifest.get("devDependencies") or {})


def _frontend_output(files: dict[str, str], directory: str) -> tuple[str, str]:
    """The frontend's build output, and the sentence saying how it was found."""
    for name in _VITE_CONFIGS:
        config = files.get(f"{directory}/{name}")
        if config is None:
            continue
        named = _OUT_DIR.search(config)
        if named:
            output = posixpath.normpath(posixpath.join(directory, named.group(1)))
            return output, f"{directory}/{name} sets the build output to {named.group(1)}"
        return f"{directory}/dist", f"{directory}/{name} keeps Vite's default output, dist"
    return f"{directory}/dist", f"{directory} has no Vite config, so the output is Vite's dist"


def _entry(start: str) -> tuple[str | None, list[str]]:
    """The file a `node` start script runs, and the flags it runs it with."""
    words = start.split()
    if not words or words[0] != "node":
        return None, []
    flags = [word for word in words[1:] if word.startswith("--")]
    files = [word for word in words[1:] if not word.startswith("-")]
    return (files[0] if files else None), flags


def detect(files: dict[str, str]) -> Detected:
    """The layout, with the evidence for it, or `Undetectable` saying what is missing."""
    if "package.json" not in files:
        raise Undetectable("there is no package.json at the root, so this is not an npm project")
    found = workspaces(files)
    if not found:
        raise Undetectable("the root package.json declares no workspaces that exist")
    evidence = [f"package.json declares the workspaces {', '.join(found)}"]

    frontends: list[str] = []
    backends: list[tuple[str, str]] = []
    for directory in found:
        manifest = _manifest(files, f"{directory}/package.json")
        scripts = manifest.get("scripts") or {}
        uses = _dependencies(manifest)
        if "vite" in uses and "vite build" in str(scripts.get("build", "")):
            frontends.append(directory)
        if "express" in (manifest.get("dependencies") or {}) and scripts.get("start"):
            backends.append((directory, str(scripts["start"])))
    if len(frontends) > 1 or len(backends) > 1:
        raise Undetectable(
            f"more than one frontend ({', '.join(frontends)}) or backend "
            f"({', '.join(b for b, _ in backends)}) workspace, which no template here separates"
        )
    frontend = frontends[0] if frontends else None
    backend, start = backends[0] if backends else (None, "")
    shared = [d for d in found if d not in (frontend, backend)]

    output = None
    if frontend:
        output, how = _frontend_output(files, frontend)
        evidence.append(f"{frontend}/package.json builds the frontend with vite build")
        evidence.append(how)

    runtime = None
    serves = False
    if backend:
        entry_file, flags = _entry(start)
        if entry_file is None:
            raise Undetectable(
                f"{backend}/package.json starts with {start!r}, which names no file for node to run"
            )
        entry = posixpath.normpath(posixpath.join(backend, entry_file))
        source = files.get(entry)
        if source is None:
            raise Undetectable(
                f"the backend's start script runs {entry}, which is not in the project"
            )
        evidence.append(f"{backend}/package.json depends on express and starts with {start!r}")
        minimum = None
        if "--experimental-strip-types" in flags:
            minimum = STRIP_TYPES_NODE
            evidence.append(
                "the backend runs TypeScript with node --experimental-strip-types, "
                f"which needs Node {STRIP_TYPES_NODE} or later"
            )
        port_match = _PORT.search(source)
        port = int(port_match.group(1)) if port_match else None
        if port is not None:
            evidence.append(f"{entry} listens on PORT, {port} when it is unset")
        if output and _STATIC.search(source):
            for match in _DIST_PATH.finditer(source):
                served = posixpath.normpath(
                    posixpath.join(posixpath.dirname(entry), match.group(1))
                )
                if served == output:
                    serves = True
                    evidence.append(
                        f"{entry} serves {output} with express.static, so one process "
                        "answers both the API and the pages"
                    )
                    break
        runtime = Runtime(entry=entry, start_script=start, node_minimum=minimum, port=port)

    if frontend and backend:
        kind = "one-process" if serves else "split"
    elif backend:
        kind = "backend-only"
    elif frontend:
        kind = "frontend-only"
    else:
        raise Undetectable("no workspace builds a Vite frontend or starts an Express backend")
    for directory in shared:
        evidence.append(f"{directory} is shared: neither built as the frontend nor started")

    return Detected(
        layout=ArchitecturalLayout(
            kind=kind,
            frontend_dir=frontend,
            backend_dir=backend,
            shared_dirs=shared,
            serves_frontend_from_backend=serves,
            evidence=evidence,
        ),
        runtime=runtime,
        frontend_output=output,
        workspaces=found,
    )
