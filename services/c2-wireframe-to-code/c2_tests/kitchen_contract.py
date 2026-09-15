"""A contract using every shape the contract type permits.

Not only the shapes the rule arm happens to emit, which is the whole point.
Every generator in this component was written against the rule arm's output:
one path parameter, always the entity's id, and four of the seven field types.
The LLM arm emits the rest, and each one it emitted broke a generator that had
never seen it.

So this contract carries all of them on purpose: every `FieldType`, a literal
sub path beside a parameterised one, a nested route with two parameters, a
request-and-response pair, a body-less write. What it is for is the sandbox
test beside it, which generates a monorepo from this and runs the real
toolchain over it. A shape that cannot compile is a generator defect, and it
should be found here rather than by an arm producing it mid ablation.
"""

from sdlc_contracts import (
    ApiContract,
    ApiEndpoint,
    EndpointSchema,
    EndpointTraces,
    EntityModel,
    SchemaField,
)


def kitchen_sink_contract(version: int = 1) -> ApiContract:
    route = EntityModel(
        name="Route",
        fields=[
            SchemaField(name="id", type="id"),
            SchemaField(name="label", type="string"),
            SchemaField(name="distance", type="number"),
            SchemaField(name="active", type="boolean"),
            SchemaField(name="startsAt", type="date"),
            SchemaField(name="stops", type="array"),
            SchemaField(name="meta", type="object"),
        ],
        traces=["R-1"],
    )
    stop = EntityModel(
        name="Stop",
        fields=[SchemaField(name="id", type="id"), SchemaField(name="name", type="string")],
        traces=["R-2"],
    )
    t = EndpointTraces(
        screen_ids=["flow/one"], action_ids=["l1"], story_ids=["US-1"], requirement_ids=["R-1"]
    )
    fields = [f for f in route.fields if f.name != "id"]
    return ApiContract(
        version=version,
        entities=[route, stop],
        endpoints=[
            ApiEndpoint(
                id="get-routes",
                method="GET",
                path="/routes",
                summary="List routes",
                response=EndpointSchema(entity="Route", fields=route.fields),
                traces=t,
                confidence=90,
            ),
            ApiEndpoint(
                id="get-routes-today",
                method="GET",
                path="/routes/today",
                summary="Today's routes",
                response=EndpointSchema(entity="Route", fields=route.fields),
                traces=t,
                confidence=90,
            ),
            ApiEndpoint(
                id="get-routes-current-stops",
                method="GET",
                path="/routes/current/stops",
                summary="Stops on the current route",
                response=EndpointSchema(entity="Stop", fields=stop.fields),
                traces=t,
                confidence=90,
            ),
            ApiEndpoint(
                id="get-routes-id",
                method="GET",
                path="/routes/{id}",
                summary="Read one route",
                response=EndpointSchema(entity="Route", fields=route.fields),
                traces=t,
                confidence=90,
            ),
            ApiEndpoint(
                id="get-routes-id-stops",
                method="GET",
                path="/routes/{id}/stops",
                summary="Stops on a route",
                response=EndpointSchema(entity="Stop", fields=stop.fields),
                traces=t,
                confidence=90,
            ),
            ApiEndpoint(
                id="patch-routes-id-stops-stop-id",
                method="PATCH",
                path="/routes/{id}/stops/{stop_id}",
                summary="Move a stop",
                auth_actors=["Planner"],
                request=EndpointSchema(
                    entity="Stop", fields=[f for f in stop.fields if f.name != "id"]
                ),
                response=EndpointSchema(entity="Stop", fields=stop.fields),
                traces=t,
                confidence=90,
            ),
            ApiEndpoint(
                id="post-routes",
                method="POST",
                path="/routes",
                summary="Create a route",
                request=EndpointSchema(entity="Route", fields=fields),
                response=EndpointSchema(entity="Route", fields=route.fields),
                traces=t,
                confidence=90,
            ),
            ApiEndpoint(
                id="delete-routes-id",
                method="DELETE",
                path="/routes/{id}",
                summary="Delete a route",
                response=EndpointSchema(entity="Route", fields=route.fields),
                traces=t,
                confidence=90,
            ),
        ],
    )
