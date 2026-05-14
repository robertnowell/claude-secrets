"""Output sanitizer.

Two layers:
1. Pattern-based: regex set for known-format secrets (sk-*, ghp_*, JWT, etc.)
   Crib from secretctl + open-source secret-scanner regex collections.
2. Literal-match: byte-for-byte match against any value currently in our
   own keychain. Catches custom-format secrets.

Output: the input string with every match replaced by [REDACTED:<NAME>] or
[REDACTED:<pattern>].
"""

import re

# Pattern set (kept short; favor precision over recall)
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("openai", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("anthropic", re.compile(r"sk-ant-[A-Za-z0-9_-]{40,}")),
    ("github", re.compile(r"gh[opusr]_[A-Za-z0-9]{36,}")),
    ("slack", re.compile(r"xox[bpa]-[A-Za-z0-9-]{10,}")),
    ("aws_access", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws_session", re.compile(r"ASIA[0-9A-Z]{16}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_.+/=-]+")),
    ("google_api", re.compile(r"AIza[0-9A-Za-z\\-_]{35}")),
    ("private_key_pem", re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----[\s\S]+?-----END")),
]


def sanitize(text: str, known_values: list[tuple[str, str]] | None = None) -> str:
    """Redact secrets from text.

    Args:
        text: Output to sanitize.
        known_values: List of (name, value) pairs. Each value's literal
                      bytes are replaced with [REDACTED:<name>] anywhere
                      they appear in text.

    Returns:
        Sanitized text with all matches replaced.
    """
    if not text:
        return text

    # 1. Literal-match against known stored values (highest precision).
    if known_values:
        # Sort by length descending so longer values get replaced before
        # any of their substrings could match a shorter value.
        for name, value in sorted(known_values, key=lambda kv: -len(kv[1])):
            if value and value in text:
                text = text.replace(value, f"[REDACTED:{name}]")

    # 2. Pattern-based fallback for unknown / unstored secrets.
    for label, pat in PATTERNS:
        text = pat.sub(f"[REDACTED:{label}]", text)

    return text
