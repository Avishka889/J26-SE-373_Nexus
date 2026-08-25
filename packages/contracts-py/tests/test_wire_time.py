"""Every time on the wire carries its zone.

Times were sent as "2026-10-03 09:12": UTC with the zone dropped, which the
pages showed as it came, five and a half hours early to a reader in Colombo.
"""

from datetime import UTC, datetime, timedelta, timezone

from sdlc_contracts import RunStatus

COLOMBO = timezone(timedelta(hours=5, minutes=30))


def _wire(started_at: object) -> str:
    status = RunStatus.model_validate(
        {"id": "r1", "state": "running", "version": 1, "startedAt": started_at}
    )
    return status.model_dump(mode="json", by_alias=True)["startedAt"]


def test_a_utc_time_goes_out_in_iso_8601_with_its_zone() -> None:
    assert _wire(datetime(2026, 10, 3, 9, 12, 41, tzinfo=UTC)) == "2026-10-03T09:12:41Z"


def test_a_time_in_another_zone_goes_out_as_the_same_moment_in_utc() -> None:
    assert _wire(datetime(2026, 10, 3, 14, 42, tzinfo=COLOMBO)) == "2026-10-03T09:12:00Z"


def test_the_older_shape_read_back_from_a_stored_artefact_is_utc() -> None:
    # What an artefact stored before this change holds, and is read back from.
    assert _wire("2026-10-03 09:12") == "2026-10-03T09:12:00Z"
