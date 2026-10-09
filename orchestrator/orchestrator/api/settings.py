"""The settings the browser reads and edits. Secret free by refusal.

The wire shape is `SettingsState` from the contracts package: per section
configuration with no credential fields at all. A patch that tries to send one
(token, apiKey, password, connectionString) is refused with a pointer to
`/connections`, because a credential stored here would sit in a row every
settings read returns.

`connected` and `scopes` are derived from the connections store on every read
and refused on write: a stored boolean and a revoked token would disagree, and
the boolean would win on screen.
"""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import ValidationError

from ..components import spec_for
from ..db import store
from ..errors import Conflict
from .connections import KNOWN_PROVIDERS
from .deps import Actor, Db, Owner

router = APIRouter(prefix="/settings", tags=["settings"])

SECTIONS = ("git", "vercel", "render", "database", "ai", "profile")

#: Field names that are credentials wherever they appear. Checked on every
#: patch, at any depth, camel or snake.
SECRET_FIELD_NAMES = frozenset(
    {
        "token",
        "apikey",
        "api_key",
        "password",
        "connectionstring",
        "connection_string",
        "secret",
    }
)

#: Derived on read, so a write would be a lie kept until the next probe.
DERIVED_FIELD_NAMES = frozenset({"connected", "scopes"})

#: The largest photo kept, in characters of its data URL. The photo is returned
#: with every settings read, and the 2 MB files once accepted were 2.7 MB strings
#: on each of them; the browser now sends a 256 pixel square of tens of kilobytes.
PHOTO_MAX_CHARS = 200_000

#: What a photo may be: an image from the person's device, carried inline. A web
#: address would have every browser that shows the avatar fetch whatever it names.
_PHOTO_PREFIXES = tuple(f"data:image/{kind};base64," for kind in ("jpeg", "png", "webp", "gif"))


def _refuse_hostile_keys(patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        normalized = key.lower()
        if normalized in SECRET_FIELD_NAMES:
            raise Conflict(
                f"'{key}' is a credential, not a setting. Credentials go to "
                "/connections, where they are encrypted and never echoed back."
            )
        if normalized in DERIVED_FIELD_NAMES:
            raise Conflict(f"'{key}' is derived from the connections store and cannot be set.")
        if isinstance(value, dict):
            _refuse_hostile_keys(value)


async def _assembled(conn: Any, owner: str) -> dict[str, Any]:
    """Stored sections over the model defaults, with the derived fields filled
    from the connections store."""
    from sdlc_contracts import SettingsState

    body = await store.settings_body(conn, owner)
    stored = body.get("settings", {})
    state = SettingsState.model_validate(stored) if stored else SettingsState()
    view = state.model_dump(by_alias=True)

    connections = body.get("connections", {})
    for provider in KNOWN_PROVIDERS:
        meta = connections.get(provider)
        if provider == "github":
            view["git"]["connected"] = meta is not None
            view["git"]["scopes"] = list(meta.get("scopes", [])) if meta else []
        elif provider in ("vercel", "render"):
            view[provider]["connected"] = meta is not None
        elif provider == "atlas":
            view["database"]["connected"] = meta is not None

    # The name and email are the account's: one name per person, the one every
    # decision is recorded under, and the email they sign in with.
    account = await store.user_by_id(conn, owner)
    if account is not None:
        view["profile"]["name"] = account["name"]
        view["profile"]["email"] = account["email"]
    return view


@router.get("")
async def get_settings(conn: Db, owner: Owner) -> dict[str, Any]:
    return await _assembled(conn, owner)


#: Each phase, as a reader knows it, and its component: the settings that name
#: its model and its thinking are that component's.
_PHASE_MODELS = (
    ("Requirements and Design", "c1"),
    ("Code Generation", "c2"),
    ("Testing and Security", "c3"),
    ("Deployment", "c4"),
)


@router.get("/models")
async def get_models(request: Request, conn: Db, owner: Owner) -> list[dict[str, Any]]:
    """The model each phase runs, how hard it thinks, and what it last ran on.

    The model is configuration, shown and not offered: the AI Model tab once
    offered OpenAI and Claude and saved a choice nothing read. It is read from
    the phase's client, as a run records it. Thinking is the account's to
    choose (3B), saved under `ai.thinking` by the phase's `key`.

    `thinkingApplies` says whether a level changes what the phase sends
    (`_thinking_applies`). Where it does, `thinking` is the level the phase's
    next run starts at: the account's choice where it made one
    (`thinkingChosen`), and otherwise the platform's switch as configured, off
    unless turned on. Where it does not, no choice is offered and `thinking` is
    what the phase's requests say about thinking at every level, or null where
    this process cannot say.

    `lastRun` is the newest of the owner's runs in that phase that recorded
    what it ran on (0014), with its project. The configuration says what the
    next run will use; only a run says what one did use. None until a run in
    that phase has recorded it.
    """
    configured = request.app.state.settings
    clients = getattr(request.app.state, "clients", {})
    last = await store.last_run_setups(conn, owner)
    chosen = await store.thinking_choices(conn, owner)
    phases = []
    for phase, component in _PHASE_MODELS:
        key = spec_for(component).audit_category
        client = clients.get(component)
        applies = _thinking_applies(client)
        phases.append(
            {
                "phase": phase,
                "key": key,
                # The client's, which is the configured model in process and
                # names the service where a phase runs over HTTP, whose model
                # this process cannot know.
                "model": str(
                    getattr(client, "model", None) or getattr(configured, f"{component}_model")
                ),
                "thinking": (
                    chosen.get(key) or str(getattr(configured, f"{component}_thinking"))
                    if applies
                    else getattr(client, "thinking", None)
                ),
                "thinkingChosen": applies and key in chosen,
                "thinkingApplies": applies,
                "lastRun": _last_run(last.get(component)),
            }
        )
    return phases


def _thinking_applies(client: Any) -> bool:
    """Whether a level changes what a phase sends, which is when a choice means anything.

    Asked of the phase's client rather than read from the mode: a phase run as
    a separate service over HTTP thinks as that service's own configuration
    says, and a model whose provider takes no thinking setting sends the same
    request at every level. A choice offered there would be one nothing reads.
    """
    thinking_for = getattr(client, "thinking_for", None)
    return callable(thinking_for) and thinking_for("off") != thinking_for("high")


def _last_run(row: store.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "model": row["model"],
        "thinking": row["thinking"],
        "startedAt": row["started_at"].isoformat(),
        "project": row["project_name"],
    }


async def _patch_section(
    conn: Any, owner: str, section: str, patch: dict[str, Any], *, actor: str
) -> dict[str, Any]:
    _refuse_hostile_keys(patch)
    from sdlc_contracts import SettingsState

    fields = sorted(patch)
    if section == "profile":
        _refuse_unfit_photo(patch)
        patch = await _account_fields(conn, owner, patch)

    body = await store.settings_body(conn, owner)
    stored = body.setdefault("settings", {})
    current = stored.get(section, {})
    merged = {**current, **patch}

    # Validating the whole state against the contract is what refuses an
    # unknown field or a wrong type, instead of storing it. The refusal is
    # translated to the error envelope: a raw ValidationError here would be a
    # 500, which reads as the server's fault when it is the patch's.
    candidate = {**stored, section: merged}
    try:
        SettingsState.model_validate(candidate)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise Conflict(f"The {section} settings refuse this: {where}: {first['msg']}") from error

    # These fields only, merged by the database: not the row, so a patch cannot
    # write back over a connection stored while it held its copy, and not the
    # section, so two fields saved at once both stay.
    await store.merge_settings_section(conn, owner, ("settings", section), patch)
    if section == "database" and _identifiers_changed(current, patch):
        await _forget_atlas_check(conn, owner, body)
    await store.record(
        conn,
        owner_id=owner,
        actor=actor,
        action=f"Updated {section} settings",
        target=section,
        category="settings",
        detail=", ".join(fields) or "nothing",
    )
    return await _assembled(conn, owner)


#: The Atlas settings its check reads, in both spellings a patch may use.
_ATLAS_IDENTIFIERS = (
    ("projectId", "project_id"),
    ("cluster", "cluster"),
    ("clientId", "client_id"),
)


def _identifiers_changed(current: dict[str, Any], patch: dict[str, Any]) -> bool:
    for camel, snake in _ATLAS_IDENTIFIERS:
        for key in (camel, snake):
            if key in patch and patch[key] != current.get(camel, current.get(snake)):
                return True
    return False


async def _forget_atlas_check(conn: Any, owner: str, body: dict[str, Any]) -> None:
    """Drop the stored Atlas check, which was made with the identifiers just replaced.

    Its verdict was about a cluster the settings no longer name, and it read as
    current; with it gone the connection says it has not been checked.
    """
    connections = body.get("connections")
    if isinstance(connections, dict) and isinstance(connections.get("atlas"), dict):
        await store.merge_settings_section(conn, owner, ("connections", "atlas"), {"probe": None})


def _refuse_unfit_photo(patch: dict[str, Any]) -> None:
    """Keep a photo only if it is an inline image small enough to send on every read."""
    for key in ("avatarUrl", "avatar_url"):
        photo = patch.get(key)
        if photo is None:
            continue
        if not isinstance(photo, str) or not photo.startswith(_PHOTO_PREFIXES):
            raise Conflict("A photo is an image chosen from your device: JPG, PNG, WebP or GIF.")
        if len(photo) > PHOTO_MAX_CHARS:
            raise Conflict(
                f"The photo is too large to keep: the limit is {PHOTO_MAX_CHARS // 1000} KB."
            )


async def _account_fields(conn: Any, owner: str, patch: dict[str, Any]) -> dict[str, Any]:
    """The profile fields that are the account's, applied to the account.

    A new name renames the account, which every later decision is recorded
    under. The email is how the person signs in, so a settings field saved as it
    is typed must not change it: it is refused unless it is the one the account
    already has. What is left is the profile's own (the workspace, the photo).
    """
    account = await store.user_by_id(conn, owner)
    if account is None:
        return patch
    rest = dict(patch)
    email = rest.pop("email", None)
    if email is not None and str(email).strip().lower() != account["email"].lower():
        raise Conflict("The email is the one you sign in with, so it cannot be changed here.")
    if "name" in rest:
        name = " ".join(str(rest.pop("name")).split())
        if not name:
            raise Conflict("A name is needed: decisions are recorded under it.")
        await store.rename_user(conn, owner, name)
    return rest


def _section_route(section: str) -> None:
    @router.patch(f"/{section}")
    async def patch_section(  # type: ignore[unused-ignore]
        patch: dict[str, Any], conn: Db, owner: Owner, actor: Actor
    ) -> dict[str, Any]:
        return await _patch_section(conn, owner, section, patch, actor=actor)


for _section in SECTIONS:
    _section_route(_section)


@router.patch("")
async def patch_settings(
    patch: dict[str, Any], conn: Db, owner: Owner, actor: Actor
) -> dict[str, Any]:
    """A whole state patch: each present section merges into its stored one."""
    unknown = sorted(set(patch) - set(SECTIONS))
    if unknown:
        raise Conflict(f"Unknown settings sections: {', '.join(unknown)}.")
    result: dict[str, Any] = await _assembled(conn, owner)
    for section, section_patch in patch.items():
        if not isinstance(section_patch, dict):
            raise Conflict(f"'{section}' must be an object of fields to change.")
        result = await _patch_section(conn, owner, section, section_patch, actor=actor)
    return result
