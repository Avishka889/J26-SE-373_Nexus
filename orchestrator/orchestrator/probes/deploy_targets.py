"""Are these deployment credentials usable: Vercel, Render, and a Render deploy hook.

One call each, where a call is safe, and the same verdicts as the GitHub probe:
SUITABLE, WORKABLE, UNUSABLE, with a reason in plain words.

- **Vercel**: `GET /v2/user`. A 200 proves the token authenticates and names the
  account. A token without the privilege to read the whole account gets the
  limited form back; that is WORKABLE, because deploying may still work, and the
  reason says what could not be checked.
- **Render**: `GET /v1/owners`. A 200 with a workspace proves the API key reaches
  one, and names it. The platform uses this key only to read; GitHub never holds
  it (least privilege).
- **A Render deploy hook** is never called, because calling it deploys. Its
  shape is checked instead: Render's host, a service id and a key. The service id
  is not a secret and is kept as the account; the key is.

Every error path passes through `redacted`, because an upstream message this
code cannot foresee might echo the credential back.
"""

import re
from dataclasses import dataclass
from typing import Literal

import httpx

from ..crypto import redacted

VERCEL_API = "https://api.vercel.com"
RENDER_API = "https://api.render.com/v1"
PROBE_TIMEOUT_SECONDS = 10.0

Verdict = Literal["SUITABLE", "WORKABLE", "UNUSABLE"]

_DEPLOY_HOOK = re.compile(
    r"^https://api\.render\.com/deploy/(srv-[A-Za-z0-9]+)\?key=[A-Za-z0-9_-]+$"
)


@dataclass(frozen=True)
class ProviderProbe:
    verdict: Verdict
    reason: str
    #: Who the credential is: a username, a workspace, a service id. Never the value.
    account: str | None = None
    token_kind: str | None = None
    scopes: tuple[str, ...] = ()

    def as_meta(self) -> dict[str, object]:
        return {"verdict": self.verdict, "reason": self.reason, "account": self.account}


async def _get(url: str, token: str, client: httpx.AsyncClient | None) -> httpx.Response | str:
    owns = client is None
    http = client or httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS)
    try:
        return await http.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as error:
        return redacted(f"could not be reached: {error}", token)
    finally:
        if owns:
            await http.aclose()


async def probe_vercel(token: str, *, client: httpx.AsyncClient | None = None) -> ProviderProbe:
    answer = await _get(f"{VERCEL_API}/v2/user", token, client)
    if isinstance(answer, str):
        return ProviderProbe(verdict="UNUSABLE", reason=f"Vercel {answer}")
    if answer.status_code in (401, 403):
        return ProviderProbe(verdict="UNUSABLE", reason="The token does not authenticate.")
    if answer.status_code != 200:
        return ProviderProbe(
            verdict="UNUSABLE",
            reason=redacted(f"Vercel answered {answer.status_code} to the identity call.", token),
        )
    user = answer.json().get("user") or {}
    name = str(user.get("username") or user.get("id") or "") or None
    if user.get("limited"):
        return ProviderProbe(
            verdict="WORKABLE",
            reason=(
                f"Authenticates as {name}, but the token may read only a limited part of the "
                "account, so what it can deploy cannot be checked from here."
            ),
            account=name,
        )
    return ProviderProbe(verdict="SUITABLE", reason=f"Authenticates as {name}.", account=name)


async def probe_render(key: str, *, client: httpx.AsyncClient | None = None) -> ProviderProbe:
    answer = await _get(f"{RENDER_API}/owners?limit=20", key, client)
    if isinstance(answer, str):
        return ProviderProbe(verdict="UNUSABLE", reason=f"Render {answer}")
    if answer.status_code in (401, 403):
        return ProviderProbe(verdict="UNUSABLE", reason="The API key does not authenticate.")
    if answer.status_code != 200:
        return ProviderProbe(
            verdict="UNUSABLE",
            reason=redacted(f"Render answered {answer.status_code} to the workspaces call.", key),
        )
    names = [
        str((item.get("owner") or {}).get("name") or "")
        for item in answer.json()
        if isinstance(item, dict)
    ]
    names = [name for name in names if name]
    if not names:
        return ProviderProbe(
            verdict="WORKABLE", reason="Authenticates, and reaches no workspace yet."
        )
    return ProviderProbe(
        verdict="SUITABLE",
        reason=f"Reaches the workspace{'s' if len(names) > 1 else ''} {', '.join(names)}.",
        account=names[0],
    )


async def probe_render_deploy_hook(
    url: str, *, client: httpx.AsyncClient | None = None
) -> ProviderProbe:
    """Checked by its shape, never called: calling a deploy hook deploys."""
    found = _DEPLOY_HOOK.match(url.strip())
    if not found:
        return ProviderProbe(
            verdict="UNUSABLE",
            reason=(
                "This is not a Render deploy hook: one looks like "
                "https://api.render.com/deploy/srv-...?key=..."
            ),
        )
    return ProviderProbe(
        verdict="WORKABLE",
        reason=(
            f"A deploy hook for {found.group(1)}. It is not called here, because calling it "
            "deploys; the first release proves it."
        ),
        account=found.group(1),
    )
