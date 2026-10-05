"""What a release ships, in a few lines a person can read.

A release had a deploy version on the platform and nothing in the repository:
no tag at its commit and no notes, so nobody reading the repository could tell
which commit a deploy version was, or what went out with it (review item C4-7).
These are the notes a verified release is tagged with, and what Activity keeps.
"""


def release_notes(
    *,
    deploy_version: int,
    code_version: int,
    test_version: int,
    candidate_hash: str,
    included: int,
    replaces: int | None,
) -> str:
    """Counted from what the release recorded, never described."""
    tests = f", with the tests approved at test version {test_version}" if test_version else ""
    updates = (
        f"{included} dependency update{'s' if included != 1 else ''} included."
        if included
        else "No dependency update included."
    )
    return "\n".join(
        (
            f"Deploy version {deploy_version}.",
            f"Code version {code_version}{tests}. Candidate {candidate_hash[:12]}.",
            updates,
            f"Replaces deploy version {replaces}." if replaces else "The first release.",
        )
    )
