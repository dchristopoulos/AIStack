# syntax=docker/dockerfile:1

# --- build: resolve and install the locked dependencies into a virtualenv ---------------------
FROM python:3.13-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1

# Pinned so a new Poetry release cannot change how the lock file is read.
RUN pip install "poetry==2.4.1"

WORKDIR /app

# Dependencies first: this layer is rebuilt only when the lock file changes.
COPY pyproject.toml poetry.lock ./
RUN poetry install --only main --no-root

# The package's metadata names the README and LICENSE, so installing it needs both.
COPY README.md LICENSE ./
COPY src ./src
RUN poetry install --only main

# --- runtime: the virtualenv and the source, nothing that built them --------------------------
FROM python:3.13-slim

# A fixed, unprivileged uid, so a mounted volume has a predictable owner.
RUN useradd --system --uid 10001 --no-create-home aistack \
    && mkdir /data \
    && chown aistack:aistack /data

WORKDIR /app
COPY --from=build /app/.venv ./.venv
COPY --from=build /app/src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # The one volume: the SQLite file lives here. Point DATABASE_URL at Postgres and the
    # volume is unused.
    DATABASE_URL="sqlite:////data/aistack.db" \
    AISTACK_HOST="0.0.0.0" \
    AISTACK_PORT="8000"

USER aistack
VOLUME /data
EXPOSE 8000

# No curl in the slim image; the interpreter is already there.
# Polled every 2s while starting, so "healthy" arrives in seconds rather than after the
# first 30s interval.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --start-interval=2s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['AISTACK_PORT'] + '/health', timeout=4)"

# AISTACK_INVITE_CODE has no default on purpose: the server refuses to start without one.
CMD ["python", "-m", "aistack.bootstrap"]
