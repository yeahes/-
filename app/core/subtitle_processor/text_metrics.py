import re
from typing import List


WORD_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)?|\d+(?:\.\d+)?")


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def word_tokens(text: str) -> List[str]:
    return WORD_RE.findall((text or "").lower())
