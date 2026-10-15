"""Is this GitHub token usable for pushing generated repositories.

One call: GET /user. What it proves, and what it honestly cannot:

- 200 proves the token authenticates and names the account repositories will
  be created under.
- A classic PAT reports its scopes in the `x-oauth-scopes` response header.
  `repo` is what creating and pushing needs; `workflow` is what pushing the
  generated CI workflow file needs. Both present is SUITABLE.
- A fine grained PAT sends no scopes header at all, so its permissions cannot
  be inspected from here. That is reported as WORKABLE with the reason, not
  guessed at: the real proof happens at push time, where a refusal carries
  GitHub's own message.

The verdict vocabulary is c1.probe's: SUITABLE, WORKABLE, UNUSABLE.
"""

from dataclasses import dataclass, field
from typing import Literal

import httpx

from ..crypto import redacted

GITHUB_API = "https://api.github.com"
PROBE_TIMEOUT_SECONDS = 10.0

Verdict = Literal["SUITABLE", "WORKABLE", "UNUSABLE"]

#: What pushing a generated monorepo needs from a classic PAT. `repo` covers
#: creating the repository and pushing content; `workflow` covers the CI
#: workflow file the monorepo carries.
REQUIRED_SCOPES = frozenset({"repo", "workflow"})


@dataclass(frozen=True)
class GithubProbe:
    verdict: Verdict
    reason: str
    login: str | None = None
    #: "classic" when the scopes header was present, "fine-grained" when a 200
    #: came back without one. None when the call never got that far.
    token_kind: Literal["classic", "fine-grained"] | None = None
    scopes: list[str] = field(default_factory=list)

    def as_meta(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "login": self.login,
        }


async def probe_github(token: str, *, client: httpx.AsyncClient | None = None) -> GithubProbe:
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS)
    try:
        response = await http.get(
            f"{GITHUB_API}/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    except httpx.HTTPError as error:
        # The exception text is upstream's; it has no business carrying the
        # token, but this code cannot know every proxy between here and there.
        reason = redacted(f"GitHub could not be reached: {error}", token)
        return GithubProbe(verdict="UNUSABLE", reason=reason)
    finally:
        if owns_client:
            await http.aclose()

    if response.status_code == 401:
        return GithubProbe(verdict="UNUSABLE", reason="The token does not authenticate.")
    if response.status_code != 200:
        reason = redacted(f"GitHub answered {response.status_code} to the identity call.", token)
        return GithubProbe(verdict="UNUSABLE", reason=reason)

    login = str(response.json().get("login", "")) or None
    scopes_header = response.headers.get("x-oauth-scopes")

    if scopes_header is None:
        return GithubProbe(
            verdict="WORKABLE",
            reason=(
                "Authenticates, but a fine grained token does not publish its "
                "permissions, so they cannot be verified from here. The push "
                "itself is the proof; a refusal there carries GitHub's message."
            ),
            login=login,
            token_kind="fine-grained",
        )

    scopes = sorted(s.strip() for s in scopes_header.split(",") if s.strip())
    missing = sorted(REQUIRED_SCOPES - set(scopes))
    if not missing:
        return GithubProbe(
            verdict="SUITABLE",
            reason=f"Authenticates as {login} with the repo and workflow scopes.",
            login=login,
            token_kind="classic",
            scopes=scopes,
        )
    return GithubProbe(
        verdict="WORKABLE",
        reason=(
            f"Authenticates as {login} but is missing the {' and '.join(missing)} "
            "scope" + ("s" if len(missing) > 1 else "") + ". Creating and pushing "
            "may work partially; the generated CI workflow file needs workflow."
        ),
        login=login,
        token_kind="classic",
        scopes=scopes,
    )


#: Plans whose private repositories have environments with required reviewers.
_REVIEWER_PLANS = frozenset({"enterprise", "business"})
#: Plans whose private repositories have environments but no required reviewers.
_ENVIRONMENT_PLANS = frozenset({"pro", "team"})


async def repository_protection(
    token: str, owner: str, repo: str, *, client: httpx.AsyncClient | None = None
) -> tuple[str, str]:
    """What GitHub can enforce for a release from this repository, and why.

    The answer shapes the generated deploy workflow at release time: its
    production jobs carry `environment:` only where GitHub has environments, and
    the saga approves a waiting job only where GitHub has reviewers. Public
    repositories have both on every plan. A private one depends on the owner's
    plan, read from the account the token belongs to; a plan that cannot be read
    is treated as Free, which enforces nothing, rather than guessed upward.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    owns = client is None
    http = client or httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS)
    try:
        repository = await http.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=headers)
        if repository.status_code != 200:
            return (
                "unavailable-private-repo",
                f"the repository could not be read (GitHub answered {repository.status_code}), "
                "so its rules are not relied on",
            )
        body = repository.json()
        if not body.get("private"):
            return (
                "configured",
                "a public repository has environments with required reviewers on every plan",
            )
        is_org = (body.get("owner") or {}).get("type") == "Organization"
        account = await http.get(
            f"{GITHUB_API}/orgs/{owner}" if is_org else f"{GITHUB_API}/user", headers=headers
        )
    except httpx.HTTPError as error:
        return (
            "unavailable-private-repo",
            redacted(
                f"GitHub could not be reached ({error}), so its rules are not relied on", token
            ),
        )
    finally:
        if owns:
            await http.aclose()
    details = account.json() if account.status_code == 200 else {}
    own_account = is_org or str(details.get("login", "")).lower() == owner.lower()
    plan = str((details.get("plan") or {}).get("name") or "").lower() if own_account else ""
    if plan in _REVIEWER_PLANS:
        return ("configured", f"a private repository on the {plan} plan has required reviewers")
    if plan in _ENVIRONMENT_PLANS:
        return (
            "unavailable-plan",
            f"a private repository on the {plan} plan has environments but no required "
            "reviewers, so the platform's gate is the only lock",
        )
    return (
        "unavailable-private-repo",
        "GitHub Free has no environments on a private repository"
        if plan == "free"
        else "the owner's plan could not be read, so it is treated as Free",
    )
