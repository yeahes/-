import re
from typing import Iterator, List, Match


# Python's Unicode-aware ``\w`` includes underscores, so use ``[^\W_]`` for
# letters/digits and keep meaningful in-token connectors.  This preserves
# surfaces such as Nestle-with-accent and R&D as one ledger word.
WORD_RE = re.compile(
    r"\d+(?:[.,]\d+)*(?:%|[^\W\d_]+[\u0300-\u036f]*)?|"
    r"[^\W\d_]+[\u0300-\u036f]*"
    r"(?:[-'\u2019&][^\W_]+[\u0300-\u036f]*)*",
    re.UNICODE,
)
SURFACE_WORD_RE = re.compile(
    r"(?:\d+(?:[.,]\d+)*(?:%|[^\W\d_]+[\u0300-\u036f]*)?|"
    r"[^\W\d_]+[\u0300-\u036f]*"
    r"(?:[-'\u2019&][^\W_]+[\u0300-\u036f]*)*)(?:[.,!?;:]+)?",
    re.UNICODE,
)
TARGET_ENGLISH_WORD_LIMIT = 14
HARD_ENGLISH_WORD_LIMIT = 16


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def word_tokens(text: str) -> List[str]:
    return [match.group(0).casefold() for match in WORD_RE.finditer(text or "")]


def surface_word_tokens(text: str) -> List[str]:
    return [match.group(0) for match in WORD_RE.finditer(text or "")]


def surface_word_matches(text: str) -> Iterator[Match[str]]:
    return SURFACE_WORD_RE.finditer(text or "")


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
