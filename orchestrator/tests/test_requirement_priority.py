# ruff: noqa: F811 - `client` is the code routes' fixture, imported to be used by name
"""A requirement's priority can be corrected, and Sprint Planning reads the correction.

Priority came from a rule over the model's rewording and nothing could correct
it: the requirement's text could be edited, its priority could not, and the
sprint was ranked on it (review item C1-2).
"""

from .conftest import needs_db
from .test_code_routes import _advance_all, _project, client  # noqa: F401

pytestmark = needs_db


class TestAPriorityCanBeCorrected:
    async def test_the_design_shows_the_corrected_priority(self, client) -> None:
        project_id = await _project(client, approve=False)
        before = (await client.get(f"/projects/{project_id}/design")).json()["requirements"][0]
        assert before["priority"] == "must"
        assert before["priorityCorrected"] is False

        answer = await client.patch(
            f"/projects/{project_id}/design/requirements/R-1", json={"priority": "could"}
        )

        assert answer.status_code == 200, answer.text
        after = answer.json()["requirements"][0]
        assert after["priority"] == "could"
        assert after["priorityCorrected"] is True
        # The text is as generated: only the priority was corrected.
        assert after["text"] == before["text"]
        assert after["adjusted"] is False

    async def test_it_is_in_the_activity(self, client) -> None:
        project_id = await _project(client, approve=False)
        await client.patch(
            f"/projects/{project_id}/design/requirements/R-1", json={"priority": "could"}
        )

        entries = (await client.get("/audit", params={"project": project_id})).json()

        [entry] = [one for one in entries if one["action"] == "Corrected a requirement's priority"]
        assert entry["target"] == "R-1"
        assert "could-have" in entry["detail"]

    async def test_a_correction_that_names_neither_is_refused(self, client) -> None:
        project_id = await _project(client, approve=False)

        answer = await client.patch(f"/projects/{project_id}/design/requirements/R-1", json={})

        assert answer.status_code == 422

    async def test_a_priority_that_is_not_one_is_refused(self, client) -> None:
        project_id = await _project(client, approve=False)

        answer = await client.patch(
            f"/projects/{project_id}/design/requirements/R-1", json={"priority": "urgent"}
        )

        assert answer.status_code == 422

    async def test_an_approved_design_is_not_corrected(self, client) -> None:
        project_id = await _project(client)

        refused = await client.patch(
            f"/projects/{project_id}/design/requirements/R-1", json={"priority": "could"}
        )

        assert refused.status_code == 409
        design = (await client.get(f"/projects/{project_id}/design")).json()
        assert design["requirements"][0]["priority"] == "must"


class TestSprintPlanningReadsIt:
    async def test_the_plan_on_the_page_is_said_to_be_ranked_on_the_old_priority(
        self, client
    ) -> None:
        project_id = await _project(client, approve=False)

        design = (
            await client.patch(
                f"/projects/{project_id}/design/requirements/R-1", json={"priority": "could"}
            )
        ).json()

        [finding] = [
            one for one in design["consistency"] if one["ruleId"] == "story-priority-is-current"
        ]
        assert finding["stageId"] == "sprint-plan"
        assert "US-1" in finding["reason"]
        assert "could-have" in finding["reason"]

    async def test_planning_the_sprint_again_ranks_on_the_correction(self, client) -> None:
        project_id = await _project(client, approve=False)
        await client.patch(
            f"/projects/{project_id}/design/requirements/R-1", json={"priority": "could"}
        )

        again = await client.post(f"/projects/{project_id}/design/stages/sprint-plan/retry")
        assert again.status_code == 200, again.text
        await _advance_all(client, project_id)

        c1 = client.app.state.c1  # type: ignore[attr-defined]
        assert c1.sprint_asked == [("R-1", "could")]

    async def test_a_new_version_s_plan_reads_it_too(self, client) -> None:
        """The correction is kept against the requirement's id, which a new
        version carries, so a change note does not lose it."""
        project_id = await _project(client, approve=False)
        await client.patch(
            f"/projects/{project_id}/design/requirements/R-1", json={"priority": "could"}
        )

        changed = await client.post(
            f"/projects/{project_id}/design/decision",
            json={"kind": "changes", "note": "Records carry a name."},
        )
        assert changed.status_code == 200, changed.text
        await _advance_all(client, project_id)

        c1 = client.app.state.c1  # type: ignore[attr-defined]
        assert c1.calls.count("sprint-plan") == 2
        assert ("R-1", "could") in c1.sprint_asked
        design = (await client.get(f"/projects/{project_id}/design")).json()
        assert design["requirements"][0]["priority"] == "could"
