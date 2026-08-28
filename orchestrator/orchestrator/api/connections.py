"""Provider connections: create, list, revoke.

The settled decision this implements: credentials are PATs with server side
encryption. A token arrives once, in the create body, is encrypted with the
key derived from SECRET_KEY, and after that only its metadata exists anywhere
a response or a log can reach: provider, when, by whom, and what the probe
learned. The value itself never appears in a response body, an audit row, or
a log line, and the tests plant one in an error to prove it.

Connections are owner scoped, one per provider per owner: the projects that
push to GitHub belong to an owner, and the token they push with is that
owner's, not the project's.
"""

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, StringConstraints

from ..config import Settings
from ..crypto import decrypt, encrypt
from ..db import store
from ..errors import Conflict, NotFound
from ..probes import (
    probe_atlas,
    probe_github,
    probe_render,
    probe_render_deploy_hook,
    probe_vercel,
)
from ..wording import provider_name, verdict_words
from .deps import Actor, Db, Owner

router = APIRouter(prefix="/connections", tags=["connections"])

#: Providers a connection can exist for. GitHub is the one C2 needs; C4's
#: release targets are Vercel, Render (an API key the platform makes services
#: and deploys with) and the Render deploy hook GitHub was once given; Atlas is
#: where each generated app's records are kept (a service account's secret). A
#: name outside this set is refused with the set in the message, which reads
#: better than a bare 422.
KNOWN_PROVIDERS = ("github", "vercel", "render", "render-deploy-hook", "atlas")

#: One probe per provider, each one call or none (a deploy hook is never called).
PROBES = {
    "github": probe_github,
    "vercel": probe_vercel,
    "render": probe_render,
    "render-deploy-hook": probe_render_deploy_hook,
    "atlas": probe_atlas,
}


class ConnectionIn(BaseModel):
    provider: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(
        description="Stored encrypted, never echoed back."
    )


def secret_key_of(request: Request) -> str:
    settings: Settings = request.app.state.settings
    return settings.secret_key


def _probe_client(request: Request) -> httpx.AsyncClient | None:
    """Tests set `app.state.github_client` to a MockTransport client; production
    leaves it unset and the probe owns a real one per call."""
    client = getattr(request.app.state, "github_client", None)
    return client if isinstance(client, httpx.AsyncClient) else None


async def _probe(provider: str, token: str, request: Request, conn: Any, owner: str) -> Any:
    """One provider's probe. Atlas's also reads the account's Atlas settings: the
    secret is only half of a service account, and the probe looks for a cluster."""
    extra: dict[str, str] = {}
    if provider == "atlas":
        from sdlc_contracts import SettingsState

        body = await store.settings_body(conn, owner)
        database = SettingsState.model_validate(body.get("settings") or {}).database
        extra = {
            "client_id": database.client_id,
            "project_id": database.project_id,
            "cluster": database.cluster,
        }
    return await PROBES[provider](token, client=_probe_client(request), **extra)


def _connections_of(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    connections = body.setdefault("connections", {})
    return connections if isinstance(connections, dict) else {}


def _public(meta: dict[str, Any]) -> dict[str, Any]:
    """The metadata a browser may see. Allow listed, not block listed: a new
    field added to storage stays private until somebody puts it here."""
    return {
        "provider": meta.get("provider"),
        "connected": True,
        "createdAt": meta.get("createdAt"),
        "createdBy": meta.get("createdBy"),
        "tokenKind": meta.get("tokenKind"),
        "scopes": meta.get("scopes", []),
        "probe": meta.get("probe"),
    }


@router.get("")
async def list_connections(conn: Db, owner: Owner) -> dict[str, Any]:
    body = await store.settings_body(conn, owner)
    connections = _connections_of(body)
    return {"connections": [_public(meta) for meta in connections.values()]}


@router.post("", status_code=201)
async def create_connection(
    body_in: ConnectionIn, request: Request, conn: Db, owner: Owner, actor: Actor
) -> dict[str, Any]:
    provider = body_in.provider.lower()
    if provider not in KNOWN_PROVIDERS:
        raise Conflict(f"Connections exist for: {', '.join(KNOWN_PROVIDERS)}.")

    ciphertext = encrypt(secret_key_of(request), body_in.token)
    await store.put_secret(conn, f"{owner}:{provider}", ciphertext)

    # Probed at create time, so the page can say what the token is good for
    # the moment it exists. The verdict is stored as metadata; the token is
    # not. An unreachable GitHub still stores the connection: the probe is
    # information, not a gate, and it can be re-run.
    probe = await _probe(provider, body_in.token, request, conn, owner)

    meta: dict[str, Any] = {
        "provider": provider,
        "createdAt": store.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "createdBy": owner,
        "tokenKind": getattr(probe, "token_kind", None),
        "scopes": list(getattr(probe, "scopes", []) or []),
        "probe": probe.as_meta(),
    }
    # This path only. Writing the whole row back meant writing back every
    # other path as it looked when this request read it, so anything stored
    # in between was silently undone. The settings field patches on every
    # keystroke, which is where the overlapping writer comes from.
    await store.put_settings_section(conn, owner, ("connections", provider), meta)

    await store.record(
        conn,
        owner_id=owner,
        actor=actor,
        action=f"Connected {provider_name(provider)}",
        target=provider,
        category="security",
        # Deliberately not the token, not its length, not a prefix: metadata
        # that narrows the value down is a slow leak.
        detail=f"Token stored encrypted. Checked: {verdict_words(probe.verdict)}.",
    )
    return _public(meta)


@router.post("/{provider}/probe")
async def reprobe_connection(
    provider: str, request: Request, conn: Db, owner: Owner, actor: Actor
) -> dict[str, Any]:
    """Re-run the one call probe against the stored token.

    The token is decrypted server side and travels only to the provider; the
    response carries the refreshed metadata, never the value.
    """
    body = await store.settings_body(conn, owner)
    connections = _connections_of(body)
    if provider not in connections:
        raise NotFound("connection", provider)
    ciphertext = await store.get_secret(conn, f"{owner}:{provider}")
    if ciphertext is None:
        raise NotFound("connection", provider)

    token = decrypt(secret_key_of(request), ciphertext)
    probe = await _probe(provider, token, request, conn, owner)

    meta = dict(connections[provider])
    meta["tokenKind"] = getattr(probe, "token_kind", None)
    meta["scopes"] = list(getattr(probe, "scopes", []) or [])
    meta["probe"] = probe.as_meta()
    await store.put_settings_section(conn, owner, ("connections", provider), meta)
    await store.record(
        conn,
        owner_id=owner,
        actor=actor,
        action=f"Checked the {provider_name(provider)} connection",
        target=provider,
        category="security",
        detail=f"{verdict_words(probe.verdict)}: {probe.reason}",
    )
    return _public(meta)


@router.delete("/{provider}", status_code=204)
async def revoke_connection(provider: str, conn: Db, owner: Owner, actor: Actor) -> None:
    body = await store.settings_body(conn, owner)
    connections = _connections_of(body)
    if provider not in connections:
        raise NotFound("connection", provider)

    await store.delete_secret(conn, f"{owner}:{provider}")
    await store.delete_settings_section(conn, owner, ("connections", provider))
    await store.record(
        conn,
        owner_id=owner,
        actor=actor,
        action=f"Removed the {provider_name(provider)} connection",
        target=provider,
        category="security",
        detail="Token deleted.",
    )
