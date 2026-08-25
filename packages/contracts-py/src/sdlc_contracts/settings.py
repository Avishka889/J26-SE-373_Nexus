"""The settings page's state: a view model, and deliberately secret free.

The fixture era kept tokens inside the settings state under a comment saying
they stay in memory. Live mode has a credential store, so the wire shape for
settings carries no secret at all: not a token, not an api key, not a
password, not a connection string. What a section keeps here is the plain
configuration beside the credential (org, team, region, database host), plus
`connected`, which the server derives from the connections store rather than
trusting a client side boolean.

A token posted to a settings route is refused with a pointer to
`/connections`; it is not a setting, and storing it here would put it in a
row every settings read returns.
"""

from typing import Any, Literal

from pydantic import Field, model_validator

from .wire import WireModel

DatabaseProvider = Literal["neon", "mongodb_atlas"]


class GitSettings(WireModel):
    provider: str = "github"
    default_org: str = ""
    #: Derived from the connections store, never stored: a stored boolean and a
    #: revoked token would disagree, and the boolean would win on screen.
    connected: bool = False
    #: What the connection's probe learned, echoed here so the settings page
    #: can say more than a boolean. Empty when not connected.
    scopes: list[str] = Field(default_factory=list)


class VercelSettings(WireModel):
    team: str = ""
    #: The project the frontend deploys to, and the account or team it belongs
    #: to: what `vercel pull` reads from VERCEL_PROJECT_ID and VERCEL_ORG_ID.
    #: Identifiers, not secrets; the token is a connection.
    project_id: str = ""
    org_id: str = ""
    #: Where the production frontend answers, such as https://app.vercel.app.
    origin: str = ""
    connected: bool = False


class RenderSettings(WireModel):
    service_id: str = ""
    region: str = "oregon"
    #: Where the backend answers, such as https://app-api.onrender.com, read
    #: from the service once the Blueprint has created it.
    origin: str = ""
    connected: bool = False


#: What the fixture era's database tab stored: a host, a port, a name and a
#: user for one database. Nothing reads them, since each project now gets its
#: own database; a stored row that still carries them loads without them.
_RETIRED_DATABASE_FIELDS = frozenset({"host", "port", "name", "username"})


class DatabaseSettings(WireModel):
    """Where a cloud release keeps each app's records: the account's Atlas cluster.

    Identifiers only. The service account's secret is a connection (`atlas`),
    and each project's database, user and password are made by the platform.
    """

    provider: DatabaseProvider = "mongodb_atlas"
    #: The Atlas project (its 24 character id) the cluster belongs to.
    project_id: str = ""
    #: The cluster each project's database is made on.
    cluster: str = ""
    #: The service account's client id, whose secret is the connection.
    client_id: str = ""
    connected: bool = False

    @model_validator(mode="before")
    @classmethod
    def _without_retired_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in _RETIRED_DATABASE_FIELDS}
        return data


#: How hard a phase asks its model to think. Off sends what was always sent;
#: the others turn DeepSeek's thinking on at that effort and take the answer as
#: JSON, since DeepSeek refuses a forced tool call while it thinks.
ThinkingLevel = Literal["off", "low", "high", "max"]


class PhaseThinking(WireModel):
    """How hard each phase is asked to think, as this account chose it.

    None is no choice: the phase thinks as the platform is configured (off
    unless configured). A choice applies from the next run, and a run keeps the
    level it started at for its whole life, regenerations included.
    """

    design: ThinkingLevel | None = None
    code: ThinkingLevel | None = None
    testing: ThinkingLevel | None = None
    deployment: ThinkingLevel | None = None


class AiSettings(WireModel):
    provider: str = ""
    model: str = ""
    temperature: float = Field(default=0.7, ge=0, le=2)
    thinking: PhaseThinking = Field(default_factory=PhaseThinking)


class ProfileSettings(WireModel):
    name: str = ""
    email: str = ""
    workspace: str = ""
    avatar_url: str | None = None


class SettingsState(WireModel):
    git: GitSettings = Field(default_factory=GitSettings)
    vercel: VercelSettings = Field(default_factory=VercelSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    ai: AiSettings = Field(default_factory=AiSettings)
    profile: ProfileSettings = Field(default_factory=ProfileSettings)
