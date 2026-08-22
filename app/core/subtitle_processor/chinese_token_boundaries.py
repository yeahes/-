"""Shared deterministic Chinese token-boundary evidence for display pages."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.config import CACHE_PATH


logger = logging.getLogger(__name__)

_TOKENIZER = None
_TOKENIZER_LOCK = threading.Lock()


def _tokenizer():
    global _TOKENIZER
    if _TOKENIZER is not None:
        return _TOKENIZER
    with _TOKENIZER_LOCK:
        if _TOKENIZER is None:
            from app._vendor import jieba

            jieba.setLogLevel(logging.WARNING)
            tokenizer = jieba.Tokenizer(
                dictionary=str(Path(jieba.__file__).with_name("dict.txt"))
            )
            cache_dir = CACHE_PATH / "jieba"
            cache_dir.mkdir(parents=True, exist_ok=True)
            tokenizer.tmp_dir = str(cache_dir)
            tokenizer.cache_file = "visual-segmentation.cache"
            _TOKENIZER = tokenizer
    return _TOKENIZER


def chinese_tokens(text: str, *, hmm: bool = True) -> tuple[str, ...] | None:
    """Return deterministic tokens only when they reconstruct the exact input."""
    try:
        raw = str(text)
        tokens = tuple(
            str(token) for token in _tokenizer().cut(raw, HMM=bool(hmm))
        )
        return tokens if "".join(tokens) == raw else None
    except Exception:
        logger.exception("Chinese display tokenizer unavailable")
        return None


def chinese_token_boundaries(
    text: str,
    *,
    hmm: bool = True,
) -> dict[int, tuple[int, int]] | None:
    """Map every token-end character offset to adjacent token lengths.

    ``None`` means tokenization was unavailable or did not reconstruct the
    exact input. Callers that enforce a page contract must fail closed in that
    case instead of falling back to arbitrary character offsets.
    """
    tokens = chinese_tokens(text, hmm=hmm)
    if tokens is None:
        return None
    try:
        boundaries: dict[int, tuple[int, int]] = {}
        offset = 0
        for index, token in enumerate(tokens):
            offset += len(token)
            if index + 1 < len(tokens):
                boundaries[offset] = (len(token), len(tokens[index + 1]))
        return boundaries
    except Exception:
        logger.exception("Chinese display tokenizer unavailable")
        return None
