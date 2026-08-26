"""Configuration, read from the environment and nowhere else.

Two database URLs on purpose. The application uses the pooled one; the LangGraph
checkpointer needs the direct one, because it holds its own connections and a
transaction pooler breaks the session state it depends on. Everything else about
which database is in play, a developer's own Neon branch or the compose Postgres
for CI, is decided by these two values alone.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: The repository root, so `.env` is found from any working directory. Alembic
#: runs from `orchestrator/` and pytest from the root, and both need the same
#: database.
REPO_ROOT = Path(__file__).resolve().parents[2]


#: What every component runs on when `.env` says nothing.
#:
#: One lane for all three, named once. It probed SUITABLE on C1, C2 and C3, it
#: supports the forced tool calls every structured output here depends on, and
#: it has no daily request cap, which is what stopped four evaluation passes on
#: free tiers before it. `deepseek-flash` and never `deepseek-reasoner`: thinking
#: mode refuses a forced tool choice with a 400.
DEFAULT_MODEL = "deepseek:deepseek-flash"

#: How hard a component asks its model to think. Off, the default, is what every
#: component always sent: thinking off, the answer a forced tool call. The
#: others turn DeepSeek's thinking on at that effort and take the answer as JSON
#: instead, because DeepSeek refuses a forced tool call while it thinks. Off
#: unless configured, until a probe shows thinking holds a component's answers.
Thinking = Literal["off", "low", "high", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: Pooled. Used by the application.
    database_url: str = Field(default="postgresql://sdlc:sdlc@localhost:5432/sdlc")
    #: Direct, not pooled. Used by the checkpointer. Falls back to the pooled
    #: URL for the compose path, where the two are the same host anyway.
    database_direct_url: str = ""

    #: `NoDecode` because pydantic-settings JSON-decodes a list field from the
    #: environment before any validator runs, so `CORS_ORIGINS=http://localhost:5173`
    #: raised a parse error at startup. That is the format `.env.example`
    #: documents and the obvious thing to write, so the config had to accept it
    #: rather than demand a JSON array.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    #: How the orchestrator reaches Component 1. `inprocess` imports it, which
    #: is the development default and what pytest uses; `http` calls the running
    #: service, which is the compose and production path. The service boundary
    #: is real either way, so this changes deployment rather than architecture.
    c1_mode: Literal["inprocess", "http"] = "inprocess"
    c1_base_url: str = "http://localhost:8001"

    #: Model strings are configuration, never hardcoded, so a component can
    #: change provider without a code change and an evaluation run can pin one.
    #:
    #: The prefix chooses the provider, and `main` reads it to decide which key
    #: to require, so this one line is the whole of switching.
    #:
    #: **A default is what runs when somebody comments out a line in `.env`, so
    #: it has to be the safe answer rather than the best one.** This one used to
    #: name a paid Anthropic model, which meant a missing line spent money
    #: silently on a project whose standing rule is that it never should. All
    #: three components now default to the same metered lane, which probed
    #: SUITABLE on all three and has no daily cap, so a missing line fails
    #: predictably and cheaply instead of expensively or not at all.
    c1_model: str = DEFAULT_MODEL
    #: Each component's thinking switch (`Thinking`), read once at startup like
    #: its model; every run records the level it ran at.
    c1_thinking: Thinking = "off"

    #: How the orchestrator reaches Component 2, and what it generates with.
    #: Generated code is the largest output this platform asks of any model, so
    #: this lane needs per request headroom more than it needs anything else.
    c2_mode: Literal["inprocess", "http"] = "inprocess"
    c2_base_url: str = "http://localhost:8002"
    c2_model: str = DEFAULT_MODEL
    c2_thinking: Thinking = "off"
    #: Whether C2's page writer rewrites the rule pages for what they are for.
    #: On, because the rule pages alone made every app the same form; each page
    #: is compiled before it ships, and one that does not compile goes back.
    c2_page_fill: bool = True

    #: How the orchestrator reaches Component 3, and what it reasons with.
    #: C3 makes the most calls of any component, which used to argue for giving
    #: it a different provider from C1 and C2, because free tier limits are per
    #: provider and one benchmark sweep could spend the quota a demo needed.
    #: That argument was about free tiers. On a metered lane with no daily cap
    #: there is nothing to ration and one provider is simpler to reason about.
    #:
    #: The model must support tool calling, because every structured output in
    #: this platform is a forced tool call.
    #:
    #: **This default does not pin the study.** The evaluation runners take the
    #: model on the command line, so the numbers in the dissertation say which
    #: model produced them regardless of what is configured here. Changing this
    #: changes the product, not the record.
    c3_mode: Literal["inprocess", "http"] = "inprocess"
    c3_base_url: str = "http://localhost:8003"
    c3_model: str = DEFAULT_MODEL
    c3_thinking: Thinking = "off"
    #: Where a generated project is written out for a lane to run it. Outside
    #: the repository on purpose: a lane installs packages and runs mutation,
    #: and neither belongs anywhere near the working tree.
    c3_workspace_root: str = "/tmp/c3-workspaces"
    #: Which detection arms the security stage runs when a pipeline triggers
    #: it. The scanner alone by default, and that default is a decision: it
    #: needs no key, spends nothing and answers the same way every time, which
    #: is what a stage somebody started by pressing a button should use.
    #:
    #: Naming `llm` is how a deployment says it has decided to spend tokens on
    #: every testing run. Naming `trained` requires `c3_trained_model_dir` to
    #: hold weights, and a stage pointed at a directory that is not there is a
    #: stage that fails. The scanner is never dropped: an arm that costs money
    #: is judged against one that does not, and that comparison is the point.
    c3_detection_arms: str = "scanner"
    #: The fine tuned weights, for the trained arm. Empty means no trained arm
    #: whatever `c3_detection_arms` says, because claiming an arm ran when its
    #: weights are absent is worse than running without it.
    c3_trained_model_dir: str = ""

    #: Component 4. Its model reads release notes, once per update, and writes
    #: the explanation a reviewer reads; everything else it does is rules.
    c4_mode: Literal["inprocess", "http"] = "inprocess"
    c4_base_url: str = "http://localhost:8004"
    c4_model: str = DEFAULT_MODEL
    c4_thinking: Thinking = "off"
    #: Where staging writes a candidate out to build it. Outside the repository
    #: for C3's reason: a build installs packages.
    c4_workspace_root: str = "/tmp/c4-workspaces"
    #: Registry answers and fetched release notes, kept between runs so an
    #: evaluation rerun reads the same notes rather than whatever changed since.
    c4_cache_dir: str = "/tmp/c4-cache"
    #: Where a release goes when nobody has chosen. Local, because the dev loop
    #: and every controlled failure scenario run in containers on this machine,
    #: and nothing is spent in the cloud until a person asks for it.
    c4_release_target_default: Literal["local", "cloud"] = "local"
    #: Off unless a deployment turns it on. With it off a cloud release is
    #: refused before anything is dispatched, whatever the decision said.
    c4_cloud_enabled: bool = False
    #: The first of the local release target's production ports, on loopback
    #: only. Each project takes its own on its first release, from this one up,
    #: and keeps it: a release moves its port to the new container, and a
    #: rollback moves it back.
    c4_local_release_port: int = Field(default=18080, ge=1024, le=65535)
    #: The label the local target's containers carry, so a restart finds them and
    #: tests, which use their own lane, never touch a real local release.
    c4_local_lane: str = "release"
    #: How often a monitoring window probes, and how long one lasts. Bounded,
    #: because a free host that is probed forever never sleeps and spends its
    #: month of hours on being watched.
    c4_monitor_interval_seconds: int = Field(default=30, ge=5)
    c4_monitor_window_seconds: int = Field(default=600, ge=30)

    @field_validator("c3_detection_arms")
    @classmethod
    def names_only_arms_that_exist(cls, value: str) -> str:
        """Refuse an unknown arm at startup rather than silently dropping it.

        A typo here would read as a deployment that decided against an arm,
        which is exactly the misconfiguration that is impossible to notice: the
        run succeeds, the report is smaller, and nothing says why.
        """
        known = {"scanner", "llm", "trained"}
        named = [one.strip() for one in value.split(",") if one.strip()]
        unknown = [one for one in named if one not in known]
        if unknown:
            raise ValueError(
                f"C3_DETECTION_ARMS names {', '.join(unknown)}, which are not arms. "
                f"Known arms are: {', '.join(sorted(known))}."
            )
        if "scanner" not in named:
            raise ValueError(
                "C3_DETECTION_ARMS must include 'scanner'. It costs nothing and it is what "
                "the model arms are measured against, so a run without it compares nothing."
            )
        return ",".join(named)

    @field_validator("c1_model", "c2_model", "c3_model", "c4_model")
    @classmethod
    def is_a_usable_model_string(cls, value: str, info: ValidationInfo) -> str:
        """Refuse a model string no provider could answer, at startup.

        Shared by every component's model field, so a typo in either is refused
        at startup rather than on the first request.

        A trailing comma in `.env` cost a run and two 404s that read as though
        Haiku did not exist: the API was correctly reporting that no model called
        `claude-haiku-4-5-20251001,` exists, and the comma was invisible in the
        error beside the real name.

        Whitespace is stripped, because a trailing space is the same mistake and
        is harder to see. Everything else is refused rather than cleaned: a comma
        is a typo, and quietly deleting it would hide the fact that the line was
        wrong. This mirrors the key gate in `main`, which also fails at startup
        rather than on the first request.
        """
        variable = (info.field_name or "model").upper()
        model = value.strip().strip("\"'")
        if not model:
            raise ValueError(f"{variable} is empty. Set it to <provider>:<model>.")
        if ":" not in model:
            raise ValueError(
                f"{variable} is {model!r}, which names no provider. "
                "Use <provider>:<model>, for example anthropic:claude-sonnet-5."
            )
        stray = {character for character in model if character.isspace() or character in ",;\"'"}
        if stray:
            shown = " ".join(sorted(repr(character) for character in stray))
            raise ValueError(
                f"{variable} is {model!r}, which contains {shown}. A model name holds "
                "none of those, and a stray one is reported by the provider as a "
                "model that does not exist, which reads like the wrong model rather "
                "than a typo."
            )
        return model

    #: Provider keys, read from .env so one file is enough to run the
    #: orchestrator.
    #:
    #: The model client takes its key from the process environment rather than
    #: from here, so without these the server started cleanly and then failed
    #: every stage with "Set the GROQ_API_KEY environment variable". Reading
    #: them into settings lets `main` put the right one where the client looks,
    #: and lets a missing key be a refusal to start rather than a surprise three
    #: stages in.
    #:
    #: Both stay configured so a comparison run costs one line. Each field name
    #: is the lowercase of its environment variable, which is how `main` finds
    #: the one the configured model needs.
    anthropic_api_key: str = ""
    #: Metered, and the only lane here with no daily request cap: the provider
    #: documents concurrency limits and nothing else, and every arm in this
    #: platform runs sequentially. The study's prompted arm was cut short four
    #: times by free tier quotas before this was added.
    deepseek_api_key: str = ""
    google_api_key: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""

    #: Encrypts provider tokens at rest. Empty disables the secret store rather
    #: than silently storing plaintext.
    secret_key: str = ""

    #: How long a sign-in lasts before the browser has to sign in again.
    session_days: int = 30
    #: The identity every row from before sign-in belongs to (migration 0003),
    #: which the first account registered takes over. A setting so the tests can
    #: give that part of registration an identity of their own.
    pre_sign_in_owner_id: str = "u_local_dev"
    #: Whether the session cookie is marked Secure, so a browser sends it over
    #: HTTPS only. On for any deployment; off by default because the platform
    #: runs on http://localhost, where the frontend and the orchestrator are
    #: two ports of one site and the cookie is SameSite=Lax either way.
    session_cookie_secure: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        """Accept a comma separated list, or a real list, or a JSON array."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            import json

            return json.loads(text)
        return [origin.strip() for origin in text.split(",") if origin.strip()]

    @property
    def checkpointer_url(self) -> str:
        """The direct URL, or the pooled one when there is no separate direct."""
        return self.database_direct_url or self.database_url

    @property
    def alembic_url(self) -> str:
        """The migration URL, in the dialect SQLAlchemy expects.

        Everything else in this codebase talks to Postgres through psycopg 3
        directly. Alembic goes through SQLAlchemy, which still reaches for
        psycopg2 on a bare `postgresql://` scheme, so the driver is named
        explicitly here rather than by installing a second driver.

        Migrations run against the direct connection: DDL through a transaction
        pooler is asking for trouble.
        """
        url = self.checkpointer_url
        if url.startswith("postgresql+"):
            return url
        return url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
