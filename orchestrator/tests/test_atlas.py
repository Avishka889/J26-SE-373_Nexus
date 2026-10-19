"""MongoDB Atlas: the service account's probe, against a fake that answers as Atlas does.

Nothing here reaches Atlas. The probe only reads: a token, the cluster, and who
may connect to it; every token it makes is revoked; and no credential, the Basic
form of it or the token, appears in anything it says.
"""

import base64

import httpx
from orchestrator.probes.atlas import probe_atlas

from .atlas_fake import CLIENT_ID, CLUSTER, PROJECT, SECRET, FakeAtlas


async def _probe(atlas: FakeAtlas, **account: str):
    return await probe_atlas(
        SECRET,
        client=atlas.client(),
        **{"client_id": CLIENT_ID, "project_id": PROJECT, "cluster": CLUSTER, **account},
    )


class TestTheAtlasProbe:
    async def test_a_cluster_apps_may_connect_to_is_suitable_and_the_token_is_revoked(
        self,
    ) -> None:
        atlas = FakeAtlas()

        probe = await _probe(atlas)

        assert (probe.verdict, probe.account) == ("SUITABLE", f"{PROJECT}/{CLUSTER}")
        assert "IDLE" in probe.reason and "1 network access entry" in probe.reason
        assert atlas.issued and atlas.revoked == atlas.issued
        assert not [call for call in atlas.calls if call[0] != "GET" and "/oauth/" not in call[1]]

    async def test_what_is_missing_from_settings_is_named_and_nothing_is_called(self) -> None:
        atlas = FakeAtlas()

        probe = await _probe(atlas, client_id="", project_id=" ")

        assert probe.verdict == "UNUSABLE"
        assert "the service account's client ID and the Atlas project ID" in probe.reason
        assert atlas.calls == []

    async def test_a_wrong_secret_does_not_authenticate(self) -> None:
        atlas = FakeAtlas()

        probe = await probe_atlas(
            "mdb_sa_sk_wrong",
            client=atlas.client(),
            client_id=CLIENT_ID,
            project_id=PROJECT,
            cluster=CLUSTER,
        )

        assert probe.verdict == "UNUSABLE"
        assert "do not authenticate" in probe.reason
        assert [path for _, path in atlas.calls] == ["/api/oauth/token"]

    async def test_a_cluster_nobody_may_connect_to_says_what_to_add(self) -> None:
        probe = await _probe(FakeAtlas(access=()))

        assert probe.verdict == "WORKABLE"
        assert "no address may connect" in probe.reason and "Network Access" in probe.reason

    async def test_a_project_it_may_not_read_names_the_two_roles_it_needs(self) -> None:
        probe = await _probe(FakeAtlas(cluster_status=403))

        assert probe.verdict == "UNUSABLE"
        assert "Project Read Only and Project Database Access Admin" in probe.reason

    async def test_a_cluster_that_is_not_there_is_named(self) -> None:
        probe = await _probe(FakeAtlas(), cluster="Cluster9")

        assert probe.verdict == "UNUSABLE"
        assert "no cluster named Cluster9" in probe.reason

    async def test_a_cluster_without_a_connection_string_is_not_suitable(self) -> None:
        probe = await _probe(FakeAtlas(srv=None))

        assert probe.verdict == "WORKABLE"
        assert "no connection string yet" in probe.reason

    async def test_an_answer_that_echoes_a_credential_is_redacted(self) -> None:
        basic = base64.b64encode(f"{CLIENT_ID}:{SECRET}".encode()).decode()
        atlas = FakeAtlas()
        atlas.token_answer = httpx.Response(500, text=f"upstream said {SECRET} and {basic}")

        probe = await _probe(atlas)

        assert probe.verdict == "UNUSABLE"
        assert SECRET not in probe.reason and basic not in probe.reason
        assert "[redacted]" in probe.reason

    async def test_an_error_that_echoes_the_token_is_redacted(self) -> None:
        token = "eyJ.fake-access-token-1"
        atlas = FakeAtlas(cluster_status=500, cluster_detail=f"bad bearer {token}")

        probe = await _probe(atlas)

        assert atlas.issued == [token]
        assert probe.verdict == "UNUSABLE"
        assert token not in probe.reason and "[redacted]" in probe.reason
