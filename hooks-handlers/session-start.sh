#!/usr/bin/env bash
# claude-secrets — SessionStart hook
# 1. Python 3.10+ check (keyring requires it)
# 2. Hash-gated venv install (skip if requirements.txt unchanged)
# 3. Emit status JSON
set -euo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT not set}"
PLUGIN_DATA="${CLAUDE_PLUGIN_DATA:?CLAUDE_PLUGIN_DATA not set}"

VENV_DIR="$PLUGIN_DATA/venv"
HASH_FILE="$PLUGIN_DATA/.deps-hash"
REQUIREMENTS="$PLUGIN_ROOT/pipeline/requirements.txt"

mkdir -p "$PLUGIN_DATA"

# --- 1. Python 3.10+ check ---
PYTHON_BIN=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    V=$("$candidate" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    MAJ=$(echo "$V" | cut -d. -f1)
    MIN=$(echo "$V" | cut -d. -f2)
    if [ "$MAJ" -ge 3 ] && [ "$MIN" -ge 10 ]; then
      PYTHON_BIN="$(command -v "$candidate")"
      break
    fi
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"claude-secrets ERROR: Python 3.10+ not found. Install via `brew install python@3.12`, then restart Claude Code."}}'
  exit 0
fi

# --- 2. Hash-gated venv reinstall ---
CURRENT_HASH=$(shasum -a 256 "$REQUIREMENTS" 2>/dev/null | cut -d' ' -f1 || echo "none")
CACHED_HASH=""
[ -f "$HASH_FILE" ] && CACHED_HASH=$(cat "$HASH_FILE")

if [ "$CURRENT_HASH" != "$CACHED_HASH" ] || [ ! -d "$VENV_DIR/bin" ]; then
  echo "claude-secrets: installing dependencies (one-time, ~10s)..." >&2
  "$PYTHON_BIN" -m venv "$VENV_DIR" 2>/dev/null || true
  "$VENV_DIR/bin/pip" install --quiet --disable-pip-version-check --upgrade pip >/dev/null 2>&1 || true
  if ! "$VENV_DIR/bin/pip" install --quiet --disable-pip-version-check -r "$REQUIREMENTS" 2>&1 | tail -5 >&2; then
    echo '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"claude-secrets ERROR: pip install of keyring failed. Check Python version and network."}}'
    exit 0
  fi
  echo "$CURRENT_HASH" > "$HASH_FILE"
fi

# --- 3. Status line ---
SECRET_COUNT=0
MANIFEST="$HOME/.config/claude-secrets/manifest.json"
if [ -f "$MANIFEST" ]; then
  SECRET_COUNT=$("$VENV_DIR/bin/python" -c "import json; print(len(json.load(open('$MANIFEST'))['secrets']))" 2>/dev/null || echo 0)
fi

echo "{\"hookSpecificOutput\":{\"hookEventName\":\"SessionStart\",\"additionalContext\":\"claude-secrets ready: ${SECRET_COUNT} secret(s) stored. Call \`claude-secrets prompt NAME\` to add. Call \`claude-secrets run --inject NAME=VAR -- cmd\` to use.\"}}"
