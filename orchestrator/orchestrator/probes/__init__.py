"""One call probes for provider connections, modeled on c1.probe.

A probe answers the question a failed run would otherwise answer expensively:
is this credential usable at all, and for what. One request, a verdict from
the same vocabulary c1.probe established (SUITABLE, WORKABLE, UNUSABLE), and a
reason in plain words.
"""

from .atlas import probe_atlas
from .deploy_targets import probe_render, probe_render_deploy_hook, probe_vercel
from .github import probe_github, repository_protection

__all__ = [
    "probe_atlas",
    "probe_github",
    "probe_render",
    "probe_render_deploy_hook",
    "probe_vercel",
    "repository_protection",
]
