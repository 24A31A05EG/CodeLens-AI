"""
Secret handling for CodeLens analysis.

Two layers of protection:

1. ``is_secret_file`` - files that should never be ingested at all (.env files,
   private keys, credential stores). The parser skips them.
2. ``redact_secrets`` - best-effort scrubbing of secret-looking values inside
   files that ARE ingested (config JSON, source with hard-coded tokens). It is
   applied to anything that is stored in chunks, returned in explanations,
   embedded in documentation, or placed into a model prompt.

Redaction is heuristic. It is defence in depth, not a guarantee.
"""

import os
import re

REDACTED = "[REDACTED]"

# File names / extensions that must never be read or analysed.
_SECRET_BASENAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    ".npmrc", ".pypirc", ".netrc", ".htpasswd",
    "credentials", "credentials.json", "service-account.json",
    "serviceaccount.json", "secrets.json", "secrets.yml", "secrets.yaml",
}
_SECRET_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".crt", ".cer"}


def is_secret_file(path: str) -> bool:
    """True for files that commonly hold secrets and must not be ingested."""
    base = os.path.basename(path.replace("\\", "/")).lower()
    if base.startswith(".env"):
        return True
    if base in _SECRET_BASENAMES:
        return True
    return os.path.splitext(base)[1] in _SECRET_EXTENSIONS


_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

# Well-known token formats.
_TOKEN_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),             # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),                 # OpenAI-style keys
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),          # Slack
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),                 # Google API key
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),  # JWT
]

# key = "value" / "key": "value" where the KEY NAME looks secret.
_SECRET_KEY_WORDS = (
    r"secret|passw(?:or)?d|passwd|token|api[_\-]?key|apikey|private[_\-]?key|"
    r"access[_\-]?key|auth[_\-]?key|client[_\-]?secret|credential|bearer"
)
_ASSIGNMENT_RE = re.compile(
    r"""(?P<lead>["']?[\w.\-]*(?:%s)[\w.\-]*["']?\s*[:=]\s*)(?P<q>["'`])(?P<val>[^"'`\n]{4,})(?P=q)"""
    % _SECRET_KEY_WORDS,
    re.IGNORECASE,
)
_URL_CREDENTIALS_RE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)


def redact_secrets(text: str) -> str:
    """Return ``text`` with secret-looking values replaced by ``[REDACTED]``."""
    if not text:
        return text
    text = _PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", text)
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _URL_CREDENTIALS_RE.sub(lambda m: f"{m.group('scheme')}{REDACTED}@", text)
    text = _ASSIGNMENT_RE.sub(
        lambda m: f"{m.group('lead')}{m.group('q')}{REDACTED}{m.group('q')}", text
    )
    return text


def looks_secret_key(name: str) -> bool:
    """True when a config KEY NAME suggests its value is sensitive."""
    return bool(re.search(_SECRET_KEY_WORDS, name or "", re.IGNORECASE))
