"""Every question intake asks the outside world, asked once and written down.

Each request is recorded as a `RegistryQuery` on the report, so "no newer
version" can be told apart from "the registry did not answer", which read the
same in a list of updates. Only stable answers are cached: a 200 or a 404 is
what the registry says about a package, while a 5xx or a dropped connection is
what the network said about this minute, and caching that would turn one bad
minute into a permanent rejection.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sdlc_contracts import RegistryQuery

from .cache import Cache

#: Short enough that one dead registry cannot hold a run for long.
TIMEOUT_SECONDS = 20.0

_STABLE = {200, 404, 410}


@dataclass(frozen=True)
class Answer:
    url: str
    #: None when nothing answered at all.
    status: int | None
    body: bytes
    retrieved_at: datetime
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200


@dataclass
class Fetcher:
    client: httpx.AsyncClient
    cache: Cache = field(default_factory=lambda: Cache(None))
    queries: list[RegistryQuery] = field(default_factory=list)

    async def get(
        self, url: str, *, registry: str, headers: dict[str, str] | None = None
    ) -> Answer:
        cached = self.cache.get(url)
        if cached is not None:
            answer = Answer(url, cached.status, cached.body, cached.retrieved_at)
            self._record(registry, answer, note="from the cache")
            return answer
        try:
            response = await self.client.get(
                url, headers=headers or {}, timeout=TIMEOUT_SECONDS, follow_redirects=True
            )
        except httpx.HTTPError as error:
            answer = Answer(
                url, None, b"", datetime.now(UTC), error=f"{type(error).__name__}: {error}"
            )
            self._record(registry, answer, note=answer.error)
            return answer
        if response.status_code in _STABLE:
            stored = self.cache.put(url, response.content, response.status_code)
            answer = Answer(url, response.status_code, response.content, stored.retrieved_at)
        else:
            answer = Answer(
                url,
                response.status_code,
                response.content,
                datetime.now(UTC),
                error=response.reason_phrase,
            )
        self._record(registry, answer)
        return answer

    def _record(self, registry: str, answer: Answer, note: str = "") -> None:
        self.queries.append(
            RegistryQuery(
                registry=registry,
                url=answer.url,
                at=answer.retrieved_at,
                status=answer.status,
                note=note,
            )
        )
