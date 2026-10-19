"""The npm registry and Maven Central, answered from recorded shapes.

No test here reaches the network: every answer comes from a mock transport, in
the shape the real registry returns it. What is under test is what intake makes
of an answer, including the answers that are not a package: a 404, a 500, and
nothing at all, each of which becomes a reason rather than an exception.
"""

import json
from pathlib import Path

import httpx
import pytest
from c4.intake import maven_central, npm_registry
from c4.intake.cache import Cache
from c4.intake.fetch import Fetcher
from c4.intake.npm_registry import NotFound, github_repository

EXPRESS = {
    "name": "express",
    "dist-tags": {"latest": "5.1.0"},
    "repository": {"type": "git", "url": "git+https://github.com/expressjs/express.git"},
    "time": {
        "created": "2010-12-29T19:38:25.450Z",
        "modified": "2025-03-31T14:00:00.000Z",
        "4.21.2": "2024-12-05T23:04:22.000Z",
        "5.0.0": "2024-09-10T00:00:00.000Z",
        "5.1.0": "2025-03-31T13:00:00.000Z",
    },
    "versions": {
        version: {
            "dist": {"tarball": f"https://registry.npmjs.org/express/-/express-{version}.tgz"}
        }
        for version in ("4.21.2", "5.0.0", "5.1.0")
    },
}

DUBBO_METADATA = b"""<?xml version="1.0" encoding="UTF-8"?>
<metadata>
  <groupId>org.apache.dubbo</groupId>
  <artifactId>dubbo</artifactId>
  <versioning>
    <latest>2.7.21</latest>
    <release>2.7.21</release>
    <versions><version>2.7.3</version><version>2.7.21</version></versions>
  </versioning>
</metadata>
"""

DUBBO_POM = b"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <scm><url>https://github.com/apache/dubbo</url></scm>
</project>
"""


def _transport(seen: list[str]) -> httpx.MockTransport:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        path = request.url.path
        if path == "/express":
            return httpx.Response(200, json=EXPRESS)
        # The raw path, because `path` is decoded and would hide whether the
        # slash in a scoped name was sent encoded, which the registry needs.
        if request.url.raw_path == b"/@vitejs%2Fplugin-react":
            return httpx.Response(200, json={**EXPRESS, "name": "@vitejs/plugin-react"})
        if path == "/flaky":
            return httpx.Response(503)
        if path == "/unplugged":
            raise httpx.ConnectError("no route to host")
        if path.endswith("/dubbo/maven-metadata.xml"):
            return httpx.Response(200, content=DUBBO_METADATA)
        if path.endswith("/dubbo-2.7.21.pom"):
            return httpx.Response(200, content=DUBBO_POM)
        return httpx.Response(404)

    return httpx.MockTransport(answer)


@pytest.fixture
def seen() -> list[str]:
    return []


@pytest.fixture
def fetcher(seen) -> Fetcher:
    return Fetcher(httpx.AsyncClient(transport=_transport(seen)))


class TestTheNpmRegistry:
    async def test_a_package_document_is_read_in_publish_order(self, fetcher) -> None:
        package = await npm_registry.fetch(fetcher, "express")
        assert not isinstance(package, NotFound)
        assert package.versions == ("5.0.0", "4.21.2", "5.1.0")
        assert package.latest == "5.1.0"
        assert package.published["5.1.0"].year == 2025
        assert package.tarballs["4.21.2"].endswith("express-4.21.2.tgz")
        assert package.repository is not None and package.repository.url == (
            "https://github.com/expressjs/express"
        )

    async def test_a_scoped_name_is_asked_for_with_its_slash_encoded(self, fetcher, seen) -> None:
        package = await npm_registry.fetch(fetcher, "@vitejs/plugin-react")
        assert not isinstance(package, NotFound)
        assert seen == ["https://registry.npmjs.org/@vitejs%2Fplugin-react"]

    @pytest.mark.parametrize(
        ("name", "reason"),
        [
            ("nothing-here", "package-not-found"),
            ("flaky", "registry-unreachable"),
            ("unplugged", "registry-unreachable"),
        ],
    )
    async def test_an_answer_that_is_not_a_package_is_a_reason(self, fetcher, name, reason) -> None:
        found = await npm_registry.fetch(fetcher, name)
        assert isinstance(found, NotFound)
        assert found.reason == reason
        assert found.detail

    async def test_every_question_is_recorded(self, fetcher) -> None:
        await npm_registry.fetch(fetcher, "express")
        await npm_registry.fetch(fetcher, "unplugged")
        assert [(q.registry, q.status) for q in fetcher.queries] == [("npm", 200), ("npm", None)]


class TestMavenCentral:
    async def test_metadata_lists_the_versions_and_the_pom_names_the_repository(
        self, fetcher
    ) -> None:
        artifact = await maven_central.fetch(fetcher, "org.apache.dubbo:dubbo")
        assert not isinstance(artifact, NotFound)
        assert artifact.versions == ("2.7.3", "2.7.21")
        assert artifact.release == "2.7.21"
        assert artifact.repository is not None and artifact.repository.name == "dubbo"

    async def test_an_unknown_artifact_is_a_reason(self, fetcher) -> None:
        found = await maven_central.fetch(fetcher, "org.example:nothing")
        assert isinstance(found, NotFound) and found.reason == "package-not-found"


class TestTheCache:
    async def test_a_stable_answer_is_read_back_with_its_first_retrieval_time(
        self, seen, tmp_path: Path
    ) -> None:
        first = Fetcher(httpx.AsyncClient(transport=_transport(seen)), cache=Cache(tmp_path))
        await npm_registry.fetch(first, "express")
        second = Fetcher(httpx.AsyncClient(transport=_transport(seen)), cache=Cache(tmp_path))
        await npm_registry.fetch(second, "express")

        assert len(seen) == 1, "the second run asked the registry again"
        assert second.queries[0].note == "from the cache"
        assert second.queries[0].at == first.queries[0].at

    async def test_a_bad_minute_is_not_remembered(self, seen, tmp_path: Path) -> None:
        for _ in range(2):
            fetcher = Fetcher(httpx.AsyncClient(transport=_transport(seen)), cache=Cache(tmp_path))
            await npm_registry.fetch(fetcher, "flaky")
        assert len(seen) == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("git+https://github.com/expressjs/express.git", ("expressjs", "express", "")),
        ("git://github.com/owner/repo.git", ("owner", "repo", "")),
        ("github:owner/repo", ("owner", "repo", "")),
        ("owner/repo", ("owner", "repo", "")),
        (
            {
                "url": "https://github.com/vitejs/vite-plugin-react.git",
                "directory": "packages/plugin-react",
            },
            ("vitejs", "vite-plugin-react", "packages/plugin-react"),
        ),
        ("https://gitlab.com/owner/repo", None),
        (None, None),
    ],
)
def test_a_repository_field_in_any_form_npm_allows(raw, expected) -> None:
    found = github_repository(raw)
    assert (None if found is None else (found.owner, found.name, found.directory)) == expected


def test_the_recorded_express_document_is_well_formed() -> None:
    assert json.loads(json.dumps(EXPRESS))["dist-tags"]["latest"] == "5.1.0"
