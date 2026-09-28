"""Component 4: Deployment Automation and Dependency Evolution.

Before a dependency update is applied, C4 says how risky it is for this project
and which files and architectural components it touches; it generates the
pipeline and deployment configuration for the stack C2 chose; it prepares a
rollback for every release; and it turns what monitoring saw into feedback C1
can act on. It analyses and generates only. Releasing, rolling back and probing
are the orchestrator's work, by architecture decisions 2 and 3.
"""
