"""A stage's model use: from the notes its component sends, to its row, to its page (0015)."""

import logging
from typing import Any

from pydantic import ValidationError
from sdlc_contracts import StageModelUse

log = logging.getLogger(__name__)


def stage_model_use(notes: dict[str, Any]) -> dict[str, Any] | None:
    """What answered the stage, in the shape its row keeps, or None when it asked no model.

    A record that does not validate is dropped with a warning rather than
    failing the stage: the artefact is what the stage is for, and losing the
    record of what made it is the smaller loss.
    """
    raw = notes.get("model_use")
    if raw is None:
        return None
    try:
        return StageModelUse.model_validate(raw).model_dump(by_alias=True, mode="json")
    except ValidationError as error:
        log.warning("a stage's model use did not validate and was not kept: %s", error)
        return None


def kept_model_use(row: dict[str, Any]) -> StageModelUse | None:
    """A stage row's model use for its page, or None.

    Validated on the way in; read defensively all the same, because a snapshot
    that refused to load over one stage's record would hide the whole phase.
    """
    raw = row.get("model_use")
    if raw is None:
        return None
    try:
        return StageModelUse.model_validate(raw)
    except ValidationError as error:
        log.warning("stage %s keeps a model use that does not validate: %s", row["stage_id"], error)
        return None
