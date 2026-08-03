from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QToolButton, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import MessageBoxBase, SwitchSettingCard, ComboBoxSettingCard

from app.common.config import cfg
from app.components.SpinBoxSettingCard import SpinBoxSettingCard
from app.core.entities import SplitTypeEnum


class SubtitleSettingDialog(MessageBoxBase):
    """字幕设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = BodyLabel(self.tr("字幕设置"), self)

        # 创建设置卡片
        self.split_card = SwitchSettingCard(
            FIF.ALIGNMENT,
            self.tr("字幕分割"),
            self.tr("使用大语言模型整理语义句；开启上屏稳定模式时，此处只做语义粗切"),
            cfg.need_split,
            self,
        )

        self.split_type_card = ComboBoxSettingCard(
            cfg.split_type,
            FIF.TILES,
            self.tr("字幕分割类型"),
            self.tr("根据句子或者根据语义对字幕进行断句"),
            texts=[model.value for model in cfg.split_type.validator.options],
            parent=self,
        )

        self.word_count_cjk_card = SpinBoxSettingCard(
            cfg.max_word_count_cjk,
            FIF.TILES,
            self.tr("中文最大字数"),
            self.tr("单条字幕的最大字数 (对于中日韩等字符)"),
            minimum=8,
            maximum=50,
            parent=self,
        )

        self.word_count_english_card = SpinBoxSettingCard(
            cfg.max_word_count_english,
            FIF.TILES,
            self.tr("英文最大单词数"),
            self.tr("单条字幕的最大单词数 (英文)"),
            minimum=8,
            maximum=50,
            parent=self,
        )

        self.remove_punctuation_card = SwitchSettingCard(
            FIF.ALIGNMENT,
            self.tr("去除末尾标点符号"),
            self.tr("是否去除中文字幕中的末尾标点符号"),
            cfg.needs_remove_punctuation,
            self,
        )

        self.stable_mode_card = SwitchSettingCard(
            FIF.TILES,
            self.tr("\u7a33\u5b9a\u53cc\u8bed\u5b57\u5e55"),
            self.tr("\u672c\u5730\u5207\u82f1\u6587\uff0c\u6a21\u578b\u53ea\u5199\u4e2d\u6587\uff0c\u4fdd\u62a4\u65f6\u95f4\u8f74\u548c\u82f1\u6587\u539f\u6587"),
            cfg.need_screen_subtitle_edit,
            self,
        )

        self.stable_mode_status = BodyLabel(
            self.tr(
                "\u6d41\u7a0b\uff1a\u8bcd\u7ea7\u65f6\u95f4\u8f74 -> \u82f1\u6587\u8bed\u6cd5\u5207\u5206 -> \u4e2d\u6587\u7ffb\u8bd1 -> \u8986\u76d6\u68c0\u67e5\u3002"
                "\u82f1\u6587\u957f\u5ea6\u770b\u4e0b\u65b9\u8f6f\u4e0a\u9650\u3002"
            ),
            self,
        )
        self.stable_mode_status.setWordWrap(True)

        self.legacy_settings_status = BodyLabel(
            self.tr(
                "\u666e\u901a/\u517c\u5bb9\u8bbe\u7f6e\uff1a\u7a33\u5b9a\u6a21\u5f0f\u4e0b\u4fdd\u6301\u9ed8\u8ba4\u5373\u53ef\uff0c"
                "\u53ea\u5728\u5173\u95ed\u7a33\u5b9a\u6a21\u5f0f\u6216\u9700\u8981\u7c97\u5206\u7ec4\u65f6\u8c03\u6574\u3002"
            ),
            self,
        )
        self.legacy_settings_status.setWordWrap(True)

        self.chinese_polish_card = SwitchSettingCard(
            FIF.EDIT,
            self.tr("中文字幕润色"),
            self.tr("仅润色本地检查出的高风险中文；不改英文、时间轴或字幕条数"),
            cfg.screen_subtitle_chinese_polish,
            self,
        )

        self.screen_cjk_card = SpinBoxSettingCard(
            cfg.screen_subtitle_max_cjk,
            FIF.TILES,
            self.tr("上屏中文字幕软上限"),
            self.tr("校正时尽量控制单条中文字幕字数，允许必要时略微超出"),
            minimum=8,
            maximum=60,
            parent=self,
        )

        self.screen_english_card = SpinBoxSettingCard(
            cfg.screen_subtitle_max_english,
            FIF.TILES,
            self.tr("上屏英文词数软上限"),
            self.tr("稳定模式低于16时仍按16作为硬容错，避免把完整意群切碎"),
            minimum=6,
            maximum=40,
            parent=self,
        )

        self.allocation_concurrency_card = SpinBoxSettingCard(
            cfg.screen_subtitle_allocation_max_concurrency,
            FIF.TILES,
            self.tr("中文分配并发"),
            self.tr("只并发请求中文逐条分配；不改变字幕切分、提示词、ID 或最终写回。建议 3，最高 10。"),
            minimum=1,
            maximum=10,
            parent=self,
        )
        self.allocation_batch_size_card = SpinBoxSettingCard(
            cfg.screen_subtitle_allocation_batch_size,
            FIF.TILES,
            self.tr("中文分配批大小"),
            self.tr("每次请求分配的语义组数量；较小更稳，较大可能单次返回更慢。默认 16。"),
            minimum=6,
            maximum=24,
            parent=self,
        )

        self.production_status = BodyLabel(
            self.tr("生产流程：词级时间轴 -> 本地英文切分 -> 固定 ID 中文分配 -> 覆盖检查"),
            self,
        )
        self.production_status.setWordWrap(True)

        self.performance_section = QWidget(self)
        performance_layout = QVBoxLayout(self.performance_section)
        performance_layout.setContentsMargins(0, 0, 0, 0)
        performance_layout.setSpacing(10)
        performance_layout.addWidget(self.allocation_concurrency_card)
        performance_layout.addWidget(self.allocation_batch_size_card)

        self.compatibility_section = QWidget(self)
        compatibility_layout = QVBoxLayout(self.compatibility_section)
        compatibility_layout.setContentsMargins(0, 0, 0, 0)
        compatibility_layout.setSpacing(10)
        compatibility_layout.addWidget(self.legacy_settings_status)
        compatibility_layout.addWidget(self.split_card)
        compatibility_layout.addWidget(self.split_type_card)
        compatibility_layout.addWidget(self.word_count_cjk_card)
        compatibility_layout.addWidget(self.word_count_english_card)
        compatibility_layout.addWidget(self.remove_punctuation_card)

        self.performance_toggle = self._create_section_toggle(
            self.tr("高级性能设置"), self.performance_section, expanded=False
        )
        self.compatibility_toggle = self._create_section_toggle(
            self.tr("兼容旧流程设置"), self.compatibility_section, expanded=False
        )

        # 添加到布局
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.production_status)
        self.viewLayout.addWidget(self.stable_mode_card)
        self.viewLayout.addWidget(self.stable_mode_status)
        self.viewLayout.addWidget(self.chinese_polish_card)
        self.viewLayout.addWidget(self.screen_cjk_card)
        self.viewLayout.addWidget(self.screen_english_card)
        self.viewLayout.addWidget(self.performance_toggle)
        self.viewLayout.addWidget(self.performance_section)
        self.viewLayout.addWidget(self.compatibility_toggle)
        self.viewLayout.addWidget(self.compatibility_section)
        self.stable_mode_card.checkedChanged.connect(self._sync_legacy_split_controls)
        self._sync_legacy_split_controls(self.stable_mode_card.isChecked())
        # 设置间距

        self.viewLayout.setSpacing(10)
        self.setMinimumSize(760, 600)
        self.resize(760, 660)

        # 设置窗口标题
        self.setWindowTitle(self.tr("字幕设置"))

        # 只显示取消按钮
        self.yesButton.hide()
        self.cancelButton.setText(self.tr("关闭"))

    def _create_section_toggle(
        self,
        title: str,
        content: QWidget,
        *,
        expanded: bool,
    ) -> QToolButton:
        toggle = QToolButton(self)
        toggle.setText(title)
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setStyleSheet(
            "QToolButton { font-weight: 600; padding: 6px 0; text-align: left; }"
        )
        content.setVisible(expanded)
        toggle.toggled.connect(
            lambda checked: self._set_section_expanded(toggle, content, checked)
        )
        return toggle

    def _set_section_expanded(
        self,
        toggle: QToolButton,
        content: QWidget,
        expanded: bool,
    ) -> None:
        content.setVisible(expanded)
        toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.adjustSize()

    def _sync_legacy_split_controls(self, screen_subtitle_enabled: bool) -> None:
        """Keep compatibility controls from implying they own stable cutting."""
        stable_mode_active = bool(screen_subtitle_enabled) and bool(
            cfg.screen_subtitle_stable_mode.value
        )
        legacy_cards = (
            self.split_card,
            self.split_type_card,
            self.word_count_cjk_card,
            self.word_count_english_card,
        )
        for card in legacy_cards:
            card.setEnabled(not stable_mode_active)

        if stable_mode_active:
            self.legacy_settings_status.setText(
                self.tr(
                    "兼容切分设置：稳定模式已固定使用词级英语语法切分；"
                    "这些设置不参与最终英文边界，也不会影响字幕 ID。"
                )
            )
        else:
            self.legacy_settings_status.setText(
                self.tr(
                    "普通/兼容设置：关闭上屏稳定模式后，可在这里选择传统断句方式和长度。"
                )
            )
