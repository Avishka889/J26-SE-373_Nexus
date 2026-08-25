"""Where a phase's newest run stands, so the page can say when it stopped.

A run that failed left nothing on the page. The stages it never reached went
back to pending and said they would start once the stage before them finished,
the review it never reached stayed empty, and the reason was written only to
the audit log. Every phase's snapshot carries this, so the page can say that
the run stopped, why, and what it never reached.
"""

from typing import Literal

from pydantic import Field, model_validator

from .wire import WireDatetime, WireModel

RunState = Literal["queued", "running", "awaiting_gate", "done", "failed", "superseded"]


class RunStatus(WireModel):
    """The phase's newest full run.

    A stage retry is a run of its own, and it is not this one: it reports on
    its own stage, and a retry that finished must not hide the full run beneath
    it that stopped short of the review.
    """

    id: str = Field(min_length=1)
    state: RunState
    #: The version this run produces on its phase's own axis.
    version: int = Field(ge=0)
    started_at: WireDatetime
    finished_at: WireDatetime | None = None
    #: Plain words, set only when the run failed.
    error: str | None = None
    #: The stage it stopped at, when it failed: the one that broke, or the
    #: first it never reached. Continuing goes on from here.
    stopped_at: str | None = None
    #: The model the run started on, as its component's client named it, for
    #: example `deepseek:deepseek-flash`. None on a run from before runs
    #: recorded it.
    model: str | None = None
    #: What the run asked that model about thinking: "disabled", or "default"
    #: where nothing was sent and the provider decided. None where not recorded.
    thinking: str | None = None

    @model_validator(mode="after")
    def failure_says_why(self) -> "RunStatus":
        if self.state == "failed" and not (self.error or "").strip():
            raise ValueError(f"run {self.id} failed without saying why")
        if self.state != "failed" and (self.error or self.stopped_at):
            raise ValueError(f"run {self.id} is {self.state} but says it stopped")
        return self
