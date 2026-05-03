"""Shared token-counting utilities for the file context system."""

import logging

logger = logging.getLogger(__name__)


def _count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken if available, else rough estimate.

    Uses cl100k_base encoding (GPT-4 / GPT-3.5-turbo tokenizer) as a good
    general-purpose model.  Falls back to char/4 if tiktoken is not installed.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except (ImportError, Exception) as exc:
        logger.debug("tiktoken unavailable (%s), falling back to char/4", exc)
        return len(text) // 4


def _get_token_limit() -> int:
    """Return the file.limit config value (0 = no limit)."""
    try:
        from config import get

        raw = get("file.limit", 0)
        return int(raw) if raw else 0
    except Exception:
        return 0
