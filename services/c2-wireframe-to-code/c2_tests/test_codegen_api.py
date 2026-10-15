"""The backend generator and the monorepo: complete handlers, honest fill."""

import json

from c2.codegen.api_gen import api_app
from c2.codegen.fill import (
    build_page_filler,
    check_handler_fill,
    check_page_fill,
    dropped_headers,
    fill_page,
)
from c2.codegen.monorepo import generate_monorepo
from c2.contract.field_rules import with_field_rules
from c2.contract.rule_arm import generate_rule_contract
from pydantic_ai.models.test import TestModel
from sdlc_contracts import SchemaField

from .design_fixture import graph, scope, wireframes


def _contract():
    return generate_rule_contract(1, graph(), wireframes(), scope())


def _bounded_contract():
    return with_field_rules(
        _contract(),
        [
            "An order total is at least 2000 and at most 9000",
            "The status is one of placed or shipped",
        ],
    )


class TestAFieldsBounds:
    """The bounds the design and the criteria state were a comment in the handler,
    and the app took any value: the Movie Tracker took release years 1999 and 2027."""

    def test_create_and_update_refuse_a_value_outside_them(self) -> None:
        contract = _bounded_contract()
        orders = api_app(contract).content_of("apps/api/src/routes/orders.ts")
        writes = [
            endpoint
            for endpoint in contract.endpoints
            if endpoint.path.startswith("/orders")
            and (
                endpoint.method in ("PATCH", "PUT")
                or (endpoint.method == "POST" and "{" not in endpoint.path)
            )
        ]
        total = (
            '    if (req.body?.total !== undefined && !(typeof req.body.total === "number" '
            "&& req.body.total >= 2000 && req.body.total <= 9000)) {"
        )
        status = (
            '    if (req.body?.status !== undefined && !(["placed","shipped"]'
            ".includes(req.body.status))) {"
        )
        assert writes and orders.count(total) == len(writes)
        assert orders.count(status) == len(writes)
        assert 'res.status(400).json({ error: "total must be between 2000 and 9000" });' in orders
        assert 'res.status(400).json({ error: "status must be one of placed, shipped" });' in orders
        # Before the write, so a refused value is never kept.
        assert orders.index(total) < orders.index("repository.create(req.body)")

    def test_its_own_tests_send_values_inside_them(self) -> None:
        tests = api_app(_bounded_contract()).content_of(
            "apps/api/src/__tests__/orders.contract.test.ts"
        )
        assert "total: 2000" in tests and 'status: "placed"' in tests
        assert "total: 1," not in tests and "total: 1 }" not in tests

    def test_an_unbounded_field_is_left_as_it_was(self) -> None:
        orders = api_app(_contract()).content_of("apps/api/src/routes/orders.ts")
        assert "res.status(400)" not in orders


class TestTheApiApp:
    def test_models_carry_the_repository_and_the_in_memory_impl(self) -> None:
        files = api_app(_contract())
        order = files.content_of("apps/api/src/models/Order.ts")
        assert "export interface Order {" in order
        assert "export interface OrderRepository {" in order
        assert "class InMemoryOrderRepository implements OrderRepository" in order

    def test_every_endpoint_gets_a_route_with_its_implements_header(self) -> None:
        contract = _contract()
        files = api_app(contract)
        routes = "".join(
            generated.content for generated in files.files if "/routes/" in generated.path
        )
        for endpoint in contract.endpoints:
            assert f"// implements {endpoint.id} {endpoint.method} {endpoint.path}" in routes

    def test_handlers_are_complete_crud_not_stubs(self) -> None:
        files = api_app(_contract())
        orders = files.content_of("apps/api/src/routes/orders.ts")
        assert "repository.create(req.body)" in orders
        assert "repository.remove(" in orders
        assert "res.status(404)" in orders
        assert "TODO" not in orders

    def test_validation_rules_land_as_handler_comments(self) -> None:
        files = api_app(_contract())
        orders = files.content_of("apps/api/src/routes/orders.ts")
        assert "// validation: An order total never exceeds available stock" in orders

    def test_the_app_mounts_every_resource(self) -> None:
        files = api_app(_contract())
        app = files.content_of("apps/api/src/app.ts")
        assert 'app.use("/orders", ordersRouter(ordersRepository));' in app
        assert 'app.use("/products", productsRouter(productsRepository));' in app

    def test_env_example_has_names_only(self) -> None:
        files = api_app(_contract())
        env = files.content_of("apps/api/.env.example")
        for line in env.splitlines():
            if "=" in line and not line.startswith("#"):
                assert line.endswith("="), f"a value leaked into .env.example: {line}"

    def test_id_endpoint_tests_seed_through_the_repository(self) -> None:
        """The contract may have no create route for an entity, so a test
        that needs an existing row seeds the repository directly."""
        files = api_app(_contract())
        orders_tests = files.content_of("apps/api/src/__tests__/orders.contract.test.ts")
        assert "await ordersRepository.create(" in orders_tests
        assert "import { app, ordersRepository }" in orders_tests
        # The only route based create left is the test of the create endpoint.
        assert orders_tests.count('request(app).post("/orders")') == 1

    def test_each_endpoint_gets_a_contract_test(self) -> None:
        contract = _contract()
        files = api_app(contract)
        tests = "".join(
            generated.content for generated in files.files if "__tests__" in generated.path
        )
        for endpoint in contract.endpoints:
            assert f'"implements {endpoint.id}"' in tests


class TestWhereTheRecordsAreKept:
    """MongoDB when the app is given one, memory when it is not, and tests in memory always."""

    def test_every_entity_has_a_mongodb_repository_beside_the_one_in_memory(self) -> None:
        order = api_app(_contract()).content_of("apps/api/src/models/Order.ts")
        assert "class MongoOrderRepository implements OrderRepository" in order
        assert 'import type { Collection, WithId } from "mongodb";' in order
        # Node strips types to run the backend, and a parameter property is
        # TypeScript it would have to compile.
        assert "constructor(private" not in order
        assert "constructor(collection: Collection<OrderDocument>)" in order
        # Ids are strings the app makes, kept as the document's own _id.
        assert "insertOne({ ...item, _id: id })" in order
        assert "randomUUID()" in order

    def test_an_empty_update_answers_with_the_record_instead_of_an_empty_set(self) -> None:
        order = api_app(_contract()).content_of("apps/api/src/models/Order.ts")
        assert "if (Object.keys(fields).length === 0) return this.get(id);" in order

    def test_the_app_takes_mongodb_when_mongodb_url_names_one_and_memory_otherwise(
        self,
    ) -> None:
        app = api_app(_contract()).content_of("apps/api/src/app.ts")
        assert "const databaseUrl = process.env.MONGODB_URL?.trim();" in app
        assert (
            "export const ordersRepository = database\n"
            '  ? new MongoOrderRepository(database.collection<OrderDocument>("orders"))\n'
            "  : new InMemoryOrderRepository();"
        ) in app
        assert 'export const storage: "mongodb" | "memory"' in app

    def test_the_server_says_where_it_keeps_the_records(self) -> None:
        server = api_app(_contract()).content_of("apps/api/src/server.ts")
        assert 'import { app, storage } from "./app.ts";' in server
        assert "records kept in memory, which a restart empties" in server

    def test_the_api_depends_on_the_official_driver(self) -> None:
        manifest = json.loads(api_app(_contract()).content_of("apps/api/package.json"))
        assert manifest["dependencies"]["mongodb"].startswith("^7.")

    def test_the_tests_run_in_memory_whatever_the_shell_exports(self) -> None:
        config = api_app(_contract()).content_of("apps/api/vitest.config.ts")
        assert 'test: { env: { MONGODB_URL: "" } }' in config


class TestTheMonorepo:
    def test_the_three_workspaces_assemble_without_collisions(self) -> None:
        files = generate_monorepo(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule"
        )
        paths = [generated.path for generated in files.files]
        assert "package.json" in paths
        assert "apps/web/src/routes.tsx" in paths
        assert "apps/api/src/app.ts" in paths
        assert "packages/contract/src/client.ts" in paths
        assert len(paths) == len(set(paths))

    def test_the_readme_names_project_version_and_arm(self) -> None:
        files = generate_monorepo(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=2, arm="merged"
        )
        readme = files.content_of("README.md")
        assert "# ShopFlow" in readme
        assert "Design version: v2" in readme
        assert "Contract arm: merged" in readme

    def test_the_carried_ci_runs_tests_only(self) -> None:
        files = generate_monorepo(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule"
        )
        workflow = files.content_of(".github/workflows/ci.yml")
        assert "npm test" in workflow
        # No deploy steps, no platform secrets. The comment SAYING deploy
        # authority stays with the platform is allowed; a deploy step is not.
        steps = [line for line in workflow.splitlines() if line.strip().startswith("- ")]
        for line in steps:
            for forbidden in ("deploy", "secrets.", "vercel", "render"):
                assert forbidden not in line.lower(), line

    def test_the_manifest_attributes_every_file(self) -> None:
        files = generate_monorepo(
            "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule"
        )
        rows = files.manifest("rule")
        assert all(row.generator in ("static", "rule") for row in rows)
        page_row = next(row for row in rows if row.path.endswith("ShopCheckoutPage.tsx"))
        assert "post-orders" in page_row.implements


class TestTheFillConstraints:
    def test_an_invented_client_method_is_refused(self) -> None:
        problems = check_page_fill("client.launchMissiles()", {"getProducts"})
        assert problems and "launchMissiles" in problems[0]

    def test_fetching_around_the_client_is_refused(self) -> None:
        assert check_page_fill('fetch("/api/x")', {"getProducts"}) != []

    def test_an_invented_repository_method_is_refused(self) -> None:
        assert check_handler_fill("repository.truncateAll()") != []

    def test_a_lawful_fill_passes(self) -> None:
        assert check_page_fill("client.getProducts()", {"getProducts"}) == []
        assert check_handler_fill("await repository.list()") == []

    def test_a_dropped_implements_header_is_refused(self) -> None:
        """The header is what the agreement check reads.

        A fill that drops it does not look worse; it makes the endpoint read as
        unimplemented, so the run reports a disagreement that is not there.
        """
        rule = "// implements get-products GET /products\nexport function Page() {}"
        problems = dropped_headers(rule, "export function Page() {}")
        assert problems and "get-products" in problems[0]

    def test_a_kept_header_passes_whatever_else_moved(self) -> None:
        rule = "// implements get-products GET /products\nold body"
        assert dropped_headers(rule, "// implements get-products GET /products\nnew body") == []

    async def test_a_fill_that_drops_a_header_falls_back_to_the_rule_body(self) -> None:
        agent = build_page_filler(TestModel(custom_output_args={"content": "client.getProducts()"}))
        outcome = await fill_page(
            agent,
            rule_body="// implements get-products GET /products\nclient.getProducts()",
            allowed_methods={"getProducts"},
        )
        assert not outcome.accepted
        assert any("was dropped" in reason for reason in outcome.refused_reasons)

    async def test_a_refused_fill_falls_back_to_the_rule_body(self) -> None:
        agent = build_page_filler(TestModel(custom_output_args={"content": "client.invented()"}))
        outcome = await fill_page(agent, rule_body="rule body", allowed_methods={"getProducts"})
        assert not outcome.accepted
        assert outcome.attempts == 2
        assert any("invented" in reason for reason in outcome.refused_reasons)

    async def test_a_lawful_fill_is_accepted_with_its_attempt_count(self) -> None:
        agent = build_page_filler(TestModel(custom_output_args={"content": "client.getProducts()"}))
        outcome = await fill_page(agent, rule_body="rule body", allowed_methods={"getProducts"})
        assert outcome.accepted and outcome.attempts == 1


class TestTheContractTestSeeds:
    """The seed values and the TypeScript types must cover the same set.

    Found on the first live walk. Only number and boolean were mapped and
    everything else fell back to a string, so the first contract carrying an
    `array` field seeded `tags: "sample"` against an `unknown[]` model and the
    whole typecheck step failed. The rule arm never emits array or object,
    which is why nothing caught it until the LLM arm produced one.
    """

    def test_every_field_type_the_contract_allows_has_a_seed(self) -> None:
        from typing import get_args

        from c2.codegen.api_gen import SAMPLE_VALUES
        from sdlc_contracts.api_contract import FieldType

        assert set(SAMPLE_VALUES) == set(get_args(FieldType))

    def test_an_array_field_seeds_an_array_not_a_string(self) -> None:
        contract = _contract()
        entity = contract.entities[0]
        widened = entity.model_copy(
            update={
                "fields": [
                    *entity.fields,
                    SchemaField(name="tags", type="array", item_ref=""),
                    SchemaField(name="meta", type="object", item_ref=""),
                ]
            }
        )
        contract = contract.model_copy(
            update={
                "entities": [widened, *contract.entities[1:]],
            }
        )
        files = api_app(contract)
        tests = "".join(
            generated.content for generated in files.files if "__tests__" in generated.path
        )
        # The seed has to typecheck against `ts_type`, which types these
        # `unknown[]` and `Record<string, unknown>`.
        assert "tags: []" in tests
        assert "meta: {}" in tests
        assert 'tags: "sample"' not in tests

    def test_a_literal_path_is_registered_before_one_that_would_shadow_it(self) -> None:
        """Express matches in registration order.

        Found on the first live walk: the LLM arm declared `GET /routes/today`
        beside `GET /routes/{id}`, the parameterised route was registered
        first, and every request for /routes/today reached the id handler,
        looked up a route called "today" and answered 404. The contract
        declared both endpoints and the code served one.
        """
        from sdlc_contracts import ApiContract, ApiEndpoint

        contract = ApiContract(
            version=1,
            entities=[],
            endpoints=[
                ApiEndpoint(id="get-routes-id", method="GET", path="/routes/{id}", traces={}),
                ApiEndpoint(id="get-routes-today", method="GET", path="/routes/today", traces={}),
                ApiEndpoint(
                    id="get-routes-id-stops", method="GET", path="/routes/{id}/stops", traces={}
                ),
            ],
        )
        routes = api_app(contract).content_of("apps/api/src/routes/routes.ts")
        registrations = [line for line in routes.splitlines() if line.strip().startswith("router.")]
        literal = next(i for i, line in enumerate(registrations) if '"/today"' in line)
        parameterised = next(i for i, line in enumerate(registrations) if '"/:id"' in line)
        assert literal < parameterised, "the literal path must be registered first"

    def test_a_nested_path_parameter_is_a_literal_not_an_entity_field(self) -> None:
        """`${created.stop_id}` against a `Route` failed the whole typecheck.

        The first parameter is the seeded row's id, because the route file is
        about that resource. Anything after it names something the contract
        never says how to create, so it is a literal and the assertion widens
        to say so rather than pretending a lookup was set up.
        """
        from .kitchen_contract import kitchen_sink_contract

        tests = api_app(kitchen_sink_contract()).content_of(
            "apps/api/src/__tests__/routes.contract.test.ts"
        )
        assert "${created.stop_id}" not in tests
        assert "/routes/${created.id}/stops/1" in tests
        # The weaker claim is stated where it is made.
        assert "expect([200, 204, 404])" in tests
        assert "a 404 is a correct answer here and a 500 is not" in tests
