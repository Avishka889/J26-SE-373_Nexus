"""Atlas's Administration API, as far as the platform uses it, answering as Atlas does.

A token only for the right client id and secret; 401 for any other bearer; 406
for a resource version the real API does not have, so a call written against
the wrong date fails here as it would there. Database users are kept, and a
password is never answered back, as Atlas never does.
"""

import base64
import json
from typing import Any
from urllib.parse import parse_qs

import httpx
from orchestrator.probes.atlas import CLUSTER_VERSION, PROJECT_VERSION

CLIENT_ID = "mdb_sa_id_0123456789abcdef01234567"
SECRET = "mdb_sa_sk_not-a-real-secret-7f6e5d4c3b2a"
PROJECT = "66f0c0ffee0123456789abcd"
CLUSTER = "Cluster0"
HOST = "cluster0.ab1cd.mongodb.net"


class FakeAtlas:
    def __init__(
        self,
        *,
        access: tuple[str, ...] = ("0.0.0.0/0",),
        srv: str | None = f"mongodb+srv://{HOST}",
        cluster_status: int = 200,
        cluster_body: dict[str, Any] | None = None,
        cluster_detail: str = "Refused by the test.",
    ) -> None:
        self.access = list(access)
        self.srv = srv
        self.cluster_status = cluster_status
        self.cluster_body = cluster_body
        self.cluster_detail = cluster_detail
        self.users: dict[str, dict[str, Any]] = {}
        self.passwords: dict[str, str] = {}
        self.issued: list[str] = []
        self.revoked: list[str] = []
        self.calls: list[tuple[str, str]] = []
        #: Set to answer the token request with this instead.
        self.token_answer: httpx.Response | None = None

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.answer))

    def answer(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if path == "/api/oauth/token":
            return self._token(request)
        if path == "/api/oauth/revoke":
            form = parse_qs(request.content.decode())
            self.revoked.extend(form.get("token", []))
            return httpx.Response(200)
        bearer = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if bearer not in self.issued or bearer in self.revoked:
            return _error(401, "UNAUTHORIZED", "Current user is not authorized.")
        prefix = f"/api/atlas/v2/groups/{PROJECT}"
        if not path.startswith(prefix):
            return _error(404, "GROUP_NOT_FOUND", "No group with the given id exists.")
        rest = path.removeprefix(prefix)
        if rest.startswith("/clusters/"):
            return self._cluster(request, rest.removeprefix("/clusters/"))
        if request.headers.get("Accept") != PROJECT_VERSION:
            return _error(406, "INVALID_VERSION_DATE", "The version does not exist.")
        if rest == "/accessList" and request.method == "GET":
            results = [{"cidrBlock": one, "groupId": PROJECT} for one in self.access]
            return httpx.Response(200, json={"results": results, "totalCount": len(results)})
        if rest == "/databaseUsers" and request.method == "POST":
            return self._create_user(request)
        if rest.startswith("/databaseUsers/admin/"):
            return self._user(request, rest.removeprefix("/databaseUsers/admin/"))
        return _error(404, "RESOURCE_NOT_FOUND", f"No resource at {path}.")

    def _token(self, request: httpx.Request) -> httpx.Response:
        if self.token_answer is not None:
            return self.token_answer
        expected = base64.b64encode(f"{CLIENT_ID}:{SECRET}".encode()).decode()
        form = parse_qs(request.content.decode())
        if request.headers.get("Authorization") != f"Basic {expected}":
            return httpx.Response(401, json={"error": "invalid_client"})
        if form.get("grant_type") != ["client_credentials"]:
            return httpx.Response(400, json={"error": "unsupported_grant_type"})
        token = f"eyJ.fake-access-token-{len(self.issued) + 1}"
        self.issued.append(token)
        return httpx.Response(
            200, json={"access_token": token, "expires_in": 3600, "token_type": "Bearer"}
        )

    def _cluster(self, request: httpx.Request, name: str) -> httpx.Response:
        if request.headers.get("Accept") != CLUSTER_VERSION:
            return _error(406, "INVALID_VERSION_DATE", "The version does not exist.")
        if self.cluster_status != 200:
            return _error(self.cluster_status, "CLUSTER_REFUSED", self.cluster_detail)
        if name != CLUSTER:
            return _error(404, "CLUSTER_NOT_FOUND", f"No cluster named {name} exists.")
        strings = {"standardSrv": self.srv} if self.srv else {}
        body = self.cluster_body or {
            "name": CLUSTER,
            "stateName": "IDLE",
            "connectionStrings": strings,
        }
        return httpx.Response(200, json=body)

    def _body(self, request: httpx.Request) -> dict[str, Any] | httpx.Response:
        if request.headers.get("Content-Type") != PROJECT_VERSION:
            return _error(415, "UNSUPPORTED_MEDIA_TYPE", "Unsupported content type.")
        return json.loads(request.content)

    def _create_user(self, request: httpx.Request) -> httpx.Response:
        body = self._body(request)
        if isinstance(body, httpx.Response):
            return body
        missing = [k for k in ("databaseName", "groupId", "roles", "username") if not body.get(k)]
        if missing:
            return _error(400, "MISSING_ATTRIBUTE", f"Missing {', '.join(missing)}.")
        if body["username"] in self.users:
            return _error(409, "USER_ALREADY_EXISTS", "The user already exists.")
        self._keep(body["username"], body)
        return httpx.Response(201, json=self.users[body["username"]])

    def _user(self, request: httpx.Request, username: str) -> httpx.Response:
        if username not in self.users:
            return _error(404, "USERNAME_NOT_FOUND", f"No user with username {username} exists.")
        if request.method == "GET":
            return httpx.Response(200, json=self.users[username])
        if request.method == "PATCH":
            body = self._body(request)
            if isinstance(body, httpx.Response):
                return body
            self._keep(username, {**self.users[username], **body})
            return httpx.Response(200, json=self.users[username])
        return _error(405, "METHOD_NOT_ALLOWED", "Not allowed.")

    def _keep(self, username: str, body: dict[str, Any]) -> None:
        if "password" in body:
            self.passwords[username] = body["password"]
        self.users[username] = {k: v for k, v in body.items() if k != "password"}


def _error(status: int, code: str, detail: str) -> httpx.Response:
    return httpx.Response(
        status, json={"error": status, "errorCode": code, "detail": detail, "reason": "Refused"}
    )
