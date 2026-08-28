"""Provider-aware OpenAI client used by the application's LLM stages.

OpenCode's DeepSeek V4 route is OpenAI-compatible at the HTTP shape, but its
default reasoning behavior is not a drop-in match for the other providers.
Keep that adaptation here so individual pipeline stages do not grow their own
provider checks.
"""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

from openai import OpenAI as _OpenAI


REASONING_GATEWAY_DEFAULT_MAX_COMPLETION_TOKENS = 8192
OPENCODE_DEFAULT_REASONING_EFFORT = "none"


def is_opencode_base_url(base_url: object) -> bool:
    """Return whether a URL points at OpenCode Zen/Go."""

    parsed = urlsplit(str(base_url or ""))
    host = (parsed.hostname or "").casefold()
    path = (parsed.path or "").casefold()
    return host == "opencode.ai" and "/zen" in path


def is_tokenrhythm_base_url(base_url: object) -> bool:
    """Return whether a URL points at the TokenRhythm gateway."""

    return (urlsplit(str(base_url or "")).hostname or "").casefold() == (
        "tokenrhythm.studio"
    )


def provider_request_kwargs(
    base_url: object,
    kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Adapt one Chat Completions request for reasoning gateways.

    OpenCode's DeepSeek V4 route can spend the entire completion budget on
    hidden reasoning when the request does not explicitly disable it. Its
    legacy ``max_tokens`` handling is also inconsistent for long prompts.
    TokenRhythm exposes the same model family with a different switch:
    ``thinking.type=disabled``. Both gateways accept
    ``max_completion_tokens`` as the reliable output limit.

    Explicit ``extra_body.reasoning_effort``/``thinking`` and
    ``max_completion_tokens`` remain authoritative. A small legacy
    ``max_tokens`` from an API health check is widened to avoid a false
    negative caused solely by hidden reasoning.
    """

    adapted = dict(kwargs)
    raw_extra_body = adapted.get("extra_body")
    extra_body = dict(raw_extra_body) if isinstance(raw_extra_body, Mapping) else {}
    if is_opencode_base_url(base_url):
        if "reasoning_effort" not in extra_body and "thinking" not in extra_body:
            extra_body["reasoning_effort"] = OPENCODE_DEFAULT_REASONING_EFFORT
    elif is_tokenrhythm_base_url(base_url):
        if "reasoning_effort" not in extra_body and "thinking" not in extra_body:
            extra_body["thinking"] = {"type": "disabled"}
    else:
        return adapted
    adapted["extra_body"] = extra_body

    explicit_completion = adapted.get("max_completion_tokens")
    if not isinstance(explicit_completion, int) or explicit_completion <= 0:
        adapted.pop("max_completion_tokens", None)
        legacy_max = adapted.pop("max_tokens", None)
        if isinstance(legacy_max, int) and legacy_max > 0:
            # A tiny legacy cap is unsuitable for a reasoning model. Preserve
            # useful larger caps while ensuring enough room for a final JSON
            # or translation payload.
            adapted["max_completion_tokens"] = max(
                REASONING_GATEWAY_DEFAULT_MAX_COMPLETION_TOKENS,
                legacy_max,
            )
        else:
            adapted["max_completion_tokens"] = (
                REASONING_GATEWAY_DEFAULT_MAX_COMPLETION_TOKENS
            )
    return adapted


def opencode_request_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Backward-compatible helper for callers that only know OpenCode."""

    return provider_request_kwargs("https://opencode.ai/zen/v1", kwargs)


class _CompletionsProxy:
    def __init__(self, owner: "ProviderAwareOpenAI", completions: object):
        self._owner = owner
        self._completions = completions

    def create(self, *args: Any, **kwargs: Any) -> Any:
        kwargs = provider_request_kwargs(self._owner.base_url, kwargs)
        return self._completions.create(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._completions, name)


class _ChatProxy:
    def __init__(self, owner: "ProviderAwareOpenAI", chat: object):
        self._chat = chat
        self.completions = _CompletionsProxy(owner, chat.completions)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chat, name)


class ProviderAwareOpenAI:
    """Small delegating wrapper that preserves the synchronous OpenAI API."""

    def __init__(self, *args: Any, **kwargs: Any):
        self._client = _OpenAI(*args, **kwargs)
        self.base_url = str(self._client.base_url)
        self.chat = _ChatProxy(self, self._client.chat)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


# Keep the import replacement terse in modules that already use ``OpenAI``.
OpenAI = ProviderAwareOpenAI
