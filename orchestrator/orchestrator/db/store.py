"""Every read and write against schema `app`.

One module rather than a file per table, because these are all raw SQL against
one schema and splitting them into ten thirty line files makes the shape harder
to see, not easier. The sections below are the seam that a repository per table
would have drawn.

Two rules hold throughout:

- Nodes persist artefacts idempotently. Only the runner writes run and gate
  lifecycle. A node that re-executes (LangGraph re-runs an interrupted node on
  resume, and the revision loop re-runs deliberately) must not create a second
  row or a second gate.
- Every automated change writes an audit entry, in the same transaction as the
  change itself, so the log cannot disagree with the state it describes.
"""

import contextlib
import copy
import hashlib
import uuid
import weakref
from collections.abc import AsyncIterator, Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import psycopg.errors
from psycopg import AsyncClientCursor, AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from sdlc_contracts import (
    ARTEFACT_KINDS,
    CODE_ARTEFACT_KINDS,
    CODE_STAGE_IDS,
    DEPLOY_ARTEFACT_KINDS,
    DEPLOY_GATED_ARTEFACT_KINDS,
    DEPLOY_STAGE_IDS,
    DESIGN_STAGE_IDS,
    TEST_ARTEFACT_KINDS,
    TEST_STAGE_IDS,
    ArtefactKind,
    CodeArtefactKind,
    CodeStageId,
    DeployArtefactKind,
    DeployStageId,
    DesignStageId,
    TestArtefactKind,
    TestStageId,
)

from ..wording import phase_name, stage_label

Row = dict[str, Any]


# ------------------------------------------------------------------ queries


@dataclass(frozen=True)
class Query:
    """One read: its SQL, its parameters, and what its rows mean.

    Neon answers about 0.2 s after each round trip from where this is used, and
    a snapshot read twenty eight times, one after another, to be composed. A
    read written as a query can share a round trip with others (`prefetch`),
    and a read-only request asks each query once (`remember_reads`); the
    store's functions still answer one read at a time, through `run`.
    """

    sql: str
    params: tuple[Any, ...] | dict[str, Any]
    shape: Callable[[list[Row]], Any]

    @property
    def key(self) -> tuple[str, str]:
        return (self.sql, repr(self.params))


def _rows(rows: list[Row]) -> list[Row]:
    return rows


def _first(rows: list[Row]) -> Row | None:
    return rows[0] if rows else None


#: What each read-only request has been answered so far, by its connection.
_ANSWERS: weakref.WeakKeyDictionary[AsyncConnection, dict[tuple[str, str], Any]] = (
    weakref.WeakKeyDictionary()
)


def remember_reads(conn: AsyncConnection) -> None:
    """Answer each query once for the rest of this read-only request.

    Never for a request that writes: its own writes, in its own transaction,
    may change what an earlier read answered.
    """
    _ANSWERS[conn] = {}


def forget_reads(conn: AsyncConnection) -> None:
    _ANSWERS.pop(conn, None)


@contextlib.asynccontextmanager
async def reads_only(conn: AsyncConnection) -> AsyncIterator[None]:
    """From here to the end of the block the request only reads: ask each query once.

    For the tail of a request that wrote. Its writes are done and its response
    is composed from reads in the same transaction, which see them; nothing in
    the block writes, so nothing an answer is kept for can change under it. A
    read-only request remembers already, and keeps doing so.
    """
    if remembering(conn):
        yield
        return
    remember_reads(conn)
    try:
        yield
    finally:
        forget_reads(conn)


def remembering(conn: AsyncConnection) -> bool:
    """Whether this request is read-only, and so answered from what it asked before."""
    return conn in _ANSWERS


async def run(conn: AsyncConnection, query: Query) -> Any:
    """One read, answered from this request's earlier answers when it has one.

    A copy, so a reader that changes what it was given cannot change what the
    next reader is given.
    """
    answers = _ANSWERS.get(conn)
    if answers is not None and query.key in answers:
        return copy.deepcopy(answers[query.key])
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query.sql, query.params)
        answer = query.shape(await cur.fetchall())
    if answers is not None:
        answers[query.key] = answer
        return copy.deepcopy(answer)
    return answer


async def prefetch(conn: AsyncConnection, *queries: Query) -> None:
    """Ask, in one round trip, what a read-only request is about to ask one by one.

    The statements go as one simple-protocol query with their parameters bound
    by psycopg on the client, the one way statements with parameters share a
    round trip (server-side binding takes one statement at a time), and each
    statement's rows come back as its own result, typed as any query's are.
    Nothing happens for a request that writes, which reads fresh every time.
    """
    answers = _ANSWERS.get(conn)
    if answers is None:
        return
    wanted = list({query.key: query for query in queries if query.key not in answers}.values())
    for query, answer in zip(wanted, await _send_together(conn, wanted), strict=True):
        answers[query.key] = answer


async def ask_together(conn: AsyncConnection, *queries: Query) -> list[Any]:
    """Several reads in one round trip, for any request, answered in order.

    Unlike `prefetch` this serves a request that writes too: the reads are asked
    at one moment, after whatever it wrote, so one round trip answers them as
    freshly as one each would.
    """
    if _ANSWERS.get(conn) is not None:
        await prefetch(conn, *queries)
        return [await run(conn, query) for query in queries]
    return await _send_together(conn, list(queries))


async def _send_together(conn: AsyncConnection, queries: list[Query]) -> list[Any]:
    if not queries:
        return []
    if len(queries) == 1:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(queries[0].sql, queries[0].params)
            return [queries[0].shape(await cur.fetchall())]
    answers = []
    async with AsyncClientCursor(conn, row_factory=dict_row) as cur:
        await cur.execute(";\n".join(cur.mogrify(query.sql, query.params) for query in queries))
        for query in queries:
            answers.append(query.shape(await cur.fetchall()))
            cur.nextset()
    return answers


#: Either phase's vocabulary. Both tables hold rows from every component, and
#: the CHECK constraints in the migrations are what actually refuse a wrong
#: one; these say so at the call site.
AnyStageId = DesignStageId | CodeStageId | TestStageId | DeployStageId
AnyArtefactKind = ArtefactKind | CodeArtefactKind | TestArtefactKind | DeployArtefactKind

RunState = Literal["queued", "running", "awaiting_gate", "done", "failed", "superseded"]
GateDecision = Literal["approved", "changes"]
ThreadKind = Literal["user_note", "answer", "stage_summary", "system"]
StageStatus = Literal["pending", "generating", "complete", "failed", "skipped"]
OverlayKind = Literal[
    "requirement_text",
    "assumption_text",
    "assumption_dismissed",
    "question_answer",
    "node_label",
    "flow_refinement",
    "architecture_selection",
]


class _Unset:
    """Sentinel meaning "leave this column as it is".

    Distinct from None, which means "set this column to null". A nullable column
    needs both, and an optional argument can only express one.
    """


UNSET = _Unset()


def now() -> datetime:
    return datetime.now(tz=UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------- audit


async def record(
    conn: AsyncConnection,
    *,
    actor: str,
    action: str,
    target: str,
    detail: str = "",
    project_id: str | None = None,
    run_id: uuid.UUID | None = None,
    category: str = "design",
    payload: dict[str, Any] | None = None,
    owner_id: str | None = None,
) -> None:
    """Write one audit entry. Called inside the transaction it describes.

    Every entry has an owner, so one owner's log never shows another's. An
    entry about a project takes the project's owner; one about the account
    itself (its settings, its connections) names the owner, and an entry with
    neither is refused rather than written where nobody can see it.
    """
    if project_id is None and owner_id is None:
        raise ValueError("an audit entry needs a project or an owner")
    await conn.execute(
        """
        INSERT INTO app.audit_events
            (project_id, run_id, actor, action, target, category, detail, payload, owner_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                COALESCE(%s, (SELECT owner_id FROM app.projects WHERE id = %s)))
        """,
        (
            project_id,
            run_id,
            actor,
            action,
            target,
            category,
            detail,
            Jsonb(payload or {}),
            owner_id,
            project_id,
        ),
    )


def phase_audit_query(
    project_id: str, categories: Collection[str], actions: Collection[str], limit: int = 200
) -> Query:
    """One phase's audit entries, newest first: its categories, and its actions filed elsewhere.

    An approval is filed under "approval" whatever the phase, so a phase names
    its own approval actions beside its categories.
    """
    return Query(
        """
        SELECT actor, action, target, detail, at FROM app.audit_events
        WHERE project_id = %s AND (category = ANY(%s) OR action = ANY(%s))
        ORDER BY at DESC, id DESC
        LIMIT %s
        """,
        (project_id, list(categories), list(actions), limit),
        _rows,
    )


async def audit_trail(
    conn: AsyncConnection,
    *,
    owner_id: str | None = None,
    project_id: str | None = None,
    limit: int = 200,
) -> list[Row]:
    """Audit entries, newest first: one owner's, one project's, or both.

    Routes always pass the signed-in owner; only internal checks read across
    owners.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if owner_id is not None:
        conditions.append("owner_id = %s")
        params.append(owner_id)
    if project_id is not None:
        conditions.append("project_id = %s")
        params.append(project_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
            SELECT id, project_id, run_id, actor, action, target, category, detail, payload, at
            FROM app.audit_events
            {where}
            ORDER BY at DESC, id DESC
            LIMIT %s
            """,
            (*params, limit),
        )
        return await cur.fetchall()


# ------------------------------------------------------------------ accounts


_USER_COLUMNS = "id, email, name, password_hash"


async def user_by_id(conn: AsyncConnection, user_id: str) -> Row | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT {_USER_COLUMNS} FROM app.users WHERE id = %s", (user_id,))
        return await cur.fetchone()


async def user_by_email(conn: AsyncConnection, email: str) -> Row | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {_USER_COLUMNS} FROM app.users WHERE lower(email) = lower(%s)", (email,)
        )
        return await cur.fetchone()


async def adopt_unclaimed_owner(
    conn: AsyncConnection, *, owner_id: str, email: str, name: str, password_hash: str
) -> Row | None:
    """Give the identity from before sign-in to the first account registered.

    Atomic on the null password, so two first registrations cannot both claim
    it: the second finds it claimed and gets an account of its own.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
            UPDATE app.users SET email = %s, name = %s, password_hash = %s
            WHERE id = %s AND password_hash IS NULL
            RETURNING {_USER_COLUMNS}
            """,
            (email, name, password_hash, owner_id),
        )
        return await cur.fetchone()


async def create_user(
    conn: AsyncConnection, *, user_id: str, email: str, name: str, password_hash: str
) -> Row:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""
            INSERT INTO app.users (id, email, name, password_hash)
            VALUES (%s, %s, %s, %s)
            RETURNING {_USER_COLUMNS}
            """,
            (user_id, email, name, password_hash),
        )
        row = await cur.fetchone()
        assert row is not None
        return row


async def rename_user(conn: AsyncConnection, user_id: str, name: str) -> None:
    await conn.execute("UPDATE app.users SET name = %s WHERE id = %s", (name, user_id))


async def create_session(
    conn: AsyncConnection, *, token_hash: str, user_id: str, days: int
) -> None:
    await conn.execute(
        """
        INSERT INTO app.sessions (token_hash, user_id, expires_at)
        VALUES (%s, %s, now() + make_interval(days => %s))
        """,
        (token_hash, user_id, days),
    )


async def session_user(conn: AsyncConnection, token_hash: str) -> Row | None:
    """The account a session token signs in, if the session exists and is current."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT u.id, u.email, u.name
            FROM app.sessions s JOIN app.users u ON u.id = s.user_id
            WHERE s.token_hash = %s AND s.expires_at > now()
            """,
            (token_hash,),
        )
        return await cur.fetchone()


async def delete_session(conn: AsyncConnection, token_hash: str) -> None:
    await conn.execute("DELETE FROM app.sessions WHERE token_hash = %s", (token_hash,))


# ------------------------------------------------------------------ projects


#: The colour every project was given before each had one of its own.
LEGACY_PROJECT_COLOR = "#2563eb"

#: The colours a project is given, all readable behind white text and beside
#: the app's blue: every project was that one blue, so no two could be told
#: apart at a glance.
PROJECT_PALETTE = (
    "#2563eb",
    "#7c3aed",
    "#059669",
    "#d97706",
    "#db2777",
    "#0891b2",
    "#4f46e5",
    "#0d9488",
    "#c2410c",
    "#9333ea",
)


def colour_for(project_id: str) -> str:
    """A project's colour, the same every time for the same project."""
    digest = hashlib.sha256(project_id.encode("utf-8")).digest()
    return PROJECT_PALETTE[digest[0] % len(PROJECT_PALETTE)]


async def create_project(
    conn: AsyncConnection,
    *,
    name: str,
    owner_id: str,
    description: str = "",
    color: str | None = None,
) -> Row:
    """A project, belonging to somebody.

    `owner_id` has no default on purpose. A default here is how every project
    ends up owned by whoever the default names, discovered the first time two
    people use this.
    """
    project_id = new_id("p")
    color = color or colour_for(project_id)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            INSERT INTO app.projects (id, name, description, color, owner_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (project_id, name, description, color, owner_id),
        )
        project = await cur.fetchone()
    assert project is not None

    # Eight stage rows up front, so the read path never has to invent one and
    # `stages` in the snapshot is always complete.
    async with conn.cursor() as cur:
        await cur.executemany(
            "INSERT INTO app.stage_states (project_id, stage_id) VALUES (%s, %s)",
            [(project_id, stage) for stage in DESIGN_STAGE_IDS],
        )
    await record(
        conn,
        actor="system",
        action="Created the project",
        target=name,
        detail="Eight design stages initialised as pending.",
        project_id=project_id,
    )
    return project


def get_project_query(project_id: str, owner_id: str) -> Query:
    return Query(
        "SELECT * FROM app.projects WHERE id = %s AND owner_id = %s", (project_id, owner_id), _first
    )


def chosen_stacks_queries(owner_id: str, project_id: str | None = None) -> tuple[Query, Query]:
    """The newest stack artefact, and the newest stack selection, of each project."""
    scope = "p.owner_id = %s AND (%s::text IS NULL OR p.id = %s)"
    params = (owner_id, project_id, project_id)
    return (
        Query(
            f"""
            SELECT DISTINCT ON (a.project_id) a.project_id, a.body
            FROM app.artefacts a JOIN app.projects p ON p.id = a.project_id
            WHERE {scope} AND a.kind = 'tech-stack'
            ORDER BY a.project_id, a.version DESC
            """,
            params,
            _rows,
        ),
        Query(
            f"""
            SELECT DISTINCT ON (o.project_id) o.project_id, o.value
            FROM app.design_overlays o JOIN app.projects p ON p.id = o.project_id
            WHERE {scope} AND o.kind = 'stack_selection'
            ORDER BY o.project_id, o.version DESC, o.at DESC
            """,
            params,
            _rows,
        ),
    )


async def chosen_stacks(
    conn: AsyncConnection, owner_id: str, project_id: str | None = None
) -> dict[str, list[str]]:
    """Each project's stack as its code phase chose it: the selected candidate's layers.

    Nothing wrote a project's stack, so every card went without one, released
    Book Tracker's included. Read from the newest stack artefact and the newest
    selection, the same way the code page reads them, so the card says what
    Code Generation built.
    """
    stacks_query, selections_query = chosen_stacks_queries(owner_id, project_id)
    selections = {row["project_id"]: str(row["value"]) for row in await run(conn, selections_query)}
    chosen: dict[str, list[str]] = {}
    for row in await run(conn, stacks_query):
        candidates = row["body"].get("candidates") or []
        ids = {candidate.get("id") for candidate in candidates}
        wanted = selections.get(row["project_id"])
        selected = wanted if wanted in ids else row["body"].get("selectedId")
        for candidate in candidates:
            if candidate.get("id") == selected:
                chosen[row["project_id"]] = [
                    layer["choice"]
                    for layer in candidate.get("layers") or []
                    if layer.get("choice")
                ]
    return chosen


async def get_project(conn: AsyncConnection, project_id: str, *, owner_id: str) -> Row | None:
    """One project, if it belongs to this owner.

    A project somebody else owns reads as one that does not exist, which is the
    same answer for the same reason: telling a caller that an id exists but is
    not theirs tells them something they have no business knowing.

    This is the choke point. Everything else keys off `project_id`, so a caller
    that cannot get the project cannot reach its artefacts, runs, gates or chat.
    """
    return await run(conn, get_project_query(project_id, owner_id))


async def project_without_owner_check(conn: AsyncConnection, project_id: str) -> Row | None:
    """A project, read without asking who owns it.

    The one escape hatch, named so that using it is a decision rather than an
    oversight. Legitimate in exactly two places, and both for the same reason:
    the claim was already established before the call.

    The run supervisor has no request and no session. Whoever owned the project
    authorised the run when they created it, and a worker picking it up later
    cannot re-check a claim nobody is making; scoping it would mean inventing an
    identity for a background task.

    `patch_project` re-reads the row when a patch turns out to change nothing,
    and every caller of it has already been through `require_project`.

    Anywhere else, use `get_project`.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM app.projects WHERE id = %s", (project_id,))
        return await cur.fetchone()


def list_projects_query(owner_id: str) -> Query:
    return Query(
        "SELECT * FROM app.projects WHERE owner_id = %s ORDER BY created_at DESC",
        (owner_id,),
        _rows,
    )


async def list_projects(conn: AsyncConnection, *, owner_id: str) -> list[Row]:
    return await run(conn, list_projects_query(owner_id))


def approved_through_patches(
    version: int, approved: Collection[int], patched: Mapping[int, int]
) -> bool:
    """Whether a code version was approved, at its own review or through its fix.

    A version written by applying an accepted security fix has no review of
    its own: the build was approved and so was the patch, and there is no third
    thing to ask about. The walk follows recorded patches, never arithmetic on
    version numbers, so a version that reached the store some other way stops
    the walk and must be approved itself.
    """
    return bool(approval_covering(version, approved, patched))


def approval_covering(version: int, approved: Collection[int], patched: Mapping[int, int]) -> int:
    """The approved version whose review covers this one, through any fixes; 0 for none."""
    seen: set[int] = set()
    while version and version not in approved and version in patched and version not in seen:
        seen.add(version)
        version = patched[version]
    return version if version and version in approved else 0


def design_source_through_patches(
    version: int, sources: Mapping[int, int], patched: Mapping[int, int]
) -> int | None:
    """The design version a code version came from, through any fixes applied to it."""
    seen: set[int] = set()
    while version and version not in seen:
        seen.add(version)
        if version in sources:
            return sources[version]
        version = patched.get(version, 0)
    return None


def project_progress_queries(owner_id: str, project_id: str | None = None) -> tuple[Query, ...]:
    """What `project_progress` asks, for a read-only request to prefetch with its own reads."""
    params = {
        "owner": owner_id,
        "project": project_id,
        "code": list(CODE_ARTEFACT_KINDS),
        "test": list(TEST_ARTEFACT_KINDS),
        "deploy": list(DEPLOY_ARTEFACT_KINDS),
    }
    scope = "p.owner_id = %(owner)s AND (%(project)s::text IS NULL OR p.id = %(project)s)"
    return (
        Query(
            f"""
        SELECT p.id,
               coalesce(s.stages, '{{}}'::jsonb) AS stages,
               v.design_version, v.code_version, v.test_version, v.deploy_version,
               EXISTS (SELECT 1 FROM app.runs r WHERE r.project_id = p.id) AS ran,
               EXISTS (
                   SELECT 1 FROM app.gates g
                   WHERE g.project_id = p.id AND g.kind = 'c1-design-review'
                     AND g.state = 'resolved' AND g.decision = 'approved'
                     AND g.requirements_version = v.design_version
               ) AS design_approved,
               EXISTS (
                   SELECT 1 FROM app.gates g
                   WHERE g.project_id = p.id AND g.kind = 'c3-test-review'
                     AND g.state = 'resolved' AND g.decision = 'approved'
                     AND g.requirements_version = v.test_version
               ) AS tests_approved_here,
               (
                   SELECT r.source_version FROM app.runs r
                   WHERE r.project_id = p.id AND r.component = 'c3'
                     AND r.only_stage IS NULL AND r.requirements_version = v.test_version
                   ORDER BY r.started_at DESC LIMIT 1
               ) AS tests_measured,
               EXISTS (
                   SELECT 1 FROM app.deployments d
                   WHERE d.project_id = p.id AND d.deploy_version = v.deploy_version
                     AND d.kind = 'release' AND d.verified AND d.state = 'succeeded'
               ) AS released_here,
               coalesce((
                   SELECT array_agg(newest.component) FROM (
                       SELECT DISTINCT ON (r.component) r.component, r.state
                       FROM app.runs r
                       WHERE r.project_id = p.id AND r.only_stage IS NULL
                       ORDER BY r.component, r.started_at DESC
                   ) newest
                   WHERE newest.state = 'failed'
               ), '{{}}') AS stopped
        FROM app.projects p
        LEFT JOIN (
            SELECT project_id, jsonb_object_agg(stage_id, status) AS stages
            FROM app.stage_states GROUP BY project_id
        ) s ON s.project_id = p.id
        CROSS JOIN LATERAL (
            SELECT
                (SELECT coalesce(max(version), 0) FROM app.design_versions dv
                 WHERE dv.project_id = p.id AND dv.applied_at IS NOT NULL) AS design_version,
                (SELECT coalesce(max(version), 0) FROM app.artefacts a
                 WHERE a.project_id = p.id AND a.kind = ANY(%(code)s)) AS code_version,
                (SELECT coalesce(max(version), 0) FROM app.artefacts a
                 WHERE a.project_id = p.id AND a.kind = ANY(%(test)s)) AS test_version,
                (SELECT coalesce(max(version), 0) FROM app.artefacts a
                 WHERE a.project_id = p.id AND a.kind = ANY(%(deploy)s)) AS deploy_version
        ) v
        WHERE {scope}
        
            """,
            params,
            _rows,
        ),
        Query(
            f"""
        SELECT g.project_id, g.requirements_version FROM app.gates g
        JOIN app.projects p ON p.id = g.project_id
        WHERE {scope} AND g.kind = 'c2-code-review'
          AND g.state = 'resolved' AND g.decision = 'approved'
        
            """,
            params,
            _rows,
        ),
        Query(
            f"""
        SELECT o.project_id, o.value FROM app.design_overlays o
        JOIN app.projects p ON p.id = o.project_id
        WHERE {scope} AND o.kind = 'remediation_decision'
        
            """,
            params,
            _rows,
        ),
        Query(
            f"""
        SELECT r.project_id, r.requirements_version, r.source_version FROM app.runs r
        JOIN app.projects p ON p.id = r.project_id
        WHERE {scope} AND r.component = 'c2' AND r.only_stage IS NULL
          AND r.source_version IS NOT NULL
        ORDER BY r.started_at
        
            """,
            params,
            _rows,
        ),
    )


async def project_progress(
    conn: AsyncConnection, *, owner_id: str, project_id: str | None = None
) -> dict[str, dict[str, Any]]:
    """What a project's status is derived from, for every project or one.

    The list and a project's own page read the same facts, so they cannot
    disagree; they derived the status two ways and did. Each phase counts only
    when its current version is approved and agrees with the phase before it:
    an approval of any version ever made, which is what this read before, kept
    a project in Testing while its newest design waited on its review.

    A constant number of round trips, because the list grows and a per project
    query does not: composing a snapshot per project took twenty one seconds.
    """
    # One round trip for the four, however many projects there are. The code
    # axis needs two walks over recorded fixes, which SQL would make
    # unreadable: the versions approved at their own review, the fixes applied,
    # and the design version each generated version came from.
    main, approved_rows, fix_rows, source_rows = await ask_together(
        conn, *project_progress_queries(owner_id, project_id)
    )
    rows = {row["id"]: row for row in main}
    approved_code: dict[str, set[int]] = {}
    for row in approved_rows:
        approved_code.setdefault(row["project_id"], set()).add(int(row["requirements_version"]))
    patched: dict[str, dict[int, int]] = {}
    for row in fix_rows:
        value = row["value"] or {}
        if value.get("appliedCodeVersion"):
            patched.setdefault(row["project_id"], {})[int(value["appliedCodeVersion"])] = int(
                value.get("patchedCodeVersion") or 0
            )
    sources: dict[str, dict[int, int]] = {}
    for row in source_rows:
        sources.setdefault(row["project_id"], {})[int(row["requirements_version"])] = int(
            row["source_version"]
        )

    facts: dict[str, dict[str, Any]] = {}
    for pid, row in rows.items():
        fixes = patched.get(pid, {})
        code_version = int(row["code_version"])
        design_ok = bool(row["design_approved"])
        came_from = design_source_through_patches(code_version, sources.get(pid, {}), fixes)
        code_ok = (
            design_ok
            and approved_through_patches(code_version, approved_code.get(pid, set()), fixes)
            and came_from in (None, int(row["design_version"]))
        )
        tests_ok = (
            code_ok and bool(row["tests_approved_here"]) and row["tests_measured"] == code_version
        )
        facts[pid] = {
            "stages": dict(row["stages"] or {}),
            "started": int(row["design_version"]) > 0 or bool(row["ran"]),
            "approved": design_ok,
            "code_approved": code_ok,
            "test_approved": tests_ok,
            "released": tests_ok and bool(row["released_here"]),
            "stopped": set(row["stopped"] or ()),
        }
    return facts


async def delete_project(conn: AsyncConnection, project_id: str, *, owner_id: str) -> None:
    await conn.execute(
        "DELETE FROM app.projects WHERE id = %s AND owner_id = %s", (project_id, owner_id)
    )


async def work_in_progress(conn: AsyncConnection, project_id: str) -> str | None:
    """What is running on a project now, in words, or None.

    A run that is queued or running on any phase, or a release still pending or
    running. A run paused at its review is not work in progress: it waits on a
    person, and deleting the project is that person's decision.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT component FROM app.runs WHERE project_id = %s AND state = ANY(%s) LIMIT 1",
            (project_id, list(WORKING_RUN_STATES)),
        )
        working = await cur.fetchone()
        if working is not None:
            return f"A {phase_name(working['component'])} run"
        await cur.execute(
            "SELECT 1 FROM app.deployments WHERE project_id = %s"
            " AND state IN ('pending', 'running') LIMIT 1",
            (project_id,),
        )
        if await cur.fetchone() is not None:
            return "A release"
    return None


async def keep_audit_trail(conn: AsyncConnection, project_id: str) -> None:
    """Detach a project's audit entries so they outlive it; they keep their owner."""
    await conn.execute(
        "UPDATE app.audit_events SET project_id = NULL WHERE project_id = %s", (project_id,)
    )


#: What a client may change on a project. `status`, `reqPhase` and `progress`
#: are absent deliberately: they are derived from run and stage state when the
#: project is read, so a client cannot patch the project into a state the run
#: does not agree with.
PATCHABLE_PROJECT_FIELDS = frozenset(
    {"name", "description", "requirement_text", "files", "tech_stack", "color"}
)


async def patch_project(
    conn: AsyncConnection, project_id: str, patch: dict[str, Any]
) -> Row | None:
    """Write the patchable fields, authorised by the caller rather than here.

    Unscoped on purpose, and the second of exactly two places that are. Its two
    callers have both already established the claim: the route goes through
    `require_project`, and the supervisor renaming a project during a run has no
    session to check because the run was authorised when it was created.

    A third caller would be a mistake. If one appears, either it goes through
    `require_project` first or this grows an `owner_id` and everything moves.
    """
    fields = {k: v for k, v in patch.items() if k in PATCHABLE_PROJECT_FIELDS}
    if not fields:
        # Nothing to write, so this is a re-read of a row the caller already
        # proved it may see. See project_without_owner_check.
        return await project_without_owner_check(conn, project_id)

    assignments = ", ".join(f"{name} = %s" for name in fields)
    values: list[Any] = [
        Jsonb(value) if name in {"files", "tech_stack"} else value for name, value in fields.items()
    ]
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"UPDATE app.projects SET {assignments}, updated_at = now() WHERE id = %s RETURNING *",
            (*values, project_id),
        )
        return await cur.fetchone()


async def append_chat_message(
    conn: AsyncConnection, project_id: str, *, role: str, type_: str, content: str
) -> None:
    await conn.execute(
        """
        INSERT INTO app.requirement_chat_messages (project_id, role, type, content)
        VALUES (%s, %s, %s, %s)
        """,
        (project_id, role, type_, content),
    )


def chat_messages_query(project_id: str) -> Query:
    return Query(
        """
        SELECT id, role, type, content, created_at
        FROM app.requirement_chat_messages
        WHERE project_id = %s
        ORDER BY created_at
        """,
        (project_id,),
        _rows,
    )


async def chat_messages(conn: AsyncConnection, project_id: str) -> list[Row]:
    return await run(conn, chat_messages_query(project_id))


# ------------------------------------------------------------------ versions


def _version_of(rows: list[Row]) -> int:
    return int(rows[0]["version"]) if rows else 0


def current_version_query(project_id: str) -> Query:
    return Query(
        """
        SELECT coalesce(max(version), 0) AS version FROM app.design_versions
        WHERE project_id = %s AND applied_at IS NOT NULL
        """,
        (project_id,),
        _version_of,
    )


async def current_version(conn: AsyncConnection, project_id: str) -> int:
    """The highest applied requirements version. Zero means nothing has run."""
    return await run(conn, current_version_query(project_id))


async def open_version(
    conn: AsyncConnection, project_id: str, *, note: str | None, by: str, applied: bool
) -> int:
    """Add a version. `applied=False` queues a change note for the loop point.

    A note that arrives while a run is in flight must not start a second graph on
    the same thread id, so it waits here and is drained when the run reaches the
    point where it can take it.
    """
    row = await (
        await conn.execute(
            "SELECT coalesce(max(version), 0) + 1 FROM app.design_versions WHERE project_id = %s",
            (project_id,),
        )
    ).fetchone()
    version = int(row[0]) if row else 1
    await conn.execute(
        """
        INSERT INTO app.design_versions (project_id, version, note, created_by, applied_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (project_id, version, note, by, now() if applied else None),
    )
    return version


def queued_notes_query(project_id: str) -> Query:
    return Query(
        """
        SELECT version, note FROM app.design_versions
        WHERE project_id = %s AND applied_at IS NULL
        ORDER BY version
        """,
        (project_id,),
        _rows,
    )


async def queued_notes(conn: AsyncConnection, project_id: str) -> list[Row]:
    return await run(conn, queued_notes_query(project_id))


async def applied_notes(conn: AsyncConnection, project_id: str, up_to_version: int) -> list[str]:
    """Every applied change note up to a version, oldest first.

    The graph's input at version N is the requirement text plus this. Reading it
    from the table rather than passing it along the call that happened to start
    the run means no path can start a run that silently ignores a note somebody
    wrote, which is what happened when the initial state seeded an empty list.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT note FROM app.design_versions
            WHERE project_id = %s AND version <= %s
              AND applied_at IS NOT NULL AND note IS NOT NULL
            ORDER BY version
            """,
            (project_id, up_to_version),
        )
        return [row[0] for row in await cur.fetchall()]


async def apply_version(conn: AsyncConnection, project_id: str, version: int) -> None:
    await conn.execute(
        """
        UPDATE app.design_versions SET applied_at = now()
        WHERE project_id = %s AND version = %s AND applied_at IS NULL
        """,
        (project_id, version),
    )


async def claim_next_version(
    conn: AsyncConnection, project_id: str, *, note: str | None, by: str
) -> tuple[int, list[str]]:
    """Allocate the version a regeneration writes to, and drain the queue into it.

    This table is the only authority on version numbers. A node that computed its
    own next version would hand out a number `open_version` later hands out
    again, and because artefacts upsert on `(project_id, kind, version)` the
    second writer would overwrite the first one's history. That history is what
    the evaluation compares, so allocation lives here.

    Notes that arrived while a run was in flight are sitting unapplied. They are
    claimed here rather than left behind, because the regeneration about to
    happen is the thing that applies them.

    Returns the version to write at and every note that version accounts for.
    """
    queued = await claim_queued(conn, project_id)
    notes = [row["note"] for row in queued if row["note"]]

    if note:
        notes.append(note)
        # The decision's own note is a change in its own right, so it gets a row.
        version = await open_version(conn, project_id, note=note, by=by, applied=True)
    elif queued and int(queued[-1]["version"]) == await newest_version(conn, project_id):
        version = int(queued[-1]["version"])
    else:
        # Never below the newest version: a run started there writes a version
        # whose review the page never shows, because it shows the newest.
        version = await open_version(conn, project_id, note=None, by=by, applied=True)
    return version, notes


async def claim_queued(conn: AsyncConnection, project_id: str) -> list[Row]:
    """Apply every queued change note, so the next version's run reads it.

    A note queued behind a run that then stopped was left behind: the next
    change opened a version without it, since only applied notes are a run's
    input, and nothing drained it until a later run finished.
    """
    queued = await queued_notes(conn, project_id)
    for row in queued:
        await apply_version(conn, project_id, int(row["version"]))
    return queued


async def newest_version(conn: AsyncConnection, project_id: str) -> int:
    """The highest design version opened, applied or not."""
    row = await (
        await conn.execute(
            "SELECT coalesce(max(version), 0) FROM app.design_versions WHERE project_id = %s",
            (project_id,),
        )
    ).fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------- runs


async def create_run(
    conn: AsyncConnection,
    *,
    project_id: str,
    requirements_version: int,
    component: str = "c1",
    only_stage: str | None = None,
    source_version: int | None = None,
) -> Row:
    """A queued run. Its id is also the LangGraph thread id.

    `only_stage` narrows it to regenerating that one artefact, which never
    reaches a gate. Null is the ordinary case: a full pass through the graph.

    `requirements_version` is the version this run produces on its own
    component's axis: the design version for C1, the code version for C2.
    `source_version` is the upstream version it read, which a C2 run pins so
    the design moving on mid run cannot change what it generated from.
    """
    run_id = uuid.uuid4()
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            INSERT INTO app.runs
                (id, project_id, component, requirements_version, state, only_stage,
                 source_version)
            VALUES (%s, %s, %s, %s, 'queued', %s, %s)
            RETURNING *
            """,
            (run_id, project_id, component, requirements_version, only_stage, source_version),
        )
        run = await cur.fetchone()
    assert run is not None
    await record(
        conn,
        actor="system",
        action="Queued a run",
        target=str(run_id),
        detail=(
            f"{phase_name(component)}, version {requirements_version}"
            + (f", regenerating {stage_label(only_stage)} only." if only_stage else ".")
        ),
        project_id=project_id,
        run_id=run_id,
    )
    return run


def get_run_query(run_id: uuid.UUID) -> Query:
    return Query("SELECT * FROM app.runs WHERE id = %s", (run_id,), _first)


async def get_run(conn: AsyncConnection, run_id: uuid.UUID) -> Row | None:
    return await run(conn, get_run_query(run_id))


def project_runs_query(project_id: str) -> Query:
    return Query(
        "SELECT * FROM app.runs WHERE project_id = %s ORDER BY started_at DESC",
        (project_id,),
        _rows,
    )


async def project_runs(conn: AsyncConnection, project_id: str) -> list[Row]:
    """One project's runs, newest first, for a caller that has checked its owner."""
    return await run(conn, project_runs_query(project_id))


async def list_runs(
    conn: AsyncConnection, project_id: str | None = None, *, owner_id: str
) -> list[Row]:
    """One account's runs, newest first: every account's, before sign-in made two."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT r.* FROM app.runs r
            JOIN app.projects p ON p.id = r.project_id
            WHERE p.owner_id = %s AND (%s::text IS NULL OR r.project_id = %s)
            ORDER BY r.started_at DESC LIMIT 100
            """,
            (owner_id, project_id, project_id),
        )
        return await cur.fetchall()


def latest_run_query(project_id: str, component: str | None = None) -> Query:
    return Query(
        """
        SELECT * FROM app.runs
        WHERE project_id = %s AND (%s::text IS NULL OR component = %s)
        ORDER BY started_at DESC LIMIT 1
        """,
        (project_id, component, component),
        _first,
    )


async def latest_run(
    conn: AsyncConnection, project_id: str, *, component: str | None = None
) -> Row | None:
    """The newest run, optionally on one component's axis.

    The filter matters wherever "is a run in flight" is asked: the design and
    the code axes are separate LangGraph threads, so a code run paused at its
    gate must not make the design phase think it is busy.
    """
    return await run(conn, latest_run_query(project_id, component))


async def last_run_setups(conn: AsyncConnection, owner_id: str) -> dict[str, Row]:
    """Per component, the newest of this owner's runs that recorded what it ran on.

    Runs from before 0014 recorded nothing and are skipped rather than shown
    as a blank: "not recorded" belongs to the run, not to the phase.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT DISTINCT ON (r.component)
                   r.component, r.model, r.thinking, r.started_at, p.name AS project_name
            FROM app.runs r JOIN app.projects p ON p.id = r.project_id
            WHERE p.owner_id = %s AND r.model IS NOT NULL
            ORDER BY r.component, r.started_at DESC
            """,
            (owner_id,),
        )
        return {row["component"]: row for row in await cur.fetchall()}


#: A run in any of these is still working, or paused waiting on a person.
ACTIVE_RUN_STATES = ("queued", "running", "awaiting_gate")

#: A run doing work now, as against one paused at its gate. A stage may be
#: retried while a review waits, never while a run is working.
WORKING_RUN_STATES = ("queued", "running")


def active_run_query(
    project_id: str, component: str, states: tuple[str, ...] = ACTIVE_RUN_STATES
) -> Query:
    return Query(
        """
        SELECT * FROM app.runs
        WHERE project_id = %s AND component = %s AND state = ANY(%s)
        ORDER BY started_at DESC LIMIT 1
        """,
        (project_id, component, list(states)),
        _first,
    )


async def active_run(
    conn: AsyncConnection,
    project_id: str,
    *,
    component: str,
    states: tuple[str, ...] = ACTIVE_RUN_STATES,
) -> Row | None:
    """Any run on one component's axis that is not finished, newest first.

    Not the newest run: a stage retry is a run of its own that finishes in a
    moment, and asking only the newest one missed an older run still paused at
    its gate beneath it.
    """
    return await run(conn, active_run_query(project_id, component, states))


def latest_full_run_query(project_id: str, component: str) -> Query:
    return Query(
        """
        SELECT * FROM app.runs
        WHERE project_id = %s AND component = %s AND only_stage IS NULL
        ORDER BY started_at DESC LIMIT 1
        """,
        (project_id, component),
        _first,
    )


async def latest_full_run(conn: AsyncConnection, project_id: str, *, component: str) -> Row | None:
    """The newest run that walks the phase's graph, as against a stage retry.

    The full run is the one that reaches the review, so it is the one whose
    failure leaves the phase stuck; a retry finished after it must not hide it.
    """
    return await run(conn, latest_full_run_query(project_id, component))


#: The resume payload of a stopped run a person asked to continue. Not a gate
#: decision: the runner invokes the graph with no input, so LangGraph goes on
#: from the run's last saved step instead of resuming an interrupt.
CONTINUE_AFTER_STOP: dict[str, Any] = {"continue": "after-stop"}


async def requeue_to_continue(conn: AsyncConnection, run_id: uuid.UUID) -> Row | None:
    """Queue a stopped run to go on from where it stopped, once.

    Conditional on the run still being failed, so a second request finds it
    queued and is refused rather than queueing it twice.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            UPDATE app.runs
            SET state = 'queued', error = NULL, finished_at = NULL,
                heartbeat_at = now(), resume_payload = %s
            WHERE id = %s AND state = 'failed'
            RETURNING *
            """,
            (Jsonb(CONTINUE_AFTER_STOP), run_id),
        )
        return await cur.fetchone()


async def lock_run_axis(conn: AsyncConnection, project_id: str, component: str) -> None:
    """Start runs on one phase of one project one request at a time.

    Asking whether a run is in flight and starting one are two statements, so
    two requests that arrived together, a double click, both found nothing and
    both started a run. The lock is the transaction's own: the second request
    waits here until the first has committed its run, then finds it and is
    refused. Taken before the question, never after.
    """
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"runs:{project_id}:{component}",),
    )


async def set_run_state(
    conn: AsyncConnection,
    run_id: uuid.UUID,
    state: RunState,
    *,
    error: str | None = None,
    resume_payload: _Unset | dict[str, Any] | None = UNSET,
) -> None:
    """Move a run. Omitting resume_payload leaves it alone; None clears it."""
    sets = ["state = %s", "heartbeat_at = now()"]
    values: list[Any] = [state]
    if state in {"done", "failed", "superseded"}:
        sets.append("finished_at = now()")
    if error is not None:
        sets.append("error = %s")
        values.append(error)
    if not isinstance(resume_payload, _Unset):
        sets.append("resume_payload = %s")
        values.append(Jsonb(resume_payload) if resume_payload is not None else None)
    await conn.execute(f"UPDATE app.runs SET {', '.join(sets)} WHERE id = %s", (*values, run_id))


async def set_run_version(conn: AsyncConnection, run_id: uuid.UUID, version: int) -> None:
    """Point a run at the version it is now producing.

    A run that loops through the gate regenerates at a later version than the one
    it started on, and `/runs` would otherwise keep reporting the first.
    """
    await conn.execute(
        "UPDATE app.runs SET requirements_version = %s WHERE id = %s", (version, run_id)
    )


async def record_run_setup(
    conn: AsyncConnection, run_id: uuid.UUID, *, model: str | None, thinking: str | None
) -> None:
    """Write down what a run runs on, once, when it starts (0014).

    A regeneration after "changes" keeps the run's own record: it resumes the
    same run, and says in its audit entry what it ran on.
    """
    await conn.execute(
        "UPDATE app.runs SET model = %s, thinking = %s WHERE id = %s", (model, thinking, run_id)
    )


async def heartbeat(conn: AsyncConnection, run_id: uuid.UUID) -> None:
    await conn.execute("UPDATE app.runs SET heartbeat_at = now() WHERE id = %s", (run_id,))


#: Past this, a run is abandoned rather than stalled and is never reclaimed.
#:
#: Comfortably beyond any real run (a design run is minutes, a code run about
#: two) and far short of the three days that made this necessary. A row this
#: old belongs to a process nobody is waiting for.
ABANDONED_AFTER_SECONDS = 6 * 3600


async def claimable_runs(
    conn: AsyncConnection,
    *,
    stale_by_component: dict[str, int] | None = None,
    abandoned_after: int = ABANDONED_AFTER_SECONDS,
) -> list[Row]:
    """Runs to pick up: queued, or running with a heartbeat that stopped.

    The second case is what makes a restart recover rather than leaving a run
    stuck at `generating` for good.

    The stale window is per component, because a code generation stage is
    legitimately slower than a design stage: reclaiming a C2 run on C1's clock
    would restart work that was making progress. A component absent from the
    map gets the 90 second default the spine started with.
    """
    windows = Jsonb(stale_by_component or {})
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT * FROM app.runs
            WHERE state = 'queued'
               OR (state = 'running'
                   AND (heartbeat_at IS NULL
                        OR heartbeat_at < now() - make_interval(
                            secs => COALESCE((%s ->> component)::int, 90)))
                   -- And not so old that it is abandoned rather than stalled.
                   -- The window above was written for a worker that crashed
                   -- seconds ago; it treated a three day old row identically,
                   -- and one was reclaimed and restarted over an approved
                   -- design.
                   --
                   -- `started_at` when there is no heartbeat, because a run
                   -- that died before its first one has a NULL there, and a
                   -- NULL compared with anything is NULL: written as a plain
                   -- `heartbeat_at >` this ceiling would have made exactly the
                   -- crashed-on-entry case unrecoverable, which is the case
                   -- the reclaim window exists for.
                   AND coalesce(heartbeat_at, started_at) > now() - make_interval(secs => %s))
            ORDER BY started_at
            LIMIT 20
            """,
            (windows, abandoned_after),
        )
        return await cur.fetchall()


async def running_runs(
    conn: AsyncConnection, *, abandoned_after: int = ABANDONED_AFTER_SECONDS
) -> list[Row]:
    """Runs a process said it was running, and not so long ago that they are abandoned.

    Read when a process starts, before it has started any run of its own, so
    every one of these was left by the process before it.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT * FROM app.runs
            WHERE state = 'running'
              AND coalesce(heartbeat_at, started_at) > now() - make_interval(secs => %s)
            ORDER BY started_at
            """,
            (abandoned_after,),
        )
        return await cur.fetchall()


# --------------------------------------------------------------------- gates


async def abandoned_runs(
    conn: AsyncConnection, *, abandoned_after: int = ABANDONED_AFTER_SECONDS
) -> list[Row]:
    """Runs too old to be recovered, still claiming to be in flight.

    They are marked failed rather than left saying running, because a row that
    says running describes work that is happening, and none is.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT * FROM app.runs
            WHERE state IN ('running', 'queued')
              AND coalesce(heartbeat_at, started_at) < now() - make_interval(secs => %s)
            ORDER BY started_at
            LIMIT 20
            """,
            (abandoned_after,),
        )
        return await cur.fetchall()


async def open_gate(
    conn: AsyncConnection,
    *,
    run_id: uuid.UUID,
    project_id: str,
    requirements_version: int,
    payload: dict[str, Any],
    interrupt_id: str | None,
    kind: str = "c1-design-review",
) -> Row:
    """Record that a run is waiting on a human.

    Written by the runner, never by the gate node: the node re-executes on
    resume, so a node that inserted here would open a second gate every time
    somebody answered the first one. `ON CONFLICT DO NOTHING` against the
    one-pending-gate index makes even a double call harmless.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            INSERT INTO app.gates
                (run_id, project_id, kind, requirements_version, payload, interrupt_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            (run_id, project_id, kind, requirements_version, Jsonb(payload), interrupt_id),
        )
        gate = await cur.fetchone()
        if gate is None:
            # The conflict fallback selects by kind too: without it, a C2 run
            # racing a pending design gate would be handed the design gate row
            # and settle itself against somebody else's decision.
            await cur.execute(
                "SELECT * FROM app.gates WHERE project_id = %s AND state = 'pending' AND kind = %s",
                (project_id, kind),
            )
            gate = await cur.fetchone()
    if gate is None:
        # The insert conflicted and no pending gate of this kind exists, which
        # the index makes impossible: it is unique on (project, kind) where
        # pending, so anything that blocked the insert is a pending gate of
        # this kind and the select above finds it.
        #
        # A bare assert until a design change ran on a project whose code
        # review was still pending, back when the index was unique on project
        # alone. That cost six model calls and produced an AssertionError with
        # no message, at the last node of the run. The index is per kind now
        # and this is the line that says what happened if one ever slips
        # through again.
        raise GateBlocked(
            f"a {kind} gate could not be opened on this project and none is pending, "
            "so something holds the one pending decision this phase is allowed."
        )
    return gate


def pending_gate_query(project_id: str, kind: str) -> Query:
    """The pending gate of one kind on one project, the form the read models ask."""
    return Query(
        "SELECT * FROM app.gates WHERE project_id = %s AND state = 'pending' AND kind = %s",
        (project_id, kind),
        _first,
    )


async def pending_gate(
    conn: AsyncConnection,
    *,
    project_id: str | None = None,
    gate_id: uuid.UUID | None = None,
    kind: str | None = None,
) -> Row | None:
    """The pending gate, optionally of one kind.

    Kind matters the moment two phases exist: the design decision route asking
    for "the pending gate" while a code review is pending would resolve the
    wrong phase's gate. By id the kind is a check; by project it is a filter.
    """
    if gate_id is None and kind is not None:
        return await run(conn, pending_gate_query(str(project_id), kind))
    async with conn.cursor(row_factory=dict_row) as cur:
        if gate_id is not None:
            await cur.execute(
                "SELECT * FROM app.gates WHERE id = %s AND state = 'pending'", (gate_id,)
            )
            found = await cur.fetchone()
            if found is not None and kind is not None and found["kind"] != kind:
                return None
            return found
        await cur.execute(
            "SELECT * FROM app.gates WHERE project_id = %s AND state = 'pending'", (project_id,)
        )
        return await cur.fetchone()


def pending_gates_query(owner_id: str, project_id: str | None = None) -> Query:
    return Query(
        """
        SELECT g.* FROM app.gates g
        JOIN app.projects p ON p.id = g.project_id
        WHERE g.state = 'pending' AND p.owner_id = %s
          AND (%s::text IS NULL OR g.project_id = %s)
        ORDER BY g.created_at
        """,
        (owner_id, project_id, project_id),
        _rows,
    )


async def pending_gates(
    conn: AsyncConnection, *, owner_id: str, project_id: str | None = None
) -> list[Row]:
    """Every gate waiting on this account, or only one of its projects'.

    Unfiltered is the inbox view: what the platform is waiting on this person
    for. Before sign-in made two accounts it was every gate on the platform.
    """
    return await run(conn, pending_gates_query(owner_id, project_id))


async def resolve_gate(
    conn: AsyncConnection,
    gate_id: uuid.UUID,
    *,
    decision: GateDecision,
    by: str,
    note: str | None,
) -> Row | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            UPDATE app.gates
               SET state = 'resolved', decision = %s, decided_by = %s,
                   decided_at = now(), note = %s
             WHERE id = %s AND state = 'pending'
            RETURNING *
            """,
            (decision, by, note, gate_id),
        )
        return await cur.fetchone()


def gate_history_query(project_id: str, kind: str) -> Query:
    return Query(
        """
        SELECT * FROM app.gates
        WHERE project_id = %s AND state = 'resolved' AND kind = %s
        ORDER BY decided_at
        """,
        (project_id, kind),
        _rows,
    )


async def gate_history(conn: AsyncConnection, project_id: str, *, kind: str) -> list[Row]:
    """Resolved gates of one kind, oldest first.

    Kind is required, not defaulted: a project holds gates from more than one
    phase once C2 exists, and a design snapshot composed over a code review
    decision reported the wrong approval. The read model asks for the kind it
    is about.
    """
    return await run(conn, gate_history_query(project_id, kind))


# ------------------------------------------------------------------ artefacts


#: Which gate decides a version, per artefact kind.
#:
#: The axes are gated separately, and a gate row records the version on its own
#: component's axis: a design gate at requirements version 1, a code gate at
#: code version 8, a test review at test version 2. The test kinds joined late
#: (defect 28): until then the report a person approved could be replaced
#: underneath the approval by a stage retry.
_GATE_FOR_KIND: dict[str, str] = {
    **dict.fromkeys(ARTEFACT_KINDS, "c1-design-review"),
    **dict.fromkeys(CODE_ARTEFACT_KINDS, "c2-code-review"),
    **dict.fromkeys(TEST_ARTEFACT_KINDS, "c3-test-review"),
    # Not every deploy kind: the monitoring report and the feedback derived
    # from it are written after the approval by design.
    **dict.fromkeys(DEPLOY_GATED_ARTEFACT_KINDS, "c4-deploy-review"),
}


class VersionAlreadyApproved(RuntimeError):
    """Somebody approved this version, so its contents may not change."""


class GateBlocked(RuntimeError):
    """A gate could not be opened and none of its kind is pending.

    The index makes this unreachable, which is the point of naming it: it is
    what an index that has stopped matching the code looks like from inside a
    run. The last one cost six model calls and reported itself as an
    `AssertionError` with no message.
    """


def version_is_approved_query(project_id: str, gate_kind: str, version: int) -> Query:
    return Query(
        """
        SELECT 1 AS approved FROM app.gates
        WHERE project_id = %s AND kind = %s AND requirements_version = %s
          AND state = 'resolved' AND decision = 'approved'
        LIMIT 1
        """,
        (project_id, gate_kind, version),
        bool,
    )


async def version_is_approved(
    conn: AsyncConnection, project_id: str, *, gate_kind: str, version: int
) -> bool:
    """Whether a decision of `approved` was recorded against this version.

    Public because a route has to be able to ask before it starts a run: the
    refusal below happens after the node has called the model, which is the
    right place to be safe and the wrong place to be told.
    """
    return await run(conn, version_is_approved_query(project_id, gate_kind, version))


async def _version_is_approved(
    conn: AsyncConnection, project_id: str, kind: str, version: int
) -> bool:
    gate_kind = _GATE_FOR_KIND.get(kind)
    if gate_kind is None:
        return False
    return await version_is_approved(conn, project_id, gate_kind=gate_kind, version=version)


async def put_artefact(
    conn: AsyncConnection,
    *,
    project_id: str,
    kind: AnyArtefactKind,
    version: int,
    body: dict[str, Any],
    run_id: uuid.UUID | None = None,
) -> None:
    """Store an artefact version, idempotently.

    A node that re-executes writes the same row again rather than a duplicate,
    which is what makes retries safe. Every earlier version stays, because the
    evaluation compares them.

    What it may not do is change a version somebody approved. This upsert is
    how a resurrected run rewrote an approved design in place: the gate still
    said approved at version 1, and version 1 was no longer what had been
    approved. An approval that can be edited afterwards is not an approval, so
    this refuses and the stage says why.
    """
    if await _version_is_approved(conn, project_id, kind, version):
        raise VersionAlreadyApproved(
            f"version {version} of this project was approved, so its {kind} cannot be "
            "rewritten. Open a new version with a change instead, which is what a "
            "decision recorded against a version means."
        )
    await conn.execute(
        """
        INSERT INTO app.artefacts (project_id, kind, version, run_id, body)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (project_id, kind, version)
        DO UPDATE SET body = EXCLUDED.body, run_id = EXCLUDED.run_id, created_at = now()
        """,
        (project_id, kind, version, run_id, Jsonb(body)),
    )


async def record_late_push(
    conn: AsyncConnection, project_id: str, *, version: int, pointer: dict[str, Any]
) -> bool:
    """Record where a version was pushed after its build, once, approved or not.

    The one write to a code artefact after its review approved it, and a
    narrow one: the repository pointer, only where none was recorded, with the
    not pushed reason it replaces. The files and the build the review approved
    are not touched. A version approved before GitHub was connected otherwise
    had nowhere to say where its code went, and a release had no commit to
    build on. Returns whether it was recorded.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE app.artefacts
            SET body = jsonb_set(body - 'notPushedReason', '{repository}', %s)
            WHERE project_id = %s AND kind = 'code-repository' AND version = %s
              AND (body->'repository' IS NULL OR body->'repository' = 'null'::jsonb)
            """,
            (Jsonb(pointer), project_id, version),
        )
        return cur.rowcount == 1


async def pushed_repository(conn: AsyncConnection, project_id: str) -> Row | None:
    """The GitHub repository this project's code went to, if it is this project's.

    The newest pointer the project recorded, unless another project recorded the
    same repository first. Repositories were named after the project alone, so
    projects with one name shared one, each push replacing the last; the first
    project to push keeps it, and a later one must not go on writing over it.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            WITH mine AS (
                SELECT body->'pointer'->>'owner' AS owner, body->'pointer'->>'name' AS name
                FROM app.artefacts
                WHERE project_id = %(project)s AND kind = 'code-repository'
                  AND jsonb_typeof(body->'pointer') = 'object'
                ORDER BY version DESC
                LIMIT 1
            )
            SELECT mine.owner, mine.name, (
                SELECT a.project_id FROM app.artefacts a
                WHERE a.kind = 'code-repository'
                  AND a.body->'pointer'->>'owner' = mine.owner
                  AND a.body->'pointer'->>'name' = mine.name
                ORDER BY a.created_at, a.id
                LIMIT 1
            ) AS first_project
            FROM mine
            """,
            {"project": project_id},
        )
        row = await cur.fetchone()
    if row is None or row["first_project"] != project_id:
        return None
    return {"owner": row["owner"], "name": row["name"]}


def latest_artefacts_query(project_id: str) -> Query:
    return Query(
        """
        SELECT DISTINCT ON (kind) kind, version, body
        FROM app.artefacts
        WHERE project_id = %s
        ORDER BY kind, version DESC
        """,
        (project_id,),
        _by_kind,
    )


async def latest_artefacts(conn: AsyncConnection, project_id: str) -> dict[str, Row]:
    """The newest version of each kind, in one index scan."""
    return await run(conn, latest_artefacts_query(project_id))


def newest_artefact_query(project_id: str, kind: str) -> Query:
    return Query(
        """
        SELECT kind, version, body FROM app.artefacts
        WHERE project_id = %s AND kind = %s
        ORDER BY created_at DESC, version DESC LIMIT 1
        """,
        (project_id, kind),
        _first,
    )


async def newest_artefact(
    conn: AsyncConnection, project_id: str, kind: AnyArtefactKind
) -> Row | None:
    """The one of this kind written last, whichever version that is.

    Written last, not the highest version: after a rollback, a window on the
    restored release writes at that release's lower version, and it is still
    the newest word on what serves. A rewrite of a version refreshes its time.
    """
    return await run(conn, newest_artefact_query(project_id, kind))


async def artefact_history(
    conn: AsyncConnection, project_id: str, kind: AnyArtefactKind, *, before: int
) -> list[Row]:
    """Every stored version of one kind below a version, oldest first.

    What identity is decided against. The last row is the version to match
    against, and every row together is the set of ids this project has already
    used, which is what stops a retired id being handed to something else. Both
    come from one query because a caller that fetched the previous version and
    forgot the rest would reissue ids, which is the defect `carry_requirement_ids`
    exists to remove.

    `before` rather than `up to`, because this runs while the version it is
    deciding ids for is being generated, and on a retry that version's own
    artefact may already be stored from the attempt that failed later.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT version, body FROM app.artefacts
            WHERE project_id = %s AND kind = %s AND version < %s
            ORDER BY version
            """,
            (project_id, kind, before),
        )
        return await cur.fetchall()


def artefact_versions_query(project_id: str, kind: str) -> Query:
    return Query(
        "SELECT version FROM app.artefacts WHERE project_id = %s AND kind = %s ORDER BY version",
        (project_id, kind),
        lambda rows: [row["version"] for row in rows],
    )


async def artefact_versions(
    conn: AsyncConnection, project_id: str, kind: AnyArtefactKind
) -> list[int]:
    """Every stored version of one artefact kind. The evaluation compares these."""
    return await run(conn, artefact_versions_query(project_id, kind))


# ------------------------------------------------------------------- overlays


async def put_overlay(
    conn: AsyncConnection,
    *,
    project_id: str,
    version: int,
    kind: OverlayKind,
    target_id: str,
    value: Any,
    by: str,
) -> None:
    """Record a human edit without touching the artefact it edits.

    The artefact body stays as the machine produced it, which is what the SAG
    ablation measures, and the correction rate becomes a metric that costs
    nothing to collect.
    """
    await conn.execute(
        """
        INSERT INTO app.design_overlays (project_id, version, kind, target_id, value, by)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (project_id, version, kind, target_id)
        DO UPDATE SET value = EXCLUDED.value, by = EXCLUDED.by, at = now()
        """,
        (project_id, version, kind, target_id, Jsonb(value), by),
    )


def overlays_query(project_id: str) -> Query:
    return Query(
        "SELECT * FROM app.design_overlays WHERE project_id = %s ORDER BY version, at",
        (project_id,),
        _rows,
    )


async def overlays(conn: AsyncConnection, project_id: str) -> list[Row]:
    return await run(conn, overlays_query(project_id))


def asked_questions_query(project_id: str) -> Query:
    """The questions each requirements version asked, and when it was written.

    For the answers in the design conversation, which keep the question they
    answered. A question's id is its place in its version's list, so only the
    version it was asked in says which question an answer answered.
    """
    return Query(
        """
        SELECT version, body->'questions' AS questions, created_at
        FROM app.artefacts
        WHERE project_id = %s AND kind = 'requirements'
        ORDER BY version
        """,
        (project_id,),
        _rows,
    )


async def asked_questions(conn: AsyncConnection, project_id: str) -> list[Row]:
    return await run(conn, asked_questions_query(project_id))


# ------------------------------------------------------------------- stages


async def set_stage(
    conn: AsyncConnection,
    project_id: str,
    stage_id: AnyStageId,
    *,
    status: StageStatus,
    version: int | None = None,
    summary: str | None = None,
    error: str | None = None,
    model_use: dict[str, Any] | None = None,
) -> None:
    """Move one stage, and when it completes, stamp what its version was made with.

    `model_use` is written on every completion (0015), null when the stage
    asked no model, so a value from an earlier version that did never stays
    behind on one made without it.
    """
    sets = ["status = %s", "error = %s"]
    values: list[Any] = [status, error]
    if status == "complete":
        sets.append("generated_at = now()")
        if version is not None:
            sets.append("generated_from_version = %s")
            values.append(version)
        sets.append("model_use = %s")
        values.append(Jsonb(model_use) if model_use is not None else None)
    if summary is not None:
        sets.append("summary = %s")
        values.append(summary)
    await conn.execute(
        f"UPDATE app.stage_states SET {', '.join(sets)} WHERE project_id = %s AND stage_id = %s",
        (*values, project_id, stage_id),
    )


async def resolve_generating(
    conn: AsyncConnection, project_id: str, *, stage_ids: tuple[str, ...] | None = None
) -> list[str]:
    """Put any stage still claiming to be generating back to pending.

    Called when a run fails. A stage that never started has not failed, and it
    has not been generated either: pending is the only truthful answer. Leaving
    it at generating is worse than either, because the client polls while
    anything is generating and the strip spins forever over work that stopped.

    The stage that actually broke has already been marked failed by its own node,
    and `status = 'generating'` no longer matches it, so this cannot overwrite the
    reason.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE app.stage_states
            SET status = 'pending', error = NULL
            WHERE project_id = %s AND status = 'generating'
              AND (%s::text[] IS NULL OR stage_id = ANY(%s::text[]))
            RETURNING stage_id
            """,
            (
                project_id,
                list(stage_ids) if stage_ids is not None else None,
                list(stage_ids) if stage_ids is not None else None,
            ),
        )
        rows = await cur.fetchall()
    return [row[0] for row in rows]


async def set_stages(
    conn: AsyncConnection,
    project_id: str,
    stage_ids: list[AnyStageId],
    *,
    status: StageStatus,
) -> None:
    if not stage_ids:
        return
    await conn.execute(
        """
        UPDATE app.stage_states SET status = %s, error = NULL
        WHERE project_id = %s AND stage_id = ANY(%s)
        """,
        (status, project_id, list(stage_ids)),
    )


async def seed_code_stages(conn: AsyncConnection, project_id: str) -> None:
    """The eight code stage rows, once per project.

    Not at project creation, because most projects never reach the code phase
    and eight pending rows on every one of them would put Code Generation in
    the read model of a project whose design has not been approved. Called
    when the first code run is created, and idempotent, because a second run
    on the same project calls it again.
    """
    async with conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO app.stage_states (project_id, stage_id) VALUES (%s, %s)
            ON CONFLICT (project_id, stage_id) DO NOTHING
            """,
            [(project_id, stage) for stage in CODE_STAGE_IDS],
        )


def stage_states_query(project_id: str) -> Query:
    return Query("SELECT * FROM app.stage_states WHERE project_id = %s", (project_id,), _rows)


async def stage_states(conn: AsyncConnection, project_id: str) -> list[Row]:
    return await run(conn, stage_states_query(project_id))


# -------------------------------------------------------------------- thread


async def post_thread_message(
    conn: AsyncConnection,
    project_id: str,
    *,
    kind: ThreadKind,
    author: str,
    content: str,
    stage_id: DesignStageId | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO app.thread_messages (project_id, kind, stage_id, author, content)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (project_id, kind, stage_id, author, content),
    )


def thread_query(project_id: str) -> Query:
    return Query(
        """
        SELECT id, kind, stage_id, author, content, at
        FROM app.thread_messages WHERE project_id = %s ORDER BY seq
        """,
        (project_id,),
        _rows,
    )


async def thread(conn: AsyncConnection, project_id: str) -> list[Row]:
    return await run(conn, thread_query(project_id))


# --------------------------------------------------- connections and settings
# The two tables the spine created and nothing used until the credential store
# landed. `secrets` holds ciphertext only, keyed "{owner}:{provider}";
# everything a UI may see about a connection lives in `settings`, one row per
# owner, body jsonb. Values and metadata never share a table, so a query that
# lists connections cannot even accidentally select a ciphertext.


async def put_secret(conn: AsyncConnection, key: str, ciphertext: bytes) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO app.secrets (key, ciphertext, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (key) DO UPDATE SET ciphertext = EXCLUDED.ciphertext, updated_at = now()
            """,
            (key, ciphertext),
        )


async def get_secret(conn: AsyncConnection, key: str) -> bytes | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT ciphertext FROM app.secrets WHERE key = %s", (key,))
        row = await cur.fetchone()
        return bytes(row["ciphertext"]) if row else None


async def delete_secret(conn: AsyncConnection, key: str) -> None:
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM app.secrets WHERE key = %s", (key,))


def settings_body_query(owner_id: str) -> Query:
    return Query(
        "SELECT body FROM app.settings WHERE id = %s",
        (owner_id,),
        lambda rows: dict(rows[0]["body"]) if rows else {},
    )


async def settings_body(conn: AsyncConnection, owner_id: str) -> dict[str, Any]:
    return await run(conn, settings_body_query(owner_id))


#: The levels an account can choose for a phase (`ThinkingLevel` in the contracts).
THINKING_LEVELS = ("off", "low", "high", "max")


async def thinking_choices(conn: AsyncConnection, owner_id: str) -> dict[str, str]:
    """The levels this account chose, by phase, leaving out every phase it did not (3B).

    Keyed by each phase's settings key, which is its audit category: design,
    code, testing or deployment. A value that is not a level reads as no choice
    rather than failing the run that asked.
    """
    body = await settings_body(conn, owner_id)
    section = body.get("settings")
    ai = section.get("ai") if isinstance(section, dict) else None
    thinking = ai.get("thinking") if isinstance(ai, dict) else None
    if not isinstance(thinking, dict):
        return {}
    return {phase: level for phase, level in thinking.items() if level in THINKING_LEVELS}


async def chosen_thinking(conn: AsyncConnection, owner_id: str, phase: str) -> str | None:
    """The level this account chose for one phase, or None where it chose nothing."""
    return (await thinking_choices(conn, owner_id)).get(phase)


async def put_settings_section(
    conn: AsyncConnection, owner_id: str, path: tuple[str, str], value: Any
) -> None:
    """Write one subtree of the settings row, leaving every other path alone.

    Read the row, change it in Python, write the whole row back and you lose
    every update that landed in between. Two writers overlap constantly here:
    the settings field patched on every keystroke, and the connections route,
    which holds its read across a network probe of the provider.

    That is how a stored GitHub connection disappeared with nothing in the
    audit log to explain it. The probe finished mid typing, the connection was
    written, and the next keystroke wrote back a body it had read before the
    connection existed. The token stayed encrypted in `app.secrets`, orphaned,
    while the page read "Not connected" and the trail showed only a successful
    connect. Reported as credentials being reset by restarting the server,
    which had nothing to do with it.

    One statement, one path. `jsonb_set` will not create a missing parent, so
    the parent is seeded from itself or an empty object in the same expression.
    """
    parent, leaf = path
    await conn.execute(
        """
        INSERT INTO app.settings (id, body)
        VALUES (%s, jsonb_build_object(%s::text, jsonb_build_object(%s::text, %s::jsonb)))
        ON CONFLICT (id) DO UPDATE SET body = jsonb_set(
            jsonb_set(
                coalesce(app.settings.body, '{}'::jsonb),
                ARRAY[%s::text],
                coalesce(app.settings.body -> %s::text, '{}'::jsonb),
                true
            ),
            ARRAY[%s::text, %s::text],
            %s::jsonb,
            true
        )
        """,
        (owner_id, parent, leaf, Jsonb(value), parent, parent, parent, leaf, Jsonb(value)),
    )


async def merge_settings_section(
    conn: AsyncConnection, owner_id: str, path: tuple[str, str], fields: dict[str, Any]
) -> None:
    """Merge `fields` into one subtree, leaving its other keys as they are at that moment.

    Writing the merged subtree back from Python loses a field the same way
    writing the whole row back lost a connection: each field of a section saves
    itself when the typing stops, three pasted in quick succession arrive
    together, each read the section before the others wrote, and the last write
    put back the two fields it had read empty. The merge is done by the
    database, in the one statement that writes, so each save adds its keys to
    whatever the section holds when it lands.
    """
    parent, leaf = path
    await conn.execute(
        """
        INSERT INTO app.settings (id, body)
        VALUES (%s, jsonb_build_object(%s::text, jsonb_build_object(%s::text, %s::jsonb)))
        ON CONFLICT (id) DO UPDATE SET body = jsonb_set(
            jsonb_set(
                coalesce(app.settings.body, '{}'::jsonb),
                ARRAY[%s::text],
                coalesce(app.settings.body -> %s::text, '{}'::jsonb),
                true
            ),
            ARRAY[%s::text, %s::text],
            coalesce(app.settings.body -> %s::text -> %s::text, '{}'::jsonb) || %s::jsonb,
            true
        )
        """,
        (
            owner_id,
            parent,
            leaf,
            Jsonb(fields),
            parent,
            parent,
            parent,
            leaf,
            parent,
            leaf,
            Jsonb(fields),
        ),
    )


async def delete_settings_section(
    conn: AsyncConnection, owner_id: str, path: tuple[str, str]
) -> None:
    """Remove one subtree, for the same reason and with the same guarantee."""
    parent, leaf = path
    await conn.execute(
        "UPDATE app.settings SET body = body #- ARRAY[%s::text, %s::text] WHERE id = %s",
        (parent, leaf, owner_id),
    )


async def put_settings_body(conn: AsyncConnection, owner_id: str, body: dict[str, Any]) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO app.settings (id, body) VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE SET body = EXCLUDED.body
            """,
            (owner_id, Jsonb(body)),
        )


# ------------------------------------------------------------- the code axis


async def next_code_version(conn: AsyncConnection, project_id: str) -> int:
    """The next version on the code axis.

    Its own counter, because the design axis is `design_versions` and a code
    regeneration must not consume a design version number (or read as though
    the requirements had changed when only the scope did).

    Runs count as well as artefacts: a version is claimed when the run that
    will produce it is created, so a second regeneration started before the
    first wrote anything cannot be handed the same number.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT coalesce(max(taken), 0) + 1 FROM (
                SELECT max(version) AS taken FROM app.artefacts
                WHERE project_id = %s AND kind = ANY(%s)
                UNION ALL
                SELECT max(requirements_version) FROM app.runs
                WHERE project_id = %s AND component = 'c2'
            ) claimed
            """,
            (project_id, list(CODE_ARTEFACT_KINDS), project_id),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 1


def current_code_version_query(project_id: str) -> Query:
    return Query(
        "SELECT coalesce(max(version), 0) AS version FROM app.artefacts "
        "WHERE project_id = %s AND kind = ANY(%s)",
        (project_id, list(CODE_ARTEFACT_KINDS)),
        _version_of,
    )


async def current_code_version(conn: AsyncConnection, project_id: str) -> int:
    """The newest code version anything was written at. Zero before the first
    run, which is how the read model says "nothing generated yet"."""
    return await run(conn, current_code_version_query(project_id))


def _by_kind(rows: list[Row]) -> dict[str, Row]:
    return {row["kind"]: row for row in rows}


def artefacts_at_query(project_id: str, version: int, kinds: tuple[str, ...]) -> Query:
    return Query(
        """
        SELECT kind, version, body FROM app.artefacts
        WHERE project_id = %s AND version = %s AND kind = ANY(%s)
        """,
        (project_id, version, list(kinds)),
        _by_kind,
    )


async def artefacts_at(
    conn: AsyncConnection, project_id: str, *, version: int, kinds: tuple[str, ...]
) -> dict[str, Row]:
    """The named kinds at exactly this version, never the latest.

    A code run pins the design version it read, so a design regenerated while
    the code run was in flight cannot change what the code was generated from.
    Reading `latest_artefacts` here was the bug this exists to prevent.
    """
    return await run(conn, artefacts_at_query(project_id, version, kinds))


TEST_FILE_STAGE = "test-generation"


async def carry_tests_forward(conn: AsyncConnection, project_id: str, *, to_version: int) -> int:
    """Bring the project's tests into a newly allocated code version.

    Files are keyed by version and stage, and the code generator writes only
    its own stages, so a regeneration left the new version with no tests at
    all. That is wrong twice over. A reader who approved a suite at one version
    would find it gone at the next, and the healing loop could never see a
    stale test, because every run would start from a version that had none and
    generate fresh ones.

    Copied rather than referenced: a version is the whole state of the
    repository at a moment, and a version that has to borrow files from another
    one to be complete is not a version.

    Returns how many came forward, so the caller can say so.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT path, content FROM app.code_files
            WHERE project_id = %s AND stage_id = %s
              AND version = (
                SELECT MAX(version) FROM app.code_files
                WHERE project_id = %s AND stage_id = %s AND version < %s
              )
            """,
            (project_id, TEST_FILE_STAGE, project_id, TEST_FILE_STAGE, to_version),
        )
        rows = await cur.fetchall()
    if not rows:
        return 0
    await put_code_files(
        conn,
        project_id,
        version=to_version,
        stage_id=TEST_FILE_STAGE,
        files={row["path"]: row["content"] for row in rows},
    )
    return len(rows)


async def put_code_files(
    conn: AsyncConnection,
    project_id: str,
    *,
    version: int,
    stage_id: str,
    files: dict[str, str],
) -> None:
    """Replace this stage's files at this version.

    Delete then insert rather than upsert, so a regeneration that produces
    fewer files leaves none of the old ones behind. The manifest on the
    artefact and the rows here have to name the same set, or the file route
    serves something no manifest lists and the viewer shows a file the reader
    cannot account for.

    An approved version's code is settled, as `put_artefact` settles its
    artefacts: a retry rewrote it here before the artefact write refused. The
    tests are the exception, because the testing phase writes the suite it
    generates against the approved version into that version.
    """
    if stage_id != TEST_FILE_STAGE and await version_is_approved(
        conn, project_id, gate_kind="c2-code-review", version=version
    ):
        raise VersionAlreadyApproved(
            f"code version {version} of this project was approved, so its {stage_id} files "
            "cannot be rewritten. Generate again to open a new version instead."
        )
    await conn.execute(
        "DELETE FROM app.code_files WHERE project_id = %s AND version = %s AND stage_id = %s",
        (project_id, version, stage_id),
    )
    if not files:
        return
    async with conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO app.code_files (project_id, version, path, content, stage_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (project_id, version, path)
            DO UPDATE SET content = EXCLUDED.content, stage_id = EXCLUDED.stage_id,
                          updated_at = now()
            """,
            [(project_id, version, path, content, stage_id) for path, content in files.items()],
        )


async def code_files(
    conn: AsyncConnection, project_id: str, *, version: int, stage_id: str | None = None
) -> dict[str, str]:
    """Every generated file at one version, path to content.

    The whole set, because the agreement checker parses across files and the
    build writes the whole tree. Serving one file to a reader goes through
    `code_file` instead. `stage_id` narrows it to what one stage wrote, such as
    the tests testing wrote beside the code.
    """
    async with conn.cursor() as cur:
        if stage_id is None:
            await cur.execute(
                "SELECT path, content FROM app.code_files WHERE project_id = %s AND version = %s",
                (project_id, version),
            )
        else:
            await cur.execute(
                "SELECT path, content FROM app.code_files "
                "WHERE project_id = %s AND version = %s AND stage_id = %s",
                (project_id, version, stage_id),
            )
        return {path: content for path, content in await cur.fetchall()}


async def code_file(
    conn: AsyncConnection, project_id: str, *, version: int, path: str
) -> str | None:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT content FROM app.code_files "
            "WHERE project_id = %s AND version = %s AND path = %s",
            (project_id, version, path),
        )
        row = await cur.fetchone()
    return row[0] if row else None


# --------------------------------------------------------------------- previews


PreviewStatus = Literal["starting", "running", "failed", "stopped"]


async def put_preview(
    conn: AsyncConnection,
    project_id: str,
    *,
    code_version: int,
    port: int,
    pid: int,
    workdir: str,
    status: PreviewStatus,
    error: str | None = None,
) -> Row:
    """Record a preview, replacing whatever this project had before.

    One per project by primary key, so starting a second is an upsert rather
    than a second process nobody is tracking.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            INSERT INTO app.previews
                (project_id, code_version, port, pid, workdir, status, error,
                 started_at, last_seen_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now())
            ON CONFLICT (project_id) DO UPDATE SET
                code_version = EXCLUDED.code_version,
                port = EXCLUDED.port,
                pid = EXCLUDED.pid,
                workdir = EXCLUDED.workdir,
                status = EXCLUDED.status,
                error = EXCLUDED.error,
                started_at = now(),
                last_seen_at = now()
            RETURNING *
            """,
            (project_id, code_version, port, pid, workdir, status, error),
        )
        row = await cur.fetchone()
    assert row is not None
    return row


async def set_preview_status(
    conn: AsyncConnection, project_id: str, *, status: PreviewStatus, error: str | None = None
) -> None:
    await conn.execute(
        "UPDATE app.previews SET status = %s, error = %s, last_seen_at = now() "
        "WHERE project_id = %s",
        (status, error, project_id),
    )


async def touch_preview(conn: AsyncConnection, project_id: str) -> None:
    """Say somebody is still looking, so the idle sweep leaves it alone."""
    await conn.execute(
        "UPDATE app.previews SET last_seen_at = now() WHERE project_id = %s", (project_id,)
    )


async def get_preview(conn: AsyncConnection, project_id: str) -> Row | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM app.previews WHERE project_id = %s", (project_id,))
        return await cur.fetchone()


async def live_previews(conn: AsyncConnection) -> list[Row]:
    """Every preview holding a process, oldest first.

    The cap counts these, and the reaper on startup kills them: a row that says
    running after a restart describes a process this orchestrator did not start
    and cannot supervise.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM app.previews WHERE status IN ('starting','running') ORDER BY started_at"
        )
        return await cur.fetchall()


async def idle_previews(conn: AsyncConnection, *, seconds: int) -> list[Row]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT * FROM app.previews
            WHERE status IN ('starting','running')
              AND last_seen_at < now() - make_interval(secs => %s)
            """,
            (seconds,),
        )
        return await cur.fetchall()


async def delete_preview(conn: AsyncConnection, project_id: str) -> None:
    await conn.execute("DELETE FROM app.previews WHERE project_id = %s", (project_id,))


async def patch_provenance(conn: AsyncConnection, project_id: str) -> dict[int, int]:
    """Code versions that exist because a fix was applied, and what they patched.

    A remediation reaches the code as an ordinary new version, written by the
    orchestrator from a patch a person accepted rather than generated by C2.
    Such a version has no run of its own and no gate of its own, so the two
    questions asked about every code version, what design it came from and
    whether a person approved it, are answered by the version it was patched
    over. This is the map that makes that one hop possible, read from the
    decision overlay the apply wrote.
    """
    return patches_in(await overlays(conn, project_id))


def patches_in(overlay_rows: Iterable[Row]) -> dict[int, int]:
    """`patch_provenance`, from overlay rows a caller already read."""
    found: dict[int, int] = {}
    for row in overlay_rows:
        if row["kind"] != "remediation_decision":
            continue
        value = row["value"] or {}
        applied = value.get("appliedCodeVersion")
        if applied:
            found[int(applied)] = int(value.get("patchedCodeVersion") or 0)
    return found


async def applied_fixes(conn: AsyncConnection, project_id: str) -> list[Row]:
    """Every accepted fix that was applied, oldest first.

    Each row names the proposal, the test version it was proposed at (where
    the proposal is stored), the code version it patched and the one it made.
    Read from the decision overlay the apply wrote, as `patch_provenance` is. A
    regeneration carries each of them into the code it writes (`carrying`).
    """
    found: list[Row] = []
    for row in await overlays(conn, project_id):
        if row["kind"] != "remediation_decision":
            continue
        value = row["value"] or {}
        applied = int(value.get("appliedCodeVersion") or 0)
        patched = int(value.get("patchedCodeVersion") or 0)
        if applied and patched:
            found.append(
                {
                    "proposal_id": row["target_id"],
                    "test_version": int(row["version"]),
                    "patched": patched,
                    "applied": applied,
                }
            )
    return sorted(found, key=lambda fix: fix["applied"])


async def design_version_for_code(
    conn: AsyncConnection, project_id: str, code_version: int
) -> int | None:
    """The design version a code version was generated from.

    Ordinarily the C2 run that produced it pinned one. A version produced by
    applying an accepted security fix inherits the provenance of the version it
    patched: the patch changed file content, not what the code was generated
    from, and a testing run that could not answer this question would have no
    acceptance criteria to derive tests from.
    """
    seen: set[int] = set()
    patched: dict[int, int] | None = None
    version = code_version
    while version and version not in seen:
        seen.add(version)
        run = await run_for_version(conn, project_id, component="c2", version=version)
        source = (run or {}).get("source_version")
        if source:
            return int(source)
        if patched is None:
            patched = await patch_provenance(conn, project_id)
        version = patched.get(version, 0)
    return None


async def scope_for_code(
    conn: AsyncConnection, project_id: str, code_version: int
) -> dict[str, Any] | None:
    """The sprint scope a code version was generated for, as its body, or None.

    The stories the code phase put in the build, which a person can change: a
    backlog story moved in, a proposed one moved out. A version produced by
    applying an accepted fix has no scope of its own and builds what the version
    it patched built, the same hop `design_version_for_code` makes.
    """
    seen: set[int] = set()
    patched: dict[int, int] | None = None
    version = code_version
    while version and version not in seen:
        seen.add(version)
        found = await artefacts_at(conn, project_id, version=version, kinds=("sprint-scope",))
        if "sprint-scope" in found:
            return found["sprint-scope"]["body"]
        if patched is None:
            patched = await patch_provenance(conn, project_id)
        version = patched.get(version, 0)
    return None


async def repository_field_through_patches(
    conn: AsyncConnection, project_id: str, code_version: int, field: str
) -> tuple[Any, int]:
    """A field of a code version's repository record, or of the version a fix patched.

    A version written by applying an accepted fix starts with no repository
    pointer and no build of its own: both were facts about the files it
    patched. Until it is pushed, its code's repository and the commit its
    lineage is on are the patched version's, the same hop `scope_for_code`
    makes. Returns the value and the version it was found at, or (None, 0).
    """
    seen: set[int] = set()
    patched: dict[int, int] | None = None
    version = code_version
    while version and version not in seen:
        seen.add(version)
        found = await artefacts_at(conn, project_id, version=version, kinds=("code-repository",))
        value = (found.get("code-repository") or {}).get("body", {}).get(field)
        if value:
            return value, version
        if patched is None:
            patched = await patch_provenance(conn, project_id)
        version = patched.get(version, 0)
    return None, 0


async def code_version_is_approved(conn: AsyncConnection, project_id: str, version: int) -> bool:
    """Whether a person approved this code version, at its own review or through its fix.

    A version an accepted security fix wrote has no review of its own
    (`approved_through_patches`). The code phase asked only the version's own
    gate, so Generate again replaced such a version without asking, a retry
    could rewrite it, and a push never landed it.
    """
    if not version:
        return False
    history = await gate_history(conn, project_id, kind="c2-code-review")
    approved = {
        int(row["requirements_version"]) for row in history if row["decision"] == "approved"
    }
    return approved_through_patches(version, approved, await patch_provenance(conn, project_id))


def run_for_version_query(project_id: str, component: str, version: int) -> Query:
    return Query(
        """
        SELECT * FROM app.runs
        WHERE project_id = %s AND component = %s AND requirements_version = %s
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (project_id, component, version),
        _first,
    )


async def run_for_version(
    conn: AsyncConnection, project_id: str, *, component: str, version: int
) -> Row | None:
    """The run that produced one version on one component's axis.

    How a testing run finds the design version its code was generated from: the
    testing run pins a code version, and the code run that produced it pinned a
    design version. Two hops rather than reading the latest design, because the
    design moving on must not rewrite the acceptance criteria the tests came
    from.
    """
    return await run(conn, run_for_version_query(project_id, component, version))


async def previous_tested_code_version(
    conn: AsyncConnection, project_id: str, *, before: int
) -> int | None:
    """The most recent code version this project already has a test report for.

    The self healing classifier's whole signal is the difference between the
    version the tests were written against and the version they now run
    against, so without one of these there is nothing that can honestly be
    called brittle. Returns None rather than guessing, and the node says so.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT max(r.source_version) FROM app.runs r
            WHERE r.project_id = %s AND r.component = 'c3'
              AND r.source_version IS NOT NULL AND r.source_version < %s
              AND EXISTS (
                  SELECT 1 FROM app.artefacts a
                  WHERE a.project_id = r.project_id
                    AND a.kind = 'test-report'
                    AND a.version = r.requirements_version
              )
            """,
            (project_id, before),
        )
        row = await cur.fetchone()
    return row[0] if row and row[0] is not None else None


async def next_test_version(conn: AsyncConnection, project_id: str) -> int:
    """The next version on the testing axis.

    Its own counter for the same reason the code axis has one: a testing run
    must not consume a code version number, or the phase would read as though
    the code had been regenerated when only the tests were run again.

    Runs count as well as artefacts, so a second run started before the first
    wrote anything cannot be handed the same number.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT coalesce(max(taken), 0) + 1 FROM (
                SELECT max(version) AS taken FROM app.artefacts
                WHERE project_id = %s AND kind = ANY(%s)
                UNION ALL
                SELECT max(requirements_version) FROM app.runs
                WHERE project_id = %s AND component = 'c3'
            ) claimed
            """,
            (project_id, list(TEST_ARTEFACT_KINDS), project_id),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 1


def current_test_version_query(project_id: str) -> Query:
    return Query(
        "SELECT coalesce(max(version), 0) AS version FROM app.artefacts "
        "WHERE project_id = %s AND kind = ANY(%s)",
        (project_id, list(TEST_ARTEFACT_KINDS)),
        _version_of,
    )


async def current_test_version(conn: AsyncConnection, project_id: str) -> int:
    """The newest testing version anything was written at, or zero."""
    return await run(conn, current_test_version_query(project_id))


async def seed_test_stages(conn: AsyncConnection, project_id: str) -> None:
    """The seven testing stage rows, once per project.

    Not at project creation, for the reason the code stages are not: most
    projects never reach this phase, and seven pending rows on every one of
    them would put Testing in the read model of a project whose code has not
    been generated. Idempotent, because a second run calls it again.
    """
    async with conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO app.stage_states (project_id, stage_id) VALUES (%s, %s)
            ON CONFLICT (project_id, stage_id) DO NOTHING
            """,
            [(project_id, stage) for stage in TEST_STAGE_IDS],
        )


# ------------------------------------------------------------- the deploy axis


async def next_deploy_version(conn: AsyncConnection, project_id: str) -> int:
    """The next version on the deploy axis.

    Its own counter, like the code and testing axes: analysing updates and
    releasing must not consume a test version number. Runs count as well as
    artefacts, so a second run started before the first wrote anything cannot
    be handed the same number.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT coalesce(max(taken), 0) + 1 FROM (
                SELECT max(version) AS taken FROM app.artefacts
                WHERE project_id = %s AND kind = ANY(%s)
                UNION ALL
                SELECT max(requirements_version) FROM app.runs
                WHERE project_id = %s AND component = 'c4'
            ) claimed
            """,
            (project_id, list(DEPLOY_ARTEFACT_KINDS), project_id),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 1


def current_deploy_version_query(project_id: str) -> Query:
    return Query(
        "SELECT coalesce(max(version), 0) AS version FROM app.artefacts "
        "WHERE project_id = %s AND kind = ANY(%s)",
        (project_id, list(DEPLOY_ARTEFACT_KINDS)),
        _version_of,
    )


async def current_deploy_version(conn: AsyncConnection, project_id: str) -> int:
    """The newest deploy version anything was written at, or zero."""
    return await run(conn, current_deploy_version_query(project_id))


async def seed_deploy_stages(conn: AsyncConnection, project_id: str) -> None:
    """The ten deploy stage rows, once per project, when the phase is first reached."""
    async with conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO app.stage_states (project_id, stage_id) VALUES (%s, %s)
            ON CONFLICT (project_id, stage_id) DO NOTHING
            """,
            [(project_id, stage) for stage in DEPLOY_STAGE_IDS],
        )


async def put_deploy_files(
    conn: AsyncConnection,
    project_id: str,
    *,
    version: int,
    stage_id: str,
    files: dict[str, str],
) -> None:
    """Replace this stage's deployment files at this deploy version.

    Kept apart from `code_files`: C2 replaces the whole repository tree on every
    push, so C4's files are committed on top of C2's commit at release time
    rather than stored among C2's, where regenerating the code would delete
    them. Delete then insert, for the reason `put_code_files` gives.
    """
    await conn.execute(
        "DELETE FROM app.deploy_files WHERE project_id = %s AND version = %s AND stage_id = %s",
        (project_id, version, stage_id),
    )
    if not files:
        return
    async with conn.cursor() as cur:
        await cur.executemany(
            """
            INSERT INTO app.deploy_files (project_id, version, path, content, sha256, stage_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id, version, stage_id, path)
            DO UPDATE SET content = EXCLUDED.content, sha256 = EXCLUDED.sha256,
                          updated_at = now()
            """,
            [
                (
                    project_id,
                    version,
                    path,
                    content,
                    hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    stage_id,
                )
                for path, content in files.items()
            ],
        )


async def deploy_files(
    conn: AsyncConnection, project_id: str, *, version: int, stage_id: str
) -> dict[str, str]:
    """One stage's deployment files at one deploy version, path to content.

    The stage is required: two stages can hold the same path at one version (the
    baseline lockfile detection pinned, and the candidate's), so a read that did
    not name its stage could get either.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT path, content FROM app.deploy_files
            WHERE project_id = %s AND version = %s AND stage_id = %s
            """,
            (project_id, version, stage_id),
        )
        return {path: content for path, content in await cur.fetchall()}


def list_deployments_query(project_id: str, limit: int = 10) -> Query:
    return Query(
        """
        SELECT * FROM app.deployments WHERE project_id = %s
        ORDER BY created_at DESC LIMIT %s
        """,
        (project_id, limit),
        _rows,
    )


def count_deployments_query(project_id: str) -> Query:
    return Query(
        "SELECT count(*) AS total FROM app.deployments WHERE project_id = %s",
        (project_id,),
        _first,
    )


async def count_deployments(conn: AsyncConnection, project_id: str) -> int:
    """How many attempts the ledger holds, of which a snapshot shows the newest ten."""
    row = await run(conn, count_deployments_query(project_id))
    return int(row["total"]) if row else 0


async def list_deployments(conn: AsyncConnection, project_id: str, *, limit: int = 10) -> list[Row]:
    """The deployment ledger, newest first: every attempt, whatever came of it."""
    return await run(conn, list_deployments_query(project_id, limit))


async def steps_of(conn: AsyncConnection, deployment_ids: list[uuid.UUID]) -> dict[str, list[Row]]:
    """The saga steps of several deployments in one read, by deployment id, each in order.

    The ledger read each deployment's steps on its own: ten deployments were ten
    more round trips on every read of the deployment page.
    """
    if not deployment_ids:
        return {}
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM app.deploy_steps WHERE deployment_id = ANY(%s) ORDER BY deployment_id, seq",
            (deployment_ids,),
        )
        found: dict[str, list[Row]] = {}
        for row in await cur.fetchall():
            found.setdefault(str(row["deployment_id"]), []).append(row)
        return found


async def deployment_steps(conn: AsyncConnection, deployment_id: uuid.UUID) -> list[Row]:
    """One deployment's saga steps, in the order they run."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM app.deploy_steps WHERE deployment_id = %s ORDER BY seq",
            (deployment_id,),
        )
        return await cur.fetchall()


class DeploymentInFlight(RuntimeError):
    """A project already has a deployment pending or running; one at a time."""


async def create_deployment(
    conn: AsyncConnection,
    *,
    project_id: str,
    deploy_version: int,
    kind: str,
    target: str,
    plan_id: str,
    candidate_hash: str,
    idempotency_key: str,
    authorised: dict[str, Any],
    requested_by: str,
    gate_id: uuid.UUID | None = None,
    restores: uuid.UUID | None = None,
) -> tuple[Row, bool]:
    """One deployment per idempotency key: asking again finds the first.

    Returns the row and whether this call created it. A second deployment for a
    project that already has one pending or running is refused by the partial
    unique index, which is the one place that rule can hold under concurrency.
    The insert runs in a savepoint, so that refusal leaves the caller's
    transaction usable.
    """
    try:
        async with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO app.deployments (
                    project_id, deploy_version, kind, target, plan_id, candidate_hash,
                    idempotency_key, state, authorised, requested_by, gate_id, restores
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING *
                """,
                (
                    project_id,
                    deploy_version,
                    kind,
                    target,
                    plan_id,
                    candidate_hash,
                    idempotency_key,
                    Jsonb(authorised),
                    requested_by,
                    gate_id,
                    restores,
                ),
            )
            created = await cur.fetchone()
    except psycopg.errors.UniqueViolation as clash:
        raise DeploymentInFlight(
            "a deployment is already pending or running on this project"
        ) from clash
    if created is not None:
        return created, True
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM app.deployments WHERE idempotency_key = %s", (idempotency_key,)
        )
        return await cur.fetchone(), False


async def get_deployment(conn: AsyncConnection, deployment_id: uuid.UUID) -> Row | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM app.deployments WHERE id = %s", (deployment_id,))
        return await cur.fetchone()


#: A running deployment whose heartbeat stopped this long ago is taken over.
DEPLOYMENT_STALE_SECONDS = 120


async def claimable_deployments(
    conn: AsyncConnection, *, stale_seconds: int = DEPLOYMENT_STALE_SECONDS
) -> list[Row]:
    """Deployments to pick up: pending, or running with a heartbeat that stopped."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT * FROM app.deployments
            WHERE state = 'pending'
               OR (state = 'running'
                   AND (heartbeat_at IS NULL
                        OR heartbeat_at < now() - make_interval(secs => %s)))
            ORDER BY created_at
            """,
            (stale_seconds,),
        )
        return await cur.fetchall()


async def claim_deployment(
    conn: AsyncConnection,
    deployment_id: uuid.UUID,
    *,
    stale_seconds: int = DEPLOYMENT_STALE_SECONDS,
) -> Row | None:
    """Take a deployment to run it, or None when it is not there to take."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            UPDATE app.deployments SET state = 'running', heartbeat_at = now()
            WHERE id = %s
              AND (state = 'pending'
                   OR (state = 'running'
                       AND (heartbeat_at IS NULL
                            OR heartbeat_at < now() - make_interval(secs => %s))))
            RETURNING *
            """,
            (deployment_id, stale_seconds),
        )
        return await cur.fetchone()


async def heartbeat_deployment(conn: AsyncConnection, deployment_id: uuid.UUID) -> None:
    await conn.execute(
        "UPDATE app.deployments SET heartbeat_at = now() WHERE id = %s", (deployment_id,)
    )


def waiting_rollbacks_query(owner_id: str) -> Query:
    return Query(
        """
        SELECT d.* FROM app.deployments d
        JOIN app.projects p ON p.id = d.project_id
        WHERE p.owner_id = %s AND d.state = 'awaiting-rollback-approval'
        ORDER BY d.created_at
        """,
        (owner_id,),
        _rows,
    )


async def waiting_rollbacks(conn: AsyncConnection, *, owner_id: str) -> list[Row]:
    """This account's releases that stopped serving and wait on a rollback decision."""
    return await run(conn, waiting_rollbacks_query(owner_id))


async def finish_deployment(
    conn: AsyncConnection,
    deployment_id: uuid.UUID,
    *,
    state: str,
    cause: str | None = None,
    verified: bool = False,
    fingerprint: dict[str, Any] | None = None,
    url: str | None = None,
    fault_injected: str | None = None,
) -> None:
    """Where a deployment ended, and why, in the provider's words where it gave any (FR16)."""
    await conn.execute(
        """
        UPDATE app.deployments
        SET state = %s, cause = %s, verified = %s,
            verified_at = CASE WHEN %s THEN now() ELSE verified_at END,
            fingerprint = COALESCE(%s, fingerprint), url = COALESCE(%s, url),
            fault_injected = COALESCE(%s, fault_injected), finished_at = now()
        WHERE id = %s
        """,
        (
            state,
            cause,
            verified,
            verified,
            Jsonb(fingerprint) if fingerprint is not None else None,
            url,
            fault_injected,
            deployment_id,
        ),
    )


async def mark_rolled_back(conn: AsyncConnection, deployment_id: uuid.UUID) -> None:
    """The release a verified rollback returned from: kept, and marked so."""
    await conn.execute(
        "UPDATE app.deployments SET state = 'rolled-back' WHERE id = %s", (deployment_id,)
    )


async def add_health_sample(
    conn: AsyncConnection,
    *,
    deployment_id: uuid.UUID,
    project_id: str,
    probe: str,
    status_code: int | None,
    latency_ms: float | None,
    ok: bool,
    observed_fingerprint: str | None = None,
    error: str | None = None,
) -> None:
    """One probe of a live release, kept so a monitoring report can be traced to it."""
    await conn.execute(
        """
        INSERT INTO app.health_samples (
            deployment_id, project_id, probe, status_code, latency_ms, ok,
            observed_fingerprint, error
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            deployment_id,
            project_id,
            probe,
            status_code,
            latency_ms,
            ok,
            observed_fingerprint,
            error,
        ),
    )


async def newer_deployment(conn: AsyncConnection, row: Row) -> Row | None:
    """The newest deployment on the same project and target begun after this one that
    may have changed what is served, or None.

    Anything but `failed` counts: a deployment fails only before its traffic moved,
    so a failed one never replaced anything. A running one may be switching now.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT * FROM app.deployments
            WHERE project_id = %s AND target = %s AND created_at > %s AND state <> 'failed'
            ORDER BY created_at DESC LIMIT 1
            """,
            (row["project_id"], row["target"], row["created_at"]),
        )
        return await cur.fetchone()


async def serving_release(conn: AsyncConnection, project_id: str, target: str) -> Row | None:
    """What serves the project on this target now, when that is a verified success.

    The newest deployment that may have changed what is served. None when it is
    still running, waits on a rollback decision, or nothing was ever released:
    then there is no verified release to watch.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT * FROM app.deployments
            WHERE project_id = %s AND target = %s AND state <> 'failed'
            ORDER BY created_at DESC LIMIT 1
            """,
            (project_id, target),
        )
        row = await cur.fetchone()
    if row is None or row["state"] != "succeeded" or not row["verified"] or not row["url"]:
        return None
    return row


def unwatched_releases_query(recent_seconds: int) -> Query:
    return Query(
        """
        SELECT d.* FROM app.deployments d
        WHERE d.state = 'succeeded' AND d.verified AND d.url IS NOT NULL
          AND d.finished_at > now() - make_interval(secs => %s)
          AND NOT EXISTS (
              SELECT 1 FROM app.deployments n
              WHERE n.project_id = d.project_id AND n.target = d.target
                AND n.created_at > d.created_at AND n.state <> 'failed'
          )
          AND NOT EXISTS (
              SELECT 1 FROM app.health_samples h
              WHERE h.deployment_id = d.id AND h.at >= d.finished_at
          )
        ORDER BY d.finished_at
        """,
        (recent_seconds,),
        _rows,
    )


async def unwatched_releases(conn: AsyncConnection, *, recent_seconds: int) -> list[Row]:
    """Verified releases serving now, finished within `recent_seconds`, never probed since.

    What the monitor supervisor opens a window on: each at most once, because the
    window's first probe is a sample after the release finished.
    """
    return await run(conn, unwatched_releases_query(recent_seconds))


async def last_health_sample_at(conn: AsyncConnection, deployment_id: uuid.UUID) -> datetime | None:
    """When this platform last probed a release, or None if it never has."""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT max(at) FROM app.health_samples WHERE deployment_id = %s", (deployment_id,)
        )
        row = await cur.fetchone()
    return row[0] if row else None


async def flag_for_rollback(conn: AsyncConnection, deployment_id: uuid.UUID, cause: str) -> bool:
    """A verified release monitoring found failing: a rollback now waits for a person.

    Only a release that succeeded and still serves moves to
    `awaiting-rollback-approval`: one a later deployment replaced is not what its
    address serves, whatever that answers. The rollback itself is still a person's
    decision (FR20). Returns whether it moved.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE app.deployments d
            SET state = 'awaiting-rollback-approval', cause = %s
            WHERE d.id = %s AND d.kind = 'release' AND d.state = 'succeeded'
              AND NOT EXISTS (
                  SELECT 1 FROM app.deployments n
                  WHERE n.project_id = d.project_id AND n.target = d.target
                    AND n.created_at > d.created_at AND n.state <> 'failed'
              )
            """,
            (cause, deployment_id),
        )
        return cur.rowcount == 1


async def close_declined_rollback(conn: AsyncConnection, deployment_id: uuid.UUID) -> str | None:
    """A person declined rolling a release back, so it no longer waits on anyone.

    A verified release that monitoring flagged serves on, as it did before the
    flag. One that failed after traffic moved was never verified, so it failed.
    Returns the state it moved to, or None when it was not waiting.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE app.deployments
            SET state = CASE WHEN verified THEN 'succeeded' ELSE 'failed' END
            WHERE id = %s AND state = 'awaiting-rollback-approval'
            RETURNING state
            """,
            (deployment_id,),
        )
        row = await cur.fetchone()
    return row[0] if row else None


async def set_fault_injected(
    conn: AsyncConnection, deployment_id: uuid.UUID, scenario: str
) -> None:
    """Record that a controlled failure was injected, so no metric counts it as organic."""
    await conn.execute(
        "UPDATE app.deployments SET fault_injected = %s WHERE id = %s", (scenario, deployment_id)
    )


async def ensure_step(
    conn: AsyncConnection,
    deployment_id: uuid.UUID,
    *,
    seq: int,
    step_id: str,
    provider: str | None,
    idempotency_key: str,
    moves_traffic: bool,
) -> Row:
    """The step's row, created the first time and found every time after."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            INSERT INTO app.deploy_steps (
                deployment_id, seq, step_id, provider, idempotency_key, state, moves_traffic
            )
            VALUES (%s, %s, %s, %s, %s, 'pending', %s)
            ON CONFLICT (deployment_id, seq) DO NOTHING
            """,
            (deployment_id, seq, step_id, provider, idempotency_key, moves_traffic),
        )
        await cur.execute(
            "SELECT * FROM app.deploy_steps WHERE deployment_id = %s AND seq = %s",
            (deployment_id, seq),
        )
        return await cur.fetchone()


async def update_step(
    conn: AsyncConnection,
    deployment_id: uuid.UUID,
    seq: int,
    *,
    state: str,
    started: bool = False,
    resource: dict[str, Any] | None = None,
    command: str | None = None,
    log_tail: str | None = None,
    error: str | None = None,
) -> None:
    """One step's new state; starting it counts an attempt."""
    await conn.execute(
        """
        UPDATE app.deploy_steps
        SET state = %s,
            attempt = attempt + CASE WHEN %s THEN 1 ELSE 0 END,
            started_at = CASE WHEN %s THEN now() ELSE started_at END,
            finished_at = CASE WHEN %s IN ('succeeded', 'failed', 'compensated', 'skipped')
                               THEN now() ELSE finished_at END,
            resource = COALESCE(%s, resource),
            command = COALESCE(%s, command),
            log_tail = COALESCE(%s, log_tail),
            error = %s
        WHERE deployment_id = %s AND seq = %s
        """,
        (
            state,
            started,
            started,
            state,
            Jsonb(resource) if resource is not None else None,
            command,
            log_tail[-4000:] if log_tail is not None else None,
            error,
            deployment_id,
            seq,
        ),
    )


def latest_verified_release_query(project_id: str) -> Query:
    return Query(
        """
        SELECT * FROM app.deployments
        WHERE project_id = %s AND verified AND state = 'succeeded'
        ORDER BY verified_at DESC NULLS LAST, created_at DESC
        LIMIT 1
        """,
        (project_id,),
        _first,
    )


async def latest_verified_release(conn: AsyncConnection, project_id: str) -> Row | None:
    """The newest release or rollback that passed verification where it runs.

    What a rollback plan restores to. Only a verified deployment counts: a
    release that went out and was never proved is not a state anyone should be
    returned to on purpose.
    """
    return await run(conn, latest_verified_release_query(project_id))


async def deploy_file(
    conn: AsyncConnection, project_id: str, *, version: int, stage_id: str, path: str
) -> str | None:
    """One stage's file at one deploy version, or None."""
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT content FROM app.deploy_files "
            "WHERE project_id = %s AND version = %s AND stage_id = %s AND path = %s",
            (project_id, version, stage_id, path),
        )
        row = await cur.fetchone()
    return row[0] if row else None
