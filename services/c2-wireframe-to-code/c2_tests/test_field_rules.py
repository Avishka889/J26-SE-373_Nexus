"""Field rules: the bounds a design's constraints and a sprint's criteria state.

The contract carried them only as words, written into each handler as a
`// validation:` comment, and the generated app took any value: the Movie
Tracker accepted release years 1999 and 2027 where its criteria said 2000 to
2026. A rule reads the common ways a bound is said, attaches each to the field
named nearest before it in the same sentence, and leaves anything else as words.
"""

from c2.contract.field_rules import rules_in, with_field_rules
from sdlc_contracts import ApiContract, ApiEndpoint, EndpointSchema, EntityModel, SchemaField

MOVIE = [
    SchemaField(name="id", type="id"),
    SchemaField(name="title", type="string"),
    SchemaField(name="releaseYear", type="number"),
    SchemaField(name="rating", type="number", required=False),
    SchemaField(name="status", type="string", required=False),
]


def _bounds(text: str) -> dict[str, dict]:
    return {
        name: rule.model_dump(exclude_defaults=True, exclude={"source"})
        for name, rule in rules_in(text, MOVIE).items()
    }


class TestASentence:
    def test_a_range_is_read_for_the_field_it_names(self) -> None:
        assert _bounds("Release years run from 2000 to 2026.") == {
            "releaseYear": {"minimum": 2000, "maximum": 2026}
        }

    def test_a_criterion_naming_two_fields_bounds_the_one_before_the_range(self) -> None:
        criterion = (
            "Given a movie with a title and a release year outside 2000 to 2026. "
            "When the user saves it. Then the app refuses it."
        )
        assert _bounds(criterion) == {"releaseYear": {"minimum": 2000, "maximum": 2026}}

    def test_a_range_written_with_a_spaced_dash(self) -> None:
        # By code point, so this file stays plain: a hyphen, an en dash, an em dash.
        for dash in ("-", chr(0x2013), chr(0x2014)):
            assert _bounds(f"Release years run 2000 {dash} 2026") == {
                "releaseYear": {"minimum": 2000, "maximum": 2026}
            }

    def test_between_and_the_one_sided_bounds(self) -> None:
        assert _bounds("The rating must be between 1 and 5") == {
            "rating": {"minimum": 1, "maximum": 5}
        }
        assert _bounds("The rating is at least 1") == {"rating": {"minimum": 1}}
        assert _bounds("A rating of 5 or less") == {"rating": {"maximum": 5}}
        assert _bounds("The release year is no earlier than 1888") == {
            "releaseYear": {"minimum": 1888}
        }
        assert _bounds("A release year no later than 2026") == {"releaseYear": {"maximum": 2026}}
        assert _bounds("The release year must be 1888 or later") == {
            "releaseYear": {"minimum": 1888}
        }

    def test_characters_bound_a_strings_length(self) -> None:
        assert _bounds("The title is at most 100 characters") == {"title": {"max_length": 100}}
        assert _bounds("A title of 3 to 50 characters") == {
            "title": {"min_length": 3, "max_length": 50}
        }

    def test_a_choice_names_its_values(self) -> None:
        assert _bounds("The status is one of watched, planned or dropped.") == {
            "status": {"one_of": ["watched", "planned", "dropped"]}
        }

    def test_two_bounds_in_one_sentence_go_to_their_own_fields(self) -> None:
        assert _bounds("The title is at most 100 characters and the rating is between 1 and 5") == {
            "title": {"max_length": 100},
            "rating": {"minimum": 1, "maximum": 5},
        }


class TestWhatItLeavesAsWords:
    def test_a_number_bound_on_a_string_without_characters(self) -> None:
        assert _bounds("The title must be between 1 and 5") == {}

    def test_a_range_that_runs_backwards(self) -> None:
        assert _bounds("Release years run from 2026 to 2000") == {}

    def test_a_date_is_not_a_range(self) -> None:
        assert _bounds("The release year was entered on 2026-01-01") == {}

    def test_a_sentence_that_names_no_field(self) -> None:
        assert _bounds("Ratings run from 1 to 5") == {"rating": {"minimum": 1, "maximum": 5}}
        assert _bounds("Scores run from 1 to 5") == {}

    def test_the_id_is_never_bounded(self) -> None:
        assert _bounds("The id is at least 1") == {}


def _contract() -> ApiContract:
    return ApiContract(
        version=1,
        entities=[EntityModel(name="Movie", fields=MOVIE, traces=["R-1"])],
        endpoints=[
            ApiEndpoint(
                id="post-movies",
                method="POST",
                path="/movies",
                request=EndpointSchema(entity="Movie", fields=[f for f in MOVIE if f.name != "id"]),
            ),
            ApiEndpoint(
                id="patch-movies-id",
                method="PATCH",
                path="/movies/{id}",
                request=EndpointSchema(entity="Movie"),
            ),
        ],
    )


class TestTheContract:
    TEXTS = (
        "Release years run from 2000 to 2026.",
        "The release year is at most 2025",
        "The status is one of watched or planned",
    )

    def test_the_entity_and_the_requests_that_spell_its_fields_carry_the_bounds(self) -> None:
        bounded = with_field_rules(_contract(), self.TEXTS)

        [movie] = bounded.entities
        year = next(field for field in movie.fields if field.name == "releaseYear")
        # Two texts, one field: the tighter bound holds, and both are kept as words.
        assert (year.minimum, year.maximum) == (2000, 2025)
        assert year.rules == list(self.TEXTS[:2])
        status = next(field for field in movie.fields if field.name == "status")
        assert status.one_of == ["watched", "planned"]
        request = bounded.endpoints[0].request
        assert request is not None
        assert next(f for f in request.fields if f.name == "releaseYear").maximum == 2025

    def test_reading_twice_changes_nothing(self) -> None:
        once = with_field_rules(_contract(), self.TEXTS)
        assert with_field_rules(once, self.TEXTS) == once

    def test_no_texts_leave_the_contract_as_it_was(self) -> None:
        assert with_field_rules(_contract(), ()) == _contract()
