"""Each project's cloud resources, created by the platform from the account's tokens.

A cloud release puts a project's frontend on Vercel and its backend on Render,
and each project gets its own of both. The account keeps two tokens in Settings,
as it keeps the GitHub one: a Vercel access token and a Render API key. From
those, on a project's first analysis with the cloud target, the platform
creates what the project needs, before the deployment layer is generated, so
that the layer names the real addresses:

- **a Vercel project** named after the project, with its production domain
  claimed at once (`<name>.vercel.app`), because Vercel otherwise gives the
  domain out only at the first deployment, first come first served, and the
  release must know the address before it deploys;
- **a Render web service** on the free plan, asked for by name: Render's API
  defaults a new service to a paid plan, so the platform never leaves the plan
  out. It builds the project's repository from its Dockerfile, is health
  checked at `/release.json`, and never deploys on a push. Render starts a
  deploy the moment a service is created, which fails, because the Dockerfile
  reaches the repository only in a release's own commit; the platform cancels
  it rather than spend build minutes on it;
- **a MongoDB database**, when the account keeps an Atlas connection: the
  project's own database on the account's cluster, and a database user that may
  read and write that database and nothing else. Its password is made here,
  kept encrypted with the platform's secrets, and set on the Render service as
  `MONGODB_URL`, which the generated backend reads to keep its records there
  rather than in memory. Render deploys nothing when a variable changes through
  its API; the release's own deploy is what picks it up. Without the connection
  the app keeps its records in memory, as before, and a variable the platform
  set earlier is taken off the service, so what the record says is what runs.

What was made is kept per project and reused after that. A resource the
provider no longer has is made again. Every call carries its token in a header
only, and every message that could echo one back is redacted. The backend is
then deployed by the orchestrator through Render's API, with the key that never
leaves it (the saga's `render` adapter), because Render's API cannot create or
read the deploy hook GitHub Actions would otherwise have called.
"""

import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Any

import httpx
from psycopg_pool import AsyncConnectionPool
from sdlc_contracts import (
    AtlasDatabase,
    CloudResources,
    RenderService,
    RepositoryPointer,
    SettingsState,
    VercelProject,
)

from ..crypto import decrypt, encrypt, redacted
from ..db import store
from ..probes.atlas import (
    CLUSTER_VERSION,
    PROJECT_VERSION,
    AtlasApi,
    AtlasRefused,
    answer_json,
)
from ..probes.deploy_targets import RENDER_API, VERCEL_API

TIMEOUT_SECONDS = 30.0
#: Render's health check path, which is also the release fingerprint.
HEALTH_PATH = "/release.json"
#: What the generated backend reads to keep its records in a database.
DATABASE_VARIABLE = "MONGODB_URL"


class ProvisionFailed(RuntimeError):
    """A resource could not be created or found, with the provider's words."""


@dataclass(frozen=True)
class _Atlas:
    """The account's Atlas service account, and the cluster each project's database goes on."""

    client_id: str
    secret: str
    project_id: str
    cluster: str


@dataclass(frozen=True)
class _Account:
    vercel_token: str
    render_key: str
    #: None when the account keeps no Atlas connection: the app keeps its records in memory.
    atlas: _Atlas | None
    #: Vercel's team, as the team id (`team_...`) or its slug; blank is the personal account.
    team: str
    region: str
    repository_url: str
    branch: str
    known: CloudResources | None


def slug_of(project_id: str) -> str:
    """The project id in the characters both providers accept, as the layer names it."""
    return re.sub(r"[^a-z0-9-]+", "-", project_id.lower()).strip("-")[:40] or "app"


def _team_query(team: str) -> dict[str, str]:
    team = team.strip()
    if not team:
        return {}
    return {"teamId": team} if team.startswith("team_") else {"slug": team}


async def _account(
    pool: AsyncConnectionPool, project_id: str, owner: str, secret_key: str, version: int
):
    async with pool.connection() as conn:
        tokens: dict[str, str] = {}
        for provider in ("vercel", "render"):
            ciphertext = await store.get_secret(conn, f"{owner}:{provider}")
            if ciphertext is None:
                raise ProvisionFailed(
                    f"there is no {provider} connection to create this project's resources with: "
                    f"add the {'Vercel token' if provider == 'vercel' else 'Render API key'} in "
                    "Settings"
                )
            tokens[provider] = decrypt(secret_key, ciphertext)
        atlas_secret = await store.get_secret(conn, f"{owner}:atlas")
        body = await store.settings_body(conn, owner)
        # The version's own push, or the one an accepted fix patched: the
        # repository is the project's either way. The version the analysis is
        # of, not the newest: the next sprint's code may not be pushed yet.
        found, _ = await store.repository_field_through_patches(
            conn, project_id, version, "repository"
        )
    if not found:
        raise ProvisionFailed(
            f"code version {version} was never pushed to a repository, so Render has nothing "
            "to build"
        )
    pointer = RepositoryPointer.model_validate(found)
    settings = SettingsState.model_validate(body.get("settings") or {})
    known = (body.get("cloud") or {}).get(project_id)
    atlas = None
    if atlas_secret is not None:
        database = settings.database
        missing = [
            label
            for label, value in (
                ("its client ID", database.client_id),
                ("the Atlas project ID", database.project_id),
                ("the cluster's name", database.cluster),
            )
            if not value
        ]
        if missing:
            raise ProvisionFailed(
                f"the MongoDB Atlas connection needs {' and '.join(missing)} in Settings before "
                "a project's database can be made"
            )
        atlas = _Atlas(
            client_id=database.client_id,
            secret=decrypt(secret_key, atlas_secret),
            project_id=database.project_id,
            cluster=database.cluster,
        )
    return _Account(
        vercel_token=tokens["vercel"],
        render_key=tokens["render"],
        atlas=atlas,
        team=settings.vercel.team,
        region=settings.render.region or "oregon",
        repository_url=f"https://github.com/{pointer.owner}/{pointer.name}",
        branch=pointer.default_branch,
        known=CloudResources.model_validate(known) if known else None,
    )


class _Api:
    """One provider's REST API, its token in a header only and redacted out of every error."""

    def __init__(self, name: str, base: str, token: str, client: httpx.AsyncClient | None):
        self.name, self.base, self.token = name, base, token
        self.client = client

    async def call(
        self, method: str, path: str, *, params: dict[str, str] | None = None, json: Any = None
    ) -> httpx.Response:
        owns = self.client is None
        http = self.client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        try:
            return await http.request(
                method,
                f"{self.base}{path}",
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
            )
        except httpx.HTTPError as error:
            raise ProvisionFailed(
                redacted(f"{self.name} could not be reached: {error}", self.token)
            ) from error
        finally:
            if owns:
                await http.aclose()

    def refused(self, what: str, answer: httpx.Response) -> ProvisionFailed:
        said = redacted(answer.text[:300], self.token)
        return ProvisionFailed(f"{self.name} refused to {what}: {answer.status_code} {said}")


async def _vercel(api: _Api, account: _Account, name: str) -> VercelProject:
    query = _team_query(account.team)
    known = account.known.vercel if account.known else None
    found = await api.call(
        "GET", f"/v9/projects/{known.project_id if known else name}", params=query
    )
    if found.status_code == 200:
        project = found.json()
    elif found.status_code == 404:
        created = await api.call(
            "POST", "/v11/projects", params=query, json={"name": name, "framework": None}
        )
        if created.status_code not in (200, 201):
            raise api.refused(f"create the Vercel project {name}", created)
        project = created.json()
        known = None
    else:
        raise api.refused(f"read the Vercel project {name}", found)

    project_id, org_id = str(project["id"]), str(project["accountId"])
    if known is not None and known.project_id == project_id:
        return known
    # Vercel gives a new project its `<name>.vercel.app` address as it creates it
    # (seen on the first live cloud run), so the address the project already has
    # is taken first, the plain one before any other. Only a project without one
    # has one claimed, so the release still knows its address before it deploys.
    listed = await api.call("GET", f"/v9/projects/{project_id}/domains", params=query)
    if listed.status_code != 200:
        raise api.refused(f"list the domains of the Vercel project {name}", listed)
    own = [
        str(item.get("name") or "")
        for item in listed.json().get("domains") or []
        if str(item.get("name") or "").endswith(".vercel.app") and not item.get("redirect")
    ]
    if own:
        chosen = f"{name}.vercel.app" if f"{name}.vercel.app" in own else own[0]
        return VercelProject(
            project_id=project_id, org_id=org_id, name=name, origin=f"https://{chosen}"
        )
    suffix = hashlib.sha256(project_id.encode()).hexdigest()[:6]
    for domain in (f"{name}.vercel.app", f"{name}-{suffix}.vercel.app"):
        added = await api.call(
            "POST", f"/v10/projects/{project_id}/domains", params=query, json={"name": domain}
        )
        # A 400 for a domain the project already has is the same domain, kept.
        if added.status_code in (200, 201) or (
            added.status_code == 400 and "already" in added.text.lower()
        ):
            return VercelProject(
                project_id=project_id, org_id=org_id, name=name, origin=f"https://{domain}"
            )
        if added.status_code != 409:
            raise api.refused(f"give the Vercel project the domain {domain}", added)
    raise ProvisionFailed(
        f"Vercel refused both {name}.vercel.app and its variant: another project holds them"
    )


async def _render(api: _Api, account: _Account, name: str) -> RenderService:
    known = account.known.render if account.known else None
    if known is not None:
        found = await api.call("GET", f"/services/{known.service_id}")
        if found.status_code == 200:
            return known
        if found.status_code != 404:
            raise api.refused(f"read the Render service {name}", found)

    owners = await api.call("GET", "/owners", params={"limit": "20"})
    if owners.status_code != 200:
        raise api.refused("list its workspaces", owners)
    workspace = next(
        (item["owner"] for item in owners.json() if isinstance(item, dict) and item.get("owner")),
        None,
    )
    if workspace is None:
        raise ProvisionFailed("the Render API key reaches no workspace to create a service in")
    owner_id = str(workspace["id"])

    listed = await api.call(
        "GET", "/services", params={"name": name, "ownerId": owner_id, "limit": "20"}
    )
    if listed.status_code != 200:
        raise api.refused("list its services", listed)
    service = next(
        (
            item["service"]
            for item in listed.json()
            if isinstance(item, dict) and (item.get("service") or {}).get("name") == name
        ),
        None,
    )
    if service is None:
        created = await api.call(
            "POST",
            "/services",
            json={
                "type": "web_service",
                "name": name,
                "ownerId": owner_id,
                "repo": account.repository_url,
                "branch": account.branch,
                "autoDeployTrigger": "off",
                "serviceDetails": {
                    "runtime": "docker",
                    # Never left out: Render's API defaults a new service to a paid plan.
                    "plan": "free",
                    "region": account.region,
                    "healthCheckPath": HEALTH_PATH,
                    "envSpecificDetails": {"dockerfilePath": "./Dockerfile", "dockerContext": "."},
                },
            },
        )
        if created.status_code not in (200, 201):
            raise ProvisionFailed(
                str(api.refused(f"create the Render service {name}", created))
                + f". Render builds only what its GitHub app can read: give it access to "
                f"{account.repository_url} in Render's GitHub settings"
            )
        answer = created.json()
        service = answer["service"]
        # The deploy Render starts on creation builds a commit with no Dockerfile yet.
        first = answer.get("deployId")
        if first:
            await api.call("POST", f"/services/{service['id']}/deploys/{first}/cancel")

    details = service.get("serviceDetails") or {}
    url = str(details.get("url") or f"https://{name}.onrender.com")
    return RenderService(
        service_id=str(service["id"]),
        name=name,
        origin=url.rstrip("/"),
        owner_id=owner_id,
        dashboard_url=str(service.get("dashboardUrl") or ""),
    )


def _password() -> str:
    """48 hex characters: 192 random bits, and nothing a connection string must escape."""
    return secrets.token_hex(24)


async def _database(
    pool: AsyncConnectionPool,
    render: _Api,
    atlas_account: _Atlas,
    service: RenderService,
    *,
    name: str,
    project_id: str,
    owner: str,
    secret_key: str,
    client: httpx.AsyncClient | None,
) -> AtlasDatabase:
    """The project's database user on the account's cluster, and MONGODB_URL on its service.

    The user is set to what the platform keeps every time (one role, on the
    project's own database, on the one cluster, and the password held here), so
    a user edited or made by hand is put back. The password is kept before Atlas
    is asked to use it, so a user never holds a password the platform does not.
    """
    group, cluster = atlas_account.project_id, atlas_account.cluster
    username, database = f"app-{name}", name
    key = f"{owner}:atlas-database:{project_id}"
    async with pool.connection() as conn:
        stored = await store.get_secret(conn, key)
        password = decrypt(secret_key, stored) if stored is not None else _password()
        if stored is None:
            await store.put_secret(conn, key, encrypt(secret_key, password))
    user = {
        "databaseName": "admin",
        "groupId": group,
        "username": username,
        "password": password,
        "roles": [{"databaseName": database, "roleName": "readWrite"}],
        "scopes": [{"name": cluster, "type": "CLUSTER"}],
        "description": f"The platform's app for project {project_id}: its own database only",
    }
    try:
        async with AtlasApi(
            atlas_account.client_id, atlas_account.secret, client=client, timeout=TIMEOUT_SECONDS
        ) as atlas:
            found = await atlas.call(
                "GET", f"/groups/{group}/clusters/{cluster}", version=CLUSTER_VERSION
            )
            if found.status_code != 200:
                raise atlas.refused(f"read the cluster {cluster}", found)
            strings = answer_json(found).get("connectionStrings") or {}
            host = str(strings.get("standardSrv") or "").removeprefix("mongodb+srv://").strip("/")
            if not host:
                raise AtlasRefused(f"the cluster {cluster} has no connection string yet")
            path = f"/groups/{group}/databaseUsers/admin/{username}"
            existing = await atlas.call("GET", path, version=PROJECT_VERSION)
            if existing.status_code == 404:
                written = await atlas.call(
                    "POST", f"/groups/{group}/databaseUsers", version=PROJECT_VERSION, json=user
                )
            elif existing.status_code == 200:
                written = await atlas.call("PATCH", path, version=PROJECT_VERSION, json=user)
            else:
                raise atlas.refused(f"read the database user {username}", existing)
            if written.status_code not in (200, 201):
                raise atlas.refused(f"set up the database user {username}", written)
    except AtlasRefused as error:
        raise ProvisionFailed(redacted(str(error), password)) from error

    url = (
        f"mongodb+srv://{username}:{password}@{host}/{database}"
        f"?retryWrites=true&w=majority&appName={name}"
    )
    answer = await render.call(
        "PUT", f"/services/{service.service_id}/env-vars/{DATABASE_VARIABLE}", json={"value": url}
    )
    if answer.status_code != 200:
        # Render answers with the variable's value, so its words go through both.
        refusal = render.refused(f"set {DATABASE_VARIABLE} on the service {service.name}", answer)
        raise ProvisionFailed(redacted(str(refusal), url, password))
    return AtlasDatabase(
        cluster=cluster,
        host=host,
        database=database,
        username=username,
        service_id=service.service_id,
    )


async def _forget_database(render: _Api, service: RenderService) -> None:
    """Take MONGODB_URL off a service whose account no longer keeps an Atlas connection."""
    answer = await render.call(
        "DELETE", f"/services/{service.service_id}/env-vars/{DATABASE_VARIABLE}"
    )
    if answer.status_code not in (200, 204, 404):
        raise render.refused(f"take {DATABASE_VARIABLE} off the service {service.name}", answer)


async def provision(
    pool: AsyncConnectionPool,
    project_id: str,
    *,
    owner: str,
    secret_key: str,
    code_version: int,
    vercel: httpx.AsyncClient | None = None,
    render: httpx.AsyncClient | None = None,
    atlas: httpx.AsyncClient | None = None,
) -> CloudResources:
    """The project's Vercel project, Render service and database, made if they do not exist yet.

    `code_version` is the version the analysis is of, whose push names the
    repository Render builds from.
    """
    account = await _account(pool, project_id, owner, secret_key, code_version)
    name = slug_of(project_id)
    frontend = await _vercel(
        _Api("Vercel", VERCEL_API, account.vercel_token, vercel), account, name
    )
    render_api = _Api("Render", RENDER_API, account.render_key, render)
    backend = await _render(render_api, account, f"{name}-api")
    database = None
    if account.atlas is not None:
        database = await _database(
            pool,
            render_api,
            account.atlas,
            backend,
            name=name,
            project_id=project_id,
            owner=owner,
            secret_key=secret_key,
            client=atlas,
        )
    elif account.known is not None and account.known.database is not None:
        await _forget_database(render_api, backend)
    # Through the wire form, so what is returned is exactly what is kept.
    made = CloudResources.model_validate(
        CloudResources(
            vercel=frontend,
            render=backend,
            database=database,
            created_at=account.known.created_at if account.known else store.now(),
        ).model_dump(by_alias=True, mode="json")
    )
    if made != account.known:
        async with pool.connection() as conn:
            await store.put_settings_section(
                conn,
                owner,
                ("cloud", project_id),
                made.model_dump(by_alias=True, mode="json"),
            )
            await store.record(
                conn,
                actor="platform",
                action="Prepared the cloud resources",
                target=project_id,
                category="deployment",
                detail=(
                    f"Vercel project {frontend.name} at {frontend.origin}; Render service "
                    f"{backend.name} at {backend.origin}, on the free plan; "
                    + (
                        f"MongoDB database {database.database} on the cluster "
                        f"{database.cluster}, for the user {database.username}"
                        if database is not None
                        else "no MongoDB Atlas connection, so the app keeps its records in memory"
                    )
                ),
                project_id=project_id,
            )
    return made


async def cloud_resources_of(conn: Any, project_id: str, owner: str) -> CloudResources | None:
    """What the platform made for this project, or None before its first cloud analysis."""
    body = await store.settings_body(conn, owner)
    known = (body.get("cloud") or {}).get(project_id)
    return CloudResources.model_validate(known) if known else None
