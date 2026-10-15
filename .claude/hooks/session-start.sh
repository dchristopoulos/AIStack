#!/bin/bash
# Prepare a Claude Code cloud session: the Python environment, a PostgreSQL for the tests'
# second half, and a Chromium the browser tests can launch. Safe to run again.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

if ! command -v poetry >/dev/null 2>&1; then
  pip install --quiet poetry
fi
poetry install --no-interaction

# PostgreSQL 16 on 5433, as compose.test.yaml would give, when the image has it and no
# Docker daemon is running.
PG_BIN=/usr/lib/postgresql/16/bin
PG_DATA=/var/lib/postgresql/aistack-test  # the postgres user cannot reach /root
if [ -x "$PG_BIN/pg_ctl" ] && id postgres >/dev/null 2>&1; then
  if ! pg_isready -q -h 127.0.0.1 -p 5433 2>/dev/null; then
    if [ ! -f "$PG_DATA/PG_VERSION" ]; then
      install -d -o postgres -m 700 "$PG_DATA"
      su postgres -c "$PG_BIN/initdb -D '$PG_DATA' -A trust -U postgres" >/dev/null
    fi
    su postgres -c "$PG_BIN/pg_ctl -D '$PG_DATA' -o '-p 5433 -k /tmp' -l '$PG_DATA/log' -w start" >/dev/null || true
  fi
  if pg_isready -q -h 127.0.0.1 -p 5433 2>/dev/null; then
    psql -q -h 127.0.0.1 -p 5433 -U postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='aistack'" | grep -q 1 \
      || psql -q -h 127.0.0.1 -p 5433 -U postgres -c "CREATE ROLE aistack LOGIN PASSWORD 'aistack' SUPERUSER"
    psql -q -h 127.0.0.1 -p 5433 -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='aistack_test'" | grep -q 1 \
      || psql -q -h 127.0.0.1 -p 5433 -U postgres -c "CREATE DATABASE aistack_test OWNER aistack"
    if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
      echo 'export TEST_DATABASE_URL=postgresql+psycopg://aistack:aistack@localhost:5433/aistack_test' >> "$CLAUDE_ENV_FILE"
    fi
  fi
fi

# The image ships a Chromium but not the headless shell the pinned Playwright asks for, and
# downloading browsers is not allowed here. Point Playwright at the shipped one instead.
if [ -x /opt/pw-browsers/chromium ]; then
  VENV="$(poetry env info -p)"
  REVISION="$("$VENV/bin/python" -c "import json, playwright, pathlib; d = json.loads((pathlib.Path(playwright.__file__).parent / 'driver/package/browsers.json').read_text()); print(next(b['revision'] for b in d['browsers'] if b['name'] == 'chromium-headless-shell'))")"
  PW="$HOME/.cache/aistack-playwright"
  SHELL_DIR="$PW/chromium_headless_shell-$REVISION/chrome-headless-shell-linux64"
  mkdir -p "$SHELL_DIR"
  ln -sf /opt/pw-browsers/chromium "$SHELL_DIR/chrome-headless-shell"
  touch "$PW/chromium_headless_shell-$REVISION/INSTALLATION_COMPLETE"
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo "export PLAYWRIGHT_BROWSERS_PATH=$PW" >> "$CLAUDE_ENV_FILE"
  fi
fi
