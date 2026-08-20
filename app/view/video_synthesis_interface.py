# -*- coding: utf-8 -*-

import os
import subprocess
import sys
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDropEvent
from PyQt5.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import Action, BodyLabel, CardWidget, CommandBar
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    TextEdit,
    ToolTipFilter,
    ToolTipPosition,
)

from app.common.config import cfg
from app.common.signal_bus import signalBus
from app.config import RESOURCE_PATH
from app.core.entities import (
    SupportedAudioFormats,
    SupportedSubtitleFormats,
    SupportedVideoFormats,
    SynthesisTask,
)
from app.core.task_factory import TaskFactory
from app.thread.video_synthesis_thread import (
    VideoSynthesisThread,
    resolve_synthesis_package_inputs,
)
from app.core.subtitle_processor.manual_final_subtitle_editor import (
    ManualFinalSubtitleEditError,
    ManualFinalSubtitleSession,
)


current_dir = Path(__file__).parent.parent
SUBTITLE_STYLE_DIR = current_dir / "resource" / "subtitle_style"
PODCAST_LOGO_DIR = (
    RESOURCE_PATH / "podcast_template" / "article_vocab" / "logos"
)


class VideoSynthesisInterface(QWidget):
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VideoSynthesisInterface")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)  # 启用拖放功能
        self._manual_draft_mode = False
        self.setup_ui()
        self.setup_style()
        self.set_value()
        self.setup_signals()
        self.task = None

        self.installEventFilter(ToolTipFilter(self, 100, ToolTipPosition.BOTTOM))

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(20)

        # 创建顶部布局
        top_layout = QHBoxLayout()

        # 添加顶部命令栏
        self.command_bar = CommandBar(self)
        self.command_bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        top_layout.addWidget(self.command_bar, 1)  # 设置stretch为1，使其尽可能占用空间

        # 设置命令栏
        self._setup_command_bar()

        # 添加开始合成按钮到水平布局
        self.synthesize_button = PrimaryPushButton(
            self.tr("开始合成"), self, icon=FIF.PLAY
        )
        self.synthesize_button.setFixedHeight(34)
        top_layout.addWidget(self.synthesize_button)

        self.main_layout.addLayout(top_layout)

        # 配置卡片
        self.config_card = CardWidget(self)
        self.config_layout = QVBoxLayout(self.config_card)
        self.config_layout.setContentsMargins(20, 20, 20, 20)
        self.config_layout.setSpacing(20)

        # 字幕文件选择
        self.subtitle_layout = QHBoxLayout()
        self.subtitle_layout.setSpacing(15)
        self.subtitle_label = BodyLabel(self.tr("字幕/稳定字幕包"), self)
        self.subtitle_input = LineEdit(self)
        self.subtitle_input.setPlaceholderText(
            self.tr("选择字幕文件或 stable-final-manifest.json")
        )
        self.subtitle_input.setAcceptDrops(True)  # 启用拖放
        self.subtitle_button = PushButton(self.tr("浏览"))
        self.subtitle_layout.addWidget(self.subtitle_label)
        self.subtitle_layout.addWidget(self.subtitle_input)
        self.subtitle_layout.addWidget(self.subtitle_button)
        self.config_layout.addLayout(self.subtitle_layout)

        # 视频文件选择
        self.video_layout = QHBoxLayout()
        self.video_layout.setSpacing(15)
        self.video_label = BodyLabel(self.tr("音频/视频文件"), self)
        self.video_input = LineEdit(self)
        self.video_input.setPlaceholderText(self.tr("选择或者拖拽原音频/视频文件"))
        self.video_input.setAcceptDrops(True)  # 启用拖放
        self.video_button = PushButton(self.tr("浏览"))
        self.video_layout.addWidget(self.video_label)
        self.video_layout.addWidget(self.video_input)
        self.video_layout.addWidget(self.video_button)
        self.config_layout.addLayout(self.video_layout)

        self.podcast_style_layout = QHBoxLayout()
        self.podcast_style_layout.setSpacing(15)
        self.podcast_style_label = BodyLabel(self.tr("模板样式"), self)
        self.podcast_style_combo = ComboBox(self)
        self.podcast_style_combo.addItems([self.tr("暗色播客"), self.tr("文章单词")])
        self.podcast_style_layout.addWidget(self.podcast_style_label)
        self.podcast_style_layout.addWidget(self.podcast_style_combo)
        self.config_layout.addLayout(self.podcast_style_layout)

        self.podcast_title_layout = QHBoxLayout()
        self.podcast_title_layout.setSpacing(15)
        self.podcast_title_label = BodyLabel(self.tr("模板标题"), self)
        self.podcast_title_input = TextEdit(self)
        self.podcast_title_input.setAcceptRichText(False)
        self.podcast_title_input.setTabChangesFocus(True)
        self.podcast_title_input.setFixedHeight(76)
        self.podcast_title_input.setPlaceholderText(self.tr("视频标题"))
        self.podcast_title_layout.addWidget(self.podcast_title_label)
        self.podcast_title_layout.addWidget(self.podcast_title_input)
        self.podcast_title_layout.setAlignment(
            self.podcast_title_label,
            Qt.AlignVCenter,
        )
        self.config_layout.addLayout(self.podcast_title_layout)

        self.podcast_background_layout = QHBoxLayout()
        self.podcast_background_layout.setSpacing(15)
        self.podcast_background_label = BodyLabel(self.tr("模板背景图"), self)
        self.podcast_background_input = LineEdit(self)
        self.podcast_background_input.setPlaceholderText(
            self.tr("可选；建议使用16:9图片，如1440x810或1920x1080")
        )
        self.podcast_background_button = PushButton(self.tr("浏览"))
        self.podcast_background_layout.addWidget(self.podcast_background_label)
        self.podcast_background_layout.addWidget(self.podcast_background_input)
        self.podcast_background_layout.addWidget(self.podcast_background_button)
        self.config_layout.addLayout(self.podcast_background_layout)

        self.podcast_cover_layout = QHBoxLayout()
        self.podcast_cover_layout.setSpacing(15)
        self.podcast_cover_label = BodyLabel(self.tr("文章封面图"), self)
        self.podcast_cover_input = LineEdit(self)
        self.podcast_cover_input.setPlaceholderText(
            self.tr("文章单词模板使用；建议1280x720")
        )
        self.podcast_cover_button = PushButton(self.tr("浏览"))
        self.podcast_cover_layout.addWidget(self.podcast_cover_label)
        self.podcast_cover_layout.addWidget(self.podcast_cover_input)
        self.podcast_cover_layout.addWidget(self.podcast_cover_button)
        self.config_layout.addLayout(self.podcast_cover_layout)

        self.podcast_logo_layout = QHBoxLayout()
        self.podcast_logo_layout.setSpacing(15)
        self.podcast_logo_label = BodyLabel(self.tr("品牌 Logo"), self)
        self.podcast_logo_input = LineEdit(self)
        self.podcast_logo_input.setPlaceholderText(
            self.tr("可选；留空不显示 Logo")
        )
        self.podcast_logo_button = PushButton(self.tr("浏览"))
        self.podcast_logo_layout.addWidget(self.podcast_logo_label)
        self.podcast_logo_layout.addWidget(self.podcast_logo_input)
        self.podcast_logo_layout.addWidget(self.podcast_logo_button)
        self.config_layout.addLayout(self.podcast_logo_layout)

        self.main_layout.addWidget(self.config_card)

        self.main_layout.addStretch(1)

        # 底部进度条和状态信息
        self.bottom_layout = QHBoxLayout()
        self.progress_bar = ProgressBar(self)
        self.status_label = BodyLabel(self.tr("就绪"), self)
        self.status_label.setMinimumWidth(100)  # 设置最小宽度
        self.status_label.setAlignment(Qt.AlignCenter)  # 设置文本居中对齐
        self.bottom_layout.addWidget(self.progress_bar, 1)  # 进度条使用剩余空间
        self.bottom_layout.addWidget(self.status_label)  # 状态标签使用固定宽度
        self.main_layout.addLayout(self.bottom_layout)

    def _setup_command_bar(self):
        """设置顶部命令栏"""
        # 添加软字幕选项
        self.soft_subtitle_action = Action(
            FIF.FONT,
            self.tr("软字幕"),
            triggered=self.on_soft_subtitle_changed,
            checkable=True,
        )
        self.soft_subtitle_action.setToolTip(self.tr("使用软字幕嵌入视频"))
        self.command_bar.addAction(self.soft_subtitle_action)

        # 添加分隔符
        self.command_bar.addSeparator()

        # 添加是否合成视频选项
        self.need_video_action = Action(
            FIF.VIDEO,
            self.tr("合成视频"),
            triggered=self.on_need_video_changed,
            checkable=True,
        )
        self.need_video_action.setToolTip(self.tr("是否生成新的视频文件"))
        self.command_bar.addAction(self.need_video_action)

        self.command_bar.addSeparator()

        self.podcast_learning_template_action = Action(
            FIF.FONT,
            self.tr("英语学习模板"),
            triggered=self.on_podcast_learning_template_changed,
            checkable=True,
        )
        self.podcast_learning_template_action.setToolTip(
            self.tr("使用Figma风格生成英语学习播客视频")
        )
        self.command_bar.addAction(self.podcast_learning_template_action)

        self.ai_vocab_action = Action(
            FIF.ROBOT,
            self.tr("智能单词卡"),
            triggered=self.on_ai_vocab_changed,
            checkable=True,
        )
        self.ai_vocab_action.setToolTip(
            self.tr("合成前让大模型根据字幕选择单词卡；会增加一次Token消耗")
        )
        self.command_bar.addAction(self.ai_vocab_action)

        self.english_only_action = Action(
            FIF.LANGUAGE,
            self.tr("仅英文字幕"),
            triggered=self.on_english_only_changed,
            checkable=True,
        )
        self.english_only_action.setToolTip(
            self.tr("隐藏视频字幕中的中文；单词卡中文释义保留")
        )
        self.command_bar.addAction(self.english_only_action)

        self.command_bar.addSeparator()

        # 添加打开文件夹按钮
        folder_action = Action(FIF.FOLDER, "", triggered=self.open_video_folder)
        folder_action.setToolTip(self.tr("打开输出文件夹"))
        self.command_bar.addAction(folder_action)

        # 添加文件选择按钮
        file_action = Action(FIF.FOLDER_ADD, "", triggered=self.choose_video_file)
        file_action.setToolTip(self.tr("选择视频文件"))
        self.command_bar.addAction(file_action)

    def setup_style(self):
        self.subtitle_input.focusOutEvent = lambda e: super(
            LineEdit, self.subtitle_input
        ).focusOutEvent(e)
        self.subtitle_input.paintEvent = lambda e: super(
            LineEdit, self.subtitle_input
        ).paintEvent(e)
        self.subtitle_input.setStyleSheet(
            self.subtitle_input.styleSheet()
            + """
            QLineEdit {
                border-radius: 15px;
                padding: 0 20px;
                background-color: transparent;
                border: 1px solid rgba(255,255, 255, 0.08);
            }
            QLineEdit:focus[transparent=true] {
                border: 1px solid rgba(47,141, 99, 0.48);
            }
        """
        )

        self.video_input.focusOutEvent = lambda e: super(
            LineEdit, self.video_input
        ).focusOutEvent(e)
        self.video_input.paintEvent = lambda e: super(
            LineEdit, self.video_input
        ).paintEvent(e)
        self.video_input.setStyleSheet(
            self.video_input.styleSheet()
            + """
            QLineEdit {
                border-radius: 15px;
                padding: 0 20px;
                background-color: transparent;
                border: 1px solid rgba(255,255, 255, 0.08);
            }
            QLineEdit:focus[transparent=true] {
                border: 1px solid rgba(47,141, 99, 0.48);
            }
        """
        )

        self.podcast_background_input.focusOutEvent = lambda e: super(
            LineEdit, self.podcast_background_input
        ).focusOutEvent(e)
        self.podcast_background_input.paintEvent = lambda e: super(
            LineEdit, self.podcast_background_input
        ).paintEvent(e)
        self.podcast_background_input.setStyleSheet(
            self.podcast_background_input.styleSheet()
            + """
            QLineEdit {
                border-radius: 15px;
                padding: 0 20px;
                background-color: transparent;
                border: 1px solid rgba(255,255, 255, 0.08);
            }
            QLineEdit:focus[transparent=true] {
                border: 1px solid rgba(47,141, 99, 0.48);
            }
        """
        )
        for line_edit in (self.podcast_cover_input,):
            line_edit.focusOutEvent = lambda e, widget=line_edit: super(
                LineEdit, widget
            ).focusOutEvent(e)
            line_edit.paintEvent = lambda e, widget=line_edit: super(
                LineEdit, widget
            ).paintEvent(e)
            line_edit.setStyleSheet(
                line_edit.styleSheet()
                + """
                QLineEdit {
                    border-radius: 15px;
                    padding: 0 20px;
                    background-color: transparent;
                    border: 1px solid rgba(255,255, 255, 0.08);
                }
                QLineEdit:focus[transparent=true] {
                    border: 1px solid rgba(47,141, 99, 0.48);
                }
            """
            )

    def setup_signals(self):
        # 文件选择相关信号
        self.subtitle_button.clicked.connect(self.choose_subtitle_file)
        self.subtitle_input.textEdited.connect(self._clear_manual_draft_mode)
        self.video_button.clicked.connect(self.choose_video_file)
        self.podcast_style_combo.currentTextChanged.connect(self.save_podcast_style)
        self.podcast_title_input.textChanged.connect(self.save_podcast_title)
        self.podcast_background_button.clicked.connect(self.choose_podcast_background)
        self.podcast_background_input.editingFinished.connect(
            self.save_podcast_background
        )
        self.podcast_cover_button.clicked.connect(self.choose_podcast_cover)
        self.podcast_cover_input.editingFinished.connect(self.save_podcast_cover)
        self.podcast_logo_button.clicked.connect(self.choose_podcast_logo)
        self.podcast_logo_input.editingFinished.connect(self.save_podcast_logo)
        # 合成和文件夹相关信号
        self.synthesize_button.clicked.connect(
            lambda: self.start_video_synthesis(need_create_task=True)
        )

        # 全局 signalBus
        signalBus.soft_subtitle_changed.connect(self.on_soft_subtitle_changed)
        signalBus.need_video_changed.connect(self.on_need_video_changed)

    def set_value(self):
        """设置初始值"""
        self.soft_subtitle_action.setChecked(cfg.soft_subtitle.value)
        self.need_video_action.setChecked(cfg.need_video.value)
        self.podcast_learning_template_action.setChecked(
            cfg.podcast_learning_template.value
        )
        self.ai_vocab_action.setChecked(cfg.podcast_template_ai_vocab.value)
        self.english_only_action.setChecked(
            cfg.podcast_template_english_only.value
        )
        self.podcast_style_combo.setCurrentText(cfg.podcast_template_style.value)
        self.podcast_title_input.setPlainText(cfg.podcast_template_title.value)
        self.podcast_background_input.setText(cfg.podcast_template_background.value)
        self.podcast_cover_input.setText(cfg.podcast_template_cover.value)
        self.podcast_logo_input.setText(cfg.podcast_template_logo.value)
        self.update_podcast_template_fields()

    def set_layout_visible(self, layout, visible: bool):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget()
            child_layout = item.layout()
            if widget:
                widget.setVisible(visible)
            elif child_layout:
                self.set_layout_visible(child_layout, visible)

    def update_podcast_template_fields(self):
        enabled = self.podcast_learning_template_action.isChecked()
        is_article = self.podcast_style_combo.currentText() == self.tr("文章单词")
        self.ai_vocab_action.setVisible(enabled)
        self.english_only_action.setVisible(enabled)
        self.set_layout_visible(self.podcast_style_layout, enabled)
        self.set_layout_visible(self.podcast_title_layout, enabled)
        self.set_layout_visible(self.podcast_background_layout, enabled and not is_article)
        self.set_layout_visible(self.podcast_cover_layout, enabled and is_article)
        self.set_layout_visible(self.podcast_logo_layout, enabled and is_article)

    def on_soft_subtitle_changed(self, checked: bool):
        """处理软字幕选项变更"""
        cfg.set(cfg.soft_subtitle, checked)
        self.soft_subtitle_action.setChecked(checked)

    def on_need_video_changed(self, checked: bool):
        """处理视频合成选项变更"""
        cfg.set(cfg.need_video, checked)
        self.need_video_action.setChecked(checked)

    def on_podcast_learning_template_changed(self, checked: bool):
        cfg.set(cfg.podcast_learning_template, checked)
        self.podcast_learning_template_action.setChecked(checked)
        if checked:
            cfg.set(cfg.need_video, True)
            self.need_video_action.setChecked(True)
        self.update_podcast_template_fields()

    def on_ai_vocab_changed(self, checked: bool):
        cfg.set(cfg.podcast_template_ai_vocab, checked)
        self.ai_vocab_action.setChecked(checked)
        if checked:
            cfg.set(cfg.podcast_learning_template, True)
            self.podcast_learning_template_action.setChecked(True)
            cfg.set(cfg.need_video, True)
            self.need_video_action.setChecked(True)
        self.update_podcast_template_fields()

    def on_english_only_changed(self, checked: bool):
        cfg.set(cfg.podcast_template_english_only, checked)
        self.english_only_action.setChecked(checked)
        if checked:
            cfg.set(cfg.podcast_learning_template, True)
            self.podcast_learning_template_action.setChecked(True)
            cfg.set(cfg.need_video, True)
            self.need_video_action.setChecked(True)
        self.update_podcast_template_fields()

    def save_podcast_title(self):
        cfg.set(
            cfg.podcast_template_title,
            self.podcast_title_input.toPlainText().strip(),
        )

    def save_podcast_style(self):
        cfg.set(cfg.podcast_template_style, self.podcast_style_combo.currentText())
        self.update_podcast_template_fields()

    def save_podcast_background(self):
        cfg.set(
            cfg.podcast_template_background,
            self.podcast_background_input.text().strip(),
        )

    def save_podcast_cover(self):
        cfg.set(cfg.podcast_template_cover, self.podcast_cover_input.text().strip())

    def save_podcast_logo(self):
        cfg.set(cfg.podcast_template_logo, self.podcast_logo_input.text().strip())

    def choose_podcast_background(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("选择模板背景图"),
            "",
            self.tr("图片文件") + " (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if file_path:
            self.podcast_background_input.setText(file_path)
            self.save_podcast_background()

    def choose_podcast_cover(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("选择文章封面图"),
            "",
            self.tr("图片文件") + " (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if file_path:
            self.podcast_cover_input.setText(file_path)
            self.save_podcast_cover()

    def choose_podcast_logo(self):
        PODCAST_LOGO_DIR.mkdir(parents=True, exist_ok=True)
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("选择品牌 Logo"),
            str(PODCAST_LOGO_DIR),
            self.tr("图片文件") + " (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if file_path:
            self.podcast_logo_input.setText(file_path)
            self.save_podcast_logo()

    def choose_subtitle_file(self):
        # 构建文件过滤器
        subtitle_formats = " ".join(
            f"*.{fmt.value}" for fmt in SupportedSubtitleFormats
        )
        filter_str = (
            f"{self.tr('字幕或稳定字幕包')} "
            f"({subtitle_formats} stable-final-manifest.json)"
        )

        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择字幕文件"), "", filter_str
        )
        if file_path:
            self.set_inputs("", file_path)

    def choose_video_file(self):
        # 构建文件过滤器
        video_formats = " ".join(f"*.{fmt.value}" for fmt in SupportedVideoFormats)
        if cfg.podcast_learning_template.value:
            audio_formats = " ".join(
                f"*.{fmt.value}" for fmt in SupportedAudioFormats
            )
            filter_str = self.tr("音频/视频文件") + f" ({video_formats} {audio_formats})"
        else:
            filter_str = f"{self.tr('视频文件')} ({video_formats})"

        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择视频文件"), "", filter_str
        )
        if file_path:
            self.video_input.setText(file_path)

    def create_task(self):
        self.save_podcast_style()
        self.save_podcast_title()
        self.save_podcast_background()
        self.save_podcast_cover()
        subtitle_file = self.subtitle_input.text()
        video_file = self.video_input.text()
        if not subtitle_file or not video_file:
            InfoBar.error(
                self.tr("错误"),
                self.tr("请选择字幕/稳定字幕包和原音频/视频文件"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return None
        if not Path(subtitle_file).is_file() or not Path(video_file).is_file():
            InfoBar.error(
                self.tr("错误"),
                self.tr("所选字幕包或媒体文件不存在。"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return None
        return TaskFactory.create_synthesis_task(
            video_file,
            subtitle_file,
            manual_draft_mode=self._manual_draft_mode,
        )

    def set_inputs(
        self,
        media_path: str,
        subtitle_or_manifest_path: str,
        *,
        manual_draft_mode: bool = False,
    ) -> None:
        selected = Path(subtitle_or_manifest_path) if subtitle_or_manifest_path else None
        if selected is not None:
            if selected.suffix.lower() == ".srt" and not manual_draft_mode:
                try:
                    linked_manifest = ManualFinalSubtitleSession.find_manifest_for_subtitle(
                        selected,
                        work_dir=cfg.work_dir.value,
                    )
                except ManualFinalSubtitleEditError as exc:
                    InfoBar.error(
                        self.tr("字幕包关联失败"),
                        str(exc),
                        duration=5000,
                        parent=self,
                    )
                    return
                if linked_manifest is not None:
                    try:
                        linked_media, _ = resolve_synthesis_package_inputs(
                            linked_manifest,
                            media_path,
                        )
                    except RuntimeError:
                        try:
                            linked_media, _ = resolve_synthesis_package_inputs(
                                linked_manifest,
                                media_path,
                                allow_manual_draft=True,
                            )
                        except RuntimeError as exc:
                            InfoBar.error(
                                self.tr("人工字幕包无效"),
                                str(exc),
                                duration=5000,
                                parent=self,
                            )
                            return
                        manual_draft_mode = True
                        InfoBar.warning(
                            self.tr("已进入人工草稿合成"),
                            self.tr(
                                "已找回该字幕的完整词级账本；输出将使用“【人工草稿】”前缀。"
                            ),
                            duration=5000,
                            parent=self,
                        )
                    media_path = linked_media or media_path
                    subtitle_or_manifest_path = str(linked_manifest)
                    selected = linked_manifest
            if manual_draft_mode and selected.name != "stable-final-manifest.json":
                InfoBar.error(
                    self.tr("人工草稿包无效"),
                    self.tr("合成草稿必须从保存过的人工终稿清单进入。"),
                    duration=4000,
                    parent=self,
                )
                return
            if selected.name == "stable-final-manifest.json":
                try:
                    media_path, subtitle_or_manifest_path = (
                        resolve_synthesis_package_inputs(
                            selected,
                            media_path,
                            allow_manual_draft=manual_draft_mode,
                        )
                    )
                except RuntimeError as exc:
                    InfoBar.error(
                        self.tr("稳定字幕包无效"),
                        str(exc),
                        duration=4000,
                        parent=self,
                    )
                    return
                selected = Path(subtitle_or_manifest_path)
            self._manual_draft_mode = bool(manual_draft_mode)
            self.subtitle_input.setText(str(selected))
        if media_path:
            self.video_input.setText(str(media_path))

    def _clear_manual_draft_mode(self, *_args) -> None:
        self._manual_draft_mode = False

    def set_task(self, task: SynthesisTask):
        self.task = task
        self._manual_draft_mode = bool(
            getattr(task.synthesis_config, "manual_draft_mode", False)
        )
        self.update_info()

    def update_info(self):
        if self.task:
            self.video_input.setText(self.task.video_path)
            self.subtitle_input.setText(self.task.subtitle_path)

    def start_video_synthesis(self, need_create_task=True):
        self.synthesize_button.setEnabled(False)
        self.progress_bar.resume()
        if need_create_task:
            self.task = self.create_task()

        if self.task:
            self.video_synthesis_thread = VideoSynthesisThread(self.task)
            self.video_synthesis_thread.finished.connect(
                self.on_video_synthesis_finished
            )
            self.video_synthesis_thread.progress.connect(
                self.on_video_synthesis_progress
            )
            self.video_synthesis_thread.error.connect(self.on_video_synthesis_error)
            self.video_synthesis_thread.start()
        else:
            self.synthesize_button.setEnabled(True)

    def process(self):
        self.start_video_synthesis(need_create_task=False)

    def on_video_synthesis_finished(self, task):
        self.synthesize_button.setEnabled(True)
        self.open_video_folder()
        InfoBar.success(
            self.tr("成功"),
            self.tr("视频合成已完成"),
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def on_video_synthesis_progress(self, progress, message):
        self.progress_bar.setValue(progress)
        self.status_label.setText(message)

    def on_video_synthesis_error(self, error):
        self.synthesize_button.setEnabled(True)
        self.progress_bar.error()
        InfoBar.error(
            self.tr("错误"),
            str(error),
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def open_video_folder(self):
        if self.task and self.task.output_path:
            file_path = Path(self.task.output_path)
            target_dir = str(
                file_path.parent
                if file_path.exists()
                else Path(self.task.video_path).parent
            )
            # Cross-platform folder opening
            if sys.platform == "win32":
                os.startfile(target_dir)
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", target_dir])
            else:  # Linux
                subprocess.run(["xdg-open", target_dir])
        else:
            InfoBar.warning(
                self.tr("警告"),
                self.tr("没有可用的视频文件夹"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def dragEnterEvent(self, event):
        """拖拽进入事件处理"""
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event: QDropEvent):
        """拖拽放下事件处理"""
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file_path in files:
            if not os.path.isfile(file_path):
                continue

            file_ext = os.path.splitext(file_path)[1][1:].lower()

            # 检查文件格式是否支持
            if file_ext in {fmt.value for fmt in SupportedSubtitleFormats} or (
                Path(file_path).name == "stable-final-manifest.json"
            ):
                self.set_inputs("", file_path)
                InfoBar.success(
                    self.tr("导入成功"),
                    self.tr("字幕文件已放入输入框"),
                    duration=2000,
                    parent=self,
                )
                break
            elif (
                cfg.podcast_learning_template.value
                and file_ext in {"png", "jpg", "jpeg", "webp", "bmp"}
            ):
                if self.podcast_style_combo.currentText() == self.tr("文章单词"):
                    self.podcast_cover_input.setText(file_path)
                    self.save_podcast_cover()
                    message = self.tr("文章封面图已放入输入框")
                else:
                    self.podcast_background_input.setText(file_path)
                    self.save_podcast_background()
                    message = self.tr("模板背景图已放入输入框")
                InfoBar.success(
                    self.tr("导入成功"),
                    message,
                    duration=2000,
                    parent=self,
                )
                break
            elif file_ext in {fmt.value for fmt in SupportedVideoFormats} or (
                cfg.podcast_learning_template.value
                and file_ext in {fmt.value for fmt in SupportedAudioFormats}
            ):
                self.video_input.setText(file_path)
                InfoBar.success(
                    self.tr("导入成功"),
                    self.tr("视频文件已输入框"),
                    duration=2000,
                    parent=self,
                )
                break
            else:
                InfoBar.error(
                    self.tr(f"格式错误") + file_ext,
                    self.tr("请拖入视频或者字幕文件"),
                    duration=3000,
                    parent=self,
                )


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    window = VideoSynthesisInterface()
    window.resize(600, 400)  # 设置窗口大小
    window.show()
    sys.exit(app.exec_())
