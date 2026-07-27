# coding:utf-8
from enum import Enum

from PyQt5.QtCore import QLocale
from PyQt5.QtGui import QColor
import openai
from qfluentwidgets import (
    qconfig,
    QConfig,
    ConfigItem,
    OptionsConfigItem,
    BoolValidator,
    OptionsValidator,
    RangeConfigItem,
    RangeValidator,
    Theme,
    FolderValidator,
    ConfigSerializer,
    EnumSerializer,
)

from app.config import WORK_PATH, SETTINGS_PATH
from ..core.entities import (
    LLMServiceEnum,
    SplitTypeEnum,
    TargetLanguageEnum,
    TranscribeModelEnum,
    TranscribeLanguageEnum,
    TranslatorServiceEnum,
    WhisperModelEnum,
    FasterWhisperModelEnum,
    Qwen3ASRModelEnum,
    VadMethodEnum,
)


class Language(Enum):
    """软件语言"""

    CHINESE_SIMPLIFIED = QLocale(QLocale.Chinese, QLocale.China)
    CHINESE_TRADITIONAL = QLocale(QLocale.Chinese, QLocale.HongKong)
    ENGLISH = QLocale(QLocale.English)
    AUTO = QLocale()


class SubtitleLayoutEnum(Enum):
    """字幕布局"""

    TRANSLATE_ON_TOP = "译文在上"
    ORIGINAL_ON_TOP = "原文在上"
    ONLY_ORIGINAL = "仅原文"
    ONLY_TRANSLATE = "仅译文"


class LanguageSerializer(ConfigSerializer):
    """Language serializer"""

    def serialize(self, language):
        return language.value.name() if language != Language.AUTO else "Auto"

    def deserialize(self, value: str):
        return Language(QLocale(value)) if value != "Auto" else Language.AUTO


class Config(QConfig):
    """应用配置"""

    # LLM配置
    llm_service = OptionsConfigItem(
        "LLM",
        "LLMService",
        LLMServiceEnum.PUBLIC,
        OptionsValidator(LLMServiceEnum),
        EnumSerializer(LLMServiceEnum),
    )

    openai_model = ConfigItem("LLM", "OpenAI_Model", "gpt-4o-mini")
    openai_api_key = ConfigItem("LLM", "OpenAI_API_Key", "")
    openai_api_base = ConfigItem("LLM", "OpenAI_API_Base", "https://api.openai.com/v1")

    silicon_cloud_model = ConfigItem("LLM", "SiliconCloud_Model", "gpt-4o-mini")
    silicon_cloud_api_key = ConfigItem("LLM", "SiliconCloud_API_Key", "")
    silicon_cloud_api_base = ConfigItem(
        "LLM", "SiliconCloud_API_Base", "https://api.siliconflow.cn/v1"
    )

    deepseek_model = ConfigItem("LLM", "DeepSeek_Model", "deepseek-chat")
    deepseek_api_key = ConfigItem("LLM", "DeepSeek_API_Key", "")
    deepseek_api_base = ConfigItem(
        "LLM", "DeepSeek_API_Base", "https://api.deepseek.com/v1"
    )

    ollama_model = ConfigItem("LLM", "Ollama_Model", "llama2")
    ollama_api_key = ConfigItem("LLM", "Ollama_API_Key", "ollama")
    ollama_api_base = ConfigItem("LLM", "Ollama_API_Base", "http://localhost:11434/v1")

    lm_studio_model = ConfigItem("LLM", "LmStudio_Model", "qwen2.5:7b")
    lm_studio_api_key = ConfigItem("LLM", "LmStudio_API_Key", "lmstudio")
    lm_studio_api_base = ConfigItem(
        "LLM", "LmStudio_API_Base", "http://localhost:1234/v1"
    )

    gemini_model = ConfigItem("LLM", "Gemini_Model", "gemini-pro")
    gemini_api_key = ConfigItem("LLM", "Gemini_API_Key", "")
    gemini_api_base = ConfigItem(
        "LLM",
        "Gemini_API_Base",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    chatglm_model = ConfigItem("LLM", "ChatGLM_Model", "glm-4")
    chatglm_api_key = ConfigItem("LLM", "ChatGLM_API_Key", "")
    chatglm_api_base = ConfigItem(
        "LLM", "ChatGLM_API_Base", "https://open.bigmodel.cn/api/paas/v4"
    )

    # 公益模型
    public_model = ConfigItem("LLM", "Public_Model", "gpt-4o-mini")
    public_api_key = ConfigItem(
        "LLM", "Public_API_Key", "please-do-not-use-for-personal-purposes"
    )
    public_api_base = ConfigItem("LLM", "Public_API_Base", "https://ddg.bkfeng.top/v1")

    # ------------------- 翻译配置 -------------------
    translator_service = OptionsConfigItem(
        "Translate",
        "TranslatorServiceEnum",
        TranslatorServiceEnum.BING,
        OptionsValidator(TranslatorServiceEnum),
        EnumSerializer(TranslatorServiceEnum),
    )
    need_reflect_translate = ConfigItem(
        "Translate", "NeedReflectTranslate", False, BoolValidator()
    )
    deeplx_endpoint = ConfigItem("Translate", "DeeplxEndpoint", "")
    batch_size = RangeConfigItem("Translate", "BatchSize", 10, RangeValidator(5, 30))
    thread_num = RangeConfigItem("Translate", "ThreadNum", 10, RangeValidator(1, 100))

    # ------------------- 转录配置 -------------------
    transcribe_model = OptionsConfigItem(
        "Transcribe",
        "TranscribeModel",
        TranscribeModelEnum.BIJIAN,
        OptionsValidator(TranscribeModelEnum),
        EnumSerializer(TranscribeModelEnum),
    )
    use_asr_cache = ConfigItem("Transcribe", "UseASRCache", True, BoolValidator())
    transcribe_language = OptionsConfigItem(
        "Transcribe",
        "TranscribeLanguage",
        TranscribeLanguageEnum.ENGLISH,
        OptionsValidator(TranscribeLanguageEnum),
        EnumSerializer(TranscribeLanguageEnum),
    )

    # ------------------- Whisper Cpp 配置 -------------------
    whisper_model = OptionsConfigItem(
        "Whisper",
        "WhisperModel",
        WhisperModelEnum.TINY,
        OptionsValidator(WhisperModelEnum),
        EnumSerializer(WhisperModelEnum),
    )

    # ------------------- Faster Whisper 配置 -------------------
    faster_whisper_program = ConfigItem(
        "FasterWhisper",
        "Program",
        "faster-whisper-xxl.exe",
    )
    faster_whisper_model = OptionsConfigItem(
        "FasterWhisper",
        "Model",
        FasterWhisperModelEnum.TINY,
        OptionsValidator(FasterWhisperModelEnum),
        EnumSerializer(FasterWhisperModelEnum),
    )
    faster_whisper_model_dir = ConfigItem("FasterWhisper", "ModelDir", "")
    faster_whisper_device = OptionsConfigItem(
        "FasterWhisper", "Device", "cuda", OptionsValidator(["cuda", "cpu"])
    )
    # VAD 参数
    faster_whisper_vad_filter = ConfigItem(
        "FasterWhisper", "VadFilter", True, BoolValidator()
    )
    faster_whisper_vad_threshold = RangeConfigItem(
        "FasterWhisper", "VadThreshold", 0.4, RangeValidator(0, 1)
    )
    faster_whisper_vad_method = OptionsConfigItem(
        "FasterWhisper",
        "VadMethod",
        VadMethodEnum.SILERO_V4,
        OptionsValidator(VadMethodEnum),
        EnumSerializer(VadMethodEnum),
    )
    # 人声提取
    faster_whisper_ff_mdx_kim2 = ConfigItem(
        "FasterWhisper", "FfMdxKim2", False, BoolValidator()
    )
    # 文本处理参数
    faster_whisper_one_word = ConfigItem(
        "FasterWhisper", "OneWord", True, BoolValidator()
    )
    # 提示词
    faster_whisper_prompt = ConfigItem("FasterWhisper", "Prompt", "")

    # ------------------- Qwen3-ASR 配置 -------------------
    qwen3_python = ConfigItem(
        "Qwen3ASR",
        "Python",
        r"E:\VideoCaptioner-screen-subtitle\qwen3-runtime\Scripts\python.exe",
    )
    qwen3_asr_model = OptionsConfigItem(
        "Qwen3ASR",
        "ASRModel",
        Qwen3ASRModelEnum.QWEN3_ASR_06B,
        OptionsValidator(Qwen3ASRModelEnum),
        EnumSerializer(Qwen3ASRModelEnum),
    )
    qwen3_aligner_model = ConfigItem(
        "Qwen3ASR", "AlignerModel", "Qwen/Qwen3-ForcedAligner-0.6B"
    )
    qwen3_device = OptionsConfigItem(
        "Qwen3ASR", "Device", "cuda", OptionsValidator(["cuda", "cpu"])
    )
    qwen3_dtype = OptionsConfigItem(
        "Qwen3ASR", "DType", "float16", OptionsValidator(["float16", "bfloat16", "float32"])
    )

    # ------------------- Whisper API 配置 -------------------
    whisper_api_base = ConfigItem("WhisperAPI", "WhisperApiBase", "")
    whisper_api_key = ConfigItem("WhisperAPI", "WhisperApiKey", "")
    whisper_api_model = OptionsConfigItem("WhisperAPI", "WhisperApiModel", "")
    whisper_api_prompt = ConfigItem("WhisperAPI", "WhisperApiPrompt", "")

    # ------------------- 字幕配置 -------------------
    need_optimize = ConfigItem("Subtitle", "NeedOptimize", False, BoolValidator())
    need_translate = ConfigItem("Subtitle", "NeedTranslate", False, BoolValidator())
    need_split = ConfigItem("Subtitle", "NeedSplit", False, BoolValidator())
    split_type = OptionsConfigItem(
        "Subtitle",
        "SplitType",
        SplitTypeEnum.SENTENCE,
        OptionsValidator(SplitTypeEnum),
        EnumSerializer(SplitTypeEnum),
    )
    target_language = OptionsConfigItem(
        "Subtitle",
        "TargetLanguage",
        TargetLanguageEnum.CHINESE_SIMPLIFIED,
        OptionsValidator(TargetLanguageEnum),
        EnumSerializer(TargetLanguageEnum),
    )
    max_word_count_cjk = ConfigItem(
        "Subtitle", "MaxWordCountCJK", 25, RangeValidator(8, 100)
    )
    max_word_count_english = ConfigItem(
        "Subtitle", "MaxWordCountEnglish", 20, RangeValidator(8, 100)
    )
    needs_remove_punctuation = ConfigItem(
        "Subtitle", "NeedsRemovePunctuation", True, BoolValidator()
    )
    need_screen_subtitle_edit = ConfigItem(
        "Subtitle", "NeedScreenSubtitleEdit", False, BoolValidator()
    )
    screen_subtitle_stable_mode = ConfigItem(
        "Subtitle", "ScreenSubtitleStableMode", True, BoolValidator()
    )
    need_screen_subtitle_quality_check = ConfigItem(
        "Subtitle", "NeedScreenSubtitleQualityCheck", False, BoolValidator()
    )
    screen_subtitle_max_cjk = ConfigItem(
        "Subtitle", "ScreenSubtitleMaxCJK", 28, RangeValidator(8, 60)
    )
    screen_subtitle_max_english = ConfigItem(
        "Subtitle", "ScreenSubtitleMaxEnglish", 12, RangeValidator(6, 40)
    )
    screen_subtitle_allocation_max_concurrency = ConfigItem(
        "Subtitle", "ScreenSubtitleAllocationMaxConcurrency", 3, RangeValidator(1, 10)
    )
    screen_subtitle_allocation_batch_size = ConfigItem(
        "Subtitle", "ScreenSubtitleAllocationBatchSize", 16, RangeValidator(6, 24)
    )
    stable_ts_alignment_enabled = ConfigItem(
        "Subtitle", "StableTsAlignmentEnabled", True, BoolValidator()
    )
    timeline_alignment_backend = OptionsConfigItem(
        "Subtitle",
        "TimelineAlignmentBackend",
        "stable-ts",
        OptionsValidator(["stable-ts", "whisperx", "whisperx-time-only"]),
    )
    stable_ts_alignment_model = OptionsConfigItem(
        "Subtitle",
        "StableTsAlignmentModel",
        "large-v3-turbo",
        OptionsValidator(["small.en", "medium.en", "large-v3", "large-v3-turbo"]),
    )
    custom_prompt_text = ConfigItem("Subtitle", "CustomPromptText", "")

    # ------------------- 字幕合成配置 -------------------
    soft_subtitle = ConfigItem("Video", "SoftSubtitle", False, BoolValidator())
    need_video = ConfigItem("Video", "NeedVideo", True, BoolValidator())
    podcast_learning_template = ConfigItem(
        "Video", "PodcastLearningTemplate", False, BoolValidator()
    )
    podcast_template_ai_vocab = ConfigItem(
        "Video", "PodcastTemplateAiVocab", False, BoolValidator()
    )
    podcast_template_title = ConfigItem(
        "Video", "PodcastTemplateTitle", "为什么人工智能会改变教育?"
    )

    # ------------------- 字幕样式配置 -------------------
    subtitle_style_name = ConfigItem("SubtitleStyle", "StyleName", "default")
    subtitle_layout = ConfigItem("SubtitleStyle", "Layout", "译文在上")
    subtitle_preview_image = ConfigItem("SubtitleStyle", "PreviewImage", "")
    subtitle_render_mode = OptionsConfigItem(
        "SubtitleStyle",
        "RenderMode",
        "ASS样式",
        OptionsValidator(["ASS样式", "圆角背景"]),
    )
    rounded_font_name = ConfigItem("SubtitleStyle", "RoundedFontName", "")
    rounded_font_size = ConfigItem(
        "SubtitleStyle", "RoundedFontSize", 28, RangeValidator(8, 200)
    )
    rounded_text_color = ConfigItem("SubtitleStyle", "RoundedTextColor", "#FFFFFF")
    rounded_cjk_font_name = ConfigItem("SubtitleStyle", "RoundedCJKFontName", "")
    rounded_cjk_font_size = ConfigItem(
        "SubtitleStyle", "RoundedCJKFontSize", 28, RangeValidator(8, 200)
    )
    rounded_cjk_text_color = ConfigItem(
        "SubtitleStyle", "RoundedCJKTextColor", "#FFFFFF"
    )
    rounded_bg_color = ConfigItem("SubtitleStyle", "RoundedBgColor", "#191919C8")
    rounded_corner_radius = ConfigItem(
        "SubtitleStyle", "RoundedCornerRadius", 14, RangeValidator(0, 100)
    )
    rounded_padding_h = ConfigItem(
        "SubtitleStyle", "RoundedPaddingH", 18, RangeValidator(0, 200)
    )
    rounded_padding_v = ConfigItem(
        "SubtitleStyle", "RoundedPaddingV", 12, RangeValidator(0, 200)
    )
    rounded_margin_bottom = ConfigItem(
        "SubtitleStyle", "RoundedMarginBottom", 40, RangeValidator(0, 400)
    )
    rounded_line_spacing = ConfigItem(
        "SubtitleStyle", "RoundedLineSpacing", 8, RangeValidator(0, 100)
    )
    rounded_letter_spacing = ConfigItem(
        "SubtitleStyle", "RoundedLetterSpacing", 0, RangeValidator(0, 50)
    )

    # ------------------- 保存配置 -------------------
    work_dir = ConfigItem("Save", "Work_Dir", WORK_PATH, FolderValidator())

    # ------------------- 软件页面配置 -------------------
    micaEnabled = ConfigItem("MainWindow", "MicaEnabled", False, BoolValidator())
    dpiScale = OptionsConfigItem(
        "MainWindow",
        "DpiScale",
        "Auto",
        OptionsValidator([1, 1.25, 1.5, 1.75, 2, "Auto"]),
        restart=True,
    )
    language = OptionsConfigItem(
        "MainWindow",
        "Language",
        Language.AUTO,
        OptionsValidator(Language),
        LanguageSerializer(),
        restart=True,
    )

    # ------------------- 更新配置 -------------------
    checkUpdateAtStartUp = ConfigItem(
        "Update", "CheckUpdateAtStartUp", True, BoolValidator()
    )


cfg = Config()
cfg.themeMode.value = Theme.DARK
cfg.themeColor.value = QColor("#ff28f08b")
qconfig.load(SETTINGS_PATH, cfg)
