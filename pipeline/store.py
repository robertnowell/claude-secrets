"""Keychain wrappers.

Uses the `keyring` library which calls macOS Security framework via PyObjC.
Values live only in this Python process's memory; they never cross process
boundaries via stdout or argv.

Storage layout:
    Service name: "claude-secrets/<NAME>"  (e.g., "claude-secrets/STRIPE_KEY")
    Account:      $USER
    Value:        the raw secret bytes (utf-8)

Metadata (timestamps, types, descriptions) is stored separately in
~/.config/claude-secrets/manifest.json — Claude can read this file safely
because it never contains values.
"""

import getpass
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import keyring

SERVICE_PREFIX = "claude-secrets"
CONFIG_DIR = Path.home() / ".config" / "claude-secrets"
MANIFEST_PATH = CONFIG_DIR / "manifest.json"


def _service_name(name: str) -> str:
    return f"{SERVICE_PREFIX}/{name}"


def _account() -> str:
    return getpass.getuser()


def _load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {"version": 1, "secrets": {}}
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def _save_manifest(manifest: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    os.chmod(MANIFEST_PATH, 0o600)


def set_secret(name: str, value: str, *, description: str = "") -> None:
    """Store a value in keychain + update manifest with metadata.

    The value passes only through this function's local variable and the
    keychain library's internal call to SecKeychainAddGenericPassword via
    PyObjC. It never touches stdout, argv, or any file we can read.
    """
    keyring.set_password(_service_name(name), _account(), value)

    manifest = _load_manifest()
    manifest["secrets"][name] = {
        "added": manifest["secrets"].get(name, {}).get("added") or now_iso(),
        "updated": now_iso(),
        "description": description,
    }
    _save_manifest(manifest)


def get_secret(name: str) -> str | None:
    """Read a value from keychain.

    Intended for use INSIDE the broker process only — the value flows into
    runner.py for exec-with-env. It must never be printed to stdout.
    """
    return keyring.get_password(_service_name(name), _account())


def delete_secret(name: str) -> bool:
    """Remove a value from keychain + manifest. Returns True if existed."""
    existed = get_secret(name) is not None
    if existed:
        keyring.delete_password(_service_name(name), _account())
    manifest = _load_manifest()
    if name in manifest["secrets"]:
        del manifest["secrets"][name]
        _save_manifest(manifest)
    return existed


def list_secrets() -> list[dict]:
    """List secret NAMES and metadata. Never values."""
    manifest = _load_manifest()
    return [
        {"name": name, **meta}
        for name, meta in sorted(manifest["secrets"].items())
    ]


def exists(name: str) -> bool:
    return get_secret(name) is not None


def all_values_for_sanitization() -> list[str]:
    """Return ALL stored values for output sanitization.

    Caller (sanitize.py) uses these to scrub any byte-for-byte appearance
    of stored secrets in command output. The values returned by this
    function stay inside the broker process — they're used to build the
    sanitizer's literal-match set, then discarded.
    """
    manifest = _load_manifest()
    values = []
    for name in manifest["secrets"]:
        v = get_secret(name)
        if v:
            values.append(v)
    return values


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
