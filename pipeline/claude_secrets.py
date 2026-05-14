"""claude-secrets — CLI entry point.

Subcommands:
    prompt <NAME>            Pop dialog, store value, return JSON status.
    list                     List secret names + metadata (never values).
    rm <NAME>                Delete a secret.
    rotate <NAME>            Pop dialog, overwrite existing value.
    run --inject N=V ... -- CMD ...
                             Exec CMD with secrets injected as env vars,
                             return sanitized stdout/stderr.
    status                   Show config state + keychain reachability.

Every subcommand emits JSON on stdout when invoked with --json (the
default mode when Claude calls it). Values are NEVER in the output.

Each subcommand exits 0 on success, non-zero on failure.
"""

import argparse
import json
import sys
from pathlib import Path

# Make absolute imports work whether invoked as module or script
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from pipeline import audit, dialog, runner, store
    from pipeline.dialog import DialogCancelled, DialogTimedOut
else:
    from . import audit, dialog, runner, store
    from .dialog import DialogCancelled, DialogTimedOut


def _emit(payload: dict) -> None:
    """Emit a JSON line and exit successfully."""
    print(json.dumps(payload))


def _emit_err(message: str, *, exit_code: int = 1) -> None:
    """Emit an error JSON and exit non-zero."""
    print(json.dumps({"status": "error", "error": message}))
    sys.exit(exit_code)


def cmd_prompt(args):
    """Pop dialog, store, return status."""
    try:
        value = dialog.prompt_secret(args.name, timeout_sec=args.timeout)
    except DialogCancelled:
        audit.log("prompt_cancelled", args.name)
        _emit({"status": "cancelled", "name": args.name})
        return
    except DialogTimedOut:
        audit.log("prompt_timeout", args.name)
        _emit({"status": "timeout", "name": args.name})
        return
    except RuntimeError as e:
        audit.log("prompt_failed", args.name, context=str(e))
        _emit_err(f"dialog failed: {e}")
        return

    try:
        store.set_secret(args.name, value, description=args.description or "")
        audit.log("prompt_stored", args.name)
        _emit({"status": "ok", "name": args.name, "action": "stored"})
    except Exception as e:
        audit.log("prompt_store_failed", args.name, context=str(e))
        _emit_err(f"failed to store: {e}")


def cmd_list(args):
    """List names + metadata. Never values."""
    secrets = store.list_secrets()
    _emit({"status": "ok", "secrets": secrets})


def cmd_rm(args):
    """Delete a secret."""
    existed = store.delete_secret(args.name)
    audit.log("rm", args.name, exit_code=0 if existed else 1)
    if existed:
        _emit({"status": "ok", "name": args.name, "action": "deleted"})
    else:
        _emit({"status": "ok", "name": args.name, "action": "not_found"})


def cmd_rotate(args):
    """Replace a secret's value (same as prompt, but warns if missing)."""
    if not store.exists(args.name) and not args.force:
        _emit_err(
            f"'{args.name}' does not exist; use prompt to create, or --force"
        )
        return
    # Reuse prompt flow
    cmd_prompt(args)


def cmd_run(args):
    """Exec command with secrets injected; return sanitized output."""
    injections: list[tuple[str, str]] = []
    for inj in args.inject:
        if "=" not in inj:
            _emit_err(f"--inject expects NAME=ENV_VAR, got: {inj}")
            return
        name, env_var = inj.split("=", 1)
        injections.append((name.strip(), env_var.strip()))

    if not args.cmd:
        _emit_err("no command provided after --")
        return

    try:
        result = runner.run_with_secret(
            injections, args.cmd, timeout_sec=args.timeout
        )
    except KeyError as e:
        audit.log("run_missing_secret", str(e))
        _emit_err(str(e), exit_code=2)
        return

    audit.log(
        "run",
        ",".join(n for n, _ in injections),
        exit_code=result.returncode,
        context=" ".join(args.cmd),
    )

    # Stream stdout/stderr to the appropriate channels.
    # Claude reads our JSON envelope; humans piping us might want the raw
    # streams. For now: emit JSON envelope only (Claude-friendly).
    _emit({
        "status": "ok",
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    })


def cmd_status(args):
    """Report config + keychain reachability."""
    info = {
        "status": "ok",
        "config_dir": str(store.CONFIG_DIR),
        "manifest_exists": store.MANIFEST_PATH.exists(),
        "secret_count": len(store.list_secrets()),
    }
    # Probe keychain access without exposing any value.
    try:
        # Try a write+read+delete of a known-throwaway value.
        store.keyring.set_password("claude-secrets-probe", "self", "ok")
        v = store.keyring.get_password("claude-secrets-probe", "self")
        store.keyring.delete_password("claude-secrets-probe", "self")
        info["keychain_reachable"] = v == "ok"
    except Exception as e:
        info["keychain_reachable"] = False
        info["keychain_error"] = str(e)
    _emit(info)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude-secrets",
        description="Safe secret storage for Claude Code via macOS Keychain.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # prompt
    p_prompt = sub.add_parser("prompt", help="Pop dialog and store a value.")
    p_prompt.add_argument("name", help="Secret name (e.g., STRIPE_KEY)")
    p_prompt.add_argument("--description", help="Optional metadata")
    p_prompt.add_argument(
        "--timeout", type=int, default=120, help="Dialog timeout in seconds"
    )
    p_prompt.set_defaults(func=cmd_prompt)

    # list
    p_list = sub.add_parser("list", help="List stored names + metadata.")
    p_list.set_defaults(func=cmd_list)

    # rm
    p_rm = sub.add_parser("rm", help="Delete a secret.")
    p_rm.add_argument("name")
    p_rm.set_defaults(func=cmd_rm)

    # rotate
    p_rot = sub.add_parser("rotate", help="Replace a secret's value.")
    p_rot.add_argument("name")
    p_rot.add_argument("--description")
    p_rot.add_argument("--timeout", type=int, default=120)
    p_rot.add_argument("--force", action="store_true")
    p_rot.set_defaults(func=cmd_rotate)

    # run
    p_run = sub.add_parser("run", help="Exec command with secrets injected.")
    p_run.add_argument(
        "--inject",
        action="append",
        default=[],
        metavar="NAME=ENV_VAR",
        help="Inject secret NAME as env var ENV_VAR. May be repeated.",
    )
    p_run.add_argument(
        "--timeout", type=int, default=600, help="Command timeout in seconds"
    )
    p_run.add_argument("cmd", nargs=argparse.REMAINDER, help="-- COMMAND ...")
    p_run.set_defaults(func=cmd_run)

    # status
    p_status = sub.add_parser("status", help="Report broker state.")
    p_status.set_defaults(func=cmd_status)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    # `run` collects remainder including leading "--"; strip it.
    if hasattr(args, "cmd") and args.cmd and args.cmd[0] == "--":
        args.cmd = args.cmd[1:]

    try:
        args.func(args)
    except Exception as e:
        # Last-resort safety net; never let raw values escape via exception.
        _emit_err(f"unexpected error: {type(e).__name__}")


if __name__ == "__main__":
    main()
