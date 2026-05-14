"""osascript dialog helpers.

Spawns native macOS hidden-answer (password) dialogs. The value the user types
flows from osascript stdout into the caller via subprocess.run(capture_output)
— never echoed to the calling process's own stdout. The caller is responsible
for piping the value to wherever it should land (keychain, exec env) without
printing it.

Validated empirically (2026-05-14): dialog renders from inside Claude Code's
Bash tool subprocess, hidden-answer field shows asterisks, returned text goes
through subprocess stdout but stays in this Python process unless we choose
to print it.
"""

import subprocess


class DialogCancelled(Exception):
    """User clicked Cancel or dismissed the dialog."""


class DialogTimedOut(Exception):
    """Dialog auto-dismissed after the timeout."""


def prompt_secret(name: str, *, timeout_sec: int = 120) -> str:
    """Pop a hidden-answer dialog. Returns the value the user typed.

    Args:
        name: Name displayed in the dialog (e.g., "STRIPE_KEY").
        timeout_sec: Auto-cancel after this many seconds.

    Raises:
        DialogCancelled: User clicked Cancel.
        DialogTimedOut: Dialog timed out before user submitted.
        RuntimeError: osascript failed for some other reason.
    """
    # Use multiple -e flags (canonical osascript multi-line pattern).
    # Backslash continuations inside a single -e string fail with
    # syntax error -2741.
    lines = [
        'tell application "System Events" to activate',
        'try',
        f'    set dlg to display dialog "Paste value for {name}:" with title "Claude Secrets" default answer "" with hidden answer buttons {{"Cancel", "Store"}} default button "Store" cancel button "Cancel" giving up after {timeout_sec}',
        '    if gave up of dlg is true then',
        '        return "::TIMEOUT::"',
        '    end if',
        '    return text returned of dlg',
        'on error errMsg number errNum',
        '    if errNum is -128 then',
        '        return "::CANCELLED::"',
        '    end if',
        '    error errMsg number errNum',
        'end try',
    ]
    cmd = ["osascript"]
    for line in lines:
        cmd.extend(["-e", line])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_sec + 5,
    )

    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")

    value = result.stdout.strip()

    if value == "::CANCELLED::":
        raise DialogCancelled()
    if value == "::TIMEOUT::":
        raise DialogTimedOut()

    # Empty value with no cancel/timeout marker is treated as cancellation.
    if not value:
        raise DialogCancelled()

    return value


def confirm(message: str, *, default: str = "Cancel") -> bool:
    """Pop a yes/no dialog. Returns True if user clicked OK.

    Used for destructive actions like rotate / rm.
    """
    lines = [
        'tell application "System Events" to activate',
        'try',
        f'    display dialog "{message}" with title "Claude Secrets" buttons {{"Cancel", "OK"}} default button "{default}" cancel button "Cancel" giving up after 60',
        '    return "OK"',
        'on error number -128',
        '    return "CANCEL"',
        'end try',
    ]
    cmd = ["osascript"]
    for line in lines:
        cmd.extend(["-e", line])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=65)
    return result.stdout.strip() == "OK"
