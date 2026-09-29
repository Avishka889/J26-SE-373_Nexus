"""References and the usage vote: where the project uses what changed, checked line by line.

Small projects written here, in both languages, each using a package in one of
the ways the search has to recognise, and each checked for the vote the rule
gives. The read back is tested by indexing one version of a file and reading
another, which is the only way a span the index recorded can stop being true.
"""

from c4.impact.api_diff import ApiDiff
from c4.impact.index import build
from c4.impact.references import candidates, read_back
from c4.impact.usage import claimed_symbols, update_impact
from sdlc_contracts import (
    ChangedSymbol,
    ChangelogReport,
    DependencyUpdate,
    UpdateImpact,
    update_id_for,
    update_key,
)


def _update(package: str, ecosystem: str = "npm", old: str = "1.0.0", new: str = "2.0.0"):
    key = update_key(ecosystem, package, old, new)
    return DependencyUpdate(
        id=update_id_for(key),
        key=key,
        ecosystem=ecosystem,  # type: ignore[arg-type]
        package=package,
        manifest_path="pom.xml" if ecosystem == "maven" else "package.json",
        scope="compile" if ecosystem == "maven" else "prod",
        declared=old,
        from_version=old,
        to_version=new,
        candidate="latest",
        change="major",
    )


def _symbol(update: DependencyUpdate, name: str, kind: str = "removed") -> ChangedSymbol:
    return ChangedSymbol(
        update_id=update.id,
        symbol=name,
        kind=kind,  # type: ignore[arg-type]
        source="api-diff",
        tool="declaration-diff/1",
    )


def _impact(update: DependencyUpdate, files: dict[str, str], *symbols: ChangedSymbol):
    impact, refused, _ = update_impact(
        update,
        build(files),
        files,
        api=ApiDiff("ran", "", tuple(symbols)),
        claimed=[],
    )
    return impact, refused


EXPRESS = _update("express")

APP = """import express from "express";
const server = express();
server.del("/items/:id", (req, res) => res.sendStatus(204));
export { server };
"""


class TestNpm:
    def test_a_removed_member_used_by_any_receiver_is_high(self) -> None:
        """The app is called `server` here, not `app` as the release note writes it."""
        impact, _ = _impact(EXPRESS, {"src/app.ts": APP}, _symbol(EXPRESS, "app.del"))
        assert impact.vote.level == "high"
        [reference] = impact.references
        assert (reference.match, reference.span.path, reference.span.start_line) == (
            "member",
            "src/app.ts",
            3,
        )
        assert "server.del" in reference.span.snippet
        assert impact.vote.evidence_ids == [f"{EXPRESS.id}-r1"]
        assert "src/app.ts:3" in impact.vote.rationale

    def test_a_removed_export_is_used_by_its_import_and_by_its_local_name(self) -> None:
        acme = _update("acme")
        files = {"src/a.ts": 'import { connect as open } from "acme";\nopen("db://");\n'}
        impact, _ = _impact(acme, files, _symbol(acme, "connect"))
        assert [(r.match, r.span.start_line) for r in impact.references] == [
            ("import", 1),
            ("identifier", 2),
        ]

    def test_an_export_reached_through_the_package_binding_is_used(self) -> None:
        files = {"src/a.ts": 'import express from "express";\nexpress.json();\n'}
        impact, _ = _impact(EXPRESS, files, _symbol(EXPRESS, "json", "signature-changed"))
        assert [(r.match, r.span.start_line) for r in impact.references] == [("member", 2)]

    def test_a_removed_constructor_is_used_only_by_a_construction(self) -> None:
        acme = _update("acme")
        constructs = 'import { Client } from "acme";\nconst c = new Client("x");\n'
        only_static = 'import { Client } from "acme";\nconst c = Client.create();\n'
        symbol = _symbol(acme, "Client#<init>")
        assert _impact(acme, {"a.ts": constructs}, symbol)[0].vote.level == "high"
        assert _impact(acme, {"a.ts": only_static}, symbol)[0].vote.level == "low"

    def test_a_types_package_is_used_where_its_package_is_imported(self) -> None:
        types = _update("@types/react")
        files = {"src/a.tsx": 'import { useId } from "react";\nconst id = useId();\n'}
        impact, _ = _impact(types, files, _symbol(types, "useId"))
        assert impact.imports_package and impact.vote.level == "high"

    def test_a_deprecation_in_use_is_medium(self) -> None:
        impact, _ = _impact(EXPRESS, {"src/app.ts": APP}, _symbol(EXPRESS, "app.del", "deprecated"))
        assert impact.vote.level == "medium"

    def test_imported_with_nothing_changed_in_use_is_low_project_specific_impact(self) -> None:
        impact, _ = _impact(EXPRESS, {"src/app.ts": APP}, _symbol(EXPRESS, "Router#param"))
        assert impact.vote.level == "low" and impact.imports_package
        assert "low project specific impact" in impact.vote.rationale
        assert impact.unreferenced == ["Router#param"]

    def test_no_changed_symbols_known_abstains_and_says_why(self) -> None:
        impact, refused, _ = update_impact(
            EXPRESS,
            build({"src/app.ts": APP}),
            {"src/app.ts": APP},
            api=ApiDiff("unavailable", "express ships no type declarations"),
            claimed=[],
        )
        assert impact.vote.level is None and not refused
        assert "express ships no type declarations" in impact.vote.abstained_reason

    def test_a_build_tool_used_only_by_a_script_is_recorded_as_such(self) -> None:
        vite = _update("vite")
        files = {"package.json": '{"scripts": {"build": "vite build"}}'}
        impact, _ = _impact(vite, files, _symbol(vite, "defineConfig", "signature-changed"))
        assert impact.used_by_scripts and not impact.imports_package
        assert impact.vote.level == "low"


class TestSymbolsFromTheChangelog:
    def test_a_verified_claims_symbols_carry_its_kind_and_its_id(self) -> None:
        report = ChangelogReport.model_validate(
            {
                "version": 1,
                "generatedAt": "2026-09-27T00:00:00Z",
                "modelId": "deepseek:deepseek-flash",
                "promptId": "changelog-extract/1",
                "promptSha256": "0" * 64,
                "perUpdate": [
                    {
                        "updateId": EXPRESS.id,
                        "notesFound": True,
                        "claims": [
                            {
                                "id": f"{EXPRESS.id}-c1",
                                "kind": "removal",
                                "symbols": ["app.del"],
                                "quote": "Removed `app.del()`.",
                                "sourceUrl": "https://example/releases",
                                "version": "5.0.0",
                            }
                        ],
                        "vote": {
                            "signal": "changelog",
                            "level": "high",
                            "ruleId": "changelog-rule/1",
                            "rationale": "written by code",
                        },
                        "model": {
                            "modelId": "deepseek:deepseek-flash",
                            "promptId": "changelog-extract/1",
                            "promptSha256": "0" * 64,
                            "outcome": "answered",
                        },
                    }
                ],
            }
        )
        [symbol] = claimed_symbols(report, EXPRESS)
        assert (symbol.symbol, symbol.kind, symbol.source, symbol.tool) == (
            "app.del",
            "removed",
            "changelog",
            f"claim:{EXPRESS.id}-c1",
        )


DUBBO = _update("org.apache.dubbo:dubbo", "maven", "2.7.3", "2.7.21")

HANDLER = """package com.example;

import com.alibaba.dubbo.rpc.RpcContext;
import static com.alibaba.dubbo.common.Constants.GROUP_CHAR_SEPERATOR;

class Handler {
    String serve() {
        RpcContext context = RpcContext.getContext();
        return context.getServerContext() + GROUP_CHAR_SEPERATOR;
    }
}
"""


class TestJava:
    def test_a_changed_member_of_an_imported_type_is_used_where_it_is_reached(self) -> None:
        impact, _ = _impact(
            DUBBO,
            {"src/Handler.java": HANDLER},
            _symbol(
                DUBBO, "com.alibaba.dubbo.rpc.RpcContext#getServerContext", "signature-changed"
            ),
            _symbol(DUBBO, "com.alibaba.dubbo.rpc.RpcContext#<init>"),
            _symbol(DUBBO, "com.alibaba.dubbo.common.Constants#GROUP_CHAR_SEPERATOR"),
            _symbol(DUBBO, "com.alibaba.dubbo.rpc.protocol.http.HttpRemoteInvocation"),
        )
        assert impact.vote.level == "high"
        found = {
            (r.symbol.rsplit(".", 1)[-1], r.match, r.span.start_line) for r in impact.references
        }
        assert found == {
            ("RpcContext#getServerContext", "member", 9),
            ("Constants#GROUP_CHAR_SEPERATOR", "import", 4),
        }
        # Never constructed here, and never imported: searched for, not used.
        assert impact.unreferenced == [
            "com.alibaba.dubbo.rpc.RpcContext#<init>",
            "com.alibaba.dubbo.rpc.protocol.http.HttpRemoteInvocation",
        ]

    def test_a_type_seen_through_a_wildcard_is_used_by_its_simple_name(self) -> None:
        wildcard = "package p;\nimport com.alibaba.dubbo.rpc.*;\nclass A { RpcContext c; }\n"
        impact, _ = _impact(
            DUBBO, {"A.java": wildcard}, _symbol(DUBBO, "com.alibaba.dubbo.rpc.RpcContext")
        )
        assert [(r.match, r.span.start_line) for r in impact.references] == [("identifier", 3)]

    def test_a_type_imported_by_name_is_used_by_the_import(self) -> None:
        impact, _ = _impact(
            DUBBO, {"src/Handler.java": HANDLER}, _symbol(DUBBO, "com.alibaba.dubbo.rpc.RpcContext")
        )
        assert ("import", 3) in {(r.match, r.span.start_line) for r in impact.references}


class TestTheReadBack:
    def test_a_span_the_file_no_longer_holds_is_refused_and_not_counted(self) -> None:
        """Indexed at one version, read at another: the removed call moved away."""
        indexed = build({"src/app.ts": APP})
        moved = APP.replace('server.del("/items/:id"', '// removed\nserver.delete("/items/:id"')
        found, _ = candidates(indexed, EXPRESS, [_symbol(EXPRESS, "app.del")])
        references, refused = read_back(found, {"src/app.ts": moved}, update_id=EXPRESS.id)
        assert references == []
        assert [(r.reason, r.line) for r in refused] == [("snippet-does-not-match", 3)]

    def test_a_file_that_is_gone_is_refused(self) -> None:
        found, _ = candidates(build({"src/app.ts": APP}), EXPRESS, [_symbol(EXPRESS, "app.del")])
        _, refused = read_back(found, {}, update_id=EXPRESS.id)
        assert [r.reason for r in refused] == ["file-not-found"]

    def test_the_impact_survives_its_own_validator(self) -> None:
        """The contract re-derives the usage vote from the references."""
        impact, _ = _impact(EXPRESS, {"src/app.ts": APP}, _symbol(EXPRESS, "app.del"))
        again = UpdateImpact.model_validate(impact.model_dump(by_alias=True, mode="json"))
        assert again.vote.level == "high"


def test_a_maven_update_is_searched_for_only_in_the_modules_that_declare_it() -> None:
    """dubbo 2.7 ships `com.alibaba.dubbo` classes, and so does dubbo 2.5, which a
    sibling module uses; a third module is on dubbo 3, which this update does not
    touch. Only the module that declares the artifact at the update's versions counts."""
    declares = (
        "<project><artifactId>v2</artifactId><dependencies><dependency>"
        "<groupId>org.apache.dubbo</groupId><artifactId>dubbo</artifactId>"
        "<version>2.7.21</version></dependency></dependencies></project>"
    )
    other = (
        "<project><artifactId>alibaba</artifactId><dependencies><dependency>"
        "<groupId>com.alibaba</groupId><artifactId>dubbo</artifactId>"
        "<version>2.5.3</version></dependency></dependencies></project>"
    )
    newer = declares.replace("<version>2.7.21</version>", "<version>3.1.1</version>")
    assert newer != declares
    files = {
        "pom.xml": "<project><artifactId>root</artifactId></project>",
        "v2/pom.xml": declares,
        "alibaba/pom.xml": other,
        "v3/pom.xml": newer,
        "v2/src/main/java/com/x/Handler.java": HANDLER,
        "alibaba/src/main/java/com/x/Handler.java": HANDLER,
        "v3/src/main/java/com/x/Handler.java": HANDLER,
    }
    impact, _ = _impact(
        DUBBO,
        files,
        _symbol(DUBBO, "com.alibaba.dubbo.rpc.RpcContext#getServerContext", "signature-changed"),
    )
    assert {r.span.path for r in impact.references} == {"v2/src/main/java/com/x/Handler.java"}


def test_a_java_receiver_declared_as_another_class_is_not_a_use() -> None:
    """The worked case's own false positive: `adapter.getInvocation()` on the
    project's DubboAdapter is not a use of `AsyncRpcResult#getInvocation`. A
    receiver declared as the changed class is, and so is one this file cannot type."""
    source = (
        "package p;\n"
        "import org.apache.dubbo.rpc.*;\n"
        "class Extractor {\n"
        "    private final DubboAdapter adapter = null;\n"
        "    Object f(AsyncRpcResult result) {\n"
        "        adapter.getInvocation();\n"
        "        result.getInvocation();\n"
        "        return lookup().getInvocation();\n"
        "    }\n"
        "}\n"
    )
    impact, _ = _impact(
        DUBBO,
        {"Extractor.java": source},
        _symbol(DUBBO, "org.apache.dubbo.rpc.AsyncRpcResult#getInvocation"),
    )
    assert [r.span.start_line for r in impact.references] == [7, 8]
