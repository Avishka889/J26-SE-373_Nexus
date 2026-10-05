"""MongoDB Atlas: the account's service account, its cluster, and who may connect.

Atlas keeps each generated app's records: one cluster the account made once
(the free M0 tier is enough), with a database and a database user per project,
which the platform makes (`deploy/provision.py`). The account gives a service
account, Atlas's OAuth 2.0 client credentials. Its client id is an identifier,
kept in Settings beside the Atlas project's id and the cluster's name; its
secret is the connection, stored encrypted like every other token.

Checked against MongoDB's Atlas Administration API reference and its OpenAPI
description on 2026-10-01:

- a token comes from `POST /api/oauth/token` (HTTP Basic with the client id and
  secret, `grant_type=client_credentials`) and lasts an hour. MongoDB asks that
  it be reused rather than made per request, and revoked once it is not needed
  (`POST /api/oauth/revoke`), which is what one `AtlasApi` session does;
- every v2 call names the resource version it was written against in its
  Accept header, and Atlas answers 406 to a version that does not exist, so
  each constant below is the reference's own date for its resource.

The probe only reads: a token, the cluster, and the network access list. The
service account needs Project Read Only (to read those) and Project Database
Access Admin (to make each project's database user), and nothing more.
"""

import base64
import contextlib
from types import TracebackType
from typing import Any

import httpx

from ..crypto import redacted
from .deploy_targets import PROBE_TIMEOUT_SECONDS, ProviderProbe

ATLAS_API = "https://cloud.mongodb.com"
#: Clusters are read at their newest resource version.
CLUSTER_VERSION = "application/vnd.atlas.2024-08-05+json"
#: Database users and the network access list have one version each.
PROJECT_VERSION = "application/vnd.atlas.2023-01-01+json"


class AtlasRefused(RuntimeError):
    """Atlas said no, in its own words, with every credential blanked."""


class AtlasApi:
    """One service account's session: one token, reused for every call, revoked at the end.

    Used as `async with AtlasApi(...) as atlas:`. Every message that leaves it
    passes through `hide`, because an upstream error this code cannot foresee
    might echo the secret, the Basic credential or the token back.
    """

    def __init__(
        self,
        client_id: str,
        secret: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = PROBE_TIMEOUT_SECONDS,
    ) -> None:
        self.client_id, self.secret = client_id.strip(), secret.strip()
        self._basic = base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
        self._given = client
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._token = ""

    def hide(self, text: str) -> str:
        return redacted(text, self.secret, self._basic, self._token)

    async def __aenter__(self) -> "AtlasApi":
        self._http = self._given or httpx.AsyncClient(timeout=self._timeout)
        try:
            answer = await self._http.post(
                f"{ATLAS_API}/api/oauth/token",
                data={"grant_type": "client_credentials"},
                headers={"Authorization": f"Basic {self._basic}", "Accept": "application/json"},
            )
        except httpx.HTTPError as error:
            await self._close()
            raise AtlasRefused(self.hide(f"Atlas could not be reached: {error}")) from error
        if answer.status_code in (400, 401, 403):
            await self._close()
            raise AtlasRefused("The service account's client ID and secret do not authenticate.")
        token = (
            str(answer_json(answer).get("access_token") or "") if answer.status_code == 200 else ""
        )
        if not token:
            await self._close()
            raise AtlasRefused(
                self.hide(
                    f"Atlas answered {answer.status_code} to the token request, with no token: "
                    f"{answer.text[:200]}"
                )
            )
        self._token = token
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if self._token and self._http is not None:
            # It expires within the hour whatever happens here.
            with contextlib.suppress(httpx.HTTPError):
                await self._http.post(
                    f"{ATLAS_API}/api/oauth/revoke",
                    data={"token": self._token, "token_type_hint": "access_token"},
                    headers={"Authorization": f"Basic {self._basic}"},
                )
        await self._close()

    async def _close(self) -> None:
        if self._given is None and self._http is not None:
            await self._http.aclose()
        self._http = None

    async def call(
        self, method: str, path: str, *, version: str, json: Any = None
    ) -> httpx.Response:
        """One v2 call, `path` below `/api/atlas/v2`, at the resource version it was written for."""
        if self._http is None:
            raise RuntimeError("AtlasApi is used as `async with AtlasApi(...) as atlas`")
        headers = {"Authorization": f"Bearer {self._token}", "Accept": version}
        if json is not None:
            headers["Content-Type"] = version
        try:
            return await self._http.request(
                method, f"{ATLAS_API}/api/atlas/v2{path}", json=json, headers=headers
            )
        except httpx.HTTPError as error:
            raise AtlasRefused(self.hide(f"Atlas could not be reached: {error}")) from error

    def refused(self, what: str, answer: httpx.Response) -> AtlasRefused:
        """Atlas's own reason, its error code first, since the code is what its docs index."""
        body = answer_json(answer)
        said = (
            " ".join(str(part) for part in (body.get("errorCode"), body.get("detail")) if part)
            or answer.text[:300]
        )
        return AtlasRefused(self.hide(f"Atlas refused to {what}: {answer.status_code} {said}"))


def answer_json(answer: httpx.Response) -> dict[str, Any]:
    """The answer's JSON object, or an empty one for anything else."""
    try:
        body = answer.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _listed(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


async def probe_atlas(
    secret: str,
    *,
    client: httpx.AsyncClient | None = None,
    client_id: str = "",
    project_id: str = "",
    cluster: str = "",
) -> ProviderProbe:
    """Can this service account reach the cluster, and may anything connect to it."""
    missing = [
        label
        for label, value in (
            ("the service account's client ID", client_id),
            ("the Atlas project ID", project_id),
            ("the cluster's name", cluster),
        )
        if not value.strip()
    ]
    if missing:
        return ProviderProbe(
            verdict="UNUSABLE", reason=f"Add {_listed(missing)} in Settings, then check again."
        )
    account = f"{project_id}/{cluster}"
    try:
        async with AtlasApi(client_id, secret, client=client) as atlas:
            found = await atlas.call(
                "GET", f"/groups/{project_id}/clusters/{cluster}", version=CLUSTER_VERSION
            )
            if found.status_code in (401, 403):
                return ProviderProbe(
                    verdict="UNUSABLE",
                    reason=str(atlas.refused(f"read the project {project_id}", found))
                    + ". Give the service account Project Read Only and Project Database Access "
                    "Admin on the project.",
                )
            if found.status_code == 404:
                return ProviderProbe(
                    verdict="UNUSABLE",
                    reason=f"The project {project_id} has no cluster named {cluster}.",
                )
            if found.status_code != 200:
                return ProviderProbe(
                    verdict="UNUSABLE", reason=str(atlas.refused("read the cluster", found))
                )
            body = answer_json(found)
            state = str(body.get("stateName") or "unknown")
            if not (body.get("connectionStrings") or {}).get("standardSrv"):
                return ProviderProbe(
                    verdict="WORKABLE",
                    reason=f"The cluster {cluster} has no connection string yet ({state}).",
                    account=account,
                )
            listed = await atlas.call(
                "GET", f"/groups/{project_id}/accessList", version=PROJECT_VERSION
            )
            if listed.status_code != 200:
                return ProviderProbe(
                    verdict="WORKABLE",
                    reason=f"Reaches the cluster {cluster} ({state}), but "
                    + str(atlas.refused("list who may connect to it", listed)),
                    account=account,
                )
            entries = answer_json(listed).get("results") or []
    except AtlasRefused as error:
        return ProviderProbe(verdict="UNUSABLE", reason=str(error))
    if not entries:
        return ProviderProbe(
            verdict="WORKABLE",
            reason=(
                f"Reaches the cluster {cluster} ({state}), but no address may connect to it "
                "yet: add your Render region's outbound addresses (a Render service lists them "
                "under Connect, Outbound), or 0.0.0.0/0, under Database & Network Access, IP "
                "Access List."
            ),
            account=account,
        )
    return ProviderProbe(
        verdict="SUITABLE",
        reason=(
            f"Reaches the cluster {cluster} ({state}), and "
            f"{len(entries)} network access {'entry lets' if len(entries) == 1 else 'entries let'} "
            "apps connect to it."
        ),
        account=account,
    )
