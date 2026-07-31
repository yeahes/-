from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget
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
            self.tr("\u4e0a\u5c4f\u7a33\u5b9a\u6a21\u5f0f"),
            self.tr("\u672c\u5730\u5207\u82f1\u6587\uff0c\u6a21\u578b\u53ea\u7ffb\u4e2d\u6587\uff0c\u4fdd\u62a4\u65f6\u95f4\u8f74\u548c\u82f1\u6587\u539f\u6587"),
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

        self.screen_quality_check_card = SwitchSettingCard(
            FIF.SEARCH,
            self.tr("\u4e0a\u5c4f\u5019\u9009\u8d28\u68c0"),
            self.tr("\u4e8c\u6b21\u68c0\u67e5\u53ef\u7591\u65ad\u53e5\uff0c\u4f1a\u589e\u52a0 Token \u6d88\u8017"),
            cfg.need_screen_subtitle_quality_check,
            self,
        )

        self.safe_auto_repair_card = SwitchSettingCard(
            FIF.ACCEPT,
            self.tr("自动复查与安全修复"),
            self.tr("只修缺中文、严重超速、句首标点和明显重复中文；不改英文和时间轴"),
            cfg.screen_subtitle_safe_auto_repair,
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

        # 添加到布局
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.stable_mode_card)
        self.viewLayout.addWidget(self.stable_mode_status)
        self.viewLayout.addWidget(self.screen_quality_check_card)
        self.viewLayout.addWidget(self.safe_auto_repair_card)
        self.viewLayout.addWidget(self.screen_cjk_card)
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
        self.viewLayout.addWidget(self.screen_english_card)
        self.viewLayout.addWidget(self.allocation_concurrency_card)
        self.viewLayout.addWidget(self.allocation_batch_size_card)
        self.viewLayout.addWidget(self.legacy_settings_status)
        self.viewLayout.addWidget(self.split_card)
        self.viewLayout.addWidget(self.split_type_card)
        self.viewLayout.addWidget(self.word_count_cjk_card)
        self.viewLayout.addWidget(self.word_count_english_card)
        self.viewLayout.addWidget(self.remove_punctuation_card)
        # 设置间距

        self.viewLayout.setSpacing(10)
        self.setMinimumSize(920, 820)
        self.resize(920, 760)

        # 设置窗口标题
        self.setWindowTitle(self.tr("字幕设置"))

        # 只显示取消按钮
        self.yesButton.hide()
        self.cancelButton.setText(self.tr("关闭"))
