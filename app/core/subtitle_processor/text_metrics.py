import re
from typing import List


WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)?|\d+(?:\.\d+)?")
TARGET_ENGLISH_WORD_LIMIT = 14
HARD_ENGLISH_WORD_LIMIT = 16


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def word_tokens(text: str) -> List[str]:
    return WORD_RE.findall((text or "").lower())


def is_allowed_discourse_overflow(text: str, count: int, hard_limit: int) -> bool:
    """Allow one complete Plus/Oh lead-in above the hard display limit.

    This narrow exception avoids creating a one-word subtitle just to satisfy a
    numeric limit. It is shared by generation and audit code so the same cue
    cannot be accepted by one path and rejected by another.
    """
    normalized = str(text or "").strip()
    return bool(
        count == hard_limit + 1
        and re.match(r"^(?:plus|oh)\s*[,.]?\s+", normalized, re.IGNORECASE)
        and re.search(r"[.!?][\"')\]]*\s*$", normalized)
    )
