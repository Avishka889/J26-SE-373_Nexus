"""A phase's gate state, read at the version it is about.

Written for the deployment phase and shaped so the others could use it: the
design, code and testing read models each carry their own copy of the same two
functions, which stay as they are rather than being touched from here.
"""

from sdlc_contracts import GateDecision, GateState

from ..db import store


def gate_decision(row: store.Row) -> GateDecision:
    return GateDecision(
        kind=row["decision"],
        at=row["decided_at"],
        by=row["decided_by"],
        version=row["requirements_version"],
        note=row["note"],
    )


def gate_state(history_rows: list[store.Row], version: int) -> GateState:
    """The decision that covers this version, with every other one behind it.

    A decision is recorded against the version it was made about. Reporting the
    newest decision whatever its version means the phase never asks again, and
    a run waiting at its gate waits for good.
    """
    current = next(
        (row for row in reversed(history_rows) if row["requirements_version"] == version),
        None,
    )
    current_id = current["id"] if current else None
    return GateState(
        decision=gate_decision(current) if current else None,
        history=[gate_decision(row) for row in history_rows if row["id"] != current_id],
    )
