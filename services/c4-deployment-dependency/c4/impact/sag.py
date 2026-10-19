"""The components an update reaches (FR10, FR11): affected files mapped onto the design.

**For a platform project, the component is a Semantic Architecture Graph node.**
The mapping is a chain of recorded facts, never a resemblance between names:

- the generation manifest says what each file implements: endpoint ids, entity
  names, screen ids;
- an endpoint's request and response schemas each say which graph entity they
  are a view of;
- an entity name matches a graph entity node's label exactly, or not at all.

So a file maps to an entity node because the manifest says it implements that
entity (`manifest-entity`), or because it implements an endpoint whose schema is
a view of it (`endpoint-entity`), and each link is kept with the manifest row
and the endpoint that made it. A file the chain does not reach is listed as
unmapped with the reason: no manifest row, nothing it implements is an entity or
an endpoint (a screen, a server entry point), a name no graph node carries, or
no graph to map onto. None is guessed onto a node whose name is merely close.

**For a project without a graph** (a BUMP client), the component is the Maven
module the file sits under: the nearest directory above it with a `pom.xml`,
named by that module's `artifactId`. The report says which granularity it
used, and the two are never pooled in one number.
"""

import re
from collections import defaultdict
from xml.etree import ElementTree

from sdlc_contracts import (
    AffectedComponent,
    ApiContract,
    ArchitectureGraph,
    ComponentLink,
    ManifestRow,
    UnmappedFile,
)

_ARTIFACT = re.compile(r"\{[^}]*\}")


def map_to_graph(
    affected: dict[str, set[str]],
    *,
    graph: ArchitectureGraph | None,
    contract: ApiContract | None,
    manifest: list[ManifestRow],
) -> tuple[list[AffectedComponent], list[UnmappedFile]]:
    """Each affected file onto the entity nodes the recorded chain reaches, or unmapped."""
    if graph is None:
        return [], [
            UnmappedFile(
                path=path,
                reason="graph-unavailable",
                detail="no Semantic Architecture Graph is recorded for this code version",
            )
            for path in sorted(affected)
        ]
    entities = {node.label: node for node in graph.nodes if node.kind == "entity"}
    endpoints = {endpoint.id: endpoint for endpoint in (contract.endpoints if contract else [])}
    rows = {row.path: row for row in manifest}

    links: dict[str, list[ComponentLink]] = defaultdict(list)
    files: dict[str, set[str]] = defaultdict(set)
    updates: dict[str, set[str]] = defaultdict(set)
    unmapped: list[UnmappedFile] = []
    for path in sorted(affected):
        row = rows.get(path)
        if row is None:
            unmapped.append(
                UnmappedFile(
                    path=path,
                    reason="not-in-manifest",
                    detail="the generation manifest has no row for this file",
                )
            )
            continue
        reached: list[tuple[str, ComponentLink]] = []
        missing: list[str] = []
        for item in row.implements:
            endpoint = endpoints.get(item)
            if endpoint is not None:
                views = [s.entity for s in (endpoint.request, endpoint.response) if s and s.entity]
                for name in dict.fromkeys(views):
                    node = entities.get(name)
                    if node is None:
                        missing.append(name)
                        continue
                    detail = f"{item} ({endpoint.method} {endpoint.path}) is a view of {name}"
                    reached.append(
                        (node.id, ComponentLink(via="endpoint-entity", path=path, detail=detail))
                    )
            elif item in entities:
                reached.append(
                    (
                        entities[item].id,
                        ComponentLink(
                            via="manifest-entity", path=path, detail=f"implements {item}"
                        ),
                    )
                )
        if not reached:
            if missing:
                reason, detail = (
                    "no-graph-node-matches",
                    f"no graph entity is named exactly {', '.join(sorted(set(missing)))}",
                )
            elif row.implements:
                reason, detail = (
                    "implements-nothing-mapped",
                    f"it implements {', '.join(row.implements)}, none of which is an entity "
                    "or an endpoint",
                )
            else:
                reason, detail = (
                    "implements-nothing-mapped",
                    "the manifest records nothing this file implements",
                )
            unmapped.append(UnmappedFile(path=path, reason=reason, detail=detail))
            continue
        for node_id, link in reached:
            links[node_id].append(link)
            files[node_id].add(path)
            updates[node_id] |= affected[path]

    by_id = {node.id: node for node in graph.nodes}
    components = [
        AffectedComponent(
            node_id=node_id,
            label=by_id[node_id].label,
            kind=by_id[node_id].kind,
            update_ids=sorted(updates[node_id]),  # type: ignore[arg-type]
            files=sorted(files[node_id]),
            links=links[node_id],
            traces=list(by_id[node_id].traces),
        )
        for node_id in sorted(links)
    ]
    return components, unmapped


def _artifact_id(pom: str) -> str:
    """A module's own `artifactId`, not its parent's."""
    try:
        root = ElementTree.fromstring(pom)
    except ElementTree.ParseError:
        return ""
    for child in root:
        if _ARTIFACT.sub("", child.tag) == "artifactId" and child.text:
            return child.text.strip()
    return ""


def map_to_modules(
    affected: dict[str, set[str]], files: dict[str, str]
) -> tuple[list[AffectedComponent], list[UnmappedFile]]:
    """Each affected file onto the Maven module it sits under."""
    modules = {
        path.removesuffix("pom.xml").rstrip("/"): _artifact_id(text)
        for path, text in files.items()
        if path == "pom.xml" or path.endswith("/pom.xml")
    }
    links: dict[str, list[ComponentLink]] = defaultdict(list)
    members: dict[str, set[str]] = defaultdict(set)
    updates: dict[str, set[str]] = defaultdict(set)
    unmapped: list[UnmappedFile] = []
    for path in sorted(affected):
        parts = path.split("/")[:-1]
        home = next(
            (
                "/".join(parts[:depth])
                for depth in range(len(parts), -1, -1)
                if "/".join(parts[:depth]) in modules
            ),
            None,
        )
        if home is None:
            unmapped.append(
                UnmappedFile(
                    path=path,
                    reason="no-build-module",
                    detail="no pom.xml sits in this file's directory or above it",
                )
            )
            continue
        build = f"{home}/pom.xml" if home else "pom.xml"
        links[home].append(ComponentLink(via="build-module", path=path, detail=f"under {build}"))
        members[home].add(path)
        updates[home] |= affected[path]
    components = [
        AffectedComponent(
            node_id=f"module:{home or '.'}",
            label=modules[home] or home or ".",
            kind="module",
            update_ids=sorted(updates[home]),  # type: ignore[arg-type]
            files=sorted(members[home]),
            links=links[home],
            traces=[],
        )
        for home in sorted(links)
    ]
    return components, unmapped
