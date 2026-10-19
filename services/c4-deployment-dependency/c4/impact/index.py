"""One symbol index of the project per run (NFR2): what each file imports, and what it names.

The impact stage builds this once, before it looks at any update, and every
update's search runs over the same index. The risk stage never receives files
at all, so the project cannot be indexed a second time by accident.

**What is parsed.** TypeScript, TSX and JavaScript (the platform's projects)
and Java (BUMP's clients), with tree-sitter and the grammar for each. A file
that does not parse cleanly is still indexed, and says so, because tree-sitter
recovers around an error and the rest of the file is still evidence.

**What is recorded, per file.**

- *Imports*: the module or class each import names, the name it imports and
  the local name it binds. For JavaScript and TypeScript that is every ES
  import, re-export, `require` and dynamic `import()`, each mapped to the npm
  package it belongs to (`react-dom/client` is `react-dom`). For Java it is the
  fully qualified name of every single type, static and wildcard import,
  because a Maven artifact's classes are named that way by its API diff.
- *References*: every member access (`app.del`, `RpcContext.getContext`) with
  the name accessed and the identifier the chain starts from, every
  construction (`new Client()` reaches `Client#<init>`), and every other
  identifier and type name, each with its line and column.

**What a symbol search cannot see.** A build also uses a package through its
command line tools and its configuration: `vitest run` in a package script,
`"types": ["vite/client"]` in a `tsconfig.json`, `@import "tailwindcss"` in a
stylesheet. Those are recorded as script and configuration uses. A tool's
package is the one whose lockfile entry declares the command (`tsc` belongs to
`typescript` because its `bin` says so), and a command no lockfile names is
taken as the package of the same name.
"""

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from functools import cache
from importlib.metadata import version as distribution_version
from typing import Literal

import tree_sitter_java
import tree_sitter_javascript
import tree_sitter_typescript
from sdlc_contracts import ExtractionRecord
from tree_sitter import Language, Node, Parser, Query, QueryCursor

LanguageName = Literal["typescript", "tsx", "javascript", "java"]

ImportKind = Literal[
    "default",
    "named",
    "namespace",
    "side-effect",
    "re-export",
    "require",
    "dynamic",
    "java",
    "java-static",
    "java-wildcard",
]

_EXTENSIONS: dict[str, LanguageName] = {
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".java": "java",
}

#: Directories that are never the project's own code.
_SKIPPED = frozenset({"node_modules", "dist", "build", "target", "coverage", ".git"})

_GRAMMARS: dict[LanguageName, str] = {
    "typescript": "tree-sitter-typescript",
    "tsx": "tree-sitter-typescript",
    "javascript": "tree-sitter-javascript",
    "java": "tree-sitter-java",
}

#: What counts as a reference, per grammar. Member accesses are read for their
#: accessed name; everything else is a name as it stands.
_QUERIES: dict[LanguageName, str] = {
    "typescript": (
        "(member_expression) @chain (new_expression) @new "
        "(identifier) @name (type_identifier) @name"
    ),
    "tsx": (
        "(member_expression) @chain (new_expression) @new "
        "(identifier) @name (type_identifier) @name"
    ),
    "javascript": "(member_expression) @chain (new_expression) @new (identifier) @name",
    "java": (
        "(method_invocation) @chain (field_access) @chain (object_creation_expression) @new "
        "(identifier) @name (type_identifier) @name"
    ),
}

#: The member name a construction reaches, in both ecosystems: `new Client()`
#: uses `Client#<init>`, which is how a removed constructor is named.
CONSTRUCTOR = "<init>"

#: The field that holds the accessed name, and the one that holds its receiver.
_MEMBER_FIELDS = {
    "member_expression": ("property", "object"),
    "method_invocation": ("name", "object"),
    "field_access": ("field", "object"),
}


@cache
def _language(name: LanguageName) -> Language:
    if name == "typescript":
        return Language(tree_sitter_typescript.language_typescript())
    if name == "tsx":
        return Language(tree_sitter_typescript.language_tsx())
    if name == "javascript":
        return Language(tree_sitter_javascript.language())
    return Language(tree_sitter_java.language())


def parser(name: LanguageName) -> Parser:
    """A parser for one grammar; parsers are cheap, the languages behind them are cached."""
    return Parser(_language(name))


@cache
def _query(name: LanguageName) -> Query:
    return Query(_language(name), _QUERIES[name])


def language_of(path: str) -> LanguageName | None:
    if _SKIPPED.intersection(path.split("/")[:-1]):
        return None
    dot = path.rfind(".")
    return _EXTENSIONS.get(path[dot:].lower()) if dot >= 0 else None


def npm_package(specifier: str) -> str | None:
    """The npm package a module specifier belongs to, or None for a relative path."""
    text = specifier.strip()
    if not text or text.startswith((".", "/")) or text.startswith("node:"):
        return None
    parts = text.split("/")
    if text.startswith("@"):
        return "/".join(parts[:2]) if len(parts) >= 2 else None
    return parts[0]


@dataclass(frozen=True)
class Import:
    path: str
    kind: ImportKind
    #: The npm package, or for Java the fully qualified name as imported.
    package: str
    #: The module specifier or Java name exactly as written.
    source: str
    #: The name imported (`Router`, `default`, `*`), or "" for a side effect.
    imported: str
    #: The local name it is bound to, or "" when none is.
    local: str
    line: int
    end_line: int


@dataclass(frozen=True)
class Reference:
    path: str
    kind: Literal["member", "identifier"]
    #: The name referred to: the accessed member, or the identifier itself.
    name: str
    #: The identifier the access chain starts from, or "" when it starts from
    #: a call or `this`. Equal to `name` for an identifier.
    head: str
    #: The expression as written, on one line and cut to a readable length.
    text: str
    line: int
    end_line: int
    column: int


@dataclass(frozen=True)
class ToolUse:
    """A package used by a build rather than by code: a script, a config, a stylesheet."""

    path: str
    package: str
    line: int
    text: str
    via: Literal["script", "tsconfig", "stylesheet"]


@dataclass
class FileIndex:
    path: str
    language: LanguageName
    has_errors: bool
    imports: list[Import] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    #: Java only: each field, local and parameter name, to the simple name of
    #: the type it is declared as. The file's last declaration of a name wins;
    #: scopes are not followed, which is recorded as the approximation it is.
    types: dict[str, str] = field(default_factory=dict)


@dataclass
class SymbolIndex:
    extraction_id: str
    files: dict[str, FileIndex]
    tools: list[ToolUse]
    seconds: float

    def record(self) -> ExtractionRecord:
        return ExtractionRecord(
            extraction_id=self.extraction_id,
            parser=f"tree-sitter {distribution_version('tree-sitter')}",
            grammars=sorted(
                {
                    f"{name} ({_GRAMMARS[name]} {distribution_version(_GRAMMARS[name])})"
                    for name in {item.language for item in self.files.values()}
                }
            ),
            files_indexed=len(self.files),
            seconds=round(self.seconds, 3),
        )


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8", "replace") if node is not None and node.text else ""


def _string(node: Node | None) -> str:
    """The value of a string literal node, without its quotes."""
    if node is None:
        return ""
    fragments = [child for child in node.named_children if child.type == "string_fragment"]
    if fragments:
        return "".join(_text(child) for child in fragments)
    return _text(node).strip("'\"`")


def _span(node: Node) -> tuple[int, int]:
    return node.start_point[0] + 1, node.end_point[0] + 1


def _head(node: Node) -> str:
    """The identifier an access chain starts from, following receivers leftwards.

    `this.adapter.run()` starts from `adapter`: `this` names nothing, and the
    field it reaches is the receiver a reader would name.
    """
    current: Node | None = node
    while current is not None:
        if current.type in ("identifier", "type_identifier"):
            return _text(current)
        if current.type == "field_access":
            receiver = current.child_by_field_name("object")
            if receiver is not None and receiver.type == "this":
                return _text(current.child_by_field_name("field"))
        if current.type in _MEMBER_FIELDS:
            current = current.child_by_field_name(_MEMBER_FIELDS[current.type][1])
        elif current.type == "call_expression":
            current = current.child_by_field_name("function")
        elif current.type in ("parenthesized_expression", "non_null_expression"):
            current = current.named_children[0] if current.named_children else None
        else:
            return ""
    return ""


def _class_name(node: Node | None) -> str:
    """The class a construction names: `Client` in `new ns.Client()` or `new Client<T>()`."""
    if node is None:
        return ""
    if node.type in ("identifier", "type_identifier"):
        return _text(node)
    if node.type == "member_expression":
        return _text(node.child_by_field_name("property"))
    if node.type in ("scoped_type_identifier", "generic_type"):
        names = [
            c
            for c in node.named_children
            if c.type in ("type_identifier", "scoped_type_identifier")
        ]
        return (
            _class_name(names[-1] if node.type == "scoped_type_identifier" else names[0])
            if names
            else ""
        )
    return ""


def _one_line(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= 120 else flat[:117] + "..."


def _js_imports(path: str, root: Node) -> list[Import]:
    found: list[Import] = []

    def add(kind, source, imported, local, node) -> None:
        package = npm_package(source)
        if package is None:
            return
        line, end = _span(node)
        found.append(Import(path, kind, package, source, imported, local, line, end))

    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "import_statement":
            source = _string(node.child_by_field_name("source"))
            clause = next((c for c in node.named_children if c.type == "import_clause"), None)
            if clause is None:
                add("side-effect", source, "", "", node)
            else:
                for part in clause.named_children:
                    if part.type == "identifier":
                        add("default", source, "default", _text(part), node)
                    elif part.type == "namespace_import":
                        names = [c for c in part.named_children if c.type == "identifier"]
                        add("namespace", source, "*", _text(names[0]) if names else "", node)
                    elif part.type == "named_imports":
                        for spec in part.named_children:
                            if spec.type != "import_specifier":
                                continue
                            name = _text(spec.child_by_field_name("name"))
                            alias = _text(spec.child_by_field_name("alias")) or name
                            add("named", source, name, alias, node)
            continue
        if node.type == "export_statement" and node.child_by_field_name("source") is not None:
            add("re-export", _string(node.child_by_field_name("source")), "*", "", node)
            continue
        if node.type == "call_expression":
            function = node.child_by_field_name("function")
            arguments = node.child_by_field_name("arguments")
            first = arguments.named_children[0] if arguments and arguments.named_children else None
            if function is not None and first is not None and first.type == "string":
                if function.type == "import":
                    add("dynamic", _string(first), "*", "", node)
                elif function.type == "identifier" and _text(function) == "require":
                    declarator = node.parent
                    target = (
                        declarator.child_by_field_name("name")
                        if declarator is not None and declarator.type == "variable_declarator"
                        else None
                    )
                    source = _string(first)
                    if target is not None and target.type == "object_pattern":
                        for prop in target.named_children:
                            if prop.type == "shorthand_property_identifier_pattern":
                                add("require", source, _text(prop), _text(prop), node)
                            elif prop.type == "pair_pattern":
                                key = _text(prop.child_by_field_name("key"))
                                value = _text(prop.child_by_field_name("value"))
                                add("require", source, key, value, node)
                    else:
                        add("require", source, "default", _text(target), node)
        stack.extend(reversed(node.named_children))
    return sorted(found, key=lambda item: item.line)


def _java_imports(path: str, root: Node) -> list[Import]:
    found: list[Import] = []
    for node in root.named_children:
        if node.type != "import_declaration":
            continue
        name_node = next(
            (c for c in node.named_children if c.type in ("scoped_identifier", "identifier")),
            None,
        )
        name = _text(name_node)
        if not name:
            continue
        wildcard = any(child.type == "asterisk" for child in node.children)
        static = any(child.type == "static" for child in node.children)
        line, end = _span(node)
        simple = name.rsplit(".", 1)[-1]
        if wildcard:
            found.append(Import(path, "java-wildcard", name, name, "*", "", line, end))
        elif static:
            found.append(Import(path, "java-static", name, name, simple, simple, line, end))
        else:
            found.append(Import(path, "java", name, name, simple, simple, line, end))
    return found


#: Top level statements whose names are recorded as imports, not as references.
_DECLARATIONS = frozenset({"import_statement", "import_declaration", "package_declaration"})


def _declared_ranges(root: Node) -> list[tuple[int, int]]:
    return [
        (node.start_byte, node.end_byte)
        for node in root.named_children
        if node.type in _DECLARATIONS
        or (node.type == "export_statement" and node.child_by_field_name("source") is not None)
    ]


def _references(path: str, language: LanguageName, root: Node) -> list[Reference]:
    """Every access and name outside the import declarations, which are imports."""
    captures = QueryCursor(_query(language)).captures(root)
    declared = _declared_ranges(root)

    def inside_a_declaration(node: Node) -> bool:
        return any(start <= node.start_byte < end for start, end in declared)

    found: list[Reference] = []
    accessed: set[tuple[int, int]] = set()
    for chain in captures.get("chain", []):
        if inside_a_declaration(chain):
            continue
        name_field, _ = _MEMBER_FIELDS[chain.type]
        name_node = chain.child_by_field_name(name_field)
        if name_node is None:
            continue
        accessed.add((name_node.start_byte, name_node.end_byte))
        line, end = _span(chain)
        found.append(
            Reference(
                path,
                "member",
                _text(name_node),
                _head(chain),
                _one_line(_text(chain)),
                line,
                end,
                name_node.start_point[1] + 1,
            )
        )
    for creation in captures.get("new", []):
        if inside_a_declaration(creation):
            continue
        created = creation.child_by_field_name(
            "type" if creation.type == "object_creation_expression" else "constructor"
        )
        class_name = _class_name(created)
        if class_name:
            line, end = _span(creation)
            found.append(
                Reference(
                    path,
                    "member",
                    CONSTRUCTOR,
                    class_name,
                    _one_line(_text(creation)),
                    line,
                    end,
                    creation.start_point[1] + 1,
                )
            )
    for node in captures.get("name", []):
        if (node.start_byte, node.end_byte) in accessed or inside_a_declaration(node):
            continue
        text = _text(node)
        line, end = _span(node)
        found.append(
            Reference(path, "identifier", text, text, text, line, end, node.start_point[1] + 1)
        )
    return sorted(found, key=lambda item: (item.line, item.column, item.kind))


#: Java declarations whose declared type names a variable's class.
_JAVA_DECLARATIONS = (
    "(field_declaration type: (_) @type declarator: (variable_declarator name: (identifier) @name))"
    " (local_variable_declaration type: (_) @type"
    " declarator: (variable_declarator name: (identifier) @name))"
    " (formal_parameter type: (_) @type name: (identifier) @name)"
    " (enhanced_for_statement type: (_) @type name: (identifier) @name)"
)


@cache
def _declarations() -> Query:
    return Query(_language("java"), _JAVA_DECLARATIONS)


def _type_name(node: Node) -> str:
    """The simple class name a declared type names: `Box` in `java.util.Box<Integer>[]`."""
    if node.type in ("type_identifier", "identifier"):
        return _text(node)
    if node.type == "scoped_type_identifier":
        names = [c for c in node.named_children if c.type == "type_identifier"]
        return _text(names[-1]) if names else ""
    if node.type in ("generic_type", "array_type", "annotated_type"):
        inner = [
            c
            for c in node.named_children
            if c.type not in ("type_arguments", "dimensions", "marker_annotation", "annotation")
        ]
        return _type_name(inner[0]) if inner else ""
    return _text(node)


def _java_types(root: Node) -> dict[str, str]:
    types: dict[str, str] = {}
    for _, captured in QueryCursor(_declarations()).matches(root):
        declared = captured.get("type", [])
        named = captured.get("name", [])
        if declared and named:
            types[_text(named[0])] = _type_name(declared[0])
    return types


def _parse(path: str, language: LanguageName, text: str) -> FileIndex:
    tree = parser(language).parse(text.encode("utf-8"))
    root = tree.root_node
    imports = _java_imports(path, root) if language == "java" else _js_imports(path, root)
    return FileIndex(
        path,
        language,
        root.has_error,
        imports,
        _references(path, language, root),
        _java_types(root) if language == "java" else {},
    )


def _bins(lockfile: str | None) -> dict[str, str]:
    """Command name to the package whose lockfile entry declares it."""
    if not lockfile:
        return {}
    try:
        packages = json.loads(lockfile).get("packages") or {}
    except (json.JSONDecodeError, AttributeError):
        return {}
    commands: dict[str, str] = {}
    for key, body in packages.items():
        if "node_modules/" not in key or not isinstance(body, dict):
            continue
        name = key.rsplit("node_modules/", 1)[-1]
        declared = body.get("bin")
        if isinstance(declared, dict):
            for command in declared:
                commands.setdefault(command, name)
        elif isinstance(declared, str):
            commands.setdefault(name.rsplit("/", 1)[-1], name)
    return commands


_SEGMENT = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_RUNNERS = {"npx", "pnpx", "bunx"}


def _line_of(text: str, needle: str) -> int:
    offset = text.find(needle)
    return text.count("\n", 0, offset) + 1 if offset >= 0 else 1


def _scripts(path: str, text: str, bins: dict[str, str]) -> list[ToolUse]:
    try:
        scripts = (json.loads(text) or {}).get("scripts") or {}
    except (json.JSONDecodeError, AttributeError):
        return []
    found: list[ToolUse] = []
    for name, command in scripts.items():
        if not isinstance(command, str):
            continue
        line = _line_of(text, f'"{name}"')
        for segment in _SEGMENT.split(command):
            words = [word for word in segment.split() if not _ASSIGNMENT.match(word)]
            if words and words[0] in _RUNNERS:
                words = words[1:]
            if not words or words[0] in ("npm", "node", "cd", "echo", "exit"):
                continue
            tool = words[0]
            package = bins.get(tool) or npm_package(tool)
            if package:
                found.append(ToolUse(path, package, line, f"{name}: {command}", "script"))
    return found


def _tsconfig(path: str, text: str) -> list[ToolUse]:
    try:
        config = json.loads(text) or {}
    except json.JSONDecodeError:
        return []
    found: list[ToolUse] = []
    for entry in (config.get("compilerOptions") or {}).get("types") or []:
        if not isinstance(entry, str):
            continue
        line = _line_of(text, f'"{entry}"')
        package = npm_package(entry)
        if package and "/" not in entry and not entry.startswith("@"):
            # `"types": ["node"]` is TypeScript resolving `@types/node`.
            found.append(ToolUse(path, f"@types/{entry}", line, f"types: {entry}", "tsconfig"))
        if package:
            found.append(ToolUse(path, package, line, f"types: {entry}", "tsconfig"))
    extends = config.get("extends")
    for entry in [extends] if isinstance(extends, str) else extends or []:
        package = npm_package(entry) if isinstance(entry, str) else None
        if package:
            found.append(
                ToolUse(
                    path, package, _line_of(text, f'"{entry}"'), f"extends: {entry}", "tsconfig"
                )
            )
    return found


_CSS_IMPORT = re.compile(r"""@(?:import|plugin)\s+(?:url\()?["']([^"']+)["']""")


def _stylesheet(path: str, text: str) -> list[ToolUse]:
    found: list[ToolUse] = []
    for match in _CSS_IMPORT.finditer(text):
        package = npm_package(match.group(1))
        if package:
            line = text.count("\n", 0, match.start()) + 1
            found.append(ToolUse(path, package, line, match.group(0), "stylesheet"))
    return found


def build(files: dict[str, str], *, lockfile: str | None = None) -> SymbolIndex:
    """Parse every source file once and record what it imports and names."""
    started = time.monotonic()
    indexed: dict[str, FileIndex] = {}
    tools: list[ToolUse] = []
    bins = _bins(lockfile)
    for path in sorted(files):
        text = files[path]
        language = language_of(path)
        if language is not None:
            indexed[path] = _parse(path, language, text)
            continue
        if _SKIPPED.intersection(path.split("/")[:-1]):
            continue
        name = path.rsplit("/", 1)[-1]
        if name == "package.json":
            tools.extend(_scripts(path, text, bins))
        elif name.startswith("tsconfig") and name.endswith(".json"):
            tools.extend(_tsconfig(path, text))
        elif name.endswith(".css"):
            tools.extend(_stylesheet(path, text))
    return SymbolIndex(
        extraction_id=f"x-{uuid.uuid4().hex[:12]}",
        files=indexed,
        tools=tools,
        seconds=time.monotonic() - started,
    )
