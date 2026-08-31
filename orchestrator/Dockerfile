# Built from the repository root, because this is one uv workspace: the
# orchestrator depends on packages/contracts-py through a workspace source, and a
# build context of orchestrator/ alone cannot see it.
#
#   docker build -f orchestrator/Dockerfile .
#
# Used by docker-compose.yml only. The dev loop runs uvicorn directly and CI uses
# a service container, so nothing routine depends on this file.

FROM python:3.12-slim

# git merges an applied security fix into code generated again
# (orchestrator/carrying.py), and the slim image has none. Without it every
# such fix is reported as not carried rather than lost, so this is what keeps
# the fixes, not what keeps the image running.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Pinned to the version that produced uv.lock, so a rebuild cannot resolve
# differently from the machine the lockfile was written on.
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# The workspace members' manifests come first so the dependency layer is cached
# independently of the source. Every member has to be present: uv resolves the
# whole workspace from one lockfile, not one project at a time.
COPY pyproject.toml uv.lock ./
COPY packages/contracts-py/pyproject.toml packages/contracts-py/
COPY orchestrator/pyproject.toml orchestrator/
RUN uv sync --frozen --no-dev --no-install-workspace

COPY packages/contracts-py/ packages/contracts-py/
COPY contracts/ contracts/
COPY orchestrator/ orchestrator/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "8000"]
