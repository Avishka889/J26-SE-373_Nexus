"""The symbol index: what each file imports and names, parsed once.

The usage signal can only find what the index recorded, so each way a project
can bring a package in is pinned here, in both languages, along with the uses a
symbol search cannot see: a command in a package script, a `types` entry, a
stylesheet import. The platform's own generated project is indexed for real at
the end, because that is the code the signal will read in production.
"""

import json
from pathlib import Path

from c4.eval.loaders.clients import read_client
from c4.impact.index import build, npm_package

STUDIES = Path(__file__).resolve().parents[1] / "studies"

TS = """import express, { Router as R, json } from "express";
import * as z from "zod";
import type { Request } from "express";
import "reflect-metadata";
import { createRoot } from "react-dom/client";
import { useQuery } from "@tanstack/react-query/build";
import { helper } from "./helper";
import fs from "node:fs";
export { thing } from "other-pkg";
const legacy = require("lodash");
const { a, b: renamed } = require("ms");
const app = express();
app.del("/items/:id", (req: Request, res) => res.json({}));
express().use(json());
const lazy = await import("dynamic-pkg");
"""


def _imports(files: dict[str, str], path: str) -> list[tuple[str, str, str, str]]:
    index = build(files)
    return [(i.kind, i.package, i.imported, i.local) for i in index.files[path].imports]


class TestJavaScriptAndTypeScriptImports:
    def test_every_way_a_module_brings_a_package_in(self) -> None:
        assert _imports({"src/app.ts": TS}, "src/app.ts") == [
            ("default", "express", "default", "express"),
            ("named", "express", "Router", "R"),
            ("named", "express", "json", "json"),
            ("namespace", "zod", "*", "z"),
            ("named", "express", "Request", "Request"),
            ("side-effect", "reflect-metadata", "", ""),
            ("named", "react-dom", "createRoot", "createRoot"),
            ("named", "@tanstack/react-query", "useQuery", "useQuery"),
            ("re-export", "other-pkg", "*", ""),
            ("require", "lodash", "default", "legacy"),
            ("require", "ms", "a", "a"),
            ("require", "ms", "b", "renamed"),
            ("dynamic", "dynamic-pkg", "*", ""),
        ]

    def test_a_relative_path_or_a_node_builtin_is_no_package(self) -> None:
        assert npm_package("./helper") is None
        assert npm_package("node:fs") is None
        assert npm_package("@scope/pkg/deep/path") == "@scope/pkg"

    def test_jsx_in_javascript_and_tsx_is_parsed_by_its_own_grammar(self) -> None:
        component = (
            'import { Link } from "react-router-dom";\nexport const A = () => <Link to="/" />;\n'
        )
        index = build({"a.jsx": component, "b.tsx": component})
        assert {path: item.language for path, item in index.files.items()} == {
            "a.jsx": "javascript",
            "b.tsx": "tsx",
        }
        names = {r.name for r in index.files["b.tsx"].references}
        assert "Link" in names and not index.files["b.tsx"].has_errors


class TestReferences:
    def test_a_member_access_records_what_it_reaches_and_where_it_starts(self) -> None:
        index = build({"src/app.ts": TS})
        members = {
            (r.head, r.name, r.line)
            for r in index.files["src/app.ts"].references
            if r.kind == "member"
        }
        assert ("app", "del", 13) in members
        assert ("res", "json", 13) in members
        # A chain that starts from a call starts from the function called.
        assert ("express", "use", 14) in members

    def test_the_accessed_name_is_not_counted_again_as_a_bare_identifier(self) -> None:
        index = build({"src/app.ts": TS})
        on_line = [
            r for r in index.files["src/app.ts"].references if r.line == 13 and r.name == "del"
        ]
        assert [r.kind for r in on_line] == ["member"]

    def test_a_construction_reaches_the_constructor_of_the_class_it_names(self) -> None:
        """`new ns.Pool<number>()` uses `Pool#<init>`, which is how a removed
        constructor is named by both diffs."""
        index = build(
            {
                "a.ts": 'import * as ns from "acme";\nconst p = new ns.Pool<number>();\n',
                "X.java": "class X { Object f() { return new java.util.ArrayList<String>(); } }\n",
            }
        )
        created = {
            (r.path, r.head)
            for item in index.files.values()
            for r in item.references
            if r.name == "<init>"
        }
        assert created == {("a.ts", "Pool"), ("X.java", "ArrayList")}

    def test_a_type_name_is_an_identifier_reference(self) -> None:
        index = build({"src/app.ts": TS})
        types = [r for r in index.files["src/app.ts"].references if r.name == "Request"]
        assert {r.line for r in types} == {13}

    def test_a_name_in_an_import_is_an_import_not_also_a_reference(self) -> None:
        index = build({"src/app.ts": TS})
        lines = {r.line for r in index.files["src/app.ts"].references}
        assert not lines & {1, 2, 3, 4, 5, 9}


JAVA = """package com.example;

import org.apache.dubbo.rpc.RpcContext;
import static org.junit.jupiter.api.Assertions.assertEquals;
import java.util.*;

class Handler {
    void handle() {
        RpcContext ctx = RpcContext.getContext();
        ctx.getAttachment("trace");
        this.count.value = 1;
    }
}
"""


class TestJava:
    def test_imports_are_recorded_by_their_fully_qualified_names(self) -> None:
        assert _imports({"src/Handler.java": JAVA}, "src/Handler.java") == [
            ("java", "org.apache.dubbo.rpc.RpcContext", "RpcContext", "RpcContext"),
            (
                "java-static",
                "org.junit.jupiter.api.Assertions.assertEquals",
                "assertEquals",
                "assertEquals",
            ),
            ("java-wildcard", "java.util", "*", ""),
        ]

    def test_method_calls_and_field_accesses_record_their_receiver(self) -> None:
        index = build({"src/Handler.java": JAVA})
        references = index.files["src/Handler.java"].references
        members = {(r.head, r.name) for r in references if r.kind == "member"}
        assert {("RpcContext", "getContext"), ("ctx", "getAttachment")} <= members
        # `this` names nothing, so the chain starts from the field it reaches.
        assert ("count", "value") in members
        assert {r.line for r in references if r.name == "RpcContext"} == {9}


class TestJavaDeclaredTypes:
    def test_fields_locals_and_parameters_are_recorded_with_their_class(self) -> None:
        source = (
            "class A {\n"
            "    private final DubboAdapter adapter;\n"
            "    A(java.util.List<String> names) {}\n"
            "    void f(AsyncRpcResult result) {\n"
            "        Box<Integer>[] boxes = null;\n"
            "        for (Item item : items) {}\n"
            "    }\n"
            "}\n"
        )
        types = build({"A.java": source}).files["A.java"].types
        assert types == {
            "adapter": "DubboAdapter",
            "names": "List",
            "result": "AsyncRpcResult",
            "boxes": "Box",
            "item": "Item",
        }


class TestWhatASymbolSearchCannotSee:
    LOCK = json.dumps(
        {
            "packages": {
                "node_modules/typescript": {"version": "5.9.3", "bin": {"tsc": "bin/tsc"}},
                "node_modules/vite": {"version": "6.4.2", "bin": {"vite": "bin/vite.js"}},
                "node_modules/eslint": {"version": "9.0.0", "bin": {"eslint": "bin/eslint.js"}},
            }
        }
    )
    MANIFEST = json.dumps(
        {
            "scripts": {
                "typecheck": "tsc --noEmit",
                "build": "NODE_ENV=production tsc -b && vite build",
                "lint": "npx eslint .",
                "start": "node server.js",
            }
        },
        indent=2,
    )

    def test_a_script_command_is_the_package_whose_lockfile_entry_declares_it(self) -> None:
        index = build({"package.json": self.MANIFEST}, lockfile=self.LOCK)
        assert [(t.package, t.line) for t in index.tools] == [
            ("typescript", 3),
            ("typescript", 4),
            ("vite", 4),
            ("eslint", 5),
        ]

    def test_types_extends_and_stylesheet_imports_are_uses(self) -> None:
        tsconfig = json.dumps(
            {
                "extends": "@tsconfig/node22/tsconfig.json",
                "compilerOptions": {"types": ["vite/client"]},
            }
        )
        index = build(
            {
                "tsconfig.json": tsconfig,
                "src/styles.css": '@import "tailwindcss";\n@plugin "@tailwindcss/typography";\n',
            }
        )
        assert sorted((t.via, t.package) for t in index.tools) == [
            ("stylesheet", "@tailwindcss/typography"),
            ("stylesheet", "tailwindcss"),
            ("tsconfig", "@tsconfig/node22"),
            ("tsconfig", "vite"),
        ]


class TestWhatIsIndexed:
    def test_installed_and_built_code_is_never_the_projects_own(self) -> None:
        index = build(
            {
                "src/a.ts": 'import x from "x";\n',
                "node_modules/x/index.js": 'import y from "y";\n',
                "dist/a.js": 'import x from "x";\n',
            }
        )
        assert list(index.files) == ["src/a.ts"]

    def test_a_file_that_does_not_parse_is_still_indexed_and_says_so(self) -> None:
        index = build({"src/broken.ts": 'import express from "express";\nconst = ;\n'})
        broken = index.files["src/broken.ts"]
        assert broken.has_errors
        assert [i.package for i in broken.imports] == ["express"]

    def test_the_generated_project_is_indexed_as_it_is(self) -> None:
        files = read_client(STUDIES / "clients" / "task-tracker")
        lockfile = (STUDIES / "pins" / "task-tracker-2026-06-01.package-lock.json").read_text()
        index = build(files, lockfile=lockfile)
        record = index.record()
        assert record.files_indexed == 24 and record.parser.startswith("tree-sitter ")
        assert not [path for path, item in index.files.items() if item.has_errors]
        packages = {i.package for item in index.files.values() for i in item.imports}
        assert {"express", "react", "react-router-dom", "vite", "vitest", "supertest"} <= packages
        tools = {(t.via, t.package) for t in index.tools}
        assert {
            ("script", "typescript"),
            ("stylesheet", "tailwindcss"),
            ("tsconfig", "vite"),
        } <= tools
