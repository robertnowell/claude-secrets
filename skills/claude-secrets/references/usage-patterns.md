# Usage patterns

Concrete examples of when and how to use each subcommand.

## ⚠️ Critical pattern: always wrap `run` commands in `bash -c '...'`

The broker exec's argv directly without a shell, so `$VAR` references in argv are passed as **literal strings**, not expanded.

```bash
# ❌ BROKEN — $K is literal, not expanded
claude-secrets run --inject STRIPE_KEY=K -- curl -H "Authorization: Bearer $K" https://api.stripe.com/v1/account
# curl sends header: "Authorization: Bearer $K"  →  401

# ✅ WORKS — bash -c opens a shell inside the subprocess where K is set
claude-secrets run --inject STRIPE_KEY=K -- bash -c '
  curl -H "Authorization: Bearer $K" https://api.stripe.com/v1/account
'
```

**Use single quotes around the bash -c body.** Single quotes prevent your outer shell from touching `$K`; the inner `bash -c` shell expands it at exec time inside the broker.

This pattern applies to **every** example below.

## Stripe API call

User: "Test that my Stripe key works."

```bash
# 1. Check if stored
claude-secrets list --json
# → if STRIPE_KEY not in the list:

# 2. Prompt user (popup appears, they type)
claude-secrets prompt STRIPE_KEY --json
# → {"status":"ok","name":"STRIPE_KEY","action":"stored"}

# 3. Use it
claude-secrets run --inject STRIPE_KEY=K -- bash -c '
  curl -s -H "Authorization: Bearer $K" https://api.stripe.com/v1/account
'
# → {"status":"ok","exit_code":0,"stdout":"{ ... account data ... }","stderr":""}
```

## GitHub Personal Access Token

```bash
claude-secrets prompt GITHUB_TOKEN --description "PAT with repo scope" --json

claude-secrets run --inject GITHUB_TOKEN=GH_PAT -- bash -c '
  gh api user --jq .login
'

# Or use directly with git:
claude-secrets run --inject GITHUB_TOKEN=GH_PAT -- bash -c '
  git push https://x:$GH_PAT@github.com/owner/repo.git main
'
```

## AWS credentials (multiple secrets, one invocation)

```bash
claude-secrets prompt AWS_ACCESS_KEY_ID --json
claude-secrets prompt AWS_SECRET_ACCESS_KEY --json

# aws CLI reads env vars directly — no $VAR expansion needed in argv,
# so this one works without bash -c:
claude-secrets run \
  --inject AWS_ACCESS_KEY_ID=AWS_ACCESS_KEY_ID \
  --inject AWS_SECRET_ACCESS_KEY=AWS_SECRET_ACCESS_KEY \
  -- aws s3 ls
```

## OpenAI API call

```bash
claude-secrets prompt OPENAI_API_KEY --json

claude-secrets run --inject OPENAI_API_KEY=OAI -- bash -c '
  curl -s https://api.openai.com/v1/models -H "Authorization: Bearer $OAI"
'
```

## Postmark / any service taking an X-... header

```bash
claude-secrets prompt POSTMARK_SERVER_TOKEN --json

claude-secrets run --inject POSTMARK_SERVER_TOKEN=PMT -- bash -c '
  curl -s -H "X-Postmark-Server-Token: $PMT" https://api.postmarkapp.com/server
'
```

## Rotating a leaked credential

```bash
# User says: "I think my Stripe key leaked, let me put a new one in."
claude-secrets rotate STRIPE_KEY --json
# Pops dialog again, overwrites the stored value. Old value gone.
```

## Cleaning up an unused credential

```bash
claude-secrets list --json
# Decide which one to remove.
claude-secrets rm OLD_SERVICE_KEY --json
```

## Checking broker health

```bash
claude-secrets status --json
# Returns:
# {"status":"ok","config_dir":"...","manifest_exists":true,"secret_count":3,"keychain_reachable":true}
# If keychain_reachable is false: macOS may have revoked Keychain access.
```

## When the user is over SSH (no WindowServer)

The `prompt` subcommand will fail with `osascript` error. Tell the user:

> "I can't pop a dialog over SSH. Run `claude-secrets prompt NAME` directly in a terminal on your laptop, then continue here."

After they store it locally, your `run` calls will work (because Keychain is local to their machine, not the SSH host).

## Negative cases — when NOT to use this

- **The credential is a one-off temp token** for a test. Just have the user paste it and you'll forget it after — don't fill up Keychain with throwaway values.
- **The credential is already in `~/.zshrc` as an exported env var**. You can just reference `$EXISTING_VAR` directly in your `run` (or any Bash command) without involving the broker.
- **The user is just asking you to look at code that mentions a credential** (e.g., reading a config file). They didn't ask you to use it.
