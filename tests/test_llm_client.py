from app.core import llm_client


class _FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, *args, **kwargs):
        self.kwargs = kwargs
        return {"ok": True}


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.base_url = kwargs.get("base_url", "")
        self.chat = _FakeChat()


def _client(monkeypatch, base_url):
    monkeypatch.setattr(llm_client, "_OpenAI", _FakeClient)
    return llm_client.OpenAI(base_url=base_url, api_key="test")


def test_opencode_request_disables_reasoning_and_sets_reliable_budget(monkeypatch):
    client = _client(monkeypatch, "https://opencode.ai/zen/go/v1")

    client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "article"}],
        max_tokens=100,
    )

    kwargs = client.chat.completions._completions.kwargs
    assert kwargs["extra_body"] == {"reasoning_effort": "none"}
    assert kwargs["max_completion_tokens"] == 8192
    assert "max_tokens" not in kwargs


def test_opencode_preserves_explicit_provider_controls(monkeypatch):
    client = _client(monkeypatch, "https://opencode.ai/zen/v1")

    client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[],
        max_completion_tokens=2048,
        extra_body={"reasoning_effort": "high", "custom_flag": True},
    )

    kwargs = client.chat.completions._completions.kwargs
    assert kwargs["max_completion_tokens"] == 2048
    assert kwargs["extra_body"] == {
        "reasoning_effort": "high",
        "custom_flag": True,
    }


def test_opencode_does_not_override_explicit_thinking_mode(monkeypatch):
    client = _client(monkeypatch, "https://opencode.ai/zen/v1")

    client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[],
        extra_body={"thinking": {"type": "enabled"}},
    )

    kwargs = client.chat.completions._completions.kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}


def test_tokenrhythm_disables_thinking_and_normalizes_legacy_budget(monkeypatch):
    client = _client(monkeypatch, "https://tokenrhythm.studio/v1")

    client.chat.completions.create(
        model="deepseek-v4-pro-0813",
        messages=[],
        max_tokens=100,
    )

    kwargs = client.chat.completions._completions.kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert kwargs["max_completion_tokens"] == 8192
    assert "max_tokens" not in kwargs


def test_reasoning_gateway_replaces_null_completion_budget(monkeypatch):
    client = _client(monkeypatch, "https://opencode.ai/zen/v1")

    client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[],
        max_completion_tokens=None,
    )

    kwargs = client.chat.completions._completions.kwargs
    assert kwargs["max_completion_tokens"] == 8192


def test_non_opencode_requests_are_unchanged(monkeypatch):
    client = _client(monkeypatch, "https://api.deepseek.com/v1")

    client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[],
        max_tokens=100,
    )

    kwargs = client.chat.completions._completions.kwargs
    assert kwargs == {
        "model": "deepseek-v4-flash",
        "messages": [],
        "max_tokens": 100,
    }
