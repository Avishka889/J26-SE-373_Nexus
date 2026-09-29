"""The API diff: what the two releases' own interfaces say changed (B2).

Roseau's report is read from an excerpt of a real run over the worked case, one
entry of each shape; the declaration diff is read from declarations written
here and from tarballs built here, served by a recorded registry. Roseau itself
is run for real once, on the worked case, where it is installed.
"""

import gzip
import io
import json
import tarfile
from pathlib import Path

import httpx
import pytest
from c4.impact.api_diff import (
    ROSEAU,
    declaration_changes,
    declarations,
    diff,
    npm_diff,
    roseau_launcher,
    roseau_symbols,
    run_roseau,
)
from c4.intake.fetch import Fetcher
from sdlc_contracts import DependencyUpdate, update_id_for, update_key

FIXTURE = Path(__file__).parent / "fixtures" / "roseau" / "dubbo-2.7.3-2.7.21.excerpt.json"


def _update(ecosystem: str, package: str, old: str, new: str, change: str) -> DependencyUpdate:
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
        change=change,  # type: ignore[arg-type]
    )


DUBBO = _update("maven", "org.apache.dubbo:dubbo", "2.7.3", "2.7.21", "patch")


class TestRoseauReports:
    def test_every_shape_of_change_is_named_the_way_client_code_names_it(self) -> None:
        symbols = roseau_symbols(json.loads(FIXTURE.read_text()), update_id=DUBBO.id)
        assert [(s.symbol, s.kind) for s in symbols] == [
            # An inherited method, reported against the subclass that lost it.
            ("com.alibaba.dubbo.config.ApplicationConfig#checkKey", "removed"),
            ("com.alibaba.dubbo.rpc.RpcContext#<init>", "removed"),
            ("com.alibaba.dubbo.rpc.RpcContext#getServerContext", "signature-changed"),
            ("com.alibaba.dubbo.rpc.protocol.http.HttpRemoteInvocation", "removed"),
            ("com.alibaba.dubbo.common.Constants#GROUP_CHAR_SEPERATOR", "removed"),
            ("com.alibaba.dubbo.remoting.Transporter#bind", "signature-changed"),
            # A new abstract method breaks every implementer: not an addition.
            ("com.alibaba.com.caucho.hessian.io.AbstractHessianInput", "signature-changed"),
            ("com.alibaba.dubbo.rpc.Result.AbstractResult", "signature-changed"),
            # Reported twice by Roseau, recorded once.
            ("com.alibaba.dubbo.common.Constants", "signature-changed"),
        ]
        assert {(s.source, s.tool) for s in symbols} == {("api-diff", ROSEAU)}
        assert symbols[0].detail.startswith(
            "EXECUTABLE_REMOVED, binary and source breaking: "
            "org.apache.dubbo.config.AbstractConfig.checkKey("
        )

    async def test_without_roseau_the_diff_is_unavailable_and_says_how_to_get_it(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("C4_ROSEAU", "/nowhere/roseau")
        async with httpx.AsyncClient() as client:
            result = await diff(DUBBO, fetcher=Fetcher(client))
        assert result.state == "unavailable"
        assert "python -m c4.impact.tools install" in result.reason and not result.symbols


@pytest.mark.tools
@pytest.mark.skipif(roseau_launcher() is None, reason=f"{ROSEAU} is not installed")
async def test_roseau_finds_the_breaks_in_a_release_the_version_number_calls_a_patch() -> None:
    """The worked case: dubbo 2.7.3 to 2.7.21 is a patch by number and failed to compile."""
    launcher = roseau_launcher()
    assert launcher is not None
    result = await run_roseau(DUBBO, launcher)
    assert result.state == "ran", result.reason
    names = {symbol.symbol for symbol in result.symbols}
    assert "com.alibaba.dubbo.rpc.RpcContext#<init>" in names
    assert len(result.symbols) > 500
    assert "without their dependencies" in result.reason


OLD = """/** The client. */
export declare function connect(url: string): Client;
export declare function legacy(): void;
export declare class Client {
    constructor(url: string);
    /** Opens the connection. */
    open(): Promise<void>;
    close(): void;
}
export interface Options { retries?: number; }
declare function internal(): void;
export { internal as helper };
"""

NEW = """export declare function connect(url: string, options?: Options): Client;
export declare class Client {
    constructor(url: string, options?: Options);
    // Documented differently, and otherwise the same.
    open(): Promise<void>;
}
export interface Options { retries?: number; timeout?: number; }
"""


class TestDeclarations:
    def test_exports_and_their_members_are_read_with_their_declarations(self) -> None:
        found = declarations({"index.d.ts": OLD})
        assert set(found) == {
            "connect",
            "legacy",
            "Client",
            "Client#<init>",
            "Client#open",
            "Client#close",
            "Options",
            "Options#retries",
            "helper",
        }
        assert "internal" not in found

    def test_what_was_removed_or_changed_and_nothing_else(self) -> None:
        changes = declaration_changes(
            declarations({"index.d.ts": OLD}),
            declarations({"index.d.ts": NEW}),
            update_id=ACME.id,
        )
        assert [(c.symbol, c.kind) for c in changes] == [
            ("Client#<init>", "signature-changed"),
            ("Client#close", "removed"),
            ("connect", "signature-changed"),
            ("helper", "removed"),
            ("legacy", "removed"),
        ]
        assert all(c.tool == "declaration-diff/1" for c in changes)


def _tarball(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"package/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return gzip.compress(buffer.getvalue())


def _registry(old: dict[str, str], new: dict[str, str]) -> httpx.MockTransport:
    tarballs = {
        "https://registry.npmjs.org/acme/-/acme-1.0.0.tgz": _tarball(old),
        "https://registry.npmjs.org/acme/-/acme-2.0.0.tgz": _tarball(new),
    }
    document = {
        "name": "acme",
        "dist-tags": {"latest": "2.0.0"},
        "versions": {
            version: {"dist": {"tarball": f"https://registry.npmjs.org/acme/-/acme-{version}.tgz"}}
            for version in ("1.0.0", "2.0.0")
        },
    }

    def answer(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://registry.npmjs.org/acme":
            return httpx.Response(200, json=document)
        if url in tarballs:
            return httpx.Response(200, content=tarballs[url])
        return httpx.Response(404)

    return httpx.MockTransport(answer)


ACME = _update("npm", "acme", "1.0.0", "2.0.0", "major")


class TestNpmPackages:
    async def test_the_declarations_both_tarballs_ship_are_compared(self) -> None:
        transport = _registry(
            {"package.json": "{}", "dist/index.d.ts": OLD, "dist/index.js": ""},
            {"package.json": "{}", "dist/index.d.ts": NEW, "dist/index.js": ""},
        )
        async with httpx.AsyncClient(transport=transport) as client:
            result = await npm_diff(ACME, Fetcher(client))
        assert result.state == "ran"
        assert {s.symbol for s in result.symbols} == {
            "Client#<init>",
            "Client#close",
            "connect",
            "helper",
            "legacy",
        }

    async def test_a_package_without_declarations_has_no_diff_and_says_why(self) -> None:
        transport = _registry({"index.js": ""}, {"index.js": ""})
        async with httpx.AsyncClient(transport=transport) as client:
            result = await npm_diff(ACME, Fetcher(client))
        assert result.state == "unavailable"
        assert "no type declarations in either release" in result.reason

    async def test_declarations_in_one_release_only_are_not_a_diff(self) -> None:
        transport = _registry({"index.js": ""}, {"index.d.ts": NEW})
        async with httpx.AsyncClient(transport=transport) as client:
            result = await npm_diff(ACME, Fetcher(client))
        assert result.state == "unavailable" and "one of the two releases" in result.reason


async def test_a_release_pairs_diff_is_run_once_and_read_back_after(tmp_path) -> None:
    """Two released versions never change, so Roseau runs once per pair."""
    runs = tmp_path / "runs"
    launcher = tmp_path / "roseau"
    launcher.write_text(
        "#!/bin/sh\n"
        f"echo run >> {runs}\n"
        'for arg in "$@"; do case "$arg" in JSON=*) out="${arg#JSON=}";; esac; done\n'
        f'cp {FIXTURE} "$out"\n'
    )
    launcher.chmod(0o755)
    first = await run_roseau(DUBBO, launcher, cache_dir=tmp_path / "cache")
    second = await run_roseau(DUBBO, launcher, cache_dir=tmp_path / "cache")
    assert runs.read_text().count("run") == 1
    assert [s.symbol for s in first.symbols] == [s.symbol for s in second.symbols]
    assert second.reason.endswith("read from the cache") and not first.reason.endswith("cache")
