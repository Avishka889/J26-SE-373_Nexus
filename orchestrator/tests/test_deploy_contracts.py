"""Where the deploy contracts meet another component's vocabulary.

The contracts package cannot import a service, so the checks that hold a C4
contract to a name another component owns live here, where both are visible.
"""

from typing import get_args

from c2.stack.catalog import CATALOG
from sdlc_contracts import StackTrack


def test_the_deploy_plan_names_stacks_as_c2_does() -> None:
    """C2 chooses the stack and C4 only reads it (proposal 4.3), so a stack id
    the deploy plan accepts and C2's catalog does not name is a plan for a
    project that cannot exist. The draft said `spring-boot`; the catalog never
    had it."""
    assert set(get_args(StackTrack)) == {entry.id for entry in CATALOG}
