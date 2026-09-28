"""Test setup for C4.

Real model requests are blocked at import, from this component's first commit,
so a test that forgets to script its model fails loudly instead of calling a
provider and spending money. C1 and C2 do the same; C3 never did. A test that
genuinely wants a live model opts back in with the fixture below and is marked
`live`, so the ordinary suite never runs it.
"""

import pytest
from pydantic_ai import models

models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def allow_live_requests():
    """Opt one test back into calling a real provider, and close the door after."""
    models.ALLOW_MODEL_REQUESTS = True
    try:
        yield
    finally:
        models.ALLOW_MODEL_REQUESTS = False
