# claude-secrets

> Paste an API key into a system popup, store it in macOS Keychain, then reference it by name from any command. The value never enters Claude's context window.

A Claude Code plugin that solves a specific problem: how do you let Claude use your credentials without ever showing them to Claude?

## The problem

Every existing answer breaks somehow:

- **`~/.zshrc` env vars** — work, but Claude can `echo $STRIPE_KEY` to introspect, and the values end up in tool output if commands echo them
- **Paste in chat** — the value lives in the conversation transcript on disk forever
- **secretctl** — stores its own master password in `~/.claude.json` plaintext
- **`security` CLI** — `find-generic-password -w` prints the value to stdout, which becomes Claude's `tool_result`
- **OAuth MCP servers** — work great but only for services that support OAuth

This plugin combines a tested pattern: a native macOS popup (osascript hidden-answer dialog) pipes the typed value directly into a Python process that stores it in Keychain. Claude orchestrates but never observes.

## Install

```
/plugin marketplace add startx-founders/claude-skills
/plugin install claude-secrets@startx-founders
```

First session after install spends ~10 seconds installing the `keyring` Python library into the plugin's venv. Once.

## Use

In Claude Code, just talk:

> "Help me test my Stripe API integration."

Claude (with this skill loaded) will:

1. Run `claude-secrets list` — sees no `STRIPE_KEY` yet
2. Suggest: "I'll trigger a popup so you can paste the key — it won't go through chat."
3. Run `claude-secrets prompt STRIPE_KEY` — system popup appears
4. You type the value, click Store
5. Run `claude-secrets run --inject STRIPE_KEY=K -- curl -H "Authorization: Bearer $K" https://api.stripe.com/v1/charges`
6. Show you the response with the key redacted from any echoes

The value lives in macOS Keychain. Claude's context shows only command output with `[REDACTED:STRIPE_KEY]` wherever the value would have appeared.

## Architecture

```
USER                CLAUDE                BROKER                KEYCHAIN
 │                    │                     │                     │
 │  "test stripe"     │                     │                     │
 ├───────────────────►│                     │                     │
 │                    │ list                │                     │
 │                    ├────────────────────►│                     │
 │                    │ STRIPE_KEY missing  │                     │
 │                    │◄────────────────────┤                     │
 │                    │ prompt STRIPE_KEY   │                     │
 │                    ├────────────────────►│                     │
 │  ┌───────────┐     │                     │                     │
 │  │  popup    │◄────┼─────────────────────┤                     │
 │  │ type sk_..│     │                     │                     │
 │  └─────┬─────┘     │                     │                     │
 │        │           │                     │  set                │
 │        ╰───────────┼─────────────────────┼────────────────────►│
 │                    │ {"status":"ok"}     │                     │
 │                    │◄────────────────────┤                     │
 │                    │ run --inject ... -- curl ...              │
 │                    ├────────────────────►│  get                │
 │                    │                     ├────────────────────►│
 │                    │                     │  value              │
 │                    │                     │◄────────────────────┤
 │                    │                     │  ┌──────────────┐   │
 │                    │                     │  │ subprocess   │   │
 │                    │                     │  │ env=K=value  │   │
 │                    │                     │  │ exec curl... │   │
 │                    │                     │  └──────┬───────┘   │
 │                    │                     │         │ stdout    │
 │                    │                     │◄────────╯           │
 │                    │ sanitized output    │                     │
 │                    │◄────────────────────┤                     │
 │  results           │                     │                     │
 │◄───────────────────┤                     │                     │
```

The value's journey: popup → osascript stdout → broker Python stdin → keyring → SecKeychain. Going out: SecKeychain → keyring → broker process memory → subprocess env → command. **Never crosses into Claude's stdio**.

## Manual use (without Claude)

You can run the broker directly from a terminal:

```bash
# After SessionStart hook installs the venv on first Claude Code session,
# or set up manually:
cd /path/to/claude-secrets
python3 -m venv .venv
.venv/bin/pip install -r pipeline/requirements.txt

# Then:
.venv/bin/python -m pipeline.claude_secrets prompt MY_KEY
.venv/bin/python -m pipeline.claude_secrets list
.venv/bin/python -m pipeline.claude_secrets run --inject MY_KEY=K -- env | grep K
.venv/bin/python -m pipeline.claude_secrets rm MY_KEY
```

## Subcommands

| Command | Effect | Claude sees |
|---|---|---|
| `prompt NAME` | Pop dialog, store value in Keychain | `{"status":"ok","name":"NAME","action":"stored"}` |
| `list` | List names + metadata | `{"status":"ok","secrets":[{"name":"...","added":"...","description":"..."},...]}` |
| `rm NAME` | Delete a stored credential | `{"status":"ok","name":"NAME","action":"deleted"}` |
| `rotate NAME` | Pop dialog to replace existing value | Same as `prompt` |
| `run --inject N=V -- cmd` | Exec command with secret injected as env var | `{"status":"ok","exit_code":N,"stdout":"...","stderr":"..."}` with values redacted |
| `status` | Report broker health | `{"status":"ok","secret_count":N,"keychain_reachable":true}` |

## Limitations

- **macOS only in v1.** The popup uses `osascript`. Linux (zenity) and Windows (PowerShell) are planned for v2.
- **First Keychain write triggers a macOS prompt** asking permission for the Python binary to access Keychain. Click "Always Allow" once.
- **Sanitization is best-effort.** Literal byte-for-byte match against stored values + regex patterns for common formats (`sk-*`, `ghp_*`, `xox[bp]-*`, JWT, AKIA*). It does NOT catch base64-encoded, URL-encoded, or otherwise transformed appearances.
- **Headless / SSH sessions** can't pop the dialog. Run `claude-secrets prompt NAME` locally on your laptop instead.
- **The audit log is informational, not tamper-proof.** If you want a real audit trail, log to an external system.

## Security model

What this protects against:
- Pasting a credential into Claude's chat transcript
- Claude reading a credential out of `~/.zshrc` and echoing it back
- A credential appearing in a tool result because curl reflected an auth header
- A credential persisting in `~/.claude/projects/*.jsonl` files

What this does NOT protect against:
- A malicious skill running in the same Claude session that invokes `claude-secrets run` with a crafted command that exfiltrates via DNS or some other side channel
- Anyone with your macOS login session reading from Keychain
- Future Claude Code bugs that change what's logged

The threat model is "an honest LLM operating with normal tool permissions." It's not adversarial.

## Why not [other tool]

| Tool | Why not |
|---|---|
| 1Password CLI | Great if you have 1Password. This plugin is the no-account local-only alternative. |
| HashiCorp Vault | Overkill for one developer. |
| secretctl | Architecturally close but stores its master password in `~/.claude.json` plaintext. |
| q-ring | Uses native keyring like we do, but AGPL license is restrictive. |
| Agent Vault | MITM proxy architecture is correct but requires running a server. Overkill for personal use. |
| `pass` / `gopass` | Designed for terminal use, not LLM use. No sanitization of LLM-visible output. |

If you have 1Password, install [claude-code-1password-skill](https://github.com/kcmadden/claude-code-1password-skill) instead. This plugin is for everyone else.

## License

MIT. See [LICENSE](LICENSE).
