"""The deterministic arm: screens and actions in, a traced contract out."""

from c2.contract.rule_arm import generate_rule_contract
from c2.contract.rules import ContractContext, validate_contract
from c2.contract.vocab import singular, verb_slug
from c2.rules.scope import derive_scope

from .corpus_io import CORPUS_DIR, load_design
from .design_fixture import graph, scope, wireframes


def _contract():
    return generate_rule_contract(1, graph(), wireframes(), scope())


def _by_key(contract):
    return {f"{e.method} {e.path}": e for e in contract.endpoints}


class TestWhatTheRulesInfer:
    def test_entities_become_models_with_typed_fields(self) -> None:
        contract = _contract()
        order = next(entity for entity in contract.entities if entity.name == "Order")
        fields = {field.name: field.type for field in order.fields}
        assert fields["id"] == "id"
        assert fields["total"] == "number"
        assert fields["placedAt"] == "date"
        assert fields["status"] == "string"

    def test_an_action_edge_becomes_a_write_with_auth_and_schema(self) -> None:
        endpoints = _by_key(_contract())
        placed = endpoints["POST /orders"]
        assert placed.auth_actors == ["Shopper"]
        assert placed.request is not None and placed.request.entity == "Order"
        assert "total" in [field.name for field in placed.request.fields]
        assert "id" not in [field.name for field in placed.request.fields]
        assert placed.origin == "rule"

    def test_a_cancel_verb_becomes_a_delete_on_one_item(self) -> None:
        endpoints = _by_key(_contract())
        assert "DELETE /orders/{id}" in endpoints

    def test_a_list_block_becomes_a_collection_read_traced_to_its_screen(self) -> None:
        endpoints = _by_key(_contract())
        listing = endpoints["GET /products"]
        assert "shop/catalog" in listing.traces.screen_ids
        assert "b1" in listing.traces.action_ids

    def test_a_summary_screen_becomes_a_detail_read(self) -> None:
        endpoints = _by_key(_contract())
        assert "GET /orders/{id}" in endpoints

    def test_the_form_grounds_the_write_in_its_screen_and_link(self) -> None:
        endpoints = _by_key(_contract())
        placed = endpoints["POST /orders"]
        assert "shop/checkout" in placed.traces.screen_ids
        assert "l2" in placed.traces.action_ids

    def test_a_constraint_becomes_validation_on_the_writes(self) -> None:
        endpoints = _by_key(_contract())
        assert any("stock" in rule for rule in endpoints["POST /orders"].validation)
        # And not on the reads: a read cannot violate a write constraint.
        assert endpoints["GET /orders/{id}"].validation == []

    def test_stories_attach_through_requirements_and_screens(self) -> None:
        endpoints = _by_key(_contract())
        assert endpoints["POST /orders"].traces.story_ids == ["US-1"]

    def test_endpoint_ids_are_deterministic_slugs(self) -> None:
        contract = _contract()
        again = generate_rule_contract(1, graph(), wireframes(), scope())
        assert [e.id for e in contract.endpoints] == [e.id for e in again.endpoints]
        assert _by_key(contract)["POST /orders"].id == "post-orders"

    def test_grounded_endpoints_outscore_ungrounded_ones(self) -> None:
        endpoints = _by_key(_contract())
        placed = endpoints["POST /orders"]
        assert placed.confidence <= 98
        assert placed.confidence >= 80  # screen + story + schema + verb grounded


class TestTheArmAgreesWithItsOwnCatalogue:
    def test_the_rule_arm_output_is_clean(self) -> None:
        """The baseline must satisfy its own rules, or the catalogue and the
        generator disagree about what a contract is and every run repairs."""
        contract = _contract()
        context = ContractContext(graph=graph(), wireframes=wireframes(), scope=scope())
        result = validate_contract(contract, context)
        assert result.errors == (), [f.reason for f in result.errors]


class TestTheVocabulary:
    def test_singular_strips_only_real_es_plurals(self) -> None:
        assert singular("browses") == "browse"
        assert singular("houses") == "house"
        assert singular("statuses") == "status"
        assert singular("classes") == "class"
        assert singular("boxes") == "box"
        assert singular("stories") == "story"
        assert singular("orders") == "order"
        assert singular("process") == "process"

    def test_a_verb_slug_keeps_the_verbs_letters(self) -> None:
        assert verb_slug("browses") == "browse"
        assert verb_slug("Submits For Review") == "submit-for-review"


class TestVerbClassification:
    def test_a_third_person_read_verb_merges_into_the_collection_read(self) -> None:
        """ "browses" is a read: it must land on GET /products, never invent a
        subaction (the bug that shipped "browsese")."""
        contract = _contract()
        endpoints = _by_key(contract)
        assert not any("browse" in endpoint.path for endpoint in contract.endpoints)
        listing = endpoints["GET /products"]
        assert "Shopper" in listing.auth_actors
        assert "R-3" in listing.traces.requirement_ids

    def test_an_unknown_verb_becomes_a_post_subaction_named_after_it(self) -> None:
        design = graph()
        edges = [
            edge.model_copy(update={"verb": "appraises"}) if edge.id == "ed3" else edge
            for edge in design.edges
        ]
        design = design.model_copy(update={"edges": edges})
        contract = generate_rule_contract(1, design, wireframes(), scope())
        sub = next(e for e in contract.endpoints if e.method == "POST" and "{id}" in e.path)
        assert sub.path == "/products/{id}/appraise"
        assert sub.id == "post-products-id-appraise"


class TestLinkOnlyGrounding:
    def test_a_screen_naming_the_entity_only_in_a_link_grounds_the_write(self) -> None:
        """The calculator keypad shape: the form screen's blocks say
        "Expression", and only the link ("Record calculation") names the
        entity. The write must still ground there."""
        wire = wireframes()
        flow = wire.flows[0]
        checkout = flow.screens[1].model_copy(
            update={
                "blocks": [
                    block.model_copy(update={"label": "Delivery details"})
                    for block in flow.screens[1].blocks
                ],
                "links": [
                    link.model_copy(update={"label": "Place order"})
                    for link in flow.screens[1].links
                ],
                "name": "Checkout",
            }
        )
        wire = wire.model_copy(
            update={
                "flows": [
                    flow.model_copy(
                        update={"screens": [flow.screens[0], checkout, flow.screens[2]]}
                    )
                ]
            }
        )
        contract = generate_rule_contract(1, graph(), wire, scope())
        placed = _by_key(contract)["POST /orders"]
        assert "shop/checkout" in placed.traces.screen_ids


class TestTheBuildGrowsASprintAtATime:
    """C2-4: an action belongs to the sprint whose stories it traces.

    On cold chain's sprint 1, reassigning a stop on a route traces only R-18,
    which only the backlog story US-13 carries, yet it was built, because the
    route is an entity sprint 1 already shows; planning US-13 into sprint 2
    then added nothing. The other way round, reconstructing a consignment's
    history traces R-6, which the in-scope US-5 carries, yet nothing was built
    for it, because no sprint 1 screen names the audit record it acts on.
    """

    @staticmethod
    def _cold_chain():
        design = load_design(CORPUS_DIR / "cold_chain_design.json")
        return design, derive_scope(design.sprint, design.wireframes)

    @staticmethod
    def _contract(design, scope):
        return generate_rule_contract(1, design.graph, design.wireframes, scope)

    @classmethod
    def _keys(cls, design, scope) -> set[str]:
        return {f"{e.method} {e.path}" for e in cls._contract(design, scope).endpoints}

    @staticmethod
    def _with_in_scope(scope, story_id: str):
        return scope.model_copy(
            update={
                "stories": [
                    story.model_copy(update={"in_scope": True}) if story.id == story_id else story
                    for story in scope.stories
                ]
            }
        )

    def test_a_backlog_story_s_action_is_not_built_in_sprint_one(self) -> None:
        design, scope = self._cold_chain()
        assert "POST /routes/{id}/reassign-stop-on" not in self._keys(design, scope)

    def test_planning_its_story_into_the_next_sprint_builds_it(self) -> None:
        design, scope = self._cold_chain()
        added = self._keys(design, self._with_in_scope(scope, "US-13")) - self._keys(design, scope)
        assert added == {"POST /routes/{id}/reassign-stop-on"}

    def test_an_in_scope_story_s_action_is_built_on_an_entity_no_screen_names(self) -> None:
        design, scope = self._cold_chain()
        contract = self._contract(design, scope)
        assert "AuditRecord" in [entity.name for entity in contract.entities]
        reconstruct = next(e for e in contract.endpoints if "reconstruct" in e.path)
        assert reconstruct.traces.story_ids == ["US-5"]

    def test_a_backlog_action_on_an_entity_waits_for_its_own_story(self) -> None:
        design, scope = self._cold_chain()
        first = self._keys(design, scope)
        assert not any("export" in key for key in first)
        added = self._keys(design, self._with_in_scope(scope, "US-15")) - first
        assert any("export" in key for key in added), added

    def test_a_write_is_credited_with_its_action_s_requirements_not_the_entity_s(self) -> None:
        design, scope = self._cold_chain()
        endpoints = {f"{e.method} {e.path}": e for e in self._contract(design, scope).endpoints}
        assert endpoints["POST /routes/{id}/follow"].traces.requirement_ids == ["R-4"]
