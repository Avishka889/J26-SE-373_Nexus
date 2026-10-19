"""Deployment execution: the orchestrator's side of Component 4.

C4 analyses and generates; this package carries out what the gate authorises,
by architecture decisions 2 and 3. It holds the release guards, the adapters
that talk to local Docker and GitHub Actions, the monitor, and the controlled
failure scenarios, as each lands.
"""
