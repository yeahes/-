from dataclasses import dataclass
from typing import Any

from app.core.entities import LLMServiceEnum


@dataclass(frozen=True)
class LLMRuntimeConfig:
    service: LLMServiceEnum
    base_url: str
    api_key: str
    model: str
    full_translation_model: str


_SERVICE_FIELDS = {
    LLMServiceEnum.OPENAI: (
        "openai_api_base",
        "openai_api_key",
        "openai_model",
        None,
    ),
    LLMServiceEnum.SILICON_CLOUD: (
        "silicon_cloud_api_base",
        "silicon_cloud_api_key",
        "silicon_cloud_model",
        None,
    ),
    LLMServiceEnum.DEEPSEEK: (
        "deepseek_api_base",
        "deepseek_api_key",
        "deepseek_model",
        "deepseek_full_translation_model",
    ),
    LLMServiceEnum.OPENCODE_GO: (
        "opencode_go_api_base",
        "opencode_go_api_key",
        "opencode_go_model",
        "opencode_go_full_translation_model",
    ),
    LLMServiceEnum.OLLAMA: (
        "ollama_api_base",
        "ollama_api_key",
        "ollama_model",
        None,
    ),
    # Keep old settings files readable even though these services are no
    # longer selectable in the UI.
    LLMServiceEnum.LM_STUDIO: (
        "lm_studio_api_base",
        "lm_studio_api_key",
        "lm_studio_model",
        None,
    ),
    LLMServiceEnum.GEMINI: (
        "gemini_api_base",
        "gemini_api_key",
        "gemini_model",
        None,
    ),
    LLMServiceEnum.CHATGLM: (
        "chatglm_api_base",
        "chatglm_api_key",
        "chatglm_model",
        None,
    ),
    LLMServiceEnum.PUBLIC: (
        "public_api_base",
        "public_api_key",
        "public_model",
        None,
    ),
}


def _config_value(config: Any, field: str) -> str:
    item = getattr(config, field)
    return str(getattr(item, "value", item) or "").strip()


def resolve_llm_service_config(config: Any = None) -> LLMRuntimeConfig:
    if config is None:
        from app.common.config import cfg

        config = cfg

    raw_service = getattr(getattr(config, "llm_service"), "value", None)
    try:
        service = (
            raw_service
            if isinstance(raw_service, LLMServiceEnum)
            else LLMServiceEnum(raw_service)
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"不支持的 LLM 服务：{raw_service!r}") from error

    fields = _SERVICE_FIELDS.get(service)
    if fields is None:
        raise ValueError(f"尚未配置 LLM 服务：{service.value}")

    base_field, key_field, model_field, full_model_field = fields
    model = _config_value(config, model_field)
    full_model = (
        _config_value(config, full_model_field) if full_model_field else model
    )
    return LLMRuntimeConfig(
        service=service,
        base_url=_config_value(config, base_field),
        api_key=_config_value(config, key_field),
        model=model,
        full_translation_model=full_model or model,
    )
