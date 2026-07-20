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
            self.tr("字幕是否使用大语言模型进行智能断句"),
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

        self.screen_edit_card = SwitchSettingCard(
            FIF.EDIT,
            self.tr("上屏短字幕校正"),
            self.tr("使用大模型轻校正双语字幕，保留短字幕节奏，适合视频播客上屏"),
            cfg.need_screen_subtitle_edit,
            self,
        )

        self.screen_quality_check_card = SwitchSettingCard(
            FIF.SEARCH,
            self.tr("\u4e0a\u5c4f\u5019\u9009\u8d28\u68c0"),
            self.tr("\u4e8c\u6b21\u68c0\u67e5\u53ef\u7591\u65ad\u53e5\uff1b\u4f1a\u589e\u52a0 Token \u6d88\u8017\uff0c\u53ef\u80fd\u5f71\u54cd\u65f6\u95f4\u8f74\u5bf9\u9f50"),
            cfg.need_screen_subtitle_quality_check,
            self,
        )

        self.stable_ts_alignment_card = SwitchSettingCard(
            FIF.ALIGNMENT,
            self.tr("stable-ts时间轴对齐"),
            self.tr("转录后用stable-ts重新生成英文词级时间轴；会变慢，但切分后的字幕更容易贴近音频"),
            cfg.stable_ts_alignment_enabled,
            self,
        )

        self.stable_ts_model_card = ComboBoxSettingCard(
            cfg.stable_ts_alignment_model,
            FIF.ROBOT,
            self.tr("stable-ts对齐模型"),
            self.tr("模型越大越慢；large-v3-turbo为当前默认"),
            texts=["small.en", "medium.en", "large-v3", "large-v3-turbo"],
            parent=self,
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
            self.tr("校正时尽量控制单条英文词数，允许必要时略微超出"),
            minimum=6,
            maximum=40,
            parent=self,
        )

        # 添加到布局
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.split_card)
        self.viewLayout.addWidget(self.split_type_card)
        self.viewLayout.addWidget(self.word_count_cjk_card)
        self.viewLayout.addWidget(self.word_count_english_card)
        self.viewLayout.addWidget(self.remove_punctuation_card)
        self.viewLayout.addWidget(self.screen_edit_card)
        self.viewLayout.addWidget(self.screen_quality_check_card)
        self.viewLayout.addWidget(self.stable_ts_alignment_card)
        self.viewLayout.addWidget(self.stable_ts_model_card)
        self.viewLayout.addWidget(self.screen_cjk_card)
        self.viewLayout.addWidget(self.screen_english_card)
        # 设置间距

        self.viewLayout.setSpacing(10)

        # 设置窗口标题
        self.setWindowTitle(self.tr("字幕设置"))

        # 只显示取消按钮
        self.yesButton.hide()
        self.cancelButton.setText(self.tr("关闭"))
