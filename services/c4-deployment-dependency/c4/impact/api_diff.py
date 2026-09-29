"""Which symbols an update changes, read from the two releases themselves (B2).

The changelog says what its authors chose to write down, and about one break in
five is not written down anywhere (Venturini). So the usage signal also looks
for the symbols a deterministic comparison of the two releases finds, and every
symbol says which of the two told it.

**Maven: Roseau** (alien-tools/roseau, MIT, 0.7.0), which compares two
releases' bytecode and reports every binary or source breaking change by the
fully qualified symbol it touches. It runs from its release archive, checked
against the published sha256 and carrying its own Java runtime, with both
versions given as Maven coordinates, so it fetches them from Maven Central
itself. It is given the artifacts alone, without their dependencies, and it
warns where that leaves a type it cannot resolve; the verdicts it can reach are
still verdicts, and the reason line says what it ran on.

Every change Roseau reports is a breaking one. A deletion (a type, a field, a
method or constructor removed) is `removed`; everything else (a changed return
type, a method now final, a new abstract method an implementer must now write)
is `signature-changed`. A change is recorded against the type a client sees it
through: a method inherited from a superclass that lost it is a change to the
subclass, which is what client code names. Members are `Type#member`, and a
constructor is `Type#<init>`, which only `new Type(...)` reaches.

**npm: the type declarations**, for packages that ship them. Both releases'
tarballs are read, every exported function, class, interface, type, constant,
enum and namespace, and every member of an exported class or interface, is
collected with its declaration (`Client#connect`, and `Client#<init>` for a
constructor, as in Maven), and the two sets are compared. An export that
is gone is `removed`; one whose declaration reads differently, comments and
whitespace aside, is `signature-changed`. This is best effort and says so: a
renamed parameter reads as a changed signature, and a package whose types live
in `@types` has none of its own to compare, so its diff is unavailable and the
changelog is the only source of symbols.
"""

import asyncio
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from sdlc_contracts import ApiDiffState, ChangedSymbol, DependencyUpdate
from tree_sitter import Node

from ..intake import npm_registry
from ..intake.fetch import Fetcher
from .index import parser as parser_for

ROSEAU_VERSION = "0.7.0"
ROSEAU = f"roseau {ROSEAU_VERSION}"
#: The release archive, and its sha256 from the release's published checksums.
ROSEAU_ARCHIVE = f"roseau-{ROSEAU_VERSION}-linux-x86_64"
ROSEAU_URL = (
    f"https://github.com/alien-tools/roseau/releases/download/v{ROSEAU_VERSION}/"
    f"{ROSEAU_ARCHIVE}.zip"
)
ROSEAU_SHA256 = "119ea7bc75c936eb2648775b90ef75cbb71fe996d0c481971ae522aa5de5e522"
#: Where the launcher is, when it is not in the default tools directory.
ROSEAU_VARIABLE = "C4_ROSEAU"
ROSEAU_TIMEOUT_SECONDS = 900

DECLARATIONS = "declaration-diff/1"

#: Enough for any package's own declarations; a ceiling on what one diff reads.
MAX_DECLARATION_BYTES = 40_000_000


@dataclass(frozen=True)
class ApiDiff:
    state: ApiDiffState
    reason: str = ""
    symbols: tuple[ChangedSymbol, ...] = field(default_factory=tuple)


def tools_directory() -> Path:
    return Path.home() / ".cache" / "sdlc-c4" / "tools"


def roseau_launcher() -> Path | None:
    """The Roseau launcher, if it has been installed and checked, else None."""
    configured = os.environ.get(ROSEAU_VARIABLE, "").strip()
    candidate = (
        Path(configured) if configured else tools_directory() / ROSEAU_ARCHIVE / "bin" / "roseau"
    )
    return candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None


def _member(symbol: str) -> str:
    """The simple name of the member a Roseau symbol names: `checkKey` in `a.B.checkKey(x)`."""
    head = symbol.split("(", 1)[0]
    return head.rsplit(".", 1)[-1]


def _is_member(entry: dict) -> bool:
    kind = str(entry.get("kind", ""))
    symbol = str(entry.get("impactedSymbol", ""))
    if kind.startswith(("FIELD_", "EXECUTABLE_", "METHOD_")):
        return True
    return kind.startswith("FORMAL_TYPE_PARAMETER_") and "(" in symbol


def _breaking(entry: dict) -> str:
    binary, source = bool(entry.get("binaryBreaking")), bool(entry.get("sourceBreaking"))
    if binary and source:
        return "binary and source breaking"
    return "binary breaking" if binary else "source breaking"


def roseau_symbols(entries: list[dict], *, update_id: str) -> list[ChangedSymbol]:
    """A Roseau JSON report as changed symbols, one per type or member, first report kept."""
    found: dict[tuple[str, str], ChangedSymbol] = {}
    for entry in entries:
        impacted_type = str(entry.get("impactedType") or "").replace("$", ".")
        symbol = str(entry.get("impactedSymbol") or "")
        if not impacted_type or not symbol:
            continue
        member = _member(symbol) if _is_member(entry) else ""
        name = f"{impacted_type}#{member}" if member else impacted_type
        kind = "removed" if entry.get("nature") == "DELETION" else "signature-changed"
        if (name, kind) in found:
            continue
        found[(name, kind)] = ChangedSymbol(
            update_id=update_id,  # type: ignore[arg-type]
            symbol=name,
            kind=kind,
            source="api-diff",
            tool=ROSEAU,
            detail=f"{entry.get('kind')}, {_breaking(entry)}: {symbol}",
        )
    return list(found.values())


def _cached_report(cache_dir: Path | None, update: DependencyUpdate) -> Path | None:
    if cache_dir is None:
        return None
    key = hashlib.sha256(
        f"{ROSEAU}|{update.package}|{update.from_version}|{update.to_version}".encode()
    ).hexdigest()
    return cache_dir / "roseau" / f"{key}.json"


async def run_roseau(
    update: DependencyUpdate, launcher: Path, *, cache_dir: Path | None = None
) -> ApiDiff:
    """Roseau over the two releases, by their Maven coordinates.

    Two released versions never change, so neither does their diff: a report is
    kept by tool version, artifact and both versions, and a second assessment
    of the same update reads it instead of running Roseau again. The reason line
    says which it was, so a latency measured on a cached diff is never read as
    one measured cold.
    """
    kept = _cached_report(cache_dir, update)
    if kept is not None and kept.is_file():
        saved = json.loads(kept.read_text())
        symbols = roseau_symbols(saved["entries"], update_id=update.id)
        return ApiDiff(
            "ran", _roseau_reason(saved, symbols) + ", read from the cache", tuple(symbols)
        )
    with tempfile.TemporaryDirectory(prefix="c4-roseau-") as scratch:
        report = Path(scratch) / "report.json"
        process = await asyncio.create_subprocess_exec(
            str(launcher),
            "--diff",
            "--v1",
            f"{update.package}:{update.from_version}",
            "--v2",
            f"{update.package}:{update.to_version}",
            "--plain",
            "--report",
            f"JSON={report}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(
                process.communicate(), timeout=ROSEAU_TIMEOUT_SECONDS
            )
        except TimeoutError:
            process.kill()
            return ApiDiff("failed", f"{ROSEAU} did not finish in {ROSEAU_TIMEOUT_SECONDS}s")
        text = output.decode("utf-8", "replace")
        if process.returncode != 0 or not report.exists():
            tail = " | ".join(line for line in text.strip().splitlines()[-3:] if line)
            return ApiDiff("failed", f"{ROSEAU} exited {process.returncode}: {tail}")
        entries = json.loads(report.read_text())
    unresolved = sum(1 for line in text.splitlines() if "Failed to resolve type reference" in line)
    saved = {"entries": entries, "unresolved": unresolved}
    if kept is not None:
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_text(json.dumps(saved))
    symbols = roseau_symbols(entries, update_id=update.id)
    return ApiDiff("ran", _roseau_reason(saved, symbols), tuple(symbols))


def _roseau_reason(saved: dict, symbols: list[ChangedSymbol]) -> str:
    unresolved = saved.get("unresolved", 0)
    return (
        f"{ROSEAU} compared the two artifacts without their dependencies: "
        f"{len(saved['entries'])} breaking changes over {len(symbols)} symbols"
        + (f", {unresolved} type references it could not resolve" if unresolved else "")
    )


# npm: the declarations each release ships.

_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)

_CONTAINERS = {
    "class_declaration",
    "abstract_class_declaration",
    "interface_declaration",
    "enum_declaration",
    "internal_module",
    "module",
}


def _normalised(node: Node) -> str:
    text = (node.text or b"").decode("utf-8", "replace")
    return " ".join(_COMMENT.sub(" ", text).split())


def _header(node: Node) -> str:
    """A container's declaration without its body: its name, type parameters and heritage."""
    body = node.child_by_field_name("body")
    text = (node.text or b"").decode("utf-8", "replace")
    if body is not None:
        text = text[: body.start_byte - node.start_byte]
    return " ".join(_COMMENT.sub(" ", text).split())


def _name(node: Node) -> str:
    named = node.child_by_field_name("name")
    return (named.text or b"").decode() if named is not None else ""


def _unwrap(node: Node) -> list[Node]:
    """The declarations a statement holds, looking through `declare`."""
    if node.type == "ambient_declaration":
        return [child for child in node.named_children if child.type != "comment"]
    return [node]


def _declared(node: Node) -> list[tuple[str, Node]]:
    """(name, node) for one declaration; a variable statement can declare several."""
    if node.type in ("lexical_declaration", "variable_declaration"):
        return [
            (_name(child), child)
            for child in node.named_children
            if child.type == "variable_declarator" and _name(child)
        ]
    name = _name(node)
    return [(name, node)] if name else []


def _record(into: dict[str, list[str]], name: str, node: Node) -> None:
    if node.type in _CONTAINERS:
        into.setdefault(name, []).append(_header(node))
        body = node.child_by_field_name("body")
        for member in body.named_children if body is not None else []:
            member_name = _name(member)
            if member_name and member.type != "comment":
                if member_name == "constructor":
                    member_name = "<init>"
                into.setdefault(f"{name}#{member_name}", []).append(_normalised(member))
    else:
        into.setdefault(name, []).append(_normalised(node))


def declarations(files: dict[str, str]) -> dict[str, str]:
    """Every exported declaration across a package's `.d.ts` files, name to its text.

    Overloads are joined, so a changed overload reads as a changed signature.
    """
    parser = parser_for("typescript")
    exported: dict[str, list[str]] = {}
    for text in files.values():
        root = parser.parse(text.encode("utf-8")).root_node
        local: dict[str, list[Node]] = {}
        for statement in root.named_children:
            if statement.type == "export_statement":
                continue
            for node in _unwrap(statement):
                for name, declared in _declared(node):
                    local.setdefault(name, []).append(declared)
        for statement in root.named_children:
            if statement.type != "export_statement":
                continue
            declaration = statement.child_by_field_name("declaration")
            if declaration is None:
                declaration = next(
                    (c for c in statement.named_children if c.type == "ambient_declaration"),
                    None,
                )
            if declaration is not None:
                for node in _unwrap(declaration):
                    for name, declared in _declared(node):
                        _record(exported, name, declared)
                continue
            for clause in statement.named_children:
                if clause.type == "export_clause":
                    for spec in clause.named_children:
                        if spec.type != "export_specifier":
                            continue
                        source = _name(spec)
                        alias = spec.child_by_field_name("alias")
                        public = (alias.text or b"").decode() if alias is not None else source
                        for declared in local.get(source, []):
                            _record(exported, public, declared)
                elif clause.type == "identifier":
                    for declared in local.get((clause.text or b"").decode(), []):
                        _record(exported, "default", declared)
    return {name: " ;; ".join(sorted(texts)) for name, texts in exported.items()}


def declaration_changes(
    old: dict[str, str], new: dict[str, str], *, update_id: str
) -> list[ChangedSymbol]:
    """What an update removed or changed among a package's exported declarations."""
    changes: list[ChangedSymbol] = []
    for name in sorted(old):
        if name not in new:
            kind, detail = "removed", "exported by the installed release, not by the target"
        elif old[name] != new[name]:
            kind, detail = "signature-changed", f"was: {old[name][:160]}"
        else:
            continue
        changes.append(
            ChangedSymbol(
                update_id=update_id,  # type: ignore[arg-type]
                symbol=name,
                kind=kind,  # type: ignore[arg-type]
                source="api-diff",
                tool=DECLARATIONS,
                detail=detail,
            )
        )
    return changes


def _declaration_files(archive: bytes) -> dict[str, str] | None:
    """The `.d.ts` files inside an npm tarball, or None when it could not be read."""
    try:
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(archive)), mode="r:") as tar:
            found: dict[str, str] = {}
            total = 0
            for member in tar.getmembers():
                name = member.name.split("/", 1)[-1]
                if not member.isfile() or not name.endswith((".d.ts", ".d.mts", ".d.cts")):
                    continue
                if "node_modules/" in name:
                    continue
                total += member.size
                if total > MAX_DECLARATION_BYTES:
                    return None
                handle = tar.extractfile(member)
                if handle is not None:
                    found[name] = handle.read().decode("utf-8", "replace")
            return found
    except (OSError, tarfile.TarError, EOFError):
        return None


async def npm_diff(update: DependencyUpdate, fetcher: Fetcher) -> ApiDiff:
    """The declaration diff of an npm update, where both releases ship declarations."""
    package = await npm_registry.fetch(fetcher, update.package)
    if isinstance(package, npm_registry.NotFound):
        return ApiDiff("failed", package.detail)
    sides: list[dict[str, str]] = []
    for version in (update.from_version, update.to_version):
        tarball = package.tarballs.get(version)
        if not tarball:
            return ApiDiff("unavailable", f"the registry names no tarball for {version}")
        answer = await fetcher.get(tarball, registry="npm")
        if not answer.ok:
            return ApiDiff("failed", f"the tarball for {version} could not be fetched")
        files = _declaration_files(answer.body)
        if files is None:
            return ApiDiff("failed", f"the tarball for {version} could not be read, or is too big")
        sides.append(files)
    old, new = sides
    if not old or not new:
        which = "either release" if not old and not new else "one of the two releases"
        return ApiDiff(
            "unavailable",
            f"{update.package} ships no type declarations in {which}, so there is nothing "
            "to compare; the changelog is the only source of changed symbols",
        )
    before, after = declarations(old), declarations(new)
    symbols = declaration_changes(before, after, update_id=update.id)
    digest = hashlib.sha256(json.dumps([sorted(old), sorted(new)]).encode()).hexdigest()[:12]
    return ApiDiff(
        "ran",
        f"{DECLARATIONS} compared {len(before)} exported declarations with {len(after)} "
        f"(files {digest}): {len(symbols)} removed or changed",
        tuple(symbols),
    )


async def diff(
    update: DependencyUpdate,
    *,
    fetcher: Fetcher,
    launcher: Path | None = None,
    cache_dir: Path | None = None,
) -> ApiDiff:
    """The API diff for one update, by its ecosystem's tool."""
    if update.ecosystem == "maven":
        tool = launcher or roseau_launcher()
        if tool is None:
            return ApiDiff(
                "unavailable",
                f"{ROSEAU} is not installed: `python -m c4.impact.tools install` fetches it, "
                f"or {ROSEAU_VARIABLE} can name the launcher",
            )
        return await run_roseau(update, tool, cache_dir=cache_dir)
    return await npm_diff(update, fetcher)
