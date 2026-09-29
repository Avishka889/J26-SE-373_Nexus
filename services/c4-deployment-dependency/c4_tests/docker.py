"""Skip a test that needs Docker, saying which part is missing.

The same shape as C3's JDK guard: the reason names what is absent, because a
skip that says only "no docker" sends the reader to install something that may
already be installed with its daemon stopped.
"""

import pytest
from c4.harness.container import docker_unavailable

_WHY = docker_unavailable()

needs_docker = pytest.mark.skipif(_WHY is not None, reason=_WHY or "")
