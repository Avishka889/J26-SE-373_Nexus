"""The generated repository is a thing a person can run.

Not "it typechecks", which the sandbox already proves, and not "the scripts
exist", which asserts the shape of a file rather than the behaviour of a
program. This writes the generated files into an empty directory, installs,
builds and starts them exactly as somebody who cloned the repository would,
then asks the running process two questions: does the page load, and does the
API answer. Anything less would let "runnable" mean whatever the generator
happened to emit.

Marked `sandbox` and skipped without node, like the other tests that run the
real toolchain.
"""

import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest
from c2.codegen.api_gen import SAMPLE_VALUES
from c2.codegen.monorepo import generate_monorepo
from c2.codegen.naming import camel
from c2.contract.rule_arm import generate_rule_contract
from c2.contract.vocab import resource_of

from .design_fixture import graph, scope, wireframes

needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs node and npm")

#: Long enough for a cold install on a slow link, short enough to fail a hung
#: one rather than a whole suite.
INSTALL_TIMEOUT = 420
BUILD_TIMEOUT = 240
BOOT_TIMEOUT = 30


def _free_port() -> int:
    """A port the OS says is free, released before the child claims it.

    A small race, and the alternative is a fixed port that collides with
    whatever a developer already has running.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run(command: list[str], cwd, timeout: int, env: dict[str, str]) -> None:
    done = subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
    )
    assert done.returncode == 0, (
        f"{' '.join(command)} failed\n--- stdout ---\n{done.stdout[-2000:]}"
        f"\n--- stderr ---\n{done.stderr[-2000:]}"
    )


def _stop(server: subprocess.Popen) -> None:
    """Stop the process group and close its pipe.

    The pipe matters: an unclosed one is a ResourceWarning, and this suite
    turns warnings into errors, so a test that passed every assertion would
    still fail on the way out.
    """
    try:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(server.pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            try:
                server.wait(timeout=10)
                break
            except subprocess.TimeoutExpired:  # pragma: no cover - a stuck child
                continue
    finally:
        if server.stdout is not None:
            server.stdout.close()


def _get(url: str, timeout: float = 5.0):
    request = urllib.request.Request(url, headers={"Accept": "text/html,application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as answer:
        return answer.status, answer.headers.get("Content-Type", ""), answer.read().decode()


@pytest.mark.sandbox
@needs_npm
class TestAFreshCheckoutRuns:
    def test_install_build_start_then_the_page_and_the_api_answer(self, tmp_path) -> None:
        contract = generate_rule_contract(1, graph(), wireframes(), scope())
        files = generate_monorepo(
            "Runnable", contract, wireframes(), scope(), design_version=1, arm="rule"
        )
        checkout = tmp_path / "checkout"
        for generated in files.files:
            target = checkout / generated.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(generated.content)

        # The build sandbox's allowlist: enough to install and compile, and
        # none of the platform's own environment.
        build_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "CI": "1",
            "npm_config_cache": "/tmp/c2-npm-cache",
        }
        _run(["npm", "install", "--no-audit", "--no-fund"], checkout, INSTALL_TIMEOUT, build_env)
        _run(["npm", "run", "build"], checkout, BUILD_TIMEOUT, build_env)

        assert (checkout / "apps/web/dist/index.html").exists(), (
            "npm run build produced no frontend for the API to serve"
        )

        # And the styling reached the build. Tailwind emits only the utilities
        # it finds in the sources it was told to scan, so a wrong `@source`
        # path fails silently: the build passes, the stylesheet ships with
        # nothing but preflight in it, and the app looks exactly as unstyled as
        # it did before. Asserting a class the generated pages use is what
        # separates "Tailwind is installed" from "Tailwind is working".
        stylesheets = list((checkout / "apps/web/dist/assets").glob("*.css"))
        assert stylesheets, "the build produced no stylesheet"
        css = "\n".join(sheet.read_text() for sheet in stylesheets)
        assert ".rounded-panel" in css, "the token set did not reach the build"
        assert "--color-ink" in css, "no theme token survived, so nothing was scanned"
        assert ".text-accent" in css, "utilities from the generated pages were not emitted"

        port = _free_port()
        # The server's own allowlist, which is tighter: a long lived process
        # running generated code gets no HOME, no npm configuration and above
        # all none of this process's environment, which holds provider keys.
        server_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOST": "127.0.0.1",
            "PORT": str(port),
            "NODE_ENV": "production",
        }
        server = subprocess.Popen(
            ["npm", "start"],
            cwd=checkout,
            env=server_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + BOOT_TIMEOUT
            page = None
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise AssertionError(
                        f"the server exited with {server.returncode}\n{server.stdout.read()[-2000:]}"
                    )
                try:
                    page = _get(f"{base}/")
                    break
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    time.sleep(0.4)
            assert page is not None, f"nothing answered on {base} within {BOOT_TIMEOUT}s"

            # The page: the API served the frontend build, not a JSON 404.
            status, content_type, body = page
            assert status == 200
            assert "text/html" in content_type
            assert '<div id="root">' in body

            # The API: a contract endpoint answers on the same origin, which is
            # the whole reason one process serves both.
            collection = next(
                endpoint
                for endpoint in contract.endpoints
                if endpoint.method == "GET" and "{" not in endpoint.path
            )
            status, content_type, body = _get(f"{base}{collection.path}")
            assert status == 200
            assert "application/json" in content_type
            # In memory repositories, so an empty list is the correct answer.
            assert isinstance(json.loads(body), list)

            # A client side route falls back to the page rather than 404ing.
            status, content_type, _ = _get(f"{base}/some/client/route")
            assert status == 200
            assert "text/html" in content_type
        finally:
            # The group, not the process: `npm start` spawns node, and killing
            # only the wrapper leaves a server holding the port. `start_new_session`
            # makes the child its own group leader, so its pid is the group id and
            # `getpgid` is not needed, which matters because the wrapper may
            # already be gone by the time this runs.
            _stop(server)


@pytest.mark.sandbox
@needs_npm
class TestTheGeneratedAppOpensARecord:
    """Its own routes test opens a record by its address, under the real toolchain.

    The string checks say the confirmation page reads its order from its
    address; this says the code compiles, and that the page asks the API for
    the order its address names. Before, it asked for `/orders/id`.
    """

    def test_its_typecheck_and_its_own_tests_pass(self) -> None:
        from c2.sandbox import run_build

        contract = generate_rule_contract(1, graph(), wireframes(), scope())
        files = generate_monorepo(
            "Runnable", contract, wireframes(), scope(), design_version=1, arm="rule"
        )
        report = run_build({generated.path: generated.content for generated in files.files})

        failed = [step for step in report.steps if step.outcome != "passed"]
        assert failed == [], "\n".join(f"{step.name}: {step.log_tail[-1500:]}" for step in failed)
        assert "unit tests" in {step.name for step in report.steps}


#: The release Atlas's free tier runs ("free clusters stay on a major version
#: (currently, MongoDB 8.0)", Atlas's version docs, read 2026-10-01), pinned by
#: digest so the database under this test does not move on its own.
MONGO_IMAGE = "mongo:8.0@sha256:4968f22d0c6c10ef29952f3e807f62872ba22b3312f25803564fbfc08255efc2"


def _quietly(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


@pytest.fixture
def mongodb_url() -> Iterator[str]:
    """A throwaway MongoDB on a loopback port, removed with everything in it afterwards."""
    if shutil.which("docker") is None or _quietly(["docker", "version"], 30).returncode != 0:
        pytest.skip("needs a Docker daemon")
    if _quietly(["docker", "image", "inspect", MONGO_IMAGE], 30).returncode != 0:
        pulled = _quietly(["docker", "pull", MONGO_IMAGE], 600)
        if pulled.returncode != 0:
            pytest.skip(f"{MONGO_IMAGE} could not be pulled: {pulled.stderr.strip()[-200:]}")
    run = ["docker", "run", "-d", "--rm", "--label", "sdlc.c2.lane=test"]
    started = _quietly([*run, "-p", "127.0.0.1::27017", MONGO_IMAGE], 120)
    assert started.returncode == 0, started.stderr
    container = started.stdout.strip()
    try:
        mapped = _quietly(["docker", "port", container, "27017/tcp"], 30).stdout
        port = mapped.strip().splitlines()[0].rsplit(":", 1)[1]
        ping = [
            "docker",
            "exec",
            container,
            "mongosh",
            "--quiet",
            "--eval",
            "db.runCommand({ping: 1}).ok",
        ]
        deadline = time.monotonic() + 60
        while _quietly(ping, 30).stdout.strip() != "1":
            assert time.monotonic() < deadline, "MongoDB did not answer within a minute"
            time.sleep(0.5)
        yield f"mongodb://127.0.0.1:{port}/runnable"
    finally:
        _quietly(["docker", "rm", "-f", container], 60)


@contextlib.contextmanager
def _serving(checkout, extra: dict[str, str]) -> Iterator[tuple[str, list[str]]]:
    """The built app started as `npm start` would start it, and what it said once stopped."""
    port = _free_port()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "NODE_ENV": "production",
        **extra,
    }
    server = subprocess.Popen(
        ["npm", "start"],
        cwd=checkout,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    said: list[str] = []
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + BOOT_TIMEOUT
        while True:
            assert server.poll() is None, f"the server exited with {server.returncode}"
            try:
                _get(f"{base}/")
                break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                assert time.monotonic() < deadline, f"nothing answered on {base}"
                time.sleep(0.4)
        yield base, said
    finally:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(server.pid, signal.SIGTERM)
        try:
            out, _ = server.communicate(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - a stuck child
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(server.pid, signal.SIGKILL)
            out, _ = server.communicate()
        said.append(out or "")


def _json(url: str, body: object | None = None) -> tuple[int, object]:
    """The status and the JSON answer, a 404 included."""
    request = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status, json.loads(answer.read().decode())
    except urllib.error.HTTPError as refused:
        with refused:
            return refused.code, json.loads(refused.read().decode() or "null")


@pytest.mark.sandbox
@pytest.mark.docker
@needs_npm
class TestTheRecordsOutliveARestart:
    def test_a_database_keeps_them_memory_does_not_and_the_tests_stay_in_memory(
        self, tmp_path, mongodb_url
    ) -> None:
        contract = generate_rule_contract(1, graph(), wireframes(), scope())
        files = generate_monorepo(
            "Kept", contract, wireframes(), scope(), design_version=1, arm="rule"
        )
        checkout = tmp_path / "checkout"
        for generated in files.files:
            target = checkout / generated.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(generated.content)
        build_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "CI": "1",
            "npm_config_cache": "/tmp/c2-npm-cache",
        }
        _run(["npm", "install", "--no-audit", "--no-fund"], checkout, INSTALL_TIMEOUT, build_env)
        _run(["npm", "run", "build"], checkout, BUILD_TIMEOUT, build_env)

        create = next(
            endpoint
            for endpoint in contract.endpoints
            if endpoint.method == "POST" and "{" not in endpoint.path
        )
        read = next(
            endpoint
            for endpoint in contract.endpoints
            if endpoint.method == "GET" and endpoint.path == f"{create.path}/{{id}}"
        )
        entity = next(
            one for one in contract.entities if resource_of(one.name) == create.path.strip("/")
        )
        body = {
            camel(field.name): json.loads(SAMPLE_VALUES[field.type])
            for field in entity.fields
            if field.name != "id"
        }
        url = mongodb_url

        def one(base: str, made: object) -> tuple[int, object]:
            assert isinstance(made, dict) and made["id"]
            return _json(f"{base}{read.path.replace('{id}', str(made['id']))}")

        with _serving(checkout, {"MONGODB_URL": url}) as (base, first_said):
            status, made = _json(f"{base}{create.path}", body)
            assert status == 201
        with _serving(checkout, {"MONGODB_URL": url}) as (base, _):
            assert one(base, made) == (200, made), "the database kept it past a restart"
        assert "records kept in the MongoDB database" in first_said[0]

        with _serving(checkout, {}) as (base, memory_said):
            status, made = _json(f"{base}{create.path}", body)
            assert status == 201
            assert one(base, made) == (200, made)
        with _serving(checkout, {}) as (base, _):
            assert one(base, made)[0] == 404, "memory keeps nothing past a restart"
        assert "records kept in memory" in memory_said[0]

        # A database exported in the shell does not reach the tests: this one
        # answers nowhere, so a test that tried it would fail on its timeout.
        _run(
            ["npm", "test", "--workspace", "@app/api"],
            checkout,
            BUILD_TIMEOUT,
            {**build_env, "MONGODB_URL": "mongodb://127.0.0.1:9/nowhere"},
        )
