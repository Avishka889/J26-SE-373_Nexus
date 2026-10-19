"""Release notes, found where projects keep them and cut to the update's window.

The window is the claim that matters: after the installed version, never
including it, and up to the target, always including it. A release outside it
describes a change this update does not make.
"""

import base64
import gzip
import hashlib
import io
import tarfile

import httpx
import pytest
from c4.intake import releases
from c4.intake.fetch import Fetcher
from c4.intake.npm_registry import Repository
from c4.intake.releases import in_window, release_notes, tag_version

EXPRESS = Repository("expressjs", "express")

RELEASES = [
    {"tag_name": "v5.2.0", "body": "- A later release the update does not reach."},
    {"tag_name": "v5.1.0", "body": "- Added `res.links` overloads."},
    {"tag_name": "v5.0.0", "body": "- Removed `app.del`, use `app.delete` instead."},
    {"tag_name": "v5.0.0-beta.1", "body": "- Dropped support for Node 16."},
    {"tag_name": "v4.21.2", "body": "- The installed release, not part of the update."},
    {"tag_name": "v4.21.1", "body": ""},
]

HISTORY = """# History

## 5.1.0
- Added `res.links` overloads.

## 5.0.0
- Removed `app.del`.

## 4.21.2
- The installed release.
"""


def _tarball(files: dict[str, str]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as archive:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"package/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue())


def _fetcher(routes: dict[str, httpx.Response]) -> Fetcher:
    def answer(request: httpx.Request) -> httpx.Response:
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                return response
        return httpx.Response(404)

    return Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(answer)))


RELEASES_URL = "https://api.github.com/repos/expressjs/express/releases"


class TestTheWindow:
    @pytest.mark.parametrize(
        ("version", "inside"),
        [
            ("4.21.2", False),
            ("5.0.0-beta.1", True),
            ("5.0.0", True),
            ("5.1.0", True),
            ("5.2.0", False),
        ],
    )
    def test_after_the_installed_version_and_up_to_the_target(self, version, inside) -> None:
        assert in_window("npm", version, "4.21.2", "5.1.0") is inside

    def test_maven_releases_are_windowed_by_maven_order(self) -> None:
        assert in_window("maven", "2.7.10", "2.7.3", "2.7.21")
        assert not in_window("maven", "2.7.3", "2.7.3", "2.7.21")


@pytest.mark.parametrize(
    ("tag", "package", "version"),
    [
        ("v5.0.0", "express", "5.0.0"),
        ("5.0.0", "express", "5.0.0"),
        ("@vitejs/plugin-react@4.3.0", "@vitejs/plugin-react", "4.3.0"),
        ("plugin-react@4.3.0", "@vitejs/plugin-react", "4.3.0"),
        ("dubbo-2.7.21", "org.apache.dubbo:dubbo", "2.7.21"),
    ],
)
def test_a_tag_names_a_version_as_projects_write_them(tag, package, version) -> None:
    assert tag_version(tag, package) == version


class TestWhereNotesAreFound:
    async def test_github_releases_inside_the_window_newest_first(self) -> None:
        fetcher = _fetcher({RELEASES_URL: httpx.Response(200, json=RELEASES)})
        notes = await release_notes(
            fetcher,
            ecosystem="npm",
            package="express",
            old="4.21.2",
            new="5.1.0",
            repository=EXPRESS,
        )
        assert [s.version for s in notes.sections] == ["5.1.0", "5.0.0", "5.0.0-beta.1"]
        assert [ref.source for ref in notes.refs] == ["github-release"]

    async def test_what_is_stored_is_what_is_hashed(self) -> None:
        fetcher = _fetcher({RELEASES_URL: httpx.Response(200, json=RELEASES)})
        notes = await release_notes(
            fetcher,
            ecosystem="npm",
            package="express",
            old="4.21.2",
            new="5.1.0",
            repository=EXPRESS,
        )
        ref = notes.refs[0]
        stored = notes.texts[ref.path]
        assert ref.sha256 == hashlib.sha256(stored.encode()).hexdigest()
        assert "Removed `app.del`" in stored and "installed release" not in stored

    async def test_a_repository_changelog_when_the_releases_say_nothing(self) -> None:
        content = base64.b64encode(HISTORY.encode()).decode()
        fetcher = _fetcher(
            {
                RELEASES_URL: httpx.Response(200, json=[{"tag_name": "v5.0.0", "body": ""}]),
                "https://api.github.com/repos/expressjs/express/contents/History.md": httpx.Response(
                    200,
                    json={
                        "encoding": "base64",
                        "content": content,
                        "html_url": "https://github.com/x",
                    },
                ),
            }
        )
        notes = await release_notes(
            fetcher,
            ecosystem="npm",
            package="express",
            old="4.21.2",
            new="5.1.0",
            repository=EXPRESS,
        )
        assert [s.version for s in notes.sections] == ["5.1.0", "5.0.0"]
        assert notes.refs[0].source == "changelog-file"

    async def test_a_changelog_in_the_tarball_when_there_is_no_repository(self) -> None:
        tarball = "https://registry.npmjs.org/express/-/express-5.1.0.tgz"
        fetcher = _fetcher(
            {tarball: httpx.Response(200, content=_tarball({"History.md": HISTORY}))}
        )
        notes = await release_notes(
            fetcher,
            ecosystem="npm",
            package="express",
            old="4.21.2",
            new="5.1.0",
            repository=None,
            tarball=tarball,
        )
        assert [s.version for s in notes.sections] == ["5.1.0", "5.0.0"]

    async def test_nothing_anywhere_is_an_honest_nothing(self) -> None:
        notes = await release_notes(
            _fetcher({}),
            ecosystem="npm",
            package="express",
            old="4.21.2",
            new="5.1.0",
            repository=EXPRESS,
        )
        assert not notes.found and notes.texts == {}

    async def test_a_long_window_is_cut_and_says_so(self, monkeypatch) -> None:
        monkeypatch.setattr(releases, "MAX_CHARS", 40)
        fetcher = _fetcher({RELEASES_URL: httpx.Response(200, json=RELEASES)})
        notes = await release_notes(
            fetcher,
            ecosystem="npm",
            package="express",
            old="4.21.2",
            new="5.1.0",
            repository=EXPRESS,
        )
        assert notes.refs[0].truncated and notes.refs[0].chars == 40


LIMITED = httpx.Response(403, json={"message": "API rate limit exceeded for 203.0.113.9."})


class TestGitHubsRateLimit:
    """A limit is not a release without notes, and is never reported as one."""

    async def test_a_rate_limit_is_recorded_as_why_no_notes_were_read(self) -> None:
        notes = await release_notes(
            _fetcher({"https://api.github.com/": LIMITED}),
            ecosystem="npm",
            package="express",
            old="4.21.2",
            new="5.1.0",
            repository=EXPRESS,
        )
        assert not notes.found
        assert notes.unavailable.startswith("GitHub answered with its rate limit")

    async def test_the_tarball_is_still_read_when_github_is_limited(self) -> None:
        tarball = "https://registry.npmjs.org/express/-/express-5.1.0.tgz"
        notes = await release_notes(
            _fetcher(
                {
                    "https://api.github.com/": LIMITED,
                    tarball: httpx.Response(200, content=_tarball({"History.md": HISTORY})),
                }
            ),
            ecosystem="npm",
            package="express",
            old="4.21.2",
            new="5.1.0",
            repository=EXPRESS,
            tarball=tarball,
        )
        assert notes.found and notes.unavailable == ""
        assert [s.version for s in notes.sections] == ["5.1.0", "5.0.0"]

    async def test_a_plain_forbidden_is_not_taken_for_a_limit(self) -> None:
        notes = await release_notes(
            _fetcher({"https://api.github.com/": httpx.Response(403, json={"message": "no"})}),
            ecosystem="npm",
            package="express",
            old="4.21.2",
            new="5.1.0",
            repository=EXPRESS,
        )
        assert notes.unavailable == ""
