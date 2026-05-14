# Anti-rules — and why each one matters

These are not stylistic preferences. Each one closes a specific leak path. Violating any of them puts the user's credential into your context window, into the conversation transcript on disk, and into whatever logs that transcript later flows through.

## ❌ Never call a `get` subcommand

It does not exist. The broker exposes `prompt`, `list`, `rm`, `rotate`, `run`, `status`. There is no `get` because returning the value to stdout would put it in your `tool_result`. If you find yourself wanting it, you want `run` instead — `run` reads the value into a subprocess's env, exec's your command, and returns only the sanitized output.

## ❌ Never `cat ~/.config/claude-secrets/manifest.json` to "look up" a secret

The manifest stores only names and timestamps — values live in Keychain. So reading it won't actually leak anything. **But the instinct is wrong.** If you find yourself wanting to inspect storage, you don't trust the design, which means you'll soon try harder to inspect it. The user installed this skill because they want a system you can't peek inside. Don't peek.

## ❌ Never `echo $VAR` to verify a credential

Inside a `run --inject NAME=VAR -- cmd` subprocess, the env var IS the value. `echo $VAR` prints it. The sanitizer catches it on the way back to you — but only by literal-match against the stored value. If the user's actual credential happens to be a substring of common English (extremely rare but possible), or if the command somehow transforms the value before printing, sanitization can fail. The right instinct: if you need to verify the credential works, make a real API call (`curl /v1/account`), don't introspect.

## ❌ Never paste a value out of `run` output into chat

If a `run` invocation returns something like `Token: [REDACTED:STRIPE_KEY] is valid`, leave the `[REDACTED]` marker as-is. Don't try to "reconstruct" the value by referencing it elsewhere. Don't tell the user "looks like the value is the Stripe key starting with sk_live_..." — even saying the prefix can be enough.

## ❌ Never ask the user "paste the key here so I can store it"

This is the most important rule. The entire point of this skill is to give you a way to **avoid** asking that question. If you find yourself typing those words, stop, run `claude-secrets prompt NAME` instead, and the user gets a popup that puts the value in Keychain without it ever touching the chat.

If the user volunteers to paste a value in chat anyway, gently redirect: "Actually, let me set up a popup — that way the value stays out of our conversation history."

## ❌ Never use `claude-secrets run` to read the value into a variable you then print

Anti-pattern:
```bash
claude-secrets run --inject STRIPE_KEY=K -- bash -c 'echo "value is: $K"'
```

The sanitizer DOES redact this back to `value is: [REDACTED:STRIPE_KEY]`, but the intent of the command is wrong — it's trying to exfiltrate. Use `run` only for legitimate API calls or commands that consume the credential without printing it.

## ❌ Never store the same credential in multiple stores

If the user has the credential in `~/.zshrc` already, don't ALSO `claude-secrets prompt` it. Pick one source of truth. The broker's storage is intended for credentials the user doesn't already have somewhere else.

## ❌ Never tell the user the broker is "perfect security"

It isn't. Specific limits:
- Sanitization is best-effort literal-match + regex; transformed values (base64-encoded, hashed-and-shown) won't be caught
- Anyone with the user's macOS login session can read from Keychain via API
- The audit log is informational, not tamper-proof
- A malicious skill running in the same Claude session could call `claude-secrets run` and exfiltrate via a crafted command

The broker raises the bar dramatically against accidental leaks. It does not eliminate them.

## ❌ Never default to suggesting the broker for everything

If the user is doing analytics on their own dataset, building UI components, or any non-credential work, don't suggest storing anything. The broker is for credentials. Mentioning it elsewhere is noise.

## The single positive rule

**When you need a credential, use the broker. When you don't, don't.**

That's the entire skill.
