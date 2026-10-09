"""The workspace resolves and every member imports.

Trivial on purpose: it exists so CI is green from the first commit, which is
what makes "green" mean anything for the commits after it.
"""

import sdlc_contracts


def test_contracts_package_imports() -> None:
    assert sdlc_contracts.__doc__


def test_workspace_members_import() -> None:
    # Both services depend on the contracts package and neither defines a
    # contract type of its own, so a clash here would mean a duplicate model.
    import c1
    import c2

    import orchestrator

    assert orchestrator.__doc__
    assert c1.__doc__
    assert c2.__doc__
