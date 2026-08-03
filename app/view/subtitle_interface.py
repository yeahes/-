# -*- coding: utf-8 -*-
import os
import re
import subprocess
import sys
import tempfile
import json
import logging
from pathlib import Path
from threading import Thread

from PyQt5.QtCore import Qt, QTime, QUrl, QAbstractTableModel, pyqtSignal
from PyQt5.QtGui import QColor, QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import Action, BodyLabel, CommandBar, isDarkTheme
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    RoundMenu,
    TableView,
    TextEdit,
    TransparentDropDownPushButton,
)

from app.common.config import cfg
from app.common.signal_bus import signalBus
from app.components.SubtitleSettingDialog import SubtitleSettingDialog
from app.config import SUBTITLE_STYLE_PATH
from app.core.bk_asr.asr_data import ASRData
from app.core.subtitle_processor.manual_final_subtitle_editor import (
    ManualFinalSubtitleEditError,
    ManualFinalSubtitleSession,
)
from app.core.subtitle_processor.subtitle_review_marks import (
    SubtitleReviewMark,
    load_subtitle_review_marks,
    review_marks_from_payload,
    syntax_review_parser_available,
)
from app.core.entities import (
    OutputSubtitleFormatEnum,
    SubtitleTask,
    SupportedSubtitleFormats,
    TargetLanguageEnum,
)
from app.core.task_factory import TaskFactory
from app.core.utils.get_subtitle_style import get_subtitle_style
from app.thread.subtitle_thread import SubtitleThread


LOG = logging.getLogger(__name__)


class SubtitleTableModel(QAbstractTableModel):
    def __init__(self, data=""):
        super().__init__()
        self._data = {}
        self._review_marks_by_subtitle_id = {}
        if isinstance(data, str):
            self.load_data(data)
        else:
            self._data = data

    def load_data(self, data: str):
        """加载字幕数据"""
        try:
            self.update_all(json.loads(data))
        except json.JSONDecodeError:
            pass

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not self._data:
            return None

        row = index.row()
        col = index.column()
        segment = self._data.get(str(row + 1))

        if not segment:
            return None

        marks = self._marks_for_segment(segment)
        if role == Qt.BackgroundRole:
            return self._review_background(marks, col)
        if role == Qt.ToolTipRole:
            return self._review_tooltip(marks, col)
        if role == Qt.DisplayRole or role == Qt.EditRole:
            if col == 0:
                return (
                    QTime(0, 0)
                    .addMSecs(segment["start_time"])
                    .toString("hh:mm:ss.zzz")[:-2]
                )
            elif col == 1:
                return (
                    QTime(0, 0)
                    .addMSecs(segment["end_time"])
                    .toString("hh:mm:ss.zzz")[:-2]
                )
            elif col == 2:
                return segment["original_subtitle"]
            elif col == 3:
                return segment["translated_subtitle"]
        elif role == Qt.TextAlignmentRole:
            if col in [0, 1]:
                return Qt.AlignCenter
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or not self._data:
            return False

        if role == Qt.EditRole:
            row = index.row()
            col = index.column()
            segment = self._data.get(str(row + 1))

            if not segment:
                return False

            if col == 2:
                segment["original_subtitle"] = value
            elif col == 3:
                segment["translated_subtitle"] = value
            else:
                return False

            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
            return True
        return False

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return [
                    self.tr("开始时间"),
                    self.tr("结束时间"),
                    self.tr("字幕内容"),
                    (
                        self.tr("翻译字幕")
                        if cfg.need_translate.value
                        else self.tr("优化字幕")
                    ),
                ][section]
            elif orientation == Qt.Vertical:
                return str(section + 1)  # 显示行号
        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter  # 居中对齐
        return None

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return 4

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        if index.column() in [2, 3]:
            return Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def update_data(self, new_data):
        """更新字幕数据"""
        updated_rows = set()

        # 更新内部数据
        for key, value in new_data.items():
            if key in self._data:
                if "||" in value:
                    original_subtitle, translated_subtitle = value.split("||", 1)
                    self._data[key]["original_subtitle"] = original_subtitle
                    self._data[key]["translated_subtitle"] = translated_subtitle
                else:
                    self._data[key]["translated_subtitle"] = value
                row = list(self._data.keys()).index(key)
                updated_rows.add(row)

        # 如果有更新，发出dataChanged信号
        if updated_rows:
            min_row = min(updated_rows)
            max_row = max(updated_rows)
            top_left = self.index(min_row, 2)
            bottom_right = self.index(max_row, 3)
            self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole, Qt.EditRole])

    def update_all(self, data: dict):
        """更新所有数据"""
        self.beginResetModel()
        self._data = data or {}
        self.endResetModel()

    def set_review_marks(self, marks_by_subtitle_id: dict) -> None:
        self._review_marks_by_subtitle_id = {
            str(subtitle_id): list(marks)
            for subtitle_id, marks in (marks_by_subtitle_id or {}).items()
        }
        if not self._data:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(max(0, self.rowCount() - 1), self.columnCount() - 1),
            [Qt.BackgroundRole, Qt.ToolTipRole],
        )

    def _marks_for_segment(self, segment: dict) -> list[SubtitleReviewMark]:
        subtitle_ids = list(segment.get("source_subtitle_ids") or [])
        subtitle_ids.extend(
            [segment.get("subtitle_id"), segment.get("manual_cue_id")]
        )
        marks = []
        seen = set()
        for subtitle_id in subtitle_ids:
            for mark in self._review_marks_by_subtitle_id.get(str(subtitle_id or ""), []):
                key = (mark.subtitle_id, mark.severity, mark.target, mark.code, mark.reason)
                if key not in seen:
                    seen.add(key)
                    marks.append(mark)
        if segment.get("chinese_review_required"):
            marks.append(
                SubtitleReviewMark(
                    subtitle_id=str(segment.get("manual_cue_id") or "人工终稿"),
                    severity="REVIEW",
                    category="manual_chinese_review",
                    target="chinese",
                    code="english_boundary_manually_moved",
                    reason="英文边界已人工调整，请检查中文是否仍与本条英文对应。",
                )
            )
        return marks

    @staticmethod
    def _review_marks_for_column(
        marks: list[SubtitleReviewMark], column: int
    ) -> list[SubtitleReviewMark]:
        target = "english" if column == 2 else "chinese" if column == 3 else ""
        return [
            mark
            for mark in marks
            if mark.target == "both" or (target and mark.target == target)
        ]

    def _review_background(self, marks: list[SubtitleReviewMark], column: int):
        relevant = self._review_marks_for_column(marks, column)
        if isDarkTheme():
            colors = {
                "blocker": "#282225",
                "english_cut": "#24364A",
                "timeline_alignment": "#302C3A",
                "chinese_allocation": "#29251E",
                "manual_chinese_review": "#27241F",
            }
        else:
            colors = {
                "blocker": "#FFF9F8",
                "english_cut": "#EAF4FF",
                "timeline_alignment": "#F4F1FB",
                "chinese_allocation": "#FFFCF7",
                "manual_chinese_review": "#FFFBF4",
            }
        if any(mark.severity == "BLOCKER" for mark in relevant):
            return QColor(colors["blocker"])
        if any(mark.category == "english_cut" for mark in relevant):
            return QColor(colors["english_cut"])
        if any(mark.category == "timeline_alignment" for mark in relevant):
            return QColor(colors["timeline_alignment"])
        if any(mark.category == "chinese_allocation" for mark in relevant):
            return QColor(colors["chinese_allocation"])
        if any(mark.category == "manual_chinese_review" for mark in relevant):
            return QColor(colors["manual_chinese_review"])
        return None

    def _review_tooltip(self, marks: list[SubtitleReviewMark], column: int):
        relevant = self._review_marks_for_column(marks, column)
        if not relevant:
            return None
        labels = {
            "structure": "结构阻断",
            "validation": "质量阻断",
            "english_cut": "英文切分复查",
            "timeline_alignment": "时间轴复查",
            "chinese_allocation": "中文分配复查",
            "manual_chinese_review": "人工调整后中文待检查",
        }
        lines = []
        for mark in relevant:
            label = labels.get(mark.category, "字幕复查")
            lines.append(f"[{label}] {mark.subtitle_id}: {mark.reason}")
        return "\n".join(lines)


class SubtitleInterface(QWidget):
    finished = pyqtSignal(str, str)
    review_marks_loaded = pyqtSignal(int, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.task = None
        self.subtitle_path = None
        self.manual_final_session = None
        self._manual_review_mark_count = 0
        self._review_mark_request_id = 0
        self._review_mark_rows = []
        self.custom_prompt_text = cfg.custom_prompt_text.value
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._init_ui()
        self._setup_signals()
        self._update_prompt_button_style()
        self.set_values()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setSpacing(20)

        self._setup_top_layout()
        self._setup_subtitle_table()
        self._setup_bottom_layout()

    def set_values(self):
        self.layout_button.setText(cfg.subtitle_layout.value)
        self.translate_button.setChecked(cfg.need_translate.value)
        self.optimize_button.setChecked(cfg.need_optimize.value)
        self.target_language_button.setText(cfg.target_language.value.value)
        self.target_language_button.setEnabled(cfg.need_translate.value)

    def _setup_top_layout(self):
        # 创建水平布局
        top_layout = QHBoxLayout()

        # 创建命令栏
        self.command_bar = CommandBar(self)
        self.command_bar.setToolButtonStyle(
            Qt.ToolButtonTextBesideIcon
        )  # 设置图标和文字并排显示
        top_layout.addWidget(self.command_bar, 1)  # 设置stretch为1，使其尽可能占用空间

        # 创建保存按钮的下拉菜单
        save_menu = RoundMenu(parent=self)
        save_menu.view.setMaxVisibleItems(8)  # 设置菜单最大高度
        for format in OutputSubtitleFormatEnum:
            action = Action(text=format.value)
            action.triggered.connect(
                lambda checked, f=format.value: self.on_save_format_clicked(f)
            )
            save_menu.addAction(action)

        # 添加保存按钮(带下拉菜单)
        save_button = TransparentDropDownPushButton(self.tr("保存"), self, FIF.SAVE)
        save_button.setMenu(save_menu)
        save_button.setFixedHeight(34)
        self.command_bar.addWidget(save_button)

        # 添加字幕排布下拉按钮
        self.layout_button = TransparentDropDownPushButton(
            self.tr("字幕排布"), self, FIF.LAYOUT
        )
        self.layout_button.setFixedHeight(34)
        self.layout_button.setMinimumWidth(125)
        self.layout_menu = RoundMenu(parent=self)
        for layout in ["译文在上", "原文在上", "仅译文", "仅原文"]:
            action = Action(text=layout)
            action.triggered.connect(
                lambda checked, l=layout: signalBus.subtitle_layout_changed.emit(l)
            )
            self.layout_menu.addAction(action)
        self.layout_button.setMenu(self.layout_menu)
        self.command_bar.addWidget(self.layout_button)

        self.command_bar.addSeparator()

        # Compatibility-only controls stay available without competing with the
        # stable bilingual production actions in the primary command bar.
        self.optimize_button = Action(
            FIF.EDIT,
            self.tr("兼容字幕校正"),
            triggered=self.on_subtitle_optimization_changed,
            checkable=True,
        )

        # 添加字幕翻译按钮
        self.translate_button = Action(
            FIF.LANGUAGE,
            self.tr("字幕翻译"),
            triggered=self.on_subtitle_translation_changed,
            checkable=True,
        )
        self.command_bar.addAction(self.translate_button)

        # 添加翻译语言选择
        self.target_language_button = TransparentDropDownPushButton(
            self.tr("翻译语言"), self, FIF.LANGUAGE
        )
        self.target_language_button.setFixedHeight(34)
        self.target_language_button.setMinimumWidth(125)
        self.target_language_menu = RoundMenu(parent=self)
        self.target_language_menu.setMaxVisibleItems(10)
        for lang in TargetLanguageEnum:
            action = Action(text=lang.value)
            action.triggered.connect(
                lambda checked, l=lang.value: signalBus.target_language_changed.emit(l)
            )
            self.target_language_menu.addAction(action)
        self.target_language_button.setMenu(self.target_language_menu)

        self.command_bar.addWidget(self.target_language_button)

        # 文稿提示与旧流程校正属于低频高级操作，收进“更多”。
        self.prompt_button = Action(
            FIF.DOCUMENT, self.tr("文稿提示"), triggered=self.show_prompt_dialog
        )

        self.quality_report_action = Action(
            FIF.SEARCH, self.tr("质量报告"), triggered=self.open_quality_report
        )
        self.quality_report_action.setEnabled(False)
        self.command_bar.addAction(self.quality_report_action)

        self.next_review_action = Action(
            FIF.SEARCH, self.tr("下一处复查"), triggered=self.focus_next_review_mark
        )
        self.next_review_action.setEnabled(False)
        self.next_review_action.setVisible(False)
        self.command_bar.addAction(self.next_review_action)

        self.manual_final_save_action = Action(
            FIF.SAVE, self.tr("保存人工终稿"), triggered=self.save_manual_final_output
        )
        self.manual_final_save_action.setEnabled(False)
        self.manual_final_save_action.setVisible(False)
        self.command_bar.addAction(self.manual_final_save_action)

        self.manual_final_undo_action = Action(
            FIF.SYNC, self.tr("撤销终稿编辑"), triggered=self.undo_manual_final_edit
        )
        self.manual_final_undo_action.setEnabled(False)
        self.manual_final_undo_action.setVisible(False)
        self.command_bar.addAction(self.manual_final_undo_action)

        self.more_menu = RoundMenu(parent=self)
        self.more_menu.addAction(self.optimize_button)
        self.more_menu.addAction(self.prompt_button)
        self.more_menu.addSeparator()
        self.subtitle_settings_action = Action(
            FIF.SETTING, self.tr("字幕设置"), triggered=self.show_subtitle_settings
        )
        self.open_folder_action = Action(
            FIF.FOLDER, self.tr("打开输出文件夹"), triggered=self.on_open_folder_clicked
        )
        self.import_subtitle_action = Action(
            FIF.FOLDER_ADD, self.tr("导入字幕"), triggered=self.on_file_select
        )
        self.more_menu.addAction(self.subtitle_settings_action)
        self.more_menu.addAction(self.open_folder_action)
        self.more_menu.addAction(self.import_subtitle_action)
        self.more_button = TransparentDropDownPushButton(self.tr("更多"), self, FIF.MORE)
        self.more_button.setMenu(self.more_menu)
        self.more_button.setFixedHeight(34)
        self.command_bar.addWidget(self.more_button)

        self.command_bar.addSeparator()

        # 添加开始按钮到水平布局
        self.start_button = PrimaryPushButton(self.tr("开始"), self, icon=FIF.PLAY)
        self.start_button.clicked.connect(
            lambda: self.start_subtitle_optimization(need_create_task=True)
        )
        self.start_button.setFixedHeight(34)
        top_layout.addWidget(self.start_button)

        self.main_layout.addLayout(top_layout)

    def _setup_subtitle_table(self):
        self.subtitle_table = TableView(self)
        self.model = SubtitleTableModel("")
        self.subtitle_table.setModel(self.model)
        self.subtitle_table.setBorderVisible(True)
        self.subtitle_table.setBorderRadius(8)
        self.subtitle_table.setWordWrap(True)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Fixed
        )
        self.subtitle_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Fixed
        )
        self.subtitle_table.setColumnWidth(0, 120)
        self.subtitle_table.setColumnWidth(1, 120)

        # 配置垂直表头
        self.subtitle_table.verticalHeader().setVisible(True)  # 显示垂直表头
        self.subtitle_table.verticalHeader().setDefaultAlignment(
            Qt.AlignCenter
        )  # 居中对齐
        self.subtitle_table.verticalHeader().setDefaultSectionSize(50)  # 行高
        self.subtitle_table.verticalHeader().setMinimumWidth(20)  # 设置最小宽度

        self.subtitle_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.subtitle_table.clicked.connect(self.on_subtitle_clicked)
        # 添加右键菜单支持
        self.subtitle_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.subtitle_table.customContextMenuRequested.connect(self.show_context_menu)
        self.main_layout.addWidget(self.subtitle_table)

    def _setup_bottom_layout(self):
        self.bottom_layout = QHBoxLayout()
        self.progress_bar = ProgressBar(self)
        self.status_label = BodyLabel(self.tr("请拖入字幕文件"), self)
        self.status_label.setMinimumWidth(100)
        self.status_label.setAlignment(Qt.AlignCenter)

        # 添加取消按钮
        self.cancel_button = PushButton(self.tr("取消"), self, icon=FIF.CANCEL)
        self.cancel_button.hide()  # 初始隐藏
        self.cancel_button.clicked.connect(self.cancel_optimization)

        self.bottom_layout.addWidget(self.progress_bar, 1)
        self.bottom_layout.addWidget(self.status_label)
        self.bottom_layout.addWidget(self.cancel_button)
        self.main_layout.addLayout(self.bottom_layout)

    def _setup_signals(self):
        self.review_marks_loaded.connect(self._apply_loaded_manual_review_marks)
        signalBus.subtitle_layout_changed.connect(self.on_subtitle_layout_changed)
        signalBus.target_language_changed.connect(self.on_target_language_changed)
        signalBus.subtitle_optimization_changed.connect(
            self.on_subtitle_optimization_changed
        )
        signalBus.subtitle_translation_changed.connect(
            self.on_subtitle_translation_changed
        )
        # self.subtitle_setting_button.clicked.connect(self.show_subtitle_settings)
        # self.video_player_button.clicked.connect(self.show_video_player)

    def show_prompt_dialog(self):
        dialog = PromptDialog(self)
        if dialog.exec_():
            self.custom_prompt_text = cfg.custom_prompt_text.value
            self._update_prompt_button_style()

    def _update_prompt_button_style(self):
        if self.custom_prompt_text.strip():
            green_icon = FIF.DOCUMENT.colored(
                QColor(76, 255, 165), QColor(76, 255, 165)
            )
            self.prompt_button.setIcon(green_icon)
        else:
            self.prompt_button.setIcon(FIF.DOCUMENT)

    def set_task(self, task: SubtitleTask):
        """设置任务并更新UI"""
        if hasattr(self, "subtitle_optimization_thread"):
            self.subtitle_optimization_thread.stop()
        self.start_button.setEnabled(True)
        self.task = task
        self.subtitle_path = task.subtitle_path
        self.update_info(task)

    def update_info(self, task: SubtitleTask):
        """更新页面信息"""
        original_subtitle_save_path = Path(self.task.subtitle_path)
        asr_data = ASRData.from_subtitle_file(original_subtitle_save_path)
        self.model.update_all(asr_data.to_json())
        self._load_manual_final_session(original_subtitle_save_path)

    def start_subtitle_optimization(self, need_create_task=True):
        # 检查是否有任务
        if not self.subtitle_path:
            InfoBar.warning(
                self.tr("警告"), self.tr("请先加载字幕文件"), duration=3000, parent=self
            )
            return
        self.start_button.setEnabled(False)
        self.progress_bar.reset()
        self.cancel_button.show()

        if need_create_task:
            self.task = TaskFactory.create_subtitle_task(file_path=self.subtitle_path)
        self.subtitle_optimization_thread = SubtitleThread(self.task)
        self.subtitle_optimization_thread.finished.connect(
            self.on_subtitle_optimization_finished
        )
        self.subtitle_optimization_thread.progress.connect(
            self.on_subtitle_optimization_progress
        )
        self.subtitle_optimization_thread.update.connect(self.update_data)
        self.subtitle_optimization_thread.update_all.connect(self.update_all)
        self.subtitle_optimization_thread.error.connect(
            self.on_subtitle_optimization_error
        )
        self.subtitle_optimization_thread.set_custom_prompt_text(
            self.custom_prompt_text
        )
        self.subtitle_optimization_thread.start()
        InfoBar.info(
            self.tr("开始优化"), self.tr("开始优化字幕"), duration=3000, parent=self
        )

    def process(self):
        """主处理函数"""
        # 检查是否有任务
        self.start_subtitle_optimization(need_create_task=False)

    def on_subtitle_optimization_finished(self, video_path, output_path):
        self.start_button.setEnabled(True)
        self.cancel_button.hide()  # 隐藏取消按钮
        self._load_manual_final_session_from_output(output_path)
        if self.task.need_next_task:
            self.finished.emit(video_path, output_path)
        InfoBar.success(
            self.tr("优化完成"),
            self.tr("优化完成字幕..."),
            duration=3000,
            position=InfoBarPosition.BOTTOM,
            parent=self.parent(),
        )
        self.check_quality_report(output_path)

    def on_subtitle_optimization_error(self, error):
        self.start_button.setEnabled(True)
        self.cancel_button.hide()  # 隐藏取消按钮
        self.progress_bar.error()
        InfoBar.error(self.tr("优化失败"), self.tr(error), duration=20000, parent=self)

    def on_subtitle_optimization_progress(self, value, status):
        self.progress_bar.setValue(value)
        self.status_label.setText(status)

    def update_data(self, data):
        self.model.update_data(data)

    def update_all(self, data):
        self.model.update_all(data)

    def quality_report_path(self, output_path: str) -> Path:
        path = Path(output_path)
        return path.with_name(f"{path.stem}-coverage-report.txt")

    def check_quality_report(self, output_path: str):
        report_path = self.quality_report_path(output_path)
        self.quality_report_action.setEnabled(report_path.exists())
        self.quality_report_action.setData(str(report_path))
        if not report_path.exists():
            self.status_label.setText(self.tr("未生成质量报告"))
            return

        text = report_path.read_text(encoding="utf-8", errors="ignore")
        gap_count = self._extract_report_count(text, "覆盖缺口数量", "缺口数量")
        missing_translation_count = self._extract_report_count(text, "缺中文字幕数量", "缺译文数量")
        overlong_count = self._extract_report_count(text, "英文超长数量")
        bad_cut_count = self._extract_report_count(text, "疑似坏切点数量")
        translationese_count = self._extract_report_count(text, "疑似翻译腔数量")
        if (
            gap_count
            or missing_translation_count
            or overlong_count
            or bad_cut_count
            or translationese_count
        ):
            message = self.tr(
                f"覆盖缺口 {gap_count} 处，缺中文字幕 {missing_translation_count} 处，"
                f"英文超长 {overlong_count} 处，疑似坏切点 {bad_cut_count} 处，"
                f"疑似翻译腔 {translationese_count} 处；点击“质量报告”查看"
            )
            self.status_label.setText(message)
            InfoBar.warning(
                self.tr("字幕质量检查发现问题"),
                message,
                duration=10000,
                position=InfoBarPosition.BOTTOM,
                parent=self.parent(),
            )
        else:
            self.status_label.setText(self.tr("字幕质量检查通过"))
            InfoBar.success(
                self.tr("字幕质量检查通过"),
                self.tr("未发现覆盖缺口、缺中文字幕、英文超长、明显坏切点或常见翻译腔"),
                duration=3000,
                position=InfoBarPosition.BOTTOM,
                parent=self.parent(),
            )

    @staticmethod
    def _extract_report_count(text: str, *labels: str) -> int:
        pattern = rf"(?:{'|'.join(re.escape(label) for label in labels)})[^0-9]*(\d+)"
        match = re.search(pattern, text)
        return int(match.group(1)) if match else 0

    def open_quality_report(self):
        report_path = Path(self.quality_report_action.data() or "")
        if not report_path.exists():
            InfoBar.warning(
                self.tr("质量报告不存在"),
                self.tr("当前任务还没有生成字幕质量报告"),
                duration=3000,
                parent=self,
            )
            return
        if sys.platform == "win32":
            os.startfile(str(report_path))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(report_path)])
        else:
            subprocess.run(["xdg-open", str(report_path)])

    def remove_widget(self):
        """隐藏顶部开始按钮和底部进度条"""
        self.start_button.hide()
        for i in range(self.bottom_layout.count()):
            widget = self.bottom_layout.itemAt(i).widget()
            if widget:
                widget.hide()

    def on_file_select(self):
        # 构建文件过滤器
        subtitle_formats = " ".join(
            f"*.{fmt.value}" for fmt in SupportedSubtitleFormats
        )
        filter_str = f"{self.tr('字幕文件')} ({subtitle_formats})"

        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择字幕文件"), "", filter_str
        )
        if file_path:
            self.subtitle_path = file_path
            self.load_subtitle_file(file_path)

    def on_save_format_clicked(self, format: str):
        """处理保存格式的选择"""
        if not self.subtitle_path:
            InfoBar.warning(
                self.tr("警告"), self.tr("请先加载字幕文件"), duration=3000, parent=self
            )
            return

        # 获取保存路径
        default_name = Path(self.subtitle_path).stem
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("保存字幕文件"),
            default_name,  # 使用原文件名作为默认名
            f"{self.tr('字幕文件')} (*.{format})",
        )
        if not file_path:
            return

        try:
            # 转换并保存字幕
            asr_data = ASRData.from_json(self.model._data)
            layout = cfg.subtitle_layout.value

            if file_path.endswith(".ass"):
                style_str = get_subtitle_style(cfg.subtitle_style_name.value)
                asr_data.to_ass(style_str, layout, file_path)
            else:
                asr_data.save(file_path, layout=layout)
            InfoBar.success(
                self.tr("保存成功"),
                self.tr(f"字幕已保存至:") + file_path,
                duration=3000,
                parent=self,
            )
        except Exception as e:
            InfoBar.error(
                self.tr("保存失败"),
                self.tr("保存字幕文件失败: ") + str(e),
                duration=5000,
                parent=self,
            )

    def on_open_folder_clicked(self):
        """打开文件夹按钮点击事件"""
        if not self.task:
            InfoBar.warning(
                self.tr("警告"), self.tr("请先加载字幕文件"), duration=3000, parent=self
            )
            return
        output_path = Path(self.task.output_path)
        target_dir = str(
            output_path.parent
            if output_path.exists()
            else Path(self.task.subtitle_path).parent
        )
        if sys.platform == "win32":
            os.startfile(target_dir)
        elif sys.platform == "darwin":  # macOS
            subprocess.run(["open", target_dir])
        else:  # Linux
            subprocess.run(["xdg-open", target_dir])

    def load_subtitle_file(self, file_path) -> bool:
        """Load a subtitle file without leaving the table in an indeterminate state."""
        try:
            asr_data = ASRData.from_subtitle_file(file_path)
        except Exception as exc:
            LOG.exception("Unable to import subtitle file: %s", file_path)
            self.status_label.setText(self.tr("字幕导入失败：") + str(exc))
            InfoBar.error(
                self.tr("导入失败"),
                self.tr("无法读取字幕文件：") + str(exc),
                duration=5000,
                parent=self,
            )
            return False

        self.subtitle_path = file_path
        self.model.update_all(asr_data.to_json())
        self._load_manual_final_session(Path(file_path))
        return True

    def _load_manual_final_session(self, subtitle_path: Path) -> None:
        self.manual_final_session = None
        self._manual_review_mark_count = 0
        self._review_mark_rows = []
        self._review_mark_request_id += 1
        self.model.set_review_marks({})
        self.next_review_action.setEnabled(False)
        self.next_review_action.setVisible(False)
        self.manual_final_save_action.setEnabled(False)
        self.manual_final_save_action.setVisible(False)
        self.manual_final_undo_action.setEnabled(False)
        self.manual_final_undo_action.setVisible(False)
        try:
            session = ManualFinalSubtitleSession.load_for_subtitle(
                subtitle_path,
                work_dir=cfg.work_dir.value,
            )
        except ManualFinalSubtitleEditError as exc:
            self.status_label.setText(
                self.tr("已加载文件；人工终稿编辑不可用：") + str(exc)
            )
            return
        self.manual_final_session = session
        self.subtitle_path = str(session.subtitle_path)
        self._load_manual_final_review_marks(session)
        self._apply_manual_final_session()
        self.status_label.setText(
            self.tr(
                f"已加载 {self.model.rowCount()} 条稳定终稿，可按词级时间移动相邻字幕边界；正在检查高优先复查点"
            )
        )

    def _load_manual_final_session_from_output(self, output_path: str) -> None:
        manifest_path = Path(output_path).parent / "stable-final-manifest.json"
        if not manifest_path.exists():
            return
        self.manual_final_session = None
        self._manual_review_mark_count = 0
        self._review_mark_rows = []
        self._review_mark_request_id += 1
        self.model.set_review_marks({})
        self.next_review_action.setEnabled(False)
        self.next_review_action.setVisible(False)
        self.manual_final_save_action.setEnabled(False)
        self.manual_final_save_action.setVisible(False)
        self.manual_final_undo_action.setEnabled(False)
        self.manual_final_undo_action.setVisible(False)
        try:
            session = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        except ManualFinalSubtitleEditError as exc:
            self.status_label.setText(self.tr("字幕已生成，但人工终稿编辑不可用：") + str(exc))
            return
        self.manual_final_session = session
        self.subtitle_path = str(session.subtitle_path)
        self._load_manual_final_review_marks(session)
        self._apply_manual_final_session()
        self.status_label.setText(
            self.tr(
                f"稳定终稿已就绪（{self.model.rowCount()} 条），可按词级时间手动调整边界；正在检查高优先复查点"
            )
        )

    def _load_manual_final_review_marks(self, session: ManualFinalSubtitleSession) -> None:
        request_id = self._review_mark_request_id
        artifact_dir = session.artifact_dir
        Thread(
            target=self._read_manual_review_marks,
            args=(request_id, artifact_dir),
            daemon=True,
        ).start()

    def _read_manual_review_marks(self, request_id: int, artifact_dir: Path) -> None:
        try:
            marks_by_subtitle_id = load_subtitle_review_marks(artifact_dir)
            if not syntax_review_parser_available():
                marks_by_subtitle_id = self._load_review_marks_in_isolated_runtime(
                    artifact_dir
                )
            error = ""
        except Exception as exc:
            LOG.exception("Unable to load subtitle review marks from: %s", artifact_dir)
            marks_by_subtitle_id = {}
            error = str(exc)
        self.review_marks_loaded.emit(request_id, marks_by_subtitle_id, error)

    @staticmethod
    def _load_review_marks_in_isolated_runtime(
        artifact_dir: Path,
    ) -> dict[str, list[SubtitleReviewMark]]:
        """Run spaCy away from the GUI's already-loaded GPU runtime."""
        project_root = Path(__file__).resolve().parents[2]
        runtime_python = project_root / "runtime" / "python.exe"
        if not runtime_python.exists():
            raise RuntimeError("本地复查运行环境不存在。")
        completed = subprocess.run(
            [
                str(runtime_python),
                "-X",
                "utf8",
                "-m",
                "app.core.subtitle_processor.subtitle_review_marks",
                str(artifact_dir),
            ],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(detail or "本地复查运行进程失败。")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("本地复查运行进程返回了无效结果。") from exc
        if not isinstance(payload, dict) or not payload.get("syntax_parser_available"):
            raise RuntimeError("本地英文句法复查引擎不可用。")
        return review_marks_from_payload(payload.get("marks"))

    def _apply_loaded_manual_review_marks(
        self, request_id: int, marks_by_subtitle_id: dict, error: str
    ) -> None:
        if request_id != self._review_mark_request_id or not self.manual_final_session:
            return
        if error:
            self.status_label.setText(
                self.tr("稳定终稿已加载；高优先复查标记加载失败，字幕内容未受影响。")
            )
            return
        self.model.set_review_marks(marks_by_subtitle_id)
        self._manual_review_mark_count = sum(
            len(marks) for marks in marks_by_subtitle_id.values()
        )
        self._review_mark_rows = self._rows_with_review_marks(marks_by_subtitle_id)
        self.next_review_action.setEnabled(bool(self._review_mark_rows))
        self.next_review_action.setVisible(bool(self._review_mark_rows))
        if self._review_mark_rows:
            time_ranges = "、".join(
                self._review_time_range(row) for row in self._review_mark_rows
            )
            self.status_label.setText(
                self.tr(
                    f"已加载稳定终稿；已标出 {self._manual_review_mark_count} 个高优先复查点（{time_ranges}），可点“下一处复查”定位"
                )
            )
        else:
            self.status_label.setText(
                self.tr("已加载稳定终稿；未发现高优先复查点。")
            )

    def _rows_with_review_marks(self, marks_by_subtitle_id: dict) -> list[int]:
        marked_ids = {str(subtitle_id) for subtitle_id in marks_by_subtitle_id}
        rows = []
        for row in range(self.model.rowCount()):
            segment = self.model._data.get(str(row + 1), {})
            source_ids = {str(value) for value in segment.get("source_subtitle_ids") or []}
            source_ids.update(
                str(value)
                for value in (segment.get("subtitle_id"), segment.get("manual_cue_id"))
                if value
            )
            if source_ids & marked_ids:
                rows.append(row)
        return rows

    def _review_time_range(self, row: int) -> str:
        segment = self.model._data.get(str(row + 1), {})
        start = QTime(0, 0).addMSecs(int(segment.get("start_time") or 0))
        end = QTime(0, 0).addMSecs(int(segment.get("end_time") or 0))
        return f"{start.toString('hh:mm:ss.zzz')}–{end.toString('hh:mm:ss.zzz')}"

    def focus_next_review_mark(self) -> None:
        if not self._review_mark_rows:
            return
        current_row = self.subtitle_table.currentIndex().row()
        target_row = next(
            (row for row in self._review_mark_rows if row > current_row),
            self._review_mark_rows[0],
        )
        target = self.model.index(target_row, 2)
        self.subtitle_table.setCurrentIndex(target)
        self.subtitle_table.selectRow(target_row)
        self.subtitle_table.scrollTo(target, QAbstractItemView.PositionAtCenter)

    def _manual_review_status_suffix(self) -> str:
        if not self._manual_review_mark_count:
            return ""
        return self.tr(f"；已标出 {self._manual_review_mark_count} 个高优先复查点")

    def _sync_manual_final_text_edits(self) -> None:
        if not self.manual_final_session:
            return
        if len(self.model._data) != len(self.manual_final_session.cues):
            raise ManualFinalSubtitleEditError("字幕行数已变化，无法安全应用人工终稿操作。")
        for index, cue in enumerate(self.manual_final_session.cues, 1):
            row = self.model._data.get(str(index))
            if not row:
                raise ManualFinalSubtitleEditError("字幕表数据不完整。")
            cue["original_subtitle"] = str(row.get("original_subtitle") or "")
            cue["translated_subtitle"] = str(row.get("translated_subtitle") or "")

    def _apply_manual_final_session(self) -> None:
        if not self.manual_final_session:
            return
        self.model.update_all(self.manual_final_session.to_model_data())
        self.manual_final_save_action.setEnabled(True)
        self.manual_final_save_action.setVisible(True)
        self.manual_final_undo_action.setEnabled(bool(self.manual_final_session.history))
        self.manual_final_undo_action.setVisible(True)

    def _move_suffix_to_next(self, row: int) -> None:
        if not self.manual_final_session:
            return
        left = self.manual_final_session.cues[row]
        maximum = int(left["word_end"]) - int(left["word_start"])
        count, accepted = QInputDialog.getInt(
            self,
            self.tr("移动末尾词"),
            self.tr("移动到下一条的末尾英文词数："),
            1,
            1,
            maximum,
        )
        if not accepted:
            return
        try:
            self._sync_manual_final_text_edits()
            self.manual_final_session.move_suffix_to_next(row, count)
            self._apply_manual_final_session()
            InfoBar.success(
                self.tr("边界已更新"),
                self.tr("英文词范围和两条时间轴已按词级账本同步更新，请检查中文。"),
                duration=3000,
                parent=self,
            )
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(self.tr("无法移动边界"), str(exc), duration=5000, parent=self)

    def _move_prefix_to_previous(self, row: int) -> None:
        if not self.manual_final_session:
            return
        right = self.manual_final_session.cues[row]
        maximum = int(right["word_end"]) - int(right["word_start"])
        count, accepted = QInputDialog.getInt(
            self,
            self.tr("移动开头词"),
            self.tr("移动到上一条的开头英文词数："),
            1,
            1,
            maximum,
        )
        if not accepted:
            return
        try:
            self._sync_manual_final_text_edits()
            self.manual_final_session.move_prefix_to_previous(row, count)
            self._apply_manual_final_session()
            InfoBar.success(
                self.tr("边界已更新"),
                self.tr("英文词范围和两条时间轴已按词级账本同步更新，请检查中文。"),
                duration=3000,
                parent=self,
            )
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(self.tr("无法移动边界"), str(exc), duration=5000, parent=self)

    def undo_manual_final_edit(self) -> None:
        if not self.manual_final_session:
            return
        try:
            self._sync_manual_final_text_edits()
            if self.manual_final_session.undo():
                self._apply_manual_final_session()
                self.status_label.setText(self.tr("已撤销最近一次人工终稿边界编辑"))
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(self.tr("无法撤销"), str(exc), duration=5000, parent=self)

    def save_manual_final_output(self) -> None:
        if not self.manual_final_session:
            InfoBar.warning(
                self.tr("人工终稿不可用"),
                self.tr("请加载带稳定 artifacts 的最终双语字幕。"),
                duration=5000,
                parent=self,
            )
            return
        try:
            self._sync_manual_final_text_edits()
            paths = self.manual_final_session.save_to_source_folder()
            self.status_label.setText(self.tr("人工终稿已保存，视频合成将优先使用它"))
            InfoBar.success(
                self.tr("人工终稿已保存"),
                self.tr("字幕：") + paths["subtitle_path"],
                duration=5000,
                parent=self,
            )
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(self.tr("保存失败"), str(exc), duration=5000, parent=self)

    def dragEnterEvent(self, event: QDragEnterEvent):
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file_path in files:
            if not os.path.isfile(file_path):
                continue

            file_ext = os.path.splitext(file_path)[1][1:].lower()

            # 检查文件格式是否支持
            supported_formats = {fmt.value for fmt in SupportedSubtitleFormats}
            is_supported = file_ext in supported_formats

            if is_supported:
                if self.load_subtitle_file(file_path):
                    InfoBar.success(
                        self.tr("导入成功"),
                        self.tr(f"成功导入") + os.path.basename(file_path),
                        duration=3000,
                        position=InfoBarPosition.BOTTOM,
                        parent=self,
                    )
                break
            else:
                InfoBar.error(
                    self.tr(f"格式错误") + file_ext,
                    self.tr(f"支持的字幕格式:") + str(supported_formats),
                    duration=3000,
                    parent=self,
                )
        event.accept()

    def closeEvent(self, event):
        if hasattr(self, "subtitle_optimization_thread"):
            self.subtitle_optimization_thread.stop()
        super().closeEvent(event)

    def show_subtitle_settings(self):
        """显示字幕设置对话框"""
        dialog = SubtitleSettingDialog(self.window())
        dialog.exec_()

    def show_video_player(self):
        """显示视频播放器窗口"""
        # 创建视频播放器窗口
        from ..components.MyVideoWidget import MyVideoWidget

        self.video_player = MyVideoWidget()
        self.video_player.resize(800, 600)

        def signal_update():
            if not self.model._data:
                return
            ass_style_name = cfg.subtitle_style_name.value
            ass_style_path = SUBTITLE_STYLE_PATH / f"{ass_style_name}.txt"
            if ass_style_path.exists():
                subtitle_style_srt = ass_style_path.read_text(encoding="utf-8")
            else:
                subtitle_style_srt = None
            temp_srt_path = os.path.join(tempfile.gettempdir(), "temp_subtitle.ass")
            asr_data = ASRData.from_json(self.model._data)
            asr_data.save(
                temp_srt_path,
                layout=cfg.subtitle_layout.value,
                ass_style=subtitle_style_srt,
            )
            signalBus.add_subtitle(temp_srt_path)

        # 如果有字幕文件,则添加字幕
        signal_update()

        signalBus.subtitle_layout_changed.connect(signal_update)
        self.model.dataChanged.connect(signal_update)
        self.model.layoutChanged.connect(signal_update)

        # 如果有关联的视频文件,则自动加载
        if self.task and hasattr(self.task, "file_path") and self.task.file_path:
            self.video_player.setVideo(QUrl.fromLocalFile(self.task.file_path))

        self.video_player.show()
        self.video_player.play()

    def on_subtitle_clicked(self, index):
        row = index.row()
        item = list(self.model._data.values())[row]
        start_time = item["start_time"]  # 毫秒
        end_time = (
            item["end_time"] - 50
            if item["end_time"] - 50 > start_time
            else item["end_time"]
        )
        signalBus.play_video_segment(start_time, end_time)

    def show_context_menu(self, pos):
        """显示右键菜单"""
        clicked_index = self.subtitle_table.indexAt(pos)
        if not clicked_index.isValid():
            return

        # Qt does not select the row on a right-click. Select the clicked row
        # before reading the selection so its contextual actions are available.
        selected_rows = {index.row() for index in self.subtitle_table.selectedIndexes()}
        if clicked_index.row() not in selected_rows:
            self.subtitle_table.clearSelection()
            self.subtitle_table.selectRow(clicked_index.row())

        menu = RoundMenu(parent=self)

        # 获取选中的行
        indexes = self.subtitle_table.selectedIndexes()
        if not indexes:
            return

        # 获取唯一的行号
        rows = sorted(set(index.row() for index in indexes))
        if not rows:
            return

        rows_are_contiguous = rows == list(range(rows[0], rows[-1] + 1))
        merge_action = Action(FIF.LINK, self.tr("合并相邻字幕"))
        menu.addAction(merge_action)
        merge_action.setShortcut("Ctrl+M")  # 设置快捷键
        merge_action.setEnabled(len(rows) > 1 and rows_are_contiguous)
        merge_action.triggered.connect(lambda: self.merge_selected_rows(rows))

        if self.manual_final_session and len(rows) == 1:
            row = rows[0]
            left = self.manual_final_session.cues[row]
            move_tail_action = Action(FIF.EDIT, self.tr("将末尾词移到下一条"))
            move_tail_action.setEnabled(
                row + 1 < len(self.manual_final_session.cues)
                and int(left["word_end"]) > int(left["word_start"])
            )
            move_tail_action.triggered.connect(lambda: self._move_suffix_to_next(row))
            menu.addAction(move_tail_action)

            right = self.manual_final_session.cues[row]
            move_head_action = Action(FIF.EDIT, self.tr("将开头词移到上一条"))
            move_head_action.setEnabled(
                row > 0 and int(right["word_end"]) > int(right["word_start"])
            )
            move_head_action.triggered.connect(lambda: self._move_prefix_to_previous(row))
            menu.addAction(move_head_action)

        # 显示菜单
        menu.exec(self.subtitle_table.viewport().mapToGlobal(pos))

    def merge_selected_rows(self, rows):
        """合并选中的字幕行"""
        if not rows or len(rows) < 2:
            return
        if rows != list(range(rows[0], rows[-1] + 1)):
            InfoBar.warning(
                self.tr("无法合并"),
                self.tr("只能合并连续相邻的字幕行，避免丢失中间字幕。"),
                duration=5000,
                parent=self,
            )
            return

        if self.manual_final_session:
            try:
                self._sync_manual_final_text_edits()
                self.manual_final_session.merge_adjacent(rows[0], rows[-1])
                self._apply_manual_final_session()
                InfoBar.success(
                    self.tr("合并成功"),
                    self.tr("已按原始词范围合并相邻字幕，请检查合并后的中文。"),
                    duration=3000,
                    parent=self,
                )
            except ManualFinalSubtitleEditError as exc:
                InfoBar.warning(self.tr("无法合并"), str(exc), duration=5000, parent=self)
            return

        # 获取选中行的数据
        data = self.model._data
        data_list = list(data.values())

        # 获取第一行和最后一行的时间戳
        first_row = data_list[rows[0]]
        last_row = data_list[rows[-1]]
        start_time = first_row["start_time"]
        end_time = last_row["end_time"]

        # 合并字幕内容
        original_subtitles = []
        translated_subtitles = []
        for row in rows:
            item = data_list[row]
            original_subtitles.append(item["original_subtitle"])
            translated_subtitles.append(item["translated_subtitle"])

        merged_original = " ".join(original_subtitles)
        merged_translated = "".join(translated_subtitles)

        # 创建新的合并后的字幕项
        merged_item = {
            "start_time": start_time,
            "end_time": end_time,
            "original_subtitle": merged_original,
            "translated_subtitle": merged_translated,
        }

        # 获取所有需要保留的键
        keys = list(data.keys())
        preserved_keys = keys[: rows[0]] + keys[rows[-1] + 1 :]

        # 创建新的数据字典
        new_data = {}
        for i, key in enumerate(preserved_keys):
            if i == rows[0]:
                new_key = f"{len(new_data)+1}"
                new_data[new_key] = merged_item
            new_key = f"{len(new_data)+1}"
            new_data[new_key] = data[key]

        # 如果合并的是最后几行，需要确保合并项被添加
        if rows[0] >= len(preserved_keys):
            new_key = f"{len(new_data)+1}"
            new_data[new_key] = merged_item

        # 更新模型数据
        self.model.update_all(new_data)

        # 显示成功提示
        InfoBar.success(
            self.tr("合并成功"),
            self.tr("已成功合并选中的字幕行"),
            duration=1000,
            parent=self,
        )

    def keyPressEvent(self, event):
        """处理键盘事件"""
        # 处理 Ctrl+M 快捷键
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_M:
            indexes = self.subtitle_table.selectedIndexes()
            if indexes:
                rows = sorted(set(index.row() for index in indexes))
                if len(rows) > 1:
                    self.merge_selected_rows(rows)
            event.accept()
        else:
            super().keyPressEvent(event)

    def cancel_optimization(self):
        """取消字幕校正"""
        if hasattr(self, "subtitle_optimization_thread"):
            self.subtitle_optimization_thread.stop()
            self.start_button.setEnabled(True)
            self.cancel_button.hide()
            self.progress_bar.setValue(0)
            self.status_label.setText(self.tr("已取消校正"))
            InfoBar.warning(
                self.tr("已取消"), self.tr("字幕校正已取消"), duration=3000, parent=self
            )

    def on_target_language_changed(self, language: str):
        """处理翻译语言变更"""
        for lang in TargetLanguageEnum:
            if lang.value == language:
                self.target_language_button.setText(lang.value)
                cfg.set(cfg.target_language, lang)
                break

    def on_subtitle_optimization_changed(self, checked: bool):
        """处理字幕优化开关变更"""
        cfg.set(cfg.need_optimize, checked)
        self.optimize_button.setChecked(checked)

    def on_subtitle_translation_changed(self, checked: bool):
        """处理字幕翻译开关变更"""
        cfg.set(cfg.need_translate, checked)
        self.translate_button.setChecked(checked)
        # 控制翻译语言选择按钮的启用状态
        self.target_language_button.setEnabled(checked)

    def on_subtitle_layout_changed(self, layout: str):
        """处理字幕排布变更"""
        cfg.set(cfg.subtitle_layout, layout)
        self.layout_button.setText(layout)


class PromptDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.setWindowTitle(self.tr("文稿提示"))
        # 连接按钮点击事件
        self.yesButton.clicked.connect(self.save_prompt)

    def setup_ui(self):
        self.titleLabel = BodyLabel(self.tr("文稿提示"), self)

        # 添加文本编辑框
        self.text_edit = TextEdit(self)
        self.text_edit.setPlaceholderText(
            self.tr(
                "请输入文稿提示（辅助校正字幕和翻译）\n\n"
                "支持以下内容:\n"
                "1. 术语表 - 专业术语、人名、特定词语的修正对照表\n"
                "示例:\n机器学习->Machine Learning\n马斯克->Elon Musk\n打call->应援\n\n"
                "2. 原字幕文稿 - 视频的原有文稿或相关内容\n"
                "示例: 完整的演讲稿、课程讲义等\n\n"
                "3. 修正要求 - 内容相关的具体修正要求\n"
                "示例: 统一人称代词、规范专业术语等\n\n"
                "注意: 使用小型LLM模型时建议控制文稿在1千字内。对于不同字幕文件,请使用与该字幕相关的文稿提示。"
            )
        )
        self.text_edit.setText(cfg.custom_prompt_text.value)

        self.text_edit.setMinimumWidth(420)
        self.text_edit.setMinimumHeight(380)

        # 添加到布局
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.text_edit)
        self.viewLayout.setSpacing(10)

        # 设置按钮文本
        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

    def get_prompt(self):
        return self.text_edit.toPlainText()

    def save_prompt(self):
        # 在点击确定按钮时保存提示文本到配置
        prompt_text = self.text_edit.toPlainText()
        cfg.set(cfg.custom_prompt_text, prompt_text)


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    window = SubtitleInterface()
    window.show()
    sys.exit(app.exec_())
