"""Exec-with-env runner.

The load-bearing operation: read a secret from keychain, exec a command
with the value injected as an env var, capture stdout+stderr, sanitize
both, return.

The secret value lives in:
- Python local variable (this process's memory)
- Subprocess's environ (kernel-managed, owner-readable only)
- ...and that's it. Never on stdout, never on argv, never on disk.

After exec, the env var is gone from this process's view. The subprocess
may print the value if it wants to (curl -v, debug mode), in which case
the sanitizer catches it on the way back to Claude.
"""

import os
import subprocess
import sys
from typing import Sequence

from . import store
from .sanitize import sanitize


class RunResult:
    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run_with_secret(
    injections: list[tuple[str, str]],
    cmd: Sequence[str],
    *,
    timeout_sec: int | None = 600,
) -> RunResult:
    """Run cmd with secrets injected as env vars; return sanitized output.

    Args:
        injections: List of (secret_name, env_var_name) tuples.
                    e.g. [("STRIPE_KEY", "STRIPE_KEY"), ("GITHUB_TOKEN", "GH_PAT")]
        cmd: argv list to exec. Passed directly to subprocess.run.
        timeout_sec: Kill subprocess if it runs longer.

    Returns:
        RunResult with sanitized stdout/stderr.

    The injected values are present in subprocess env for the duration of
    the call. After return, this function holds them in known_values for
    the sanitization pass, then they go out of scope.
    """
    # Build env: start from current, add the injected secrets.
    env = os.environ.copy()
    known_values: list[tuple[str, str]] = []

    for secret_name, var_name in injections:
        value = store.get_secret(secret_name)
        if value is None:
            raise KeyError(
                f"Secret '{secret_name}' not found. "
                f"Run: claude-secrets prompt {secret_name}"
            )
        env[var_name] = value
        known_values.append((secret_name, value))

    # Add ALL stored values to the sanitizer pass — not just the injected
    # ones — to catch any spillage if the subprocess somehow accesses them.
    for extra_name, extra_val in (
        (n, store.get_secret(n)) for n in [s["name"] for s in store.list_secrets()]
    ):
        if extra_val and (extra_name, extra_val) not in known_values:
            known_values.append((extra_name, extra_val))

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        # Sanitize even the timeout-partial output.
        partial_stdout = sanitize(
            (e.stdout or b"").decode("utf-8", errors="replace"), known_values
        )
        partial_stderr = sanitize(
            (e.stderr or b"").decode("utf-8", errors="replace"), known_values
        )
        return RunResult(124, partial_stdout, partial_stderr + "\n[TIMEOUT]")

    return RunResult(
        result.returncode,
        sanitize(result.stdout, known_values),
        sanitize(result.stderr, known_values),
    )
