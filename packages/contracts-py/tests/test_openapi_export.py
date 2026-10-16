"""The api-contract as OpenAPI, checked by something that reads the spec.

The document is validated with `openapi-spec-validator` rather than by reading
it, because "this is OpenAPI" is a claim the proposal makes and my own opinion
of the shape is not evidence for it. The rest of these assert the two decisions
the translation makes that a generic converter would get wrong: the status
codes describe what the generated server actually answers, and the traceability
survives into the document.
"""

import pytest
from openapi_spec_validator import validate
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError
from sdlc_contracts import (
    ApiContract,
    ApiEndpoint,
    EndpointSchema,
    EndpointTraces,
    EntityModel,
    SchemaField,
)
from sdlc_contracts.openapi import path_parameters, to_openapi


def _contract() -> ApiContract:
    """One of each shape the translation has to handle."""
    return ApiContract(
        version=2,
        entities=[
            EntityModel(
                name="Order",
                fields=[
                    SchemaField(name="id", type="id"),
                    SchemaField(name="total", type="number"),
                    SchemaField(name="placedAt", type="date"),
                    SchemaField(name="tags", type="array", item_ref="", required=False),
                ],
                traces=["R-1"],
            ),
        ],
        endpoints=[
            ApiEndpoint(
                id="get-orders",
                method="GET",
                path="/orders",
                summary="Every order",
                response=EndpointSchema(entity="Order"),
                traces=EndpointTraces(
                    screen_ids=["shop/list"], story_ids=["US-1"], requirement_ids=["R-1"]
                ),
            ),
            ApiEndpoint(
                id="post-orders",
                method="POST",
                path="/orders",
                request=EndpointSchema(
                    fields=[SchemaField(name="total", type="number")],
                ),
                response=EndpointSchema(entity="Order"),
                validation=["total must be greater than zero"],
                auth_actors=["Customer"],
            ),
            ApiEndpoint(
                id="get-orders-id",
                method="GET",
                path="/orders/{id}",
                response=EndpointSchema(entity="Order"),
            ),
            ApiEndpoint(
                id="delete-orders-id",
                method="DELETE",
                path="/orders/{id}",
            ),
            # The shape that broke C2: more than one path parameter.
            ApiEndpoint(
                id="patch-routes-id-stops-stop-id",
                method="PATCH",
                path="/routes/{id}/stops/{stop_id}",
                request=EndpointSchema(fields=[SchemaField(name="position", type="number")]),
            ),
        ],
    )


class TestItIsActuallyOpenApi:
    def test_the_document_validates_against_the_specification(self) -> None:
        validate(to_openapi(_contract(), title="ShopFlow"))

    def test_an_empty_contract_still_produces_a_valid_document(self) -> None:
        """A project whose contract has no endpoints yet is a real state, and
        the export should answer with an empty document rather than a broken
        one."""
        validate(to_openapi(ApiContract(version=1), title="Empty"))

    def test_the_validator_would_notice_a_broken_document(self) -> None:
        """Teeth for the two tests above: the validator is doing work.

        `info.title` rather than an operation's `responses`, which was the
        first thing tried here and does not work: `responses` became optional
        in OpenAPI 3.1, so deleting one produces a document that is still
        valid, and a teeth proof that passes for the wrong reason is worse than
        none.
        """
        document = to_openapi(_contract(), title="ShopFlow")
        del document["info"]["title"]
        with pytest.raises(OpenAPIValidationError):
            validate(document)


class TestTheStatusCodesDescribeTheRealServer:
    """Taken from the code generator, not from a style guide.

    An OpenAPI that says 200 where the server says 201 produces API tests that
    fail against a correct implementation, which is worse than no OpenAPI.
    """

    def test_a_create_answers_201_and_a_delete_answers_204(self) -> None:
        paths = to_openapi(_contract(), title="t")["paths"]
        assert "201" in paths["/orders"]["post"]["responses"]
        assert "204" in paths["/orders/{id}"]["delete"]["responses"]
        assert "200" in paths["/orders"]["get"]["responses"]

    def test_a_parameterised_path_can_answer_404(self) -> None:
        paths = to_openapi(_contract(), title="t")["paths"]
        assert "404" in paths["/orders/{id}"]["get"]["responses"]
        assert "404" not in paths["/orders"]["get"]["responses"]

    def test_declared_auth_produces_a_401_and_a_security_requirement(self) -> None:
        operation = to_openapi(_contract(), title="t")["paths"]["/orders"]["post"]
        assert "401" in operation["responses"]
        assert operation["security"] == [{"bearerAuth": []}]

    def test_no_declared_auth_means_no_401_invented(self) -> None:
        operation = to_openapi(_contract(), title="t")["paths"]["/orders"]["get"]
        assert "401" not in operation["responses"]
        assert "security" not in operation

    def test_a_body_or_a_rule_produces_a_400(self) -> None:
        paths = to_openapi(_contract(), title="t")["paths"]
        assert "400" in paths["/orders"]["post"]["responses"]
        assert "400" not in paths["/orders"]["get"]["responses"]


class TestTheShapesSurvive:
    def test_a_collection_get_returns_an_array_and_a_single_get_does_not(self) -> None:
        paths = to_openapi(_contract(), title="t")["paths"]
        collection = paths["/orders"]["get"]["responses"]["200"]["content"]["application/json"]
        single = paths["/orders/{id}"]["get"]["responses"]["200"]["content"]["application/json"]
        assert collection["schema"]["type"] == "array"
        assert collection["schema"]["items"] == {"$ref": "#/components/schemas/Order"}
        assert single["schema"] == {"$ref": "#/components/schemas/Order"}

    def test_every_path_parameter_becomes_a_parameter_not_just_the_first(self) -> None:
        """The single parameter assumption is what broke C2's generated tests."""
        assert path_parameters("/routes/{id}/stops/{stop_id}") == ["id", "stop_id"]
        operation = to_openapi(_contract(), title="t")["paths"]["/routes/{id}/stops/{stop_id}"][
            "patch"
        ]
        assert [p["name"] for p in operation["parameters"]] == ["id", "stop_id"]

    def test_explicit_request_fields_win_over_the_entity_reference(self) -> None:
        """A request that omits the id is a different shape from the entity."""
        body = to_openapi(_contract(), title="t")["paths"]["/orders"]["post"]["requestBody"]
        schema = body["content"]["application/json"]["schema"]
        assert schema["properties"] == {"total": {"type": "number"}}
        assert "$ref" not in schema

    def test_the_contract_types_map_onto_json_schema(self) -> None:
        schema = to_openapi(_contract(), title="t")["components"]["schemas"]["Order"]
        assert schema["properties"]["total"] == {"type": "number"}
        assert schema["properties"]["placedAt"] == {"type": "string", "format": "date-time"}
        assert schema["properties"]["id"] == {"type": "string"}
        assert schema["properties"]["tags"]["type"] == "array"
        # Optional fields are not required, which is what `required` means.
        assert "tags" not in schema["required"]


class TestTraceabilitySurvives:
    """Dropping the traces here would mean recovering them later by matching
    paths, which is guesswork. A test generated from this document has to be
    able to name the story it came from."""

    def test_an_operation_carries_the_traces_of_its_endpoint(self) -> None:
        operation = to_openapi(_contract(), title="t")["paths"]["/orders"]["get"]
        assert operation["x-traces"]["storyIds"] == ["US-1"]
        assert operation["x-traces"]["requirementIds"] == ["R-1"]
        assert operation["x-traces"]["screenIds"] == ["shop/list"]

    def test_an_endpoint_with_no_traces_carries_no_empty_block(self) -> None:
        """An empty traces block reads as "traced to nothing" rather than as
        "not traced", and the difference is a finding."""
        operation = to_openapi(_contract(), title="t")["paths"]["/orders/{id}"]["delete"]
        assert "x-traces" not in operation

    def test_the_declared_invariants_travel_as_written(self) -> None:
        """The third tier of the oracle: status class, schema, then these."""
        operation = to_openapi(_contract(), title="t")["paths"]["/orders"]["post"]
        assert operation["x-validation"] == ["total must be greater than zero"]

    def test_the_operation_id_is_the_contract_id(self) -> None:
        """So a test, a finding and an operation all name the endpoint alike."""
        paths = to_openapi(_contract(), title="t")["paths"]
        assert paths["/orders"]["post"]["operationId"] == "post-orders"


class TestItIsDeterministic:
    def test_the_same_contract_produces_the_same_document(self) -> None:
        """One of the self healing classifier's inputs is a diff between two
        versions of this document, and a diff against a reordered document is
        noise."""
        first = to_openapi(_contract(), title="t")
        second = to_openapi(_contract(), title="t")
        assert first == second
        assert list(first["paths"]) == list(second["paths"])


class TestTheBoundsAreJsonSchema:
    """A field's bounds reach the document as the standard keywords, so the tests
    generated from it, and anything else that reads OpenAPI, can see them."""

    def test_ranges_lengths_and_choices_become_keywords(self) -> None:
        contract = ApiContract(
            version=1,
            entities=[
                EntityModel(
                    name="Movie",
                    fields=[
                        SchemaField(
                            name="releaseYear",
                            type="number",
                            minimum=2000,
                            maximum=2026,
                            rules=["release years run from 2000 to 2026"],
                        ),
                        SchemaField(name="title", type="string", min_length=1, max_length=100),
                        SchemaField(name="status", type="string", one_of=["watched", "planned"]),
                    ],
                    traces=["R-1"],
                ),
            ],
        )

        document = to_openapi(contract, title="Movie Tracker")

        validate(document)
        properties = document["components"]["schemas"]["Movie"]["properties"]
        assert properties["releaseYear"] == {
            "type": "number",
            "minimum": 2000,
            "maximum": 2026,
            "description": "release years run from 2000 to 2026",
        }
        assert properties["title"] == {"type": "string", "minLength": 1, "maxLength": 100}
        assert properties["status"] == {"type": "string", "enum": ["watched", "planned"]}
