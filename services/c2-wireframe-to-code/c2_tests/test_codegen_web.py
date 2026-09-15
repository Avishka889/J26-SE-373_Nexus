"""The contract package and the web app: rule generated, traced, functional.

String level assertions here; the sandbox build test proves the same output
typechecks under tsc with the real toolchain, behind its own marker.
"""

import re

from c2.codegen.client_gen import contract_package, generate_client, generate_types
from c2.codegen.web_gen import web_app
from c2.contract.rule_arm import generate_rule_contract

from .design_fixture import graph, scope, wireframes


def _contract():
    return generate_rule_contract(1, graph(), wireframes(), scope())


class TestTheTypes:
    def test_entities_become_interfaces_with_mapped_types(self) -> None:
        types = generate_types(_contract())
        assert "export interface Order {" in types
        assert "total: number;" in types
        assert "placedAt: string;" in types  # dates travel as strings
        assert "id: string;" in types

    def test_request_types_omit_the_id(self) -> None:
        types = generate_types(_contract())
        assert "PostOrdersRequest" in types


class TestTheClient:
    def test_one_method_per_endpoint_with_its_implements_header(self) -> None:
        contract = _contract()
        client = generate_client(contract)
        for endpoint in contract.endpoints:
            assert f"// implements {endpoint.id} {endpoint.method} {endpoint.path}" in client
        assert client.count("// implements") == len(contract.endpoints)

    def test_path_parameters_become_arguments(self) -> None:
        client = generate_client(_contract())
        assert "getOrdersId(id: string)" in client

    def test_writes_take_a_typed_body(self) -> None:
        client = generate_client(_contract())
        assert "postOrders(body: PostOrdersRequest)" in client

    def test_the_package_manifest_records_what_each_file_implements(self) -> None:
        contract = _contract()
        files = contract_package(contract, "rule arm")
        rows = files.manifest("rule")
        client_row = next(row for row in rows if row.path.endswith("client.ts"))
        assert set(client_row.implements) == {e.id for e in contract.endpoints}
        assert client_row.generator == "rule"


class TestTheWebApp:
    def test_scoped_screens_become_routes_and_pages(self) -> None:
        files = web_app(_contract(), wireframes(), scope())
        routes = files.content_of("apps/web/src/routes.tsx")
        assert '<Route path="/shop/catalog"' in routes
        assert '<Route path="/shop/checkout"' in routes
        # The confirmation shows one order, so its address takes the order's id.
        assert '<Route path="/shop/done/:id?"' in routes
        paths = [generated.path for generated in files.files]
        assert "apps/web/src/pages/ShopCatalogPage.tsx" in paths

    def test_a_list_screen_fetches_through_the_traced_client_method(self) -> None:
        files = web_app(_contract(), wireframes(), scope())
        catalog = files.content_of("apps/web/src/pages/ShopCatalogPage.tsx")
        assert "client.getProducts()" in catalog
        assert "// implements get-products GET /products" in catalog

    def test_a_form_screen_submits_through_the_traced_write(self) -> None:
        files = web_app(_contract(), wireframes(), scope())
        checkout = files.content_of("apps/web/src/pages/ShopCheckoutPage.tsx")
        assert "client.postOrders(" in checkout
        assert 'useState("")' in checkout
        # The submit is asserted by its wiring and its label, not by its class
        # list: styling is allowed to move, calling the traced endpoint is not.
        assert "onClick={submit}" in checkout
        assert ">Place order</Button>" in checkout

    def test_a_list_renders_the_entity_fields_rather_than_the_whole_row(self) -> None:
        """`JSON.stringify(item)` in a table cell reads as an unfinished app.

        The contract already carries the entity's fields, so the table has
        columns and a reader can tell a working page from a placeholder.
        """
        files = web_app(_contract(), wireframes(), scope())
        catalog = files.content_of("apps/web/src/pages/ShopCatalogPage.tsx")
        assert "<DataTable" in catalog
        assert "cell(item.name)" in catalog
        # How the app finds a row, not something a reader looks for.
        assert "cell(item.id)" not in catalog
        assert "{JSON.stringify(item)}</li>" not in catalog

    def test_the_shell_navigates_to_every_scoped_screen(self) -> None:
        """Screen links only go where their own flow goes; without a shell a
        reader who lands on the entry screen can walk one path and no other."""
        files = web_app(_contract(), wireframes(), scope())
        routes = files.content_of("apps/web/src/routes.tsx")
        for screen_id in ("catalog", "checkout", "done"):
            assert f'{{ to: "/shop/{screen_id}"' in routes

    def test_the_styling_is_wired_end_to_end(self) -> None:
        """A token set nothing imports is a file, not a style."""
        files = web_app(_contract(), wireframes(), scope())
        assert '@import "tailwindcss"' in files.content_of("apps/web/src/styles.css")
        assert 'import "./styles.css"' in files.content_of("apps/web/src/main.tsx")
        assert "tailwindcss()" in files.content_of("apps/web/vite.config.ts")
        assert '"tailwindcss"' in files.content_of("apps/web/package.json")

    def test_pages_never_fetch_outside_the_client(self) -> None:
        files = web_app(_contract(), wireframes(), scope())
        for generated in files.files:
            if "/pages/" in generated.path:
                assert "fetch(" not in generated.content
                assert "axios" not in generated.content

    def test_a_page_imports_only_the_hooks_it_uses(self) -> None:
        """A form screen has no fetch on mount, so it has no effect to run.

        An unused import is not a build error under this tsconfig, which is
        exactly why nothing caught it: generated code is read by people who are
        deciding whether to trust it.
        """
        files = web_app(_contract(), wireframes(), scope())
        checkout = files.content_of("apps/web/src/pages/ShopCheckoutPage.tsx")
        assert "useEffect" not in checkout
        catalog = files.content_of("apps/web/src/pages/ShopCatalogPage.tsx")
        assert 'import { useEffect, useState } from "react";' in catalog

    def test_a_column_heading_reads_as_a_person_wrote_it(self) -> None:
        files = web_app(_contract(), wireframes(), scope())
        done = files.content_of("apps/web/src/pages/ShopDonePage.tsx")
        assert ">Placed at</dt>" in done, "a camelCase field name reached a heading"
        assert "PlacedAt" not in done

    def test_a_label_with_jsx_punctuation_does_not_break_the_build(self) -> None:
        """Labels come from a language model, not from a developer.

        One `{` in a screen name ends the build, and the failure surfaces as
        `npm run build` exiting with an esbuild error about an unexpected
        token, which reads as a generator bug with no clue which of fifty
        files caused it.
        """
        wires = wireframes()
        wires.flows[0].screens[0].name = "Catalog {beta} <new>"
        files = web_app(_contract(), wires, scope())
        page = files.content_of("apps/web/src/pages/ShopCatalogPage.tsx")
        assert '{"Catalog {beta} <new>"}' in page
        assert ">Catalog {beta}" not in page

    def test_the_routes_test_stubs_the_network_honestly(self) -> None:
        files = web_app(_contract(), wireframes(), scope())
        test_source = files.content_of("apps/web/src/__tests__/routes.test.tsx")
        assert 'vi.stubGlobal("fetch"' in test_source
        assert "renders Product Catalog" in test_source


class TestAFieldWithoutAWiredWrite:
    def test_the_input_still_binds_declared_state(self) -> None:
        """A field block on a screen with no grounded write endpoint must not
        reference state that was never declared (the calculator keypad bug:
        the page rendered value={expression} with no useState behind it)."""
        wire = wireframes()
        checkout = wire.flows[0].screens[1]
        orphan = checkout.model_copy(update={"links": []})
        wire = wire.model_copy(
            update={
                "flows": [
                    wire.flows[0].model_copy(update={"screens": [wire.flows[0].screens[0], orphan]})
                ]
            }
        )
        contract = generate_rule_contract(1, graph(), wire, scope())
        files = web_app(contract, wire, scope())
        page = files.content_of("apps/web/src/pages/ShopCheckoutPage.tsx")
        for state in ("deliveryAddress", "paymentMethod"):
            if f"value={{{state}}}" in page:
                assert f"const [{state}, " in page, page


class TestTheDesignSystem:
    """Every app ships one, and every page is built from it.

    The rule generator wrote each page from raw utility strings, so every app came
    out as the same admin form: no loading, no empty state, and nothing to say
    whether a save had worked. The owner compared that with what Replit makes of
    the same prompt, and the difference was the design system.
    """

    def test_every_app_ships_the_components_and_the_tokens(self) -> None:
        files = web_app(_contract(), wireframes(), scope(), "Shopfront")
        paths = {generated.path for generated in files.files}
        for component in ("AppShell", "Button", "Card", "DataTable", "Field", "Notice"):
            assert f"apps/web/src/ui/{component}.tsx" in paths
        styles = files.content_of("apps/web/src/styles.css")
        assert "--color-accent-soft" in styles
        assert "@media (prefers-color-scheme: dark)" in styles

    def test_every_page_is_built_from_it(self) -> None:
        files = web_app(_contract(), wireframes(), scope())
        for generated in files.files:
            if "/pages/" in generated.path:
                assert 'from "../ui";' in generated.content, generated.path
                assert "<PageHeader title=" in generated.content, generated.path

    def test_the_shell_and_the_document_carry_the_app_s_name(self) -> None:
        files = web_app(_contract(), wireframes(), scope(), "Shopfront")
        assert 'name={"Shopfront"}' in files.content_of("apps/web/src/routes.tsx")
        assert "<title>Shopfront</title>" in files.content_of("apps/web/index.html")

    def test_a_list_says_when_it_is_loading_empty_or_failed(self) -> None:
        files = web_app(_contract(), wireframes(), scope())
        catalog = files.content_of("apps/web/src/pages/ShopCatalogPage.tsx")
        assert "loading={loading}" in catalog
        assert "<EmptyState" in catalog
        assert "This list could not be loaded" in catalog

    def test_a_save_moves_to_where_its_primary_link_goes(self) -> None:
        """The checkout's "Place order" is both the save and the way to the
        confirmation, and it was also offered a second time as a link."""
        files = web_app(_contract(), wireframes(), scope())
        checkout = files.content_of("apps/web/src/pages/ShopCheckoutPage.tsx")
        assert 'navigate(recordPath("/shop/done", created));' in checkout
        assert '<Link to="/shop/done"' not in checkout
        assert "busy={saving}" in checkout

    def test_a_numeric_field_is_sent_as_a_number(self) -> None:
        """A form's inputs hold text, and the contract says what it sends: Book
        Tracker's year was posted as "1965"."""
        from sdlc_contracts import SchemaField

        contract = _contract()
        for endpoint in contract.endpoints:
            if endpoint.id == "post-orders" and endpoint.request is not None:
                endpoint.request.fields.append(SchemaField(name="payment_method", type="number"))
        files = web_app(contract, wireframes(), scope())
        checkout = files.content_of("apps/web/src/pages/ShopCheckoutPage.tsx")
        assert "paymentMethod: Number(paymentMethod)" in checkout, checkout
        assert 'label="Payment method" type="number"' in checkout


class TestAScreenThatIsUsedRatherThanFilledIn:
    """Keys and a read-out, for a calculator, a counter or a timer. With only
    fields, rows and lists every screen came out as a form or a table."""

    @staticmethod
    def _keypad(with_field: bool):
        from sdlc_contracts import FlowLink, ScreenBlock

        wires = wireframes()
        screen = wires.flows[0].screens[2]  # shop/done: no field of its own
        screen.links = [FlowLink(id="back", label="Back", target_id="catalog", variant="text")]
        screen.blocks = [
            *([ScreenBlock(id="f1", kind="field", label="Expression")] if with_field else []),
            ScreenBlock(id="d1", kind="display", label="Result", value="0"),
            *(
                ScreenBlock(id=f"k{key}", kind="button", label=key, value=key)
                for key in ("7", "8", "+")
            ),
            ScreenBlock(id="kc", kind="button", label="C", value=""),
            ScreenBlock(id="kb", kind="button", label="Back", link_id="back"),
        ]
        return web_app(_contract(), wires, scope()).content_of(
            "apps/web/src/pages/ShopDonePage.tsx"
        )

    def test_keys_enter_their_values_and_an_empty_key_clears(self) -> None:
        page = self._keypad(with_field=False)

        assert 'const [entry, setEntry] = useState("");' in page
        assert 'onClick={() => setEntry(entry + "7")}' in page
        assert 'onClick={() => setEntry("")}' in page
        assert '<div className="grid grid-cols-4 gap-2">' in page

    def test_the_display_reads_out_the_entry(self) -> None:
        page = self._keypad(with_field=False)

        assert '{entry || "0"}' in page
        assert 'aria-live="polite"' in page

    def test_a_key_with_a_link_goes_there(self) -> None:
        page = self._keypad(with_field=False)

        assert '<Link to="/shop/catalog"' in page
        assert page.count(">Back</Link>") == 1, "the key's link was offered twice"

    def test_on_a_screen_with_a_field_the_keys_write_into_it(self) -> None:
        page = self._keypad(with_field=True)

        assert "const [entry," not in page
        assert 'onClick={() => setExpression(expression + "8")}' in page
        assert '{expression || "0"}' in page


def _corpus_app(stem: str):
    """A corpus design's contract and web app, generated by rule as a run would."""
    from c2.rules.scope import derive_scope

    from .corpus_io import CORPUS_DIR, load_design

    design = load_design(CORPUS_DIR / f"{stem}_design.json")
    scoped = derive_scope(design.sprint, design.wireframes)
    contract = generate_rule_contract(1, design.graph, design.wireframes, scoped)
    return contract, web_app(contract, design.wireframes, scoped, name=design.name)


#: A client call whose first argument is a written-in string: `client.getOrdersId("id")`.
WRITTEN_IN_ID = re.compile(r"\bclient\.\w+\(\s*[\"'`]")


class TestTheRecordAScreenIsAbout:
    """A screen that shows one record learns which one from its address.

    Every detail and edit screen called the client with the parameter's own
    name, `client.getOrdersId("id")`, so opening any record asked the API for
    `/orders/id` and showed a 404, while the build, the routes test and the
    agreement all passed.
    """

    def test_its_route_takes_the_record_and_the_page_reads_it(self) -> None:
        files = web_app(_contract(), wireframes(), scope())
        done = files.content_of("apps/web/src/pages/ShopDonePage.tsx")

        assert '<Route path="/shop/done/:id?"' in files.content_of("apps/web/src/routes.tsx")
        assert "const { id } = useParams();" in done
        assert "client.getOrdersId(id)" in done
        assert "}, [id]);" in done, "a new address must load the record it names"

    def test_no_generated_page_passes_a_written_in_id(self) -> None:
        apps = [web_app(_contract(), wireframes(), scope())] + [
            _corpus_app(stem)[1] for stem in ("shopflow", "cold_chain", "nexuspay", "calculator")
        ]
        written_in = [
            (generated.path, match.group(0))
            for files in apps
            for generated in files.files
            if "/pages/" in generated.path
            for match in WRITTEN_IN_ID.finditer(generated.content)
        ]
        assert written_in == []

    def test_with_no_record_in_its_address_it_asks_for_one(self) -> None:
        done = web_app(_contract(), wireframes(), scope()).content_of(
            "apps/web/src/pages/ShopDonePage.tsx"
        )

        assert "if (!id) {" in done, "with no id it asked the API for `undefined`"
        assert "Nothing is open here yet: open one to see it here." in done

    def test_a_save_opens_the_record_it_created(self) -> None:
        checkout = web_app(_contract(), wireframes(), scope()).content_of(
            "apps/web/src/pages/ShopCheckoutPage.tsx"
        )

        assert ".then((created) => {" in checkout
        assert 'navigate(recordPath("/shop/done", created));' in checkout

    def test_a_row_opens_the_screen_about_its_record(self) -> None:
        _, files = _corpus_app("shopflow")
        catalog = files.content_of("apps/web/src/pages/FlowCatalogCatalogPage.tsx")

        assert 'recordPath("/flow-catalog/product", item)' in catalog
        assert '<Link to="/flow-catalog/product"' not in catalog, (
            "the bare link only opens the product screen asking for a product"
        )

    def test_a_write_about_another_record_says_so_rather_than_guessing(self) -> None:
        """The product page shows a product; its form fills a cart it cannot name."""
        _, files = _corpus_app("shopflow")
        product = files.content_of("apps/web/src/pages/FlowCatalogProductPage.tsx")

        assert "client.postCartsIdFill(" not in product
        assert "does not say which record this would change, so nothing was sent" in product

    def test_the_routes_test_opens_a_record_by_its_address(self) -> None:
        routes_test = web_app(_contract(), wireframes(), scope()).content_of(
            "apps/web/src/__tests__/routes.test.tsx"
        )

        assert "opens Order Confirmed for the record its address names" in routes_test
        assert '"/shop/done/41"' in routes_test and 'asked("41")' in routes_test
        assert "afterEach(cleanup);" in routes_test


class TestTheWriteAScreenSubmits:
    """Chosen for the screen, not taken in contract order: PATCH sorts before POST."""

    @staticmethod
    def _contract(*endpoints):
        from sdlc_contracts import ApiContract, ApiEndpoint, EndpointSchema, EndpointTraces

        return ApiContract(
            version=1,
            entities=[],
            endpoints=[
                ApiEndpoint(
                    id=f"{method.lower()}-{path.strip('/').replace('/', '-').replace('{', '').replace('}', '')}",
                    method=method,
                    path=path,
                    summary=f"{method} {path}",
                    response=EndpointSchema(entity="Order"),
                    traces=EndpointTraces(screen_ids=["f/s"]),
                )
                for method, path in endpoints
            ],
        )

    def test_a_screen_about_one_record_writes_to_that_record(self) -> None:
        from c2.codegen.web_gen import _endpoints_for_screen

        contract = self._contract(
            ("GET", "/orders/{id}"), ("PATCH", "/orders/{id}"), ("POST", "/orders")
        )
        _, write = _endpoints_for_screen(contract, "f/s")

        assert write is not None and (write.method, write.path) == ("PATCH", "/orders/{id}")

    def test_any_other_screen_creates(self) -> None:
        from c2.codegen.web_gen import _endpoints_for_screen

        contract = self._contract(
            ("GET", "/orders"), ("PATCH", "/orders/{id}"), ("POST", "/orders")
        )
        _, write = _endpoints_for_screen(contract, "f/s")

        assert write is not None and (write.method, write.path) == ("POST", "/orders")


class TestAPageRewriteKeepsItsRecord:
    """The page writer may restyle a page, not forget which record it shows."""

    RULE = "const { id } = useParams();\nclient.getOrdersId(id);\n"

    def test_a_rewrite_that_stops_reading_the_address_is_refused(self) -> None:
        from c2.codegen.fill import lost_the_record

        problems = lost_the_record(self.RULE, "client.getOrdersId(order);\n")

        assert problems and "useParams" in problems[0]

    def test_a_rewrite_that_passes_a_written_in_id_is_refused(self) -> None:
        from c2.codegen.fill import lost_the_record

        problems = lost_the_record(self.RULE, 'useParams();\nclient.getOrdersId("id");\n')

        assert problems == [
            "client.getOrdersId is passed a written-in string; pass the id the page reads "
            "from its address instead"
        ]

    def test_a_rewrite_that_keeps_both_is_accepted(self) -> None:
        from c2.codegen.fill import lost_the_record

        assert lost_the_record(self.RULE, self.RULE + "<Card />\n") == []
