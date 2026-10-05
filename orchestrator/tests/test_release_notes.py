"""What a release ships, as its notes say it (review item C4-7)."""

from orchestrator.deploy.notes import release_notes


def test_the_notes_say_what_ships_and_what_it_replaces() -> None:
    notes = release_notes(
        deploy_version=3,
        code_version=2,
        test_version=4,
        candidate_hash="a" * 64,
        included=2,
        replaces=2,
    )

    assert notes.splitlines() == [
        "Deploy version 3.",
        "Code version 2, with the tests approved at test version 4. Candidate aaaaaaaaaaaa.",
        "2 dependency updates included.",
        "Replaces deploy version 2.",
    ]


def test_a_first_release_with_no_updates_and_no_test_version_on_record() -> None:
    notes = release_notes(
        deploy_version=1,
        code_version=1,
        test_version=0,
        candidate_hash="b" * 64,
        included=0,
        replaces=None,
    )

    assert notes.splitlines() == [
        "Deploy version 1.",
        "Code version 1. Candidate bbbbbbbbbbbb.",
        "No dependency update included.",
        "The first release.",
    ]
