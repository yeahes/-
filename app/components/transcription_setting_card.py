from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, CardWidget, ComboBox, ComboBoxSettingCard
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    HyperlinkCard,
    RangeSettingCard,
    SettingCardGroup,
    SingleDirectionScrollArea,
    SwitchSettingCard,
)

from app.components.SpinBoxSettingCard import DoubleSpinBoxSettingCard

from ..common.config import cfg
from ..core.entities import (
    FasterWhisperModelEnum,
    TranscribeLanguageEnum,
    TranscribeModelEnum,
    VadMethodEnum,
    WhisperModelEnum,
)
from .EditComboBoxSettingCard import EditComboBoxSettingCard
from .FasterWhisperSettingWidget import FasterWhisperSettingWidget
from .LineEditSettingCard import LineEditSettingCard
from .Qwen3ASRSettingWidget import Qwen3ASRSettingWidget
from .WhisperAPISettingWidget import WhisperAPISettingWidget
from .WhisperCppSettingWidget import WhisperCppSettingWidget


class TranscriptionSettingCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # 设置界面堆叠
        self.stacked_widget = QStackedWidget(self)

        # 添加各个设置界面
        self.empty_widget = QWidget(self)  # 添加空白页面作为默认显示
        self.whisper_cpp_widget = WhisperCppSettingWidget(self)
        self.whisper_api_widget = WhisperAPISettingWidget(self)
        self.faster_whisper_widget = FasterWhisperSettingWidget(self)
        self.qwen3_asr_widget = Qwen3ASRSettingWidget(self)

        self.stacked_widget.addWidget(self.empty_widget)  # 添加空白页面
        self.stacked_widget.addWidget(self.whisper_cpp_widget)
        self.stacked_widget.addWidget(self.whisper_api_widget)
        self.stacked_widget.addWidget(self.faster_whisper_widget)
        self.stacked_widget.addWidget(self.qwen3_asr_widget)

        self.main_layout.addWidget(self.stacked_widget)
        self._setup_timeline_alignment_group()

    def _setup_timeline_alignment_group(self):
        self.timeline_group = SettingCardGroup(self.tr("转录时间轴增强"), self)
        self.stable_ts_alignment_card = SwitchSettingCard(
            FIF.ALIGNMENT,
            self.tr("词级时间轴对齐"),
            self.tr("转录后重新生成英文词级时间轴；FasterWhisper可用，Qwen3-ASR会自动跳过"),
            cfg.stable_ts_alignment_enabled,
            self.timeline_group,
        )
        self.timeline_backend_card = ComboBoxSettingCard(
            cfg.timeline_alignment_backend,
            FIF.ROBOT,
            self.tr("时间轴对齐后端"),
            self.tr("stable-ts为默认；WhisperX time-only只在最终阶段替换时间，不改变切分和翻译"),
            texts=["stable-ts", "whisperx", "whisperx-time-only"],
            parent=self.timeline_group,
        )
        self.stable_ts_model_card = ComboBoxSettingCard(
            cfg.stable_ts_alignment_model,
            FIF.ROBOT,
            self.tr("stable-ts对齐模型"),
            self.tr("模型越大越慢；large-v3-turbo为当前默认"),
            texts=["small.en", "medium.en", "large-v3", "large-v3-turbo"],
            parent=self.timeline_group,
        )
        self.timeline_group.addSettingCard(self.stable_ts_alignment_card)
        self.timeline_group.addSettingCard(self.timeline_backend_card)
        self.timeline_group.addSettingCard(self.stable_ts_model_card)
        self.main_layout.addWidget(self.timeline_group)
        self._sync_stable_ts_cards(cfg.transcribe_model.value.value)

    def on_model_changed(self, value):
        # 切换对应的设置界面
        if value == TranscribeModelEnum.WHISPER_CPP.value:
            self.stacked_widget.setCurrentWidget(self.whisper_cpp_widget)
        elif value == TranscribeModelEnum.WHISPER_API.value:
            self.stacked_widget.setCurrentWidget(self.whisper_api_widget)
        elif value == TranscribeModelEnum.FASTER_WHISPER.value:
            self.stacked_widget.setCurrentWidget(self.faster_whisper_widget)
        elif value == TranscribeModelEnum.QWEN3_ASR.value:
            self.stacked_widget.setCurrentWidget(self.qwen3_asr_widget)
        else:
            self.stacked_widget.setCurrentWidget(self.empty_widget)
        self._sync_stable_ts_cards(value)

    def _sync_stable_ts_cards(self, model_name: str):
        is_qwen3 = model_name == TranscribeModelEnum.QWEN3_ASR.value
        self.stable_ts_alignment_card.setEnabled(not is_qwen3)
        self.timeline_backend_card.setEnabled(not is_qwen3)
        self.stable_ts_model_card.setEnabled(not is_qwen3)
        if is_qwen3:
            self.stable_ts_alignment_card.setContent(
                self.tr("Qwen3-ASR已使用ForcedAligner生成词级时间轴；这里会自动跳过，避免重复对齐")
            )
            self.timeline_backend_card.setContent(
                self.tr("当前转录模型为Qwen3-ASR时不需要额外时间轴后端")
            )
            self.stable_ts_model_card.setContent(
                self.tr("当前转录模型为Qwen3-ASR时不需要stable-ts模型")
            )
        else:
            self.stable_ts_alignment_card.setContent(
                self.tr("转录后重新生成英文词级时间轴；会变慢，但切分后的字幕更容易贴近音频")
            )
            self.timeline_backend_card.setContent(
                self.tr("stable-ts为默认；whisperx会参与切分，whisperx-time-only只替换最终时间")
            )
            self.stable_ts_model_card.setContent(
                self.tr("模型越大越慢；large-v3-turbo为当前默认")
            )
