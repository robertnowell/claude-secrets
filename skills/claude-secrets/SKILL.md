---
name: claude-secrets
description: "When the user needs a credential to make an API call, store it once via a system popup, then reference it by name in any command. The value lives only in the macOS Keychain and the broker subprocess; it never enters this conversation."
allowed-tools: Bash
---

# Claude Secrets

This skill provides a safe way to use credentials without ever reading them. The user types a value into a native system popup, the broker stores it in macOS Keychain, and you reference it by name when running commands. The actual value never crosses into your context.

## The two commands you use

### 1. Storing a credential

When the user asks to set up a credential, run:

```bash
claude-secrets prompt NAME --json
```

Replace `NAME` with a clear identifier (e.g., `STRIPE_KEY`, `GITHUB_TOKEN`, `AWS_ACCESS_KEY`). A system popup appears on the user's screen — they type the value there. You see only:

```json
{"status":"ok","name":"STRIPE_KEY","action":"stored"}
```

If the user cancels: `{"status":"cancelled","name":"..."}`. If they don't type within 2 minutes: `{"status":"timeout","name":"..."}`. Handle gracefully.

### 2. Using a credential

When you need to use a stored credential, run:

```bash
claude-secrets run --inject NAME=ENV_VAR -- <command>
```

The broker reads the value from Keychain, exec's your command with `ENV_VAR` set, captures stdout and stderr, runs them through a sanitizer that redacts any byte-for-byte appearance of the value, and returns:

```json
{"status":"ok","exit_code":0,"stdout":"...","stderr":"..."}
```

Example — testing a Stripe API call:

```bash
claude-secrets run --inject STRIPE_KEY=K -- bash -c '
  curl -s -H "Authorization: Bearer $K" https://api.stripe.com/v1/charges
'
```

**Critical: wrap the command in `bash -c '...'`.** The broker exec's argv directly (no shell), so `$VAR` in argv is passed as a literal string. The `bash -c` wrapper opens a shell inside the subprocess where the env var actually expands. Without `bash -c`, your curl would send `Authorization: Bearer $K` literally and get a 401.

## Storing a credential you can fetch but must not see

When the value lives somewhere you can *read programmatically* (a database, another API, a decrypt call) but must never enter your context, use `store-from` instead of the popup. It runs a producer command, captures its stdout, and writes the stripped value straight to Keychain — you see only a byte count.

```bash
claude-secrets store-from NAME [--description D] [--inject SECRET=ENV ...] -- <producer-command>
```

The producer must print **only** the value to stdout (diagnostics to stderr) — its whole stripped stdout becomes the secret. A plausible byte count in the result confirms nothing else leaked. `--inject` lets the producer itself use other stored secrets (e.g. a DB URL). Example — decrypt a key out of a database and store it without ever printing it:

```bash
claude-secrets store-from SERVICE_KEY --inject DB_URL=DB_URL -- bash -c 'my-decrypt-tool --field api_key'
```

## Other commands

| Command | Purpose |
|---|---|
| `claude-secrets list --json` | List stored names + metadata (never values) |
| `claude-secrets rotate NAME --json` | Replace the value (pops dialog again) |
| `claude-secrets store-from NAME -- CMD` | Store a value from a command's stdout (never shown) |
| `claude-secrets rm NAME --json` | Delete a stored credential |
| `claude-secrets status --json` | Check if the broker is working |

## When to suggest storing a credential

When the user asks you to do something that needs an API key or token:
1. Run `claude-secrets list --json` first to check if it's already stored.
2. If not, suggest: "I can store your `<service>` key safely so I never see it — should I trigger the popup?"
3. On their yes, run `claude-secrets prompt NAME --json`.

## Anti-rules (load-bearing)

**Never run any of these.** They defeat the entire point.

- ❌ Never call `claude-secrets get NAME` — that subcommand does not exist; the broker has no read-to-stdout path on purpose.
- ❌ Never `cat ~/.config/claude-secrets/manifest.json` to "look at" the secret — the manifest stores names only, but reading it suggests you don't trust the design.
- ❌ Never run `echo $STRIPE_KEY` to "verify" a value works. The whole architecture exists so you cannot do this.
- ❌ Never copy a stored value out of a `run` invocation's output into chat. The sanitizer will redact it, but the intent is wrong.
- ❌ Never ask the user to "paste the key here so I can store it." If you find yourself typing those words, use `prompt` instead.

## See also

- [references/usage-patterns.md](references/usage-patterns.md) — concrete examples for Stripe, AWS, GitHub, OpenAI
- [references/anti-rules.md](references/anti-rules.md) — the full rationale for each anti-rule

## Limitations (be honest with the user)

- **macOS only in v1.** Linux and Windows are planned for v2.
- **First store prompts macOS** to allow the broker's Python process access to Keychain. The user clicks "Always Allow" once.
- **Sanitizer is best-effort.** It catches literal byte-for-byte appearances of stored values plus regex patterns for common formats (`sk-*`, `ghp_*`, JWT, AKIA*, etc.). It does NOT catch base64-encoded, URL-encoded, or otherwise transformed appearances of a value. If a command base64-encodes the credential and prints it, the encoded form will reach the user.
- **Headless / SSH sessions**: the popup needs a WindowServer connection. If the user is over SSH without forwarding, `prompt` will fail; tell them to run `claude-secrets prompt NAME` locally on their machine.
