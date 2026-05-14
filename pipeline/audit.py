"""Append-only audit log.

JSONL at ~/.claude/plugins/data/claude-secrets/audit.jsonl (or fallback
to ~/.config/claude-secrets/audit.jsonl if not in plugin context).

NEVER logs values. Only: timestamp, action, name, exit_code, sanitized
context (e.g., first 60 chars of the command).
"""

import json
import os
from pathlib import Path

from .store import now_iso


def _audit_path() -> Path:
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        base = Path(plugin_data)
    else:
        base = Path.home() / ".config" / "claude-secrets"
    base.mkdir(parents=True, exist_ok=True)
    return base / "audit.jsonl"


def log(action: str, name: str | None = None, *, exit_code: int | None = None,
        context: str = "") -> None:
    """Append one audit entry. Best-effort — failures swallowed."""
    try:
        entry = {
            "ts": now_iso(),
            "action": action,
            "name": name,
        }
        if exit_code is not None:
            entry["exit_code"] = exit_code
        if context:
            # Truncate context to prevent giant log entries
            entry["context"] = context[:200]
        path = _audit_path()
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        os.chmod(path, 0o600)
    except Exception:
        # Audit failure must not crash the operation
        pass
