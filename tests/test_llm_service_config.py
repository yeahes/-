from types import SimpleNamespace
from unittest.mock import patch

from app.core.entities import AVAILABLE_LLM_SERVICES, LLMServiceEnum
from app.core.llm_service_config import LLMRuntimeConfig, resolve_llm_service_config
from app.core.task_factory import TaskFactory
from app.core.utils import podcast_learning_video


def _item(value):
    return SimpleNamespace(value=value)


def _config(service):
    return SimpleNamespace(
        llm_service=_item(service),
        openai_api_base=_item("https://openai.test/v1"),
        openai_api_key=_item("openai-key"),
        openai_model=_item("openai-model"),
        silicon_cloud_api_base=_item("https://silicon.test/v1"),
        silicon_cloud_api_key=_item("silicon-key"),
        silicon_cloud_model=_item("silicon-model"),
        deepseek_api_base=_item("https://deepseek.test/v1"),
        deepseek_api_key=_item("deepseek-key"),
        deepseek_model=_item("deepseek-v4-flash"),
        deepseek_full_translation_model=_item("deepseek-v4-pro"),
        opencode_go_api_base=_item("https://opencode.ai/zen/go/v1"),
        opencode_go_api_key=_item("opencode-go-key"),
        opencode_go_model=_item("deepseek-v4-flash"),
        opencode_go_full_translation_model=_item("deepseek-v4-flash"),
        ollama_api_base=_item("http://localhost:11434/v1"),
        ollama_api_key=_item("ollama"),
        ollama_model=_item("local-model"),
        lm_studio_api_base=_item("http://localhost:1234/v1"),
        lm_studio_api_key=_item("legacy-lm-studio-key"),
        lm_studio_model=_item("legacy-lm-studio-model"),
        gemini_api_base=_item("https://gemini.test/v1"),
        gemini_api_key=_item("legacy-gemini-key"),
        gemini_model=_item("legacy-gemini-model"),
        chatglm_api_base=_item("https://chatglm.test/v1"),
        chatglm_api_key=_item("legacy-chatglm-key"),
        chatglm_model=_item("legacy-chatglm-model"),
        public_api_base=_item("https://public.test/v1"),
        public_api_key=_item("legacy-public-key"),
        public_model=_item("legacy-public-model"),
    )


def test_visible_llm_services_include_go_and_hide_retired_choices():
    from app.common.config import cfg

    assert tuple(cfg.llm_service.validator.options) == AVAILABLE_LLM_SERVICES
    assert LLMServiceEnum.OPENCODE_GO in AVAILABLE_LLM_SERVICES
    assert LLMServiceEnum.DEEPSEEK in AVAILABLE_LLM_SERVICES
    assert LLMServiceEnum.LM_STUDIO not in AVAILABLE_LLM_SERVICES
    assert LLMServiceEnum.GEMINI not in AVAILABLE_LLM_SERVICES
    assert LLMServiceEnum.CHATGLM not in AVAILABLE_LLM_SERVICES
    assert LLMServiceEnum.PUBLIC not in AVAILABLE_LLM_SERVICES


def test_opencode_go_uses_isolated_credentials_and_role_models():
    resolved = resolve_llm_service_config(_config(LLMServiceEnum.OPENCODE_GO))

    assert resolved.service == LLMServiceEnum.OPENCODE_GO
    assert resolved.base_url == "https://opencode.ai/zen/go/v1"
    assert resolved.api_key == "opencode-go-key"
    assert resolved.model == "deepseek-v4-flash"
    assert resolved.full_translation_model == "deepseek-v4-flash"


def test_deepseek_official_does_not_read_opencode_go_credentials():
    resolved = resolve_llm_service_config(_config(LLMServiceEnum.DEEPSEEK))

    assert resolved.service == LLMServiceEnum.DEEPSEEK
    assert resolved.base_url == "https://deepseek.test/v1"
    assert resolved.api_key == "deepseek-key"
    assert resolved.model == "deepseek-v4-flash"
    assert resolved.full_translation_model == "deepseek-v4-pro"


def test_single_model_provider_uses_same_model_for_both_roles():
    resolved = resolve_llm_service_config(_config(LLMServiceEnum.OPENAI))

    assert resolved.model == "openai-model"
    assert resolved.full_translation_model == "openai-model"


def test_task_factory_freezes_opencode_go_role_models():
    runtime = LLMRuntimeConfig(
        service=LLMServiceEnum.OPENCODE_GO,
        base_url="https://opencode.ai/zen/go/v1",
        api_key="opencode-go-key",
        model="deepseek-v4-flash",
        full_translation_model="deepseek-v4-flash",
    )
    source = __file__
    with patch(
        "app.core.task_factory.resolve_llm_service_config",
        return_value=runtime,
    ):
        task = TaskFactory.create_subtitle_task(source)

    assert task.subtitle_config.base_url == runtime.base_url
    assert task.subtitle_config.api_key == runtime.api_key
    assert task.subtitle_config.llm_model == "deepseek-v4-flash"
    assert (
        task.subtitle_config.screen_subtitle_allocation_review_model
        == "deepseek-v4-flash"
    )
    assert (
        task.subtitle_config.screen_subtitle_full_translation_model
        == "deepseek-v4-flash"
    )


def test_podcast_vocab_uses_selected_provider_model():
    runtime = LLMRuntimeConfig(
        service=LLMServiceEnum.OPENCODE_GO,
        base_url="https://opencode.ai/zen/go/v1",
        api_key="opencode-go-key",
        model="deepseek-v4-flash",
        full_translation_model="deepseek-v4-flash",
    )
    with patch.object(
        podcast_learning_video,
        "resolve_llm_service_config",
        return_value=runtime,
    ):
        assert podcast_learning_video.current_llm_config() == (
            runtime.base_url,
            runtime.api_key,
            runtime.model,
        )


if __name__ == "__main__":
    test_visible_llm_services_include_go_and_hide_retired_choices()
    test_opencode_go_uses_isolated_credentials_and_role_models()
    test_deepseek_official_does_not_read_opencode_go_credentials()
    test_single_model_provider_uses_same_model_for_both_roles()
    test_task_factory_freezes_opencode_go_role_models()
    test_podcast_vocab_uses_selected_provider_model()
    print("LLM service configuration tests passed")
