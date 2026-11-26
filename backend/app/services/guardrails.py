import re

# High-precision prompt injection signatures (adversarial override phrases)
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(
        r"disregard\s+(all\s+)?(previous|prior|system)\s+(instructions|rules|prompts)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(reveal|print|output|show|leak)\s+(your\s+)?(system\s+prompt|hidden\s+instructions)",
        re.IGNORECASE,
    ),
    re.compile(r"system\s+override\s*:", re.IGNORECASE),
    re.compile(r"<\s*/?\s*retrieved_context\s*>", re.IGNORECASE),
]

# High-confidence PII & secret patterns redacted before outbound LLM calls
_REDACTION_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(r"\b(?:sk|pk)-(?:proj-|live-|lf-|ant-)?[A-Za-z0-9_-]{20,}\b"),
        "[REDACTED_API_KEY]",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), lambda m: _mask_card_if_luhn_length(m.group(0))),  # type: ignore[arg-type]
]


def _mask_card_if_luhn_length(candidate: str) -> str:
    """Mask 13-16 digit credit card numbers using Luhn check to avoid corrupting normal numbers."""
    digits = [int(ch) for ch in candidate if ch.isdigit()]
    if not (13 <= len(digits) <= 16):
        return candidate
    # Avoid false positives on simple hyphenated dates/identifiers unless Luhn passes
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return "[REDACTED_CARD]" if checksum % 10 == 0 else candidate


def detect_prompt_injection(text: str) -> bool:
    """Return True if text matches known prompt-injection override patterns."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def redact_pii(text: str) -> str:
    """Redact high-confidence secrets and PII (SSNs, private keys, API keys, Luhn cards)."""
    if not text:
        return text
    cleaned = text
    for pattern, replacement in _REDACTION_RULES:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned
