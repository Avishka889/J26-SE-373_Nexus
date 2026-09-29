"""Where the project uses what an update changed, each place read back before it counts (FR9).

The search runs over the one index the run built, file by file, and only in the
files that bring the package in. A changed symbol is looked for the ways code
can reach it:

**npm.** A top level export `N` is used where a file imports `N` by name (an
`import` match on the import itself), names the local it bound `N` to (an
`identifier` match), or reaches `N` through a default or namespace binding of
the package, as `express.json` reaches `json` (a `member` match). A member
`Owner#m`, or `owner.m` as a release note writes it, is used where a file that
imports the package reaches a member called `m`, whatever the receiver is
called, because an instance is rarely named after its class
(`const server = express()`). A constructor `Owner#<init>` is used only by
`new Owner(...)`. `@types/react` is imported as `react`.

**Java.** Only files inside a module whose POM declares the updated artifact
are searched (`maven_scope`), because one class name can come from more than
one artifact or version. A file sees a changed type through a single type
import of it or of the type it is nested in, or a wildcard import of its package.
Java declares its types, so a member is not counted when its receiver is a
field, local or parameter the file declares as another class
(`DubboAdapter adapter; adapter.getInvocation()` is not a use of
`AsyncRpcResult#getInvocation`); a receiver the file does not declare, such as
a call's result, still counts, which keeps the search on the side of recall. A type is used
by that import and by its simple name; a member `Type#m` by a static import of
it or by reaching `m` in a file that sees the type; a constructor only by
`new Type(...)`.

**Every candidate is read back.** Its lines are read from the file as it is now
and must still hold what the index saw there, or it is refused with the reason
and counted: a file that is gone, lines past its end, or lines that say
something else. An index and a file that disagree are not evidence.

These are name matches, not type resolution, and are recorded as such: the
`match` kind on each reference says which rule found it, so a reader can weigh
an import of a removed type differently from a method of the same name.
"""

from collections import defaultdict
from dataclasses import dataclass

from sdlc_contracts import (
    ChangedSymbol,
    DependencyUpdate,
    EvidenceSpan,
    MatchKind,
    RefusedReference,
    UsageReference,
)

from ..intake.manifests import maven_dependencies
from .index import CONSTRUCTOR, FileIndex, Import, Reference, SymbolIndex

#: How many lines of a span are kept as its snippet.
SNIPPET_LINES = 5
SNIPPET_CHARS = 400


@dataclass(frozen=True)
class Target:
    """A changed symbol as code reaches it: what it hangs off, and the name reached.

    For npm the owner is "" for a top level export; for Java it is the type's
    fully qualified name, or its simple name when a release note wrote only that.
    `name` is "" for a Java type itself.
    """

    owner: str
    name: str


@dataclass(frozen=True)
class Candidate:
    symbol: ChangedSymbol
    match: MatchKind
    path: str
    line: int
    end_line: int
    #: What must still be on those lines when they are read back.
    expect: str


def importable(update: DependencyUpdate) -> set[str]:
    """The package names an update's code is imported under."""
    names = {update.package}
    if update.ecosystem == "npm" and update.package.startswith("@types/"):
        rest = update.package.removeprefix("@types/")
        names.add("@" + rest.replace("__", "/", 1) if "__" in rest else rest)
    return names


def target(symbol: ChangedSymbol, ecosystem: str) -> Target:
    text = symbol.symbol.strip().split("(", 1)[0].strip()
    if "#" in text:
        owner, name = text.rsplit("#", 1)
        return Target(owner, name)
    if ecosystem == "maven":
        head, _, last = text.rpartition(".")
        if head and last[:1].islower() and head.rsplit(".", 1)[-1][:1].isupper():
            return Target(head, last)
        return Target(text, "")
    if "." in text:
        owner, name = text.rsplit(".", 1)
        return Target(owner, name)
    return Target("", text)


def _simple(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _npm_candidates(
    item: FileIndex, mine: list[Import], symbols: list[ChangedSymbol], by_name
) -> list[Candidate]:
    bound: dict[str, set[str]] = defaultdict(set)
    carriers: set[str] = set()
    for imported in mine:
        if imported.imported in ("*", "default") and imported.local:
            carriers.add(imported.local)
        elif imported.local:
            bound[imported.imported].add(imported.local)
    found: list[Candidate] = []
    for symbol in symbols:
        aim = target(symbol, "npm")
        if not aim.owner:
            for imported in mine:
                if imported.imported == aim.name:
                    found.append(
                        Candidate(
                            symbol, "import", item.path, imported.line, imported.end_line, aim.name
                        )
                    )
            for local in bound.get(aim.name, ()):
                for reference in by_name.get(local, ()):
                    if reference.kind == "identifier":
                        found.append(_at(symbol, "identifier", reference, local))
            for reference in by_name.get(aim.name, ()):
                if reference.kind == "member" and reference.head in carriers:
                    found.append(_at(symbol, "member", reference, aim.name))
        elif aim.name == CONSTRUCTOR:
            classes = {_simple(aim.owner)} | bound.get(_simple(aim.owner), set())
            for reference in by_name.get(CONSTRUCTOR, ()):
                if reference.head in classes:
                    found.append(_at(symbol, "member", reference, reference.head))
        else:
            for reference in by_name.get(aim.name, ()):
                if reference.kind == "member":
                    found.append(_at(symbol, "member", reference, aim.name))
    return found


def _sees(imports: list[Import], type_name: str) -> list[Import]:
    """The imports through which a Java file sees a type, by name or by its package."""
    package = type_name.rsplit(".", 1)[0] if "." in type_name else ""

    def through(imported: Import) -> bool:
        if imported.kind == "java":
            # The type itself, or the type it is nested in.
            return imported.package == type_name or type_name.startswith(imported.package + ".")
        return imported.kind == "java-wildcard" and imported.package == package

    return [imported for imported in imports if through(imported)]


def _java_candidates(item: FileIndex, symbols: list[ChangedSymbol], by_name) -> list[Candidate]:
    found: list[Candidate] = []
    for symbol in symbols:
        aim = target(symbol, "maven")
        simple = _simple(aim.owner)
        if "." in aim.owner:
            seen = _sees(item.imports, aim.owner)
            if not seen and not (aim.name and _static(item.imports, aim)):
                continue
        else:
            # A release note names the type by its simple name alone.
            seen = [i for i in item.imports if i.kind == "java" and _simple(i.package) == simple]
            if not seen:
                continue
        if not aim.name:
            for imported in seen:
                if _imports_the_type(imported, aim):
                    found.append(
                        Candidate(
                            symbol, "import", item.path, imported.line, imported.end_line, simple
                        )
                    )
            for reference in by_name.get(simple, ()):
                if reference.kind == "identifier":
                    found.append(_at(symbol, "identifier", reference, simple))
        elif aim.name == CONSTRUCTOR:
            for reference in by_name.get(CONSTRUCTOR, ()):
                if reference.head == simple:
                    found.append(_at(symbol, "member", reference, simple))
        else:
            for imported in _static(item.imports, aim):
                found.append(
                    Candidate(
                        symbol, "import", item.path, imported.line, imported.end_line, aim.name
                    )
                )
            if seen:
                for reference in by_name.get(aim.name, ()):
                    if reference.kind != "member":
                        continue
                    declared = item.types.get(reference.head)
                    if declared is not None and declared != simple:
                        # Its receiver is declared, in this file, as another class.
                        continue
                    found.append(_at(symbol, "member", reference, aim.name))
    return found


def _imports_the_type(imported: Import, aim: Target) -> bool:
    """A single type import of exactly this type: by its full name, or by its simple
    name when a release note gave only that."""
    if imported.kind != "java":
        return False
    if "." in aim.owner:
        return imported.package == aim.owner
    return _simple(imported.package) == aim.owner


def _static(imports: list[Import], aim: Target) -> list[Import]:
    return [
        imported
        for imported in imports
        if imported.kind == "java-static" and imported.package == f"{aim.owner}.{aim.name}"
    ]


def _at(symbol: ChangedSymbol, match: MatchKind, reference: Reference, expect: str) -> Candidate:
    return Candidate(symbol, match, reference.path, reference.line, reference.end_line, expect)


def maven_scope(files: dict[str, str], update: DependencyUpdate) -> tuple[str, ...]:
    """The modules whose POM declares the updated artifact at this update's versions.

    A Java import names a class, and one class name can come from more than one
    artifact or version: dubbo 2.7 ships the `com.alibaba.dubbo` classes that
    dubbo 2.5 is, and a project can hold a module on dubbo 2.7 beside one on
    dubbo 3. So a file only counts inside a module that declares this artifact
    at the version the update starts from, or at the one it moves to (a client
    read after the update was applied). Empty means the whole project: the root
    declares it, or no POM names it at those versions directly (a parent or a
    bill of materials manages it).
    """
    versions = {update.from_version, update.to_version}
    homes = {
        declared.manifest_path.removesuffix("pom.xml").rstrip("/")
        for declared in maven_dependencies(files)
        if declared.package == update.package
        and declared.scope not in ("plugin", "import")
        and declared.declared in versions
    }
    if not homes or "" in homes:
        return ()
    return tuple(sorted(homes))


def _in_scope(path: str, scope: tuple[str, ...]) -> bool:
    return not scope or any(path.startswith(home + "/") for home in scope)


def candidates(
    index: SymbolIndex,
    update: DependencyUpdate,
    symbols: list[ChangedSymbol],
    *,
    scope: tuple[str, ...] = (),
) -> tuple[list[Candidate], list[str]]:
    """Every place a changed symbol may be used, and the files that bring the package in."""
    names = importable(update)
    found: list[Candidate] = []
    importers: list[str] = []
    for item in index.files.values():
        if not _in_scope(item.path, scope):
            continue
        by_name: dict[str, list[Reference]] = defaultdict(list)
        for reference in item.references:
            by_name[reference.name].append(reference)
        if update.ecosystem == "npm":
            mine = [imported for imported in item.imports if imported.package in names]
            if not mine:
                continue
            importers.append(item.path)
            found.extend(_npm_candidates(item, mine, symbols, by_name))
        elif item.language == "java" and item.imports:
            before = len(found)
            found.extend(_java_candidates(item, symbols, by_name))
            if len(found) > before:
                importers.append(item.path)
    return found, importers


def read_back(
    found: list[Candidate], files: dict[str, str], *, update_id: str
) -> tuple[list[UsageReference], list[RefusedReference]]:
    """Each candidate checked against the file as it is now, kept or refused with the reason."""
    kept: dict[tuple[str, str, int, str], UsageReference] = {}
    refused: list[RefusedReference] = []
    for candidate in found:
        text = files.get(candidate.path)
        if text is None:
            refused.append(
                RefusedReference(
                    update_id=update_id,  # type: ignore[arg-type]
                    path=candidate.path,
                    line=candidate.line,
                    reason="file-not-found",
                    detail=f"{candidate.path} is not among the files that were read",
                )
            )
            continue
        lines = text.splitlines()
        if candidate.line < 1 or candidate.end_line > len(lines):
            refused.append(
                RefusedReference(
                    update_id=update_id,  # type: ignore[arg-type]
                    path=candidate.path,
                    line=candidate.line,
                    reason="span-out-of-range",
                    detail=f"lines {candidate.line} to {candidate.end_line} of {len(lines)}",
                )
            )
            continue
        span = lines[candidate.line - 1 : candidate.end_line]
        snippet = "\n".join(span[:SNIPPET_LINES])[:SNIPPET_CHARS]
        if candidate.expect not in "\n".join(span):
            refused.append(
                RefusedReference(
                    update_id=update_id,  # type: ignore[arg-type]
                    path=candidate.path,
                    line=candidate.line,
                    reason="snippet-does-not-match",
                    detail=f"{candidate.expect!r} is not on those lines any more",
                )
            )
            continue
        key = (candidate.symbol.symbol, candidate.path, candidate.line, candidate.match)
        kept.setdefault(
            key,
            UsageReference(
                symbol=candidate.symbol.symbol,
                symbol_kind=candidate.symbol.kind,
                match=candidate.match,
                span=EvidenceSpan(
                    path=candidate.path,
                    start_line=candidate.line,
                    end_line=candidate.end_line,
                    snippet=snippet,
                ),
            ),
        )
    ordered = sorted(
        kept.values(), key=lambda r: (r.span.path, r.span.start_line, r.symbol, r.match)
    )
    return ordered, refused
