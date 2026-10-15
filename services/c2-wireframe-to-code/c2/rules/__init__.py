"""The rule layer: everything here runs without a model.

The split is C1's and it is a package boundary for the same reason: the
component's claims are only checkable if the deterministic parts are
deterministic. Scope is derived, never asked for.
"""

from .scope import derive_scope

__all__ = ["derive_scope"]
