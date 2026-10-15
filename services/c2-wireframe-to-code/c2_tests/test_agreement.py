"""Static agreement: clean on the generated monorepo, loud on every break.

The clean case is the load bearing one: the generators and the checker must
agree about what agreement is, or every honest run reports defects it does
not have. Every break is then planted one at a time.
"""

from c2.codegen.monorepo import generate_monorepo
from c2.contract.rule_arm import generate_rule_contract
from c2.validate.agreement import check_agreement

from .design_fixture import graph, scope, wireframes


def _contract():
    return generate_rule_contract(1, graph(), wireframes(), scope())


def _sources() -> dict[str, str]:
    files = generate_monorepo(
        "ShopFlow", _contract(), wireframes(), scope(), design_version=1, arm="rule"
    )
    return {generated.path: generated.content for generated in files.files}


class TestTheCleanCase:
    def test_the_generated_monorepo_agrees_with_its_own_contract(self) -> None:
        agreement = check_agreement(_contract(), _sources())
        assert [f.reason for f in agreement.errors] == []
        assert agreement.counts.agreement_rate == 1.0
        assert agreement.counts.endpoints_missing == []
        assert agreement.counts.orphan_routes == []
        assert agreement.counts.foreign_calls == []
        assert agreement.counts.schema_mismatches == 0

    def test_the_counts_account_for_every_endpoint(self) -> None:
        contract = _contract()
        agreement = check_agreement(contract, _sources())
        assert agreement.counts.endpoints_total == len(contract.endpoints)
        assert agreement.counts.endpoints_implemented == len(contract.endpoints)
        # Reads with a screen are called; writes are called by their forms.
        assert agreement.counts.endpoints_called >= 2


class TestEveryBreakIsLoud:
    def test_a_missing_route_is_an_error_with_the_endpoint_named(self) -> None:
        sources = _sources()
        routes = sources["apps/api/src/routes/orders.ts"]
        sources["apps/api/src/routes/orders.ts"] = "\n".join(
            line for line in routes.splitlines() if 'router.post("/"' not in line
        )
        agreement = check_agreement(_contract(), sources)
        missing = [f for f in agreement.errors if f.rule_id == "endpoint-not-implemented"]
        assert len(missing) == 1 and missing[0].subject == "post-orders"
        assert agreement.counts.agreement_rate < 1.0

    def test_an_orphan_route_is_an_error_with_its_location(self) -> None:
        sources = _sources()
        sources["apps/api/src/routes/orders.ts"] += (
            "\nexport function extraRouter(repository: OrderRepository): Router {\n"
            "  const router = Router();\n"
            '  router.get("/secret", async (req, res) => { res.json([]); });\n'
            "  return router;\n}\n"
        )
        sources["apps/api/src/app.ts"] += '\napp.use("/orders", extraRouter(ordersRepository));\n'
        agreement = check_agreement(_contract(), sources)
        orphans = [f for f in agreement.errors if f.rule_id == "orphan-route"]
        assert len(orphans) == 1
        assert orphans[0].location is not None
        assert orphans[0].location.path == "apps/api/src/routes/orders.ts"
        assert orphans[0].location.line is not None and orphans[0].location.line > 1

    def test_a_foreign_fetch_in_a_page_is_an_error(self) -> None:
        sources = _sources()
        sources["apps/web/src/pages/ShopCatalogPage.tsx"] += '\nvoid fetch("/api/extra");\n'
        agreement = check_agreement(_contract(), sources)
        assert any(f.rule_id == "foreign-call" for f in agreement.errors)
        assert "apps/web/src/pages/ShopCatalogPage.tsx" in agreement.counts.foreign_calls

    def test_an_unknown_client_method_is_an_error(self) -> None:
        sources = _sources()
        sources["apps/web/src/pages/ShopCatalogPage.tsx"] += "\nvoid client.launchMissiles();\n"
        agreement = check_agreement(_contract(), sources)
        unknown = [f for f in agreement.errors if f.rule_id == "unknown-client-method"]
        assert len(unknown) == 1 and unknown[0].subject == "launchMissiles"

    def test_a_missing_entity_model_is_a_schema_mismatch(self) -> None:
        sources = _sources()
        del sources["apps/api/src/models/Order.ts"]
        agreement = check_agreement(_contract(), sources)
        assert agreement.counts.schema_mismatches == 1
        assert any(f.rule_id == "entity-model-missing" for f in agreement.errors)

    def test_an_uncalled_endpoint_is_a_warning_never_an_error(self) -> None:
        sources = _sources()
        # DELETE has no form on any screen in this fixture, so it is unused.
        agreement = check_agreement(_contract(), sources)
        unused = [f for f in agreement.findings if f.rule_id == "endpoint-not-called"]
        assert unused, "the fixture should have at least one uncalled endpoint"
        assert all(f.severity == "warning" for f in unused)


class TestAnActionThatChangesNothing:
    """A domain action (`POST /orders/{id}/settle`) is served, and changes nothing.

    The design names the verb and not what it does, so the generated handler
    answers with the record unchanged. Counted as implemented, it read as done:
    shopflow's checkout "settles the order" and nothing settled.
    """

    def test_each_one_is_reported_where_its_handler_is(self) -> None:
        from c2.codegen.monorepo import generate_monorepo as monorepo
        from c2.rules.scope import derive_scope

        from .corpus_io import CORPUS_DIR, load_design

        design = load_design(CORPUS_DIR / "shopflow_design.json")
        scoped = derive_scope(design.sprint, design.wireframes)
        contract = generate_rule_contract(1, design.graph, design.wireframes, scoped)
        files = monorepo(
            "ShopFlow", contract, design.wireframes, scoped, design_version=1, arm="rule"
        )
        sources = {generated.path: generated.content for generated in files.files}

        agreement = check_agreement(contract, sources)
        reported = sorted(
            finding.subject
            for finding in agreement.findings
            if finding.rule_id == "action-does-nothing"
        )

        actions = sorted(
            endpoint.id
            for endpoint in contract.endpoints
            if endpoint.method == "POST" and endpoint.path.count("/") == 3
        )
        assert actions and reported == actions
        finding = next(f for f in agreement.findings if f.rule_id == "action-does-nothing")
        assert finding.severity == "warning"
        assert finding.location is not None and finding.location.path.startswith(
            "apps/api/src/routes/"
        )

    def test_a_create_or_an_update_is_not_reported(self) -> None:
        agreement = check_agreement(_contract(), _sources())

        assert [f for f in agreement.findings if f.rule_id == "action-does-nothing"] == []


class TestAFormNothingSaves:
    """A screen with fields and no write gets a form with no submit, and it
    counted as implemented like any other screen (review item C2-3)."""

    def test_it_is_reported_on_the_page_that_shows_it(self) -> None:
        contract = _contract()
        without = contract.model_copy(
            update={"endpoints": [e for e in contract.endpoints if e.id != "post-orders"]}
        )
        files = generate_monorepo(
            "ShopFlow", without, wireframes(), scope(), design_version=1, arm="rule"
        )
        sources = {generated.path: generated.content for generated in files.files}

        agreement = check_agreement(without, sources)

        [unwired] = [f for f in agreement.findings if f.rule_id == "form-not-wired"]
        assert unwired.severity == "warning"
        assert unwired.location is not None
        assert unwired.location.path == "apps/web/src/pages/ShopCheckoutPage.tsx"
        assert unwired.location.line is not None and unwired.location.line > 1
        assert "nothing saves" in unwired.reason

    def test_a_read_on_the_page_does_not_save_the_form(self) -> None:
        from c2.codegen.naming import client_method_name

        contract = _contract()
        without = contract.model_copy(
            update={"endpoints": [e for e in contract.endpoints if e.id != "post-orders"]}
        )
        files = generate_monorepo(
            "ShopFlow", without, wireframes(), scope(), design_version=1, arm="rule"
        )
        sources = {generated.path: generated.content for generated in files.files}
        page = "apps/web/src/pages/ShopCheckoutPage.tsx"
        sources[page] += f"\nvoid client.{client_method_name('get-products')}();\n"

        agreement = check_agreement(without, sources)

        assert [f.subject for f in agreement.findings if f.rule_id == "form-not-wired"] == [page]

    def test_a_form_that_calls_its_write_is_not_reported(self) -> None:
        agreement = check_agreement(_contract(), _sources())
        assert [f for f in agreement.findings if f.rule_id == "form-not-wired"] == []
