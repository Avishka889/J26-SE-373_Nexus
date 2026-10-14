"""One violating fixture per rule: C1's discipline, C2's catalogue.

Each test breaks exactly one thing about an otherwise clean contract and
asserts the one rule that exists for it fires, with a hint that is not the
reason restated, because the hint is what the repair loop sends back.
"""

from c2.contract.rule_arm import generate_rule_contract
from c2.contract.rules import ALL_RULES, RULE_IDS, ContractContext, validate_contract
from sdlc_contracts import ApiEndpoint, EndpointSchema, EndpointTraces

from .design_fixture import graph, scope, wireframes


def _context() -> ContractContext:
    return ContractContext(graph=graph(), wireframes=wireframes(), scope=scope())


def _clean():
    return generate_rule_contract(1, graph(), wireframes(), scope())


def _fired(contract, rule_id: str) -> list:
    result = validate_contract(contract, _context())
    return [finding for finding in result.findings if finding.rule_id == rule_id]


def _endpoint(**overrides) -> ApiEndpoint:
    base = dict(
        id="get-orders",
        method="GET",
        path="/orders",
        traces=EndpointTraces(screen_ids=["shop/catalog"]),
    )
    base.update(overrides)
    return ApiEndpoint(**base)


class TestOneViolationPerRule:
    def test_endpoint_traces(self) -> None:
        contract = _clean()
        contract.endpoints.append(
            _endpoint(id="get-nowhere", path="/orders", method="DELETE", traces=EndpointTraces())
        )
        fired = _fired(contract, "endpoint-traces")
        assert len(fired) == 1 and fired[0].subject == "get-nowhere"
        assert fired[0].hint != fired[0].reason

    def test_traces_resolve(self) -> None:
        contract = _clean()
        contract.endpoints.append(
            _endpoint(
                id="get-ghost",
                traces=EndpointTraces(screen_ids=["shop/ghost"], story_ids=["US-99"]),
            )
        )
        fired = _fired(contract, "traces-resolve")
        assert len(fired) == 2
        assert any("shop/ghost" in finding.reason for finding in fired)
        assert any("US-99" in finding.reason for finding in fired)

    def test_schema_entity_known(self) -> None:
        contract = _clean()
        contract.endpoints.append(
            _endpoint(id="get-mystery", request=EndpointSchema(entity="Mystery"))
        )
        fired = _fired(contract, "schema-entity-known")
        assert len(fired) == 1 and "Mystery" in fired[0].reason

    def test_no_duplicate_paths(self) -> None:
        contract = _clean()
        # Duplicate an endpoint the clean contract really has, or the rule has
        # nothing to collide with and the test passes on air.
        existing = contract.endpoints[0]
        contract.endpoints.append(
            _endpoint(id=f"{existing.id}-again", method=existing.method, path=existing.path)
        )
        assert len(_fired(contract, "no-duplicate-paths")) == 1

    def test_method_path_shape(self) -> None:
        contract = _clean()
        contract.endpoints.append(_endpoint(id="patch-orders", method="PATCH", path="/orders"))
        fired = _fired(contract, "method-path-shape")
        assert len(fired) == 1 and "{id}" in fired[0].hint

    def test_resource_from_an_entity(self) -> None:
        contract = _clean()
        contract.endpoints.append(_endpoint(id="get-invoices", path="/invoices"))
        fired = _fired(contract, "resource-from-an-entity")
        assert len(fired) == 1 and "invoices" in fired[0].reason

    def test_screen_action_has_an_endpoint(self) -> None:
        contract = _clean()
        # Remove every write: the checkout form now submits nowhere.
        contract.endpoints = [
            endpoint for endpoint in contract.endpoints if endpoint.method == "GET"
        ]
        fired = _fired(contract, "screen-action-has-an-endpoint")
        assert len(fired) == 1 and fired[0].subject == "shop/checkout"

    def test_list_screen_has_a_read(self) -> None:
        contract = _clean()
        contract.endpoints = [
            endpoint
            for endpoint in contract.endpoints
            if "shop/catalog" not in endpoint.traces.screen_ids
        ]
        fired = _fired(contract, "list-screen-has-a-read")
        assert len(fired) == 1 and fired[0].subject == "shop/catalog"

    def test_auth_actor_known(self) -> None:
        contract = _clean()
        contract.endpoints.append(
            _endpoint(id="get-orders-admin", path="/orders/{id}", auth_actors=["Administrator"])
        )
        fired = _fired(contract, "auth-actor-known")
        assert len(fired) == 1 and fired[0].severity == "warning"


class TestTheCatalogueIsPinned:
    def test_rule_ids_match_the_functions(self) -> None:
        assert len(ALL_RULES) == len(RULE_IDS) == 9

    def test_every_rule_id_fires_somewhere_in_this_file(self) -> None:
        """The denominator check: a rule nobody can violate is not a rule."""
        import pathlib

        source = pathlib.Path(__file__).read_text()
        for rule_id in RULE_IDS:
            assert f'"{rule_id}"' in source, f"{rule_id} has no violating fixture"
