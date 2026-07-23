from PyQt5.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import ComboBoxSettingCard, SettingCardGroup
from qfluentwidgets import FluentIcon as FIF

from app.common.config import cfg
from app.components.LineEditSettingCard import LineEditSettingCard


class Qwen3ASRSettingWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.setting_group = SettingCardGroup(self.tr("Qwen3-ASR 设置"), self)

        self.python_card = LineEditSettingCard(
            cfg.qwen3_python,
            FIF.CODE,
            self.tr("Python路径"),
            self.tr("独立Qwen3-ASR环境中的python.exe路径"),
            self.tr("例如 E:\\VideoCaptioner-screen-subtitle\\qwen3-runtime\\Scripts\\python.exe"),
            self.setting_group,
        )
        self.asr_model_card = ComboBoxSettingCard(
            cfg.qwen3_asr_model,
            FIF.ROBOT,
            self.tr("ASR模型"),
            self.tr("6GB显存建议先使用0.6B；1.7B更强但更容易爆显存"),
            texts=[model.value for model in cfg.qwen3_asr_model.validator.options],
            parent=self.setting_group,
        )
        self.aligner_model_card = LineEditSettingCard(
            cfg.qwen3_aligner_model,
            FIF.CALENDAR,
            self.tr("ForcedAligner模型"),
            self.tr("用于生成词级时间戳"),
            "Qwen/Qwen3-ForcedAligner-0.6B",
            self.setting_group,
        )
        self.device_card = ComboBoxSettingCard(
            cfg.qwen3_device,
            FIF.SPEED_HIGH,
            self.tr("设备"),
            self.tr("优先使用CUDA；显存不足时改CPU但会很慢"),
            texts=["cuda", "cpu"],
            parent=self.setting_group,
        )
        self.dtype_card = ComboBoxSettingCard(
            cfg.qwen3_dtype,
            FIF.DEVELOPER_TOOLS,
            self.tr("精度"),
            self.tr("6GB显存建议float16"),
            texts=["float16", "bfloat16", "float32"],
            parent=self.setting_group,
        )

        self.setting_group.addSettingCard(self.python_card)
        self.setting_group.addSettingCard(self.asr_model_card)
        self.setting_group.addSettingCard(self.aligner_model_card)
        self.setting_group.addSettingCard(self.device_card)
        self.setting_group.addSettingCard(self.dtype_card)

        self.main_layout.addWidget(self.setting_group)
        self.main_layout.addStretch(1)
