"""The app boots, answers, and speaks the shapes the browser expects.

Everything here runs over httpx's ASGI transport, so there is no server to start
and no port to pick, which is what keeps these fast enough to run on every save.
"""

from pathlib import Path

import httpx
import pytest
from orchestrator.config import Settings
from orchestrator.errors import Conflict, DomainError, NotFound
from orchestrator.main import PROVIDER_KEYS, create_app, resolve_provider_key
from pydantic import ValidationError


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql://sdlc:sdlc@localhost:5432/sdlc",
        cors_origins=["http://localhost:5173"],
    )


@pytest.fixture
async def client(settings: Settings):
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_cors_origins_accept_the_format_the_env_example_documents() -> None:
    """A plain comma separated list, which is what anyone writes in a .env.

    This regressed the moment a real .env carried CORS_ORIGINS: pydantic-settings
    JSON-decodes a list field before any validator runs, so the documented format
    raised a parse error and every route failed at import.
    """
    assert Settings(cors_origins="http://a.test, http://b.test").cors_origins == [
        "http://a.test",
        "http://b.test",
    ]
    assert Settings(cors_origins='["http://c.test"]').cors_origins == ["http://c.test"]
    assert Settings(cors_origins=["http://d.test"]).cors_origins == ["http://d.test"]


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_cors_allows_the_dev_origin(client: httpx.AsyncClient) -> None:
    """The browser calls this cross origin in development, so a missing header
    is a blank page rather than an error anyone can read."""
    response = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_cors_refuses_an_unknown_origin(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/health",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


class TestErrorEnvelope:
    """The frontend's HttpError carries the parsed JSON body, so the body is the
    only place a caller learns why. One shape, always."""

    @pytest.fixture
    async def failing_client(self, settings: Settings):
        app = create_app(settings)

        @app.get("/boom/{kind}")
        async def boom(kind: str) -> None:
            if kind == "missing":
                raise NotFound("project", "p9")
            if kind == "conflict":
                raise Conflict("a run is already in flight for this project")
            if kind == "unexpected":
                raise RuntimeError("cannot open /home/someone/projects/research/.env")
            raise DomainError("plain refusal")

        # The server sees an unexpected error raised on after the answer, as
        # uvicorn does to log it; the browser sees only the answer.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    async def test_not_found(self, failing_client: httpx.AsyncClient) -> None:
        response = await failing_client.get("/boom/missing")
        assert response.status_code == 404
        assert response.json() == {"error": "project p9 does not exist"}

    async def test_conflict(self, failing_client: httpx.AsyncClient) -> None:
        response = await failing_client.get("/boom/conflict")
        assert response.status_code == 409
        assert "already in flight" in response.json()["error"]

    async def test_plain_domain_error(self, failing_client: httpx.AsyncClient) -> None:
        response = await failing_client.get("/boom/other")
        assert response.status_code == 400
        assert response.json() == {"error": "plain refusal"}

    async def test_an_unexpected_error_reaches_the_browser_as_an_answer(
        self, failing_client: httpx.AsyncClient
    ) -> None:
        """Starlette answers an unhandled exception outside every middleware the app
        adds, CORS included, so the browser got a 500 without CORS headers and
        reported "Failed to fetch": the page could not tell the server had answered."""
        response = await failing_client.get(
            "/boom/unexpected", headers={"Origin": "http://localhost:5173"}
        )

        assert response.status_code == 500
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
        body = response.json()
        assert set(body) == {"error"}
        # What went wrong stays in the server's log: it named a path on the server.
        assert "/home/" not in body["error"]

    async def test_an_address_with_nothing_there_answers_in_the_envelope(
        self, failing_client: httpx.AsyncClient
    ) -> None:
        response = await failing_client.get("/no/such/route")

        assert response.status_code == 404
        assert response.json() == {"error": "There is nothing at this address."}


class TestSettings:
    def test_origins_split_from_a_comma_list(self) -> None:
        """Environment variables are strings, and a list in one is a comma
        list, not JSON."""
        s = Settings(cors_origins="http://a.test, http://b.test")  # type: ignore[arg-type]
        assert s.cors_origins == ["http://a.test", "http://b.test"]

    def test_checkpointer_prefers_the_direct_url(self) -> None:
        s = Settings(
            database_url="postgresql://pooled/db",
            database_direct_url="postgresql://direct/db",
        )
        assert s.checkpointer_url == "postgresql://direct/db"

    def test_checkpointer_falls_back_to_the_pooled_url(self) -> None:
        """The compose path has one host, so a separate direct URL would be the
        same string twice."""
        s = Settings(database_url="postgresql://only/db", database_direct_url="")
        assert s.checkpointer_url == "postgresql://only/db"


class TestTheProviderKeyGate:
    """Which key the orchestrator demands comes from C1_MODEL's prefix.

    Worth pinning because a wrong mapping is not a failed request, it is a server
    that will not start, and both providers stay installed so a comparison run
    costs one line in `.env`. That means both keys are normally set at once, and
    the wrong one must not answer for the right one.
    """

    DB = "postgresql://sdlc:sdlc@localhost:5432/sdlc"

    def test_an_anthropic_model_wants_the_anthropic_key(self) -> None:
        settings = Settings(
            database_url=self.DB,
            c1_model="anthropic:claude-sonnet-5",
            anthropic_api_key="a-key",
        )
        assert resolve_provider_key(settings) == ("ANTHROPIC_API_KEY", "a-key")

    def test_a_groq_model_wants_the_groq_key(self) -> None:
        """The free tier stays reachable for comparison runs."""
        settings = Settings(
            database_url=self.DB,
            c1_model="groq:any-model",
            groq_api_key="g-key",
        )
        assert resolve_provider_key(settings) == ("GROQ_API_KEY", "g-key")

    def test_the_other_provider_key_does_not_satisfy_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Having both keys set is the normal state, not an escape hatch.

        The empty `anthropic_api_key` is the point of the test, so it is passed
        rather than left to default: `Settings` reads the repository `.env`, and
        a developer who has filled in a real key would otherwise silently turn
        this into a test that asserts nothing. `delenv` closes the same hole in
        the ambient environment, which the resolver falls back to.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        settings = Settings(
            database_url=self.DB,
            c1_model="anthropic:claude-sonnet-5",
            anthropic_api_key="",
            groq_api_key="g-key",
        )
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            resolve_provider_key(settings)

    def test_an_unknown_provider_names_the_ones_that_work(self) -> None:
        """The message has to be actionable: the fix is always one variable.

        Derived from the map rather than written out, because this assertion was
        pinned to "anthropic, groq" and broke the day two providers were added,
        which teaches the next reader to update the literal rather than to check
        that the message is still useful.

        The unknown provider is a name nothing will ever be called. It used to
        be `deepseek`, which broke the day deepseek was added: an example of a
        thing that does not exist has to be chosen so that it cannot start
        existing.
        """
        settings = Settings(database_url=self.DB, c1_model="nosuchprovider:some-model")
        with pytest.raises(RuntimeError) as raised:
            resolve_provider_key(settings)

        message = str(raised.value)
        assert "nosuchprovider" in message, "it has to say which provider was asked for"
        for provider in PROVIDER_KEYS:
            assert provider in message, f"{provider} is wired but the message omits it"


class TestTheModelStringIsCheckedAtStartup:
    """A stray character in C1_MODEL, refused before a run pays for it.

    A trailing comma in `.env` produced two 404s reading `model:
    claude-haiku-4-5-20251001,` and looked exactly like Haiku not existing. The
    comma sat at the end of the real name, invisible unless you were looking for
    it, and the model was never actually tested.

    Same principle as the provider key gate: a configuration mistake fails when
    the process starts, not on the first request.
    """

    DB = "postgresql://sdlc:sdlc@localhost:5432/sdlc"

    def settings(self, model: str) -> Settings:
        return Settings(database_url=self.DB, c1_model=model, anthropic_api_key="k")

    def test_a_well_formed_string_is_kept_exactly(self) -> None:
        assert self.settings("anthropic:claude-haiku-4-5").c1_model == "anthropic:claude-haiku-4-5"

    @pytest.mark.parametrize(
        "raw",
        [
            "  anthropic:claude-sonnet-5  ",
            '"anthropic:claude-sonnet-5"',
            "'anthropic:claude-sonnet-5'",
        ],
    )
    def test_wrapping_whitespace_and_quotes_are_stripped(self, raw: str) -> None:
        # A quoted value is how a .env is often written, and a trailing space is
        # the same mistake as the comma but harder to see.
        assert self.settings(raw).c1_model == "anthropic:claude-sonnet-5"

    def test_the_comma_that_caused_this_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="','"):
            self.settings("anthropic:claude-haiku-4-5-20251001,")

    def test_a_stray_character_is_refused_rather_than_cleaned(self) -> None:
        # Deleting it quietly would hide that the line was wrong, and the next
        # reader would find a model they did not choose.
        with pytest.raises(ValidationError):
            self.settings("anthropic:claude sonnet 5")

    def test_a_string_naming_no_provider_is_refused(self) -> None:
        # The prefix is what selects the provider and its key, so a bare model
        # name has nowhere to go.
        with pytest.raises(ValidationError, match="names no provider"):
            self.settings("claude-sonnet-5")

    def test_an_empty_string_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            self.settings("")


class TestEveryWiredProviderIsWiredCompletely:
    """A provider needs three things, and two of them fail quietly.

    The extra in C1's dependencies, a field on `Settings`, and an entry in
    `PROVIDER_KEYS`. Miss the entry and the orchestrator refuses to start with a
    clear message. Miss the field and `resolve_provider_key` reads an attribute
    that is not there, falls back to the ambient environment, and a developer with
    a stale export in their shell gets a run they cannot reproduce.

    The field name has to be the lowercase of the variable, because that is how
    `resolve_provider_key` finds it. Nothing else enforces that.
    """

    DB = "postgresql://sdlc:sdlc@localhost:5432/sdlc"

    def test_each_gate_entry_has_a_settings_field_named_after_it(self) -> None:
        for provider, variable in PROVIDER_KEYS.items():
            field = variable.lower()
            assert field in Settings.model_fields, (
                f"{provider!r} maps to {variable}, so Settings needs a {field!r} field "
                "or its key can only come from the ambient environment"
            )

    @pytest.mark.parametrize("provider", sorted(PROVIDER_KEYS))
    def test_a_key_set_in_settings_is_the_one_used(self, provider: str) -> None:
        variable = PROVIDER_KEYS[provider]
        settings = Settings(
            database_url=self.DB,
            c1_model=f"{provider}:a-model",
            **{variable.lower(): "from-settings"},
        )
        assert resolve_provider_key(settings) == (variable, "from-settings")

    def test_the_providers_wired_here_are_the_ones_documented(self) -> None:
        # .env.example lists a key per provider. A provider wired in code but
        # absent there is one nobody knows they can use.
        example = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
        for variable in PROVIDER_KEYS.values():
            assert f"{variable}=" in example, f"{variable} is wired but not in .env.example"


class TestTheMeteredLane:
    """DeepSeek, added because every free lane this study ran on has a daily
    request cap and its prompted arm was cut short four times by one. The
    provider documents concurrency limits and no request cap, and every arm
    here runs sequentially.
    """

    DB = "postgresql://sdlc:sdlc@localhost:5432/sdlc"

    def test_a_deepseek_model_wants_the_deepseek_key(self) -> None:
        settings = Settings(
            database_url=self.DB,
            c1_model="deepseek:deepseek-flash",
            deepseek_api_key="d-key",
        )

        assert resolve_provider_key(settings) == ("DEEPSEEK_API_KEY", "d-key")

    def test_every_provider_in_the_table_has_a_field_to_read_it_from(self) -> None:
        """The resolver finds the key by lowercasing the variable name, so a
        provider in the table with no matching field would report a missing key
        for one that was set."""
        missing = [
            variable
            for variable in PROVIDER_KEYS.values()
            if variable.lower() not in Settings.model_fields
        ]

        assert missing == [], f"no settings field for: {', '.join(missing)}"


class TestWhatRunsWhenNobodyConfiguredAnything:
    """A default is what runs when somebody comments out a line in `.env`.

    C1's used to name a paid Anthropic model, so a missing line spent money
    silently on a project whose standing rule is that it never should. These
    tests are about the failure mode rather than the choice: whatever the
    default becomes, it must not be the lane kept for deliberate manual use.
    """

    def test_no_component_defaults_to_the_lane_reserved_for_manual_runs(self) -> None:
        settings = Settings(database_url="postgresql://sdlc:sdlc@localhost:5432/sdlc")

        for field in ("c1_model", "c2_model", "c3_model"):
            default = Settings.model_fields[field].default
            assert not default.startswith("anthropic:"), (
                f"{field} defaults to {default}, so a commented out .env line bills for a run "
                "nobody asked for"
            )
            assert settings  # the settings themselves may be overridden by .env, and that is fine

    def test_the_three_components_default_to_one_lane(self) -> None:
        """One place to change, and no component quietly on a different
        provider from the other two."""
        defaults = {
            field: Settings.model_fields[field].default
            for field in ("c1_model", "c2_model", "c3_model")
        }

        assert len(set(defaults.values())) == 1, defaults

    def test_the_default_names_a_provider_the_key_table_knows(self) -> None:
        """A default whose provider has no key mapping is a server that will
        not start, which is worse than one that starts and asks for a key."""
        provider = Settings.model_fields["c1_model"].default.split(":", 1)[0]

        assert provider in PROVIDER_KEYS
