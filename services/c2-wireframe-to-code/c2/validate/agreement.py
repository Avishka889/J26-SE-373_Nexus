"""Static contract agreement: validation before execution. The novelty.

Everything here is a parse of the generated sources plus the manifest, and
nothing here runs the code. The sources are ours by construction, so their
regular shapes are dependable: express routes register as
`router.<method>("<path>", ...)` under an `app.use("<prefix>", ...)` mount,
the generated client carries one `// implements <id> <METHOD> <path>` header
per method, and pages call `client.<method>(...)`. Findings carry real file
and line locations, because "somewhere in this file" is not a location.
"""

import re
from dataclasses import dataclass

from sdlc_contracts import (
    AgreementCounts,
    AgreementFinding,
    ApiContract,
    CodeLocation,
    ContractAgreement,
)

from ..codegen.api_gen import ACKNOWLEDGED_ONLY
from ..codegen.naming import pascal
from ..contract.vocab import canonical

_ROUTE = re.compile(r"router\.(get|post|put|patch|delete)\(\s*\"([^\"]*)\"")
_MOUNT = re.compile(r"app\.use\(\s*\"(/[^\"]*)\"\s*,\s*(\w+)\(")
_ROUTER_FUNCTION = re.compile(r"export function (\w+)\(")
_CLIENT_HEADER = re.compile(r"//\s*implements\s+(\S+)\s+(GET|POST|PUT|PATCH|DELETE)\s+(\S+)")
_CLIENT_METHOD = re.compile(r"^\s{2}(\w+)\(", re.MULTILINE)
_CLIENT_CALL = re.compile(r"\bclient\.(\w+)\s*\(")
_FOREIGN = re.compile(r"\bfetch\s*\(|\baxios\b|XMLHttpRequest")
_ACKNOWLEDGED = re.compile(
    r"//\s*" + re.escape(ACKNOWLEDGED_ONLY) + r"\s+(GET|POST|PUT|PATCH|DELETE)\s+(\S+)"
)


def _line_of(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


@dataclass(frozen=True)
class _Implemented:
    key: str
    path: str
    line: int


def _implemented_routes(sources: dict[str, str]) -> list[_Implemented]:
    """The canonical keys the backend actually serves, with locations.

    Mount prefixes come from app.ts; each route file's registrations combine
    with the prefix of the router function app.ts mounted it under.
    """
    app_source = sources.get("apps/api/src/app.ts", "")
    prefix_by_router: dict[str, str] = {
        match.group(2): match.group(1) for match in _MOUNT.finditer(app_source)
    }

    implemented: list[_Implemented] = []
    for path, content in sources.items():
        if not path.startswith("apps/api/src/routes/"):
            continue
        function_match = _ROUTER_FUNCTION.search(content)
        router_name = function_match.group(1) if function_match else ""
        prefix = prefix_by_router.get(router_name, "")
        for match in _ROUTE.finditer(content):
            method = match.group(1).upper()
            sub_path = match.group(2)
            full = prefix + ("" if sub_path == "/" else sub_path)
            implemented.append(
                _Implemented(
                    key=canonical(method, full or "/"),
                    path=path,
                    line=_line_of(content, match.start()),
                )
            )
    return implemented


def _client_methods(sources: dict[str, str]) -> dict[str, tuple[str, str]]:
    """methodName -> (endpoint id, canonical key), from the client's headers."""
    client_source = sources.get("packages/contract/src/client.ts", "")
    table: dict[str, tuple[str, str]] = {}
    pending: tuple[str, str] | None = None
    for line in client_source.splitlines():
        header = _CLIENT_HEADER.search(line)
        if header:
            pending = (header.group(1), canonical(header.group(2), header.group(3)))
            continue
        method = re.match(r"^\s{2}(\w+)\(", line)
        if method and pending is not None:
            table[method.group(1)] = pending
            pending = None
    return table


def check_agreement(contract: ApiContract, sources: dict[str, str]) -> ContractAgreement:
    findings: list[AgreementFinding] = []
    contract_keys = {canonical(e.method, e.path): e for e in contract.endpoints}

    # The backend side: every contract endpoint implemented, nothing extra.
    implemented = _implemented_routes(sources)
    implemented_keys = {route.key for route in implemented}
    missing = sorted(set(contract_keys) - implemented_keys)
    for key in missing:
        endpoint = contract_keys[key]
        findings.append(
            AgreementFinding(
                rule_id="endpoint-not-implemented",
                severity="error",
                reason=f"the contract declares {key} and the backend does not serve it",
                hint=f"Add the route for {key} to apps/api/src/routes/.",
                subject=endpoint.id,
            )
        )
    for route in implemented:
        if route.key not in contract_keys:
            findings.append(
                AgreementFinding(
                    rule_id="orphan-route",
                    severity="error",
                    reason=f"the backend serves {route.key}, which the contract never declared",
                    hint=f"Remove the route or add {route.key} to the contract.",
                    subject=route.key,
                    location=CodeLocation(path=route.path, line=route.line),
                )
            )

    # An action the backend answers without doing anything. Served, so not
    # missing; but a reviewer approving "checkout settles the order" has to
    # know the settle changes nothing.
    for path, content in sources.items():
        if not path.startswith("apps/api/src/routes/"):
            continue
        for match in _ACKNOWLEDGED.finditer(content):
            key = canonical(match.group(1), match.group(2))
            endpoint = contract_keys.get(key)
            findings.append(
                AgreementFinding(
                    rule_id="action-does-nothing",
                    severity="warning",
                    reason=(
                        f"the backend answers {match.group(1)} {match.group(2)} with the record "
                        "unchanged: the design names this action but not what it changes, so "
                        "nothing was generated for it"
                    ),
                    hint="Say in the design what the action changes, or write its handler.",
                    subject=endpoint.id if endpoint is not None else key,
                    location=CodeLocation(path=path, line=_line_of(content, match.start())),
                )
            )

    # The frontend side: pages call only client methods that exist, and every
    # call resolves to a contract endpoint.
    methods = _client_methods(sources)
    called_ids: set[str] = set()
    for path, content in sources.items():
        if not path.startswith("apps/web/src/"):
            continue
        for match in _CLIENT_CALL.finditer(content):
            name = match.group(1)
            if name not in methods:
                findings.append(
                    AgreementFinding(
                        rule_id="unknown-client-method",
                        severity="error",
                        reason=f"{path} calls client.{name}, which the generated client does not have",
                        hint=f"Call one of: {', '.join(sorted(methods))}.",
                        subject=name,
                        location=CodeLocation(path=path, line=_line_of(content, match.start())),
                    )
                )
                continue
            endpoint_id, key = methods[name]
            called_ids.add(endpoint_id)
            if key not in contract_keys:
                findings.append(
                    AgreementFinding(
                        rule_id="stale-implements-header",
                        severity="warning",
                        reason=f"the client's {name} claims {key}, which the contract no longer has",
                        hint="Regenerate the contract package.",
                        subject=name,
                        location=CodeLocation(path="packages/contract/src/client.ts", line=1),
                    )
                )
        foreign = _FOREIGN.search(content)
        if foreign:
            findings.append(
                AgreementFinding(
                    rule_id="foreign-call",
                    severity="error",
                    reason=f"{path} requests outside the generated client",
                    hint="Route every request through the client, which is what agreement measures.",
                    subject=path,
                    location=CodeLocation(path=path, line=_line_of(content, foreign.start())),
                )
            )

    # A form whose fields nothing saves. A screen with fields and no write is
    # generated with no submit, and it counted as implemented like any other
    # screen (review item C2-3). By what the page calls rather than by a
    # handler's name, so a page the model rewrote is judged the same way.
    for path, content in sorted(sources.items()):
        if not path.startswith("apps/web/src/pages/"):
            continue
        field = content.find("<Field ")
        if field < 0:
            continue
        writes = {
            name
            for name in _CLIENT_CALL.findall(content)
            if name in methods and methods[name][1].split(" ", 1)[0] in ("POST", "PATCH", "PUT")
        }
        if not writes:
            findings.append(
                AgreementFinding(
                    rule_id="form-not-wired",
                    severity="warning",
                    reason=(
                        f"{path} shows a form whose fields nothing saves: the design gives "
                        "this screen no write, so it was generated without a submit"
                    ),
                    hint=(
                        "Say in the design what this form saves, so its write is inferred, "
                        "or take the fields off the screen."
                    ),
                    subject=path,
                    location=CodeLocation(path=path, line=_line_of(content, field)),
                )
            )

    unused = sorted(
        endpoint.id for key, endpoint in contract_keys.items() if endpoint.id not in called_ids
    )
    for endpoint_id in unused:
        findings.append(
            AgreementFinding(
                rule_id="endpoint-not-called",
                severity="warning",
                reason=f"no generated page calls {endpoint_id}",
                hint=(
                    f"Either a screen should use {endpoint_id} or it exists for a "
                    "non UI caller; the gate reader decides which."
                ),
                subject=endpoint_id,
            )
        )

    # The schema side: every entity a schema references has its model file.
    schema_mismatches = 0
    for entity in contract.entities:
        model_path = f"apps/api/src/models/{pascal(entity.name)}.ts"
        if model_path not in sources:
            schema_mismatches += 1
            findings.append(
                AgreementFinding(
                    rule_id="entity-model-missing",
                    severity="error",
                    reason=f"entity {entity.name} has no generated model file",
                    hint=f"Generate {model_path} from the contract's entity.",
                    subject=entity.name,
                )
            )
        elif f"export interface {pascal(entity.name)} " not in sources[model_path]:
            schema_mismatches += 1
            findings.append(
                AgreementFinding(
                    rule_id="entity-model-missing",
                    severity="error",
                    reason=f"{model_path} does not declare the {entity.name} interface",
                    hint=f"Regenerate {model_path}.",
                    subject=entity.name,
                    location=CodeLocation(path=model_path, line=1),
                )
            )

    orphan_keys = sorted({route.key for route in implemented} - set(contract_keys))
    foreign_paths = sorted(
        {finding.subject for finding in findings if finding.rule_id == "foreign-call"}
    )
    total = len(contract_keys)
    implemented_count = total - len(missing)

    counts = AgreementCounts(
        endpoints_total=total,
        endpoints_implemented=implemented_count,
        endpoints_missing=[contract_keys[key].id for key in missing],
        endpoints_called=len(called_ids),
        endpoints_unused=unused,
        orphan_routes=orphan_keys,
        foreign_calls=foreign_paths,
        schema_mismatches=schema_mismatches,
        agreement_rate=(implemented_count / total) if total else 1.0,
    )
    return ContractAgreement(contract_version=contract.version, findings=findings, counts=counts)
