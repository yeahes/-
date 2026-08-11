# -*- coding: utf-8 -*-
import copy
import html
import os
import re
import subprocess
import sys
import tempfile
import json
import logging
from pathlib import Path
from threading import Lock, Thread

from PyQt5.QtCore import Qt, QTime, QUrl, QAbstractTableModel, pyqtSignal
from PyQt5.QtGui import QColor, QDragEnterEvent, QDropEvent
from PyQt5.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    CommandBar,
    CommandButton,
    SpinBox,
    isDarkTheme,
)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    InfoBar,
    InfoBarPosition,
    IndeterminateProgressBar,
    MessageBox,
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
    review_marks_require_syntax_parser,
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
from app.thread.video_synthesis_thread import (
    MANUAL_DRAFT_ALLOWED_BLOCK_REASONS,
    resolve_synthesis_package_inputs,
)


LOG = logging.getLogger(__name__)
SUBTITLE_TIME_COLUMN_WIDTH = 96
_MANUAL_FINAL_SAVE_LOCK = Lock()
_MANUAL_FINAL_SAVE_ACTIVITY_LOCK = Lock()
_MANUAL_FINAL_SAVE_ACTIVE_COUNT = 0


def _manual_final_save_worker_started() -> None:
    global _MANUAL_FINAL_SAVE_ACTIVE_COUNT
    with _MANUAL_FINAL_SAVE_ACTIVITY_LOCK:
        _MANUAL_FINAL_SAVE_ACTIVE_COUNT += 1


def _manual_final_save_worker_finished() -> None:
    global _MANUAL_FINAL_SAVE_ACTIVE_COUNT
    with _MANUAL_FINAL_SAVE_ACTIVITY_LOCK:
        _MANUAL_FINAL_SAVE_ACTIVE_COUNT = max(
            0,
            _MANUAL_FINAL_SAVE_ACTIVE_COUNT - 1,
        )


def manual_final_save_worker_active() -> bool:
    with _MANUAL_FINAL_SAVE_ACTIVITY_LOCK:
        return _MANUAL_FINAL_SAVE_ACTIVE_COUNT > 0


class _StateAwareCommandBar(CommandBar):
    """Command bar that honors business visibility for actions and widgets."""

    _AVAILABLE_PROPERTY = "commandBarAvailable"

    def addAction(self, action):
        button = super().addAction(action)
        action.changed.connect(self.updateGeometry)
        self.updateGeometry()
        return button

    def insertAction(self, before, action):
        button = super().insertAction(before, action)
        if button is not None:
            action.changed.connect(self.updateGeometry)
            self.updateGeometry()
        return button

    def setWidgetAvailable(self, widget: QWidget, available: bool) -> None:
        if widget not in self._widgets:
            return
        widget.setProperty(self._AVAILABLE_PROPERTY, bool(available))
        if not available:
            widget.hide()
        self.updateGeometry()

    def _availableWidgets(self):
        available = []
        for widget in self._widgets:
            if isinstance(widget, CommandButton):
                action = widget.action()
                if action is not None and not action.isVisible():
                    continue
            if widget.property(self._AVAILABLE_PROPERTY) is False:
                continue
            available.append(widget)
        return available

    def _visibleHiddenActions(self):
        return [action for action in self._hiddenActions if action.isVisible()]

    @staticmethod
    def _widgetsWidth(widgets, spacing: int) -> int:
        return sum(widget.width() for widget in widgets) + spacing * max(
            len(widgets) - 1,
            0,
        )

    def _visibleWidgets(self):
        available = self._availableWidgets()
        hidden_actions = self._visibleHiddenActions()
        suitable_width = self._widgetsWidth(available, self.spacing())
        if hidden_actions:
            suitable_width += self.moreButton.width()
            if available:
                suitable_width += self.spacing()
        if suitable_width <= self.width():
            return available

        visible = []
        used_width = self.moreButton.width()
        for widget in available:
            candidate_width = used_width + widget.width()
            if visible:
                candidate_width += self.spacing()
            if candidate_width > self.width():
                break
            visible.append(widget)
            used_width = candidate_width
        return visible

    def suitableWidth(self):
        available = self._availableWidgets()
        widths = [widget.width() for widget in available]
        if self._visibleHiddenActions():
            widths.append(self.moreButton.width())
        return sum(widths) + self.spacing() * max(len(widths) - 1, 0)

    def updateGeometry(self):
        self._hiddenWidgets.clear()
        self.moreButton.hide()

        available = self._availableWidgets()
        visible = self._visibleWidgets()
        for widget in self._widgets:
            widget.hide()

        x = self.contentsMargins().left()
        height = self.height()
        for widget in visible:
            widget.show()
            widget.move(x, (height - widget.height()) // 2)
            x += widget.width() + self.spacing()

        overflow = available[len(visible) :]
        self._hiddenWidgets.extend(overflow)
        if self._visibleHiddenActions() or overflow:
            self.moreButton.show()
            self.moreButton.move(x, (height - self.moreButton.height()) // 2)


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
            review_tooltip = self._review_tooltip(marks, col)
            return review_tooltip or None
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
                if segment.get("display_page_view"):
                    chinese_present = bool(str(value or "").strip())
                    segment["display_page_chinese_confirmed"] = chinese_present
                    segment["chinese_review_required"] = not chinese_present
            else:
                return False

            bottom_right = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(
                index,
                bottom_right,
                [Qt.DisplayRole, Qt.EditRole, Qt.ToolTipRole],
            )
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
                row = self._data.get(str(section + 1)) or {}
                stable_id = str(
                    row.get("display_page_id")
                    or row.get("manual_cue_id")
                    or ""
                ).strip()
                return stable_id or str(section + 1)
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
        segment = self._data.get(str(index.row() + 1)) or {}
        editable_columns = (
            [3]
            if segment.get("display_page_view") or segment.get("manual_cue_id")
            else [2, 3]
        )
        if index.column() in editable_columns:
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

    def remove_review_marks_for_subtitle_ids(self, subtitle_ids) -> None:
        removed = {str(value) for value in subtitle_ids if str(value)}
        if not removed:
            return
        filtered = {
            subtitle_id: marks
            for subtitle_id, marks in self._review_marks_by_subtitle_id.items()
            if subtitle_id not in removed
        }
        if len(filtered) != len(self._review_marks_by_subtitle_id):
            self.set_review_marks(filtered)

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
        if segment.get("display_page_chinese_stale") and not segment.get(
            "display_page_chinese_confirmed"
        ):
            local_split_proposal = (
                str(segment.get("display_page_chinese_draft_kind") or "")
                == "local_parent_split_proposal"
            )
            marks.append(
                SubtitleReviewMark(
                    subtitle_id=str(segment.get("manual_cue_id") or "人工终稿"),
                    severity="REVIEW",
                    category="manual_chinese_review",
                    target="chinese",
                    code=(
                        "local_parent_split_proposal"
                        if local_split_proposal
                        else "stale_page_chinese_draft"
                    ),
                    reason=(
                        "这里显示的是程序按父字幕中文和英文页词数生成的本地建议稿；"
                        "请逐页编辑或确认，未确认时不会用于正式成片。"
                        if local_split_proposal
                        else "这里显示的是父字幕更新前的分页中文旧稿；请逐页编辑或确认，"
                        "未确认时不会用于正式成片。"
                    ),
                )
            )
        elif segment.get("chinese_review_required"):
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
        if segment.get("display_page_unavailable"):
            marks.append(
                SubtitleReviewMark(
                    subtitle_id=str(segment.get("manual_cue_id") or "人工终稿"),
                    severity="BLOCKER",
                    category="visual_page",
                    target="english",
                    code="display_page_unavailable",
                    reason="当前父字幕没有可用的实际分页，需要刷新或人工分屏。",
                )
            )
        elif segment.get("display_page_review_required"):
            issue_codes = [
                str(code)
                for code in segment.get("display_page_issue_codes") or []
                if str(code)
            ]
            classification = str(
                segment.get("display_page_boundary_classification") or "review"
            )
            marks.append(
                SubtitleReviewMark(
                    subtitle_id=str(segment.get("manual_cue_id") or "人工终稿"),
                    severity=("BLOCKER" if classification == "hard" else "REVIEW"),
                    category="visual_page",
                    target="english",
                    code=(issue_codes[0] if issue_codes else "display_page_review"),
                    reason=(
                        "实际分页切点需要人工确认：" + ", ".join(issue_codes)
                        if issue_codes
                        else "实际分页切点需要人工确认。"
                    ),
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
                "visual_page": "#29322E",
                "manual_chinese_review": "#27241F",
            }
        else:
            colors = {
                "blocker": "#FFF9F8",
                "english_cut": "#EAF4FF",
                "timeline_alignment": "#F4F1FB",
                "chinese_allocation": "#FFFCF7",
                "visual_page": "#ECF8F1",
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
        if any(mark.category == "visual_page" for mark in relevant):
            return QColor(colors["visual_page"])
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
            "visual_page": "视觉分页复查",
            "manual_chinese_review": "人工调整后中文待检查",
        }
        lines = []
        for mark in relevant:
            label = labels.get(mark.category, "字幕复查")
            lines.append(f"[{label}] {mark.subtitle_id}: {mark.reason}")
        return "\n".join(lines)


class SubtitleInterface(QWidget):
    finished = pyqtSignal(str, str)
    manual_final_ready = pyqtSignal(str, str)
    manual_draft_ready = pyqtSignal(str, str)
    review_marks_loaded = pyqtSignal(int, object, str)
    manual_final_save_finished = pyqtSignal(int, object, str)
    manual_final_save_progress = pyqtSignal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.task = None
        self.subtitle_path = None
        self.manual_final_session = None
        self._manual_review_mark_count = 0
        self._review_mark_request_id = 0
        self._review_mark_rows = []
        self._manual_review_invalidated_ids = set()
        self._manual_package_manifest_path = ""
        self._manual_page_view = True
        self._manual_parent_boundaries_dirty = False
        self._manual_boundary_left_index_value = 0
        self._manual_boundary_refreshing = False
        self._manual_boundary_word_count_value = 1
        self._manual_boundary_kind = ""
        self._manual_boundary_left_page_id = ""
        self._manual_boundary_table_left_row = 0
        self._manual_boundary_parent_left_index = 0
        self._manual_boundary_index_widgets = []
        self._manual_boundary_resized_rows = {}
        self._manual_boundary_edit_active = False
        self._manual_boundary_move_direction = ""
        self._manual_save_request_id = 0
        self._manual_save_in_progress = False
        self._manual_refresh_requested = False
        self._manual_active_save_context = None
        self._manual_pending_page_split = None
        self._manual_has_unsaved_changes = False
        self._manual_model_has_pending_edits = False
        self._manual_clean_state_fingerprint = ""
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
        self.command_bar = _StateAwareCommandBar(self)
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
        self.save_button = TransparentDropDownPushButton(
            self.tr("保存"), self, FIF.SAVE
        )
        self.save_button.setMenu(save_menu)
        self.save_button.setFixedHeight(34)
        self.command_bar.addWidget(self.save_button)

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

        self.next_review_action = Action(
            FIF.SEARCH, self.tr("下一处复查"), triggered=self.focus_next_review_mark
        )
        self.next_review_action.setEnabled(False)
        self.next_review_action.setVisible(False)
        self.command_bar.addAction(self.next_review_action)

        self.manual_page_view_action = Action(
            FIF.VIEW,
            self.tr("查看父字幕"),
            triggered=self.toggle_manual_page_view,
        )
        self.manual_page_view_action.setEnabled(False)
        self.manual_page_view_action.setVisible(False)
        self.command_bar.addAction(self.manual_page_view_action)

        self.manual_final_save_action = Action(
            FIF.SAVE, self.tr("保存人工终稿"), triggered=self.save_manual_final_output
        )
        self.manual_final_save_action.setEnabled(False)
        self.manual_final_save_action.setVisible(False)
        self.command_bar.addAction(self.manual_final_save_action)

        self.manual_final_synthesis_action = Action(
            FIF.VIDEO,
            self.tr("前往视频合成"),
            triggered=self.open_manual_final_in_synthesis,
        )
        self.manual_final_synthesis_action.setEnabled(False)
        self.manual_final_synthesis_action.setVisible(False)
        self.command_bar.addAction(self.manual_final_synthesis_action)

        self.manual_draft_synthesis_action = Action(
            FIF.VIDEO,
            self.tr("合成草稿"),
            triggered=self.open_manual_draft_in_synthesis,
        )
        self.manual_draft_synthesis_action.setEnabled(False)
        self.manual_draft_synthesis_action.setVisible(False)
        self.command_bar.addAction(self.manual_draft_synthesis_action)

        self.manual_final_undo_action = Action(
            FIF.SYNC, self.tr("撤销"), triggered=self.undo_manual_final_edit
        )
        self.manual_final_undo_action.setEnabled(False)
        self.manual_final_undo_action.setVisible(False)
        self.command_bar.addAction(self.manual_final_undo_action)

        self.more_menu = RoundMenu(parent=self)
        self.more_menu.addAction(self.optimize_button)
        self.more_menu.addAction(self.prompt_button)
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

        # 添加开始按钮到水平布局
        self.start_button = PrimaryPushButton(self.tr("开始"), self, icon=FIF.PLAY)
        self.start_button.clicked.connect(
            lambda: self.start_subtitle_optimization(need_create_task=True)
        )
        self.start_button.setFixedHeight(34)
        top_layout.addWidget(self.start_button)

        self.main_layout.addLayout(top_layout)

    def _set_manual_editor_mode(self, enabled: bool) -> None:
        """Expose one coherent command set for processing or manual final editing."""
        manual_mode = bool(enabled)
        table = getattr(self, "subtitle_table", None)
        if table is not None:
            table.verticalHeader().setMinimumWidth(84 if manual_mode else 36)
        self.command_bar.setWidgetAvailable(self.save_button, True)
        self.save_button.setText(self.tr("导出字幕" if manual_mode else "保存"))
        for widget in (
            self.layout_button,
            self.target_language_button,
        ):
            self.command_bar.setWidgetAvailable(widget, not manual_mode)
        self.start_button.setVisible(not manual_mode)
        self.translate_button.setVisible(not manual_mode)
        menu_actions = self.more_menu.menuActions()
        if manual_mode:
            for action in (self.optimize_button, self.prompt_button):
                if action in menu_actions:
                    self.more_menu.removeAction(action)
        else:
            for action in (self.optimize_button, self.prompt_button):
                action.setVisible(True)
            menu_actions = self.more_menu.menuActions()
            if self.optimize_button not in menu_actions:
                self.more_menu.insertAction(
                    self.subtitle_settings_action,
                    self.optimize_button,
                )
            menu_actions = self.more_menu.menuActions()
            if self.prompt_button not in menu_actions:
                self.more_menu.insertAction(
                    self.subtitle_settings_action,
                    self.prompt_button,
                )
        self.subtitle_settings_action.setVisible(True)
        self.more_button.setText(self.tr("文件" if manual_mode else "更多"))
        self.open_folder_action.setText(
            self.tr("打开终稿文件夹" if manual_mode else "打开输出文件夹")
        )

    def _setup_subtitle_table(self):
        self.subtitle_table = TableView(self)
        self.model = SubtitleTableModel("")
        self.subtitle_table.setModel(self.model)
        self.subtitle_table.setBorderVisible(True)
        self.subtitle_table.setBorderRadius(8)
        self.subtitle_table.setWordWrap(True)
        self.model.modelReset.connect(self._apply_subtitle_table_column_layout)
        self._apply_subtitle_table_column_layout()

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
        self.subtitle_table.selectionModel().currentRowChanged.connect(
            self._on_subtitle_current_row_changed
        )
        # 添加右键菜单支持
        self.subtitle_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.subtitle_table.customContextMenuRequested.connect(self.show_context_menu)

        self.review_color_legend = CaptionLabel(
            self.tr(
                "浅蓝：英文切分复查  淡黄：中文对应复查  "
                "紫色：时间轴复查  绿色：视觉分页复查  淡红：结构阻断"
            ),
            self,
        )
        self.review_color_legend.setWordWrap(True)
        self.main_layout.addWidget(self.review_color_legend)
        self.main_layout.addWidget(self.subtitle_table, 1)

    def _apply_subtitle_table_column_layout(self) -> None:
        header = self.subtitle_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        for column in (0, 1):
            if column < self.model.columnCount():
                header.setSectionResizeMode(column, QHeaderView.Fixed)
                self.subtitle_table.setColumnWidth(
                    column, SUBTITLE_TIME_COLUMN_WIDTH
                )

    @staticmethod
    def _manual_boundary_left_index(cue_count: int, selected_row: int) -> int | None:
        if cue_count < 2:
            return None
        return min(max(int(selected_row), 0), cue_count - 2)

    @staticmethod
    def _manual_boundary_text_html(
        text: str,
        *,
        highlight_head: int = 0,
        highlight_tail: int = 0,
        dark_theme: bool = False,
    ) -> str:
        tokens = str(text or "").split()
        if not tokens:
            return ""
        head = min(max(int(highlight_head), 0), len(tokens))
        tail = min(max(int(highlight_tail), 0), len(tokens) - head)
        highlight_style = (
            "background-color:#5a4a20;color:#fff0ad;font-weight:600;"
            if dark_theme
            else "background-color:#fff0a8;color:#3d3200;font-weight:600;"
        )
        parts = []
        if head:
            parts.append(
                f'<span style="{highlight_style}">{html.escape(" ".join(tokens[:head]))}</span>'
            )
        middle_end = len(tokens) - tail if tail else len(tokens)
        if middle_end > head:
            parts.append(html.escape(" ".join(tokens[head:middle_end])))
        if tail:
            parts.append(
                f'<span style="{highlight_style}">{html.escape(" ".join(tokens[middle_end:]))}</span>'
            )
        return " ".join(part for part in parts if part)

    def _on_subtitle_current_row_changed(self, current, _previous) -> None:
        self._manual_boundary_edit_active = False
        self._manual_boundary_move_direction = ""
        self._refresh_manual_boundary_inspector(current.row())

    def _toggle_manual_boundary_edit(self) -> None:
        if getattr(self, "_manual_boundary_edit_active", False):
            self._cancel_manual_boundary_edit()
            return
        current = self.subtitle_table.currentIndex()
        selected_row = current.row() if current.isValid() else 0
        context = self._manual_boundary_context(selected_row)
        if context is None:
            InfoBar.warning(
                self.tr("没有可调整的相邻边界"),
                self.tr("请选择一条后面仍有字幕或分页的行。"),
                duration=3500,
                parent=self,
            )
            return
        self._start_manual_boundary_edit(int(context["left_row"]))

    def _start_manual_boundary_edit(self, left_row: int) -> None:
        context = self._manual_boundary_context(int(left_row))
        if context is None:
            return
        self._manual_boundary_edit_active = True
        self._manual_boundary_move_direction = ""
        self._manual_boundary_word_count_value = 1
        self._refresh_manual_boundary_inspector(int(context["left_row"]))

    def _cancel_manual_boundary_edit(self) -> None:
        self._manual_boundary_edit_active = False
        self._manual_boundary_move_direction = ""
        self._refresh_manual_boundary_inspector()

    def _choose_manual_boundary_direction(self, direction: str) -> None:
        if direction not in {"next", "previous"}:
            return
        self._manual_boundary_move_direction = direction
        self._manual_boundary_word_count_value = 1
        count_box = getattr(self, "manual_boundary_word_count", None)
        if count_box is not None:
            blocked = count_box.blockSignals(True)
            count_box.setValue(1)
            count_box.blockSignals(blocked)
        if not self._update_manual_boundary_preview():
            self._refresh_manual_boundary_inspector(
                self._manual_boundary_table_left_row
            )

    def _confirm_manual_boundary_move(self) -> None:
        direction = str(getattr(self, "_manual_boundary_move_direction", ""))
        if direction == "next":
            self._move_boundary_words_to_next()
        elif direction == "previous":
            self._move_boundary_words_to_previous()

    def _clear_manual_boundary_index_widgets(self) -> None:
        table = getattr(self, "subtitle_table", None)
        model = getattr(self, "model", None)
        if table is not None and model is not None:
            for entry in list(getattr(self, "_manual_boundary_index_widgets", [])):
                row, column = entry[:2]
                widget = entry[2] if len(entry) > 2 else None
                if widget is not None:
                    widget.hide()
                if 0 <= row < model.rowCount():
                    index = model.index(row, column)
                    current_widget = table.indexWidget(index)
                    if current_widget is not None:
                        current_widget.hide()
                    table.setIndexWidget(index, None)
                if widget is not None:
                    widget.deleteLater()
            header = table.verticalHeader()
            for row, size in dict(
                getattr(self, "_manual_boundary_resized_rows", {})
            ).items():
                if 0 <= row < model.rowCount():
                    header.resizeSection(row, int(size))
        self._manual_boundary_index_widgets = []
        self._manual_boundary_resized_rows = {}
        self.manual_boundary_left_text_label = None
        self.manual_boundary_right_text_label = None
        self.manual_boundary_word_count = None
        self.manual_boundary_confirm_button = None

    def _manual_boundary_context(self, selected_row: int | None) -> dict | None:
        session = self.manual_final_session
        if session is None or len(session.cues) < 2 or self.model.rowCount() < 2:
            return None
        if selected_row is None:
            current = self.subtitle_table.currentIndex()
            selected_row = (
                current.row()
                if current.isValid()
                else self._manual_boundary_table_left_row
            )
        selected_row = int(selected_row)
        if selected_row < 0 or selected_row + 1 >= self.model.rowCount():
            return None
        left_row = selected_row
        left = dict(self.model._data.get(str(left_row + 1)) or {})
        right = dict(self.model._data.get(str(left_row + 2)) or {})
        if not left or not right:
            return None

        page_mode = bool(left.get("display_page_view"))
        if page_mode and (
            left.get("display_page_unavailable")
            or right.get("display_page_unavailable")
        ):
            return None
        same_parent_pages = bool(
            page_mode
            and left.get("display_page_id")
            and right.get("display_page_id")
            and str(left.get("manual_cue_id") or "")
            == str(right.get("manual_cue_id") or "")
        )
        kind = "display" if same_parent_pages else "parent"
        if kind == "parent" and page_mode:
            parent_left_index = int(left.get("parent_cue_index", -1))
            parent_right_index = int(right.get("parent_cue_index", -1))
            if (
                parent_left_index < 0
                or parent_right_index != parent_left_index + 1
            ):
                return None
        else:
            parent_left_index = (
                int(left.get("parent_cue_index", -1))
                if page_mode
                else self._manual_boundary_left_index(len(session.cues), left_row)
            )
            if parent_left_index is None or parent_left_index < 0:
                return None

        left_word_count = int(left["word_end"]) - int(left["word_start"]) + 1
        right_word_count = int(right["word_end"]) - int(right["word_start"]) + 1
        return {
            "kind": kind,
            "left_row": left_row,
            "right_row": left_row + 1,
            "left": left,
            "right": right,
            "parent_left_index": parent_left_index,
            "left_page_id": str(left.get("display_page_id") or ""),
            "move_to_next_max": max(left_word_count - 1, 0),
            "move_to_previous_max": max(right_word_count - 1, 0),
        }

    def _manual_boundary_row_widget(
        self,
        context: dict,
        *,
        side: str,
        word_count: int,
    ) -> QWidget:
        row = context["left"] if side == "left" else context["right"]
        widget = QFrame(self.subtitle_table.viewport())
        widget.setObjectName("manualBoundaryRowControl")
        if isDarkTheme():
            background = "#292929"
            border = "#675b31"
        else:
            background = "#fffdf5"
            border = "#d8bd57"
        widget.setStyleSheet(
            "#manualBoundaryRowControl {"
            f"background:{background}; border:1px solid {border}; border-radius:4px;"
            "}"
        )
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(3)

        text_label = BodyLabel("", widget)
        text_label.setTextFormat(Qt.RichText)
        text_label.setWordWrap(True)
        direction = str(getattr(self, "_manual_boundary_move_direction", ""))
        direction_capacity_ok = (
            word_count <= context["move_to_next_max"]
            if side == "left"
            else word_count <= context["move_to_previous_max"]
        )
        source_selected = (
            direction == "next" if side == "left" else direction == "previous"
        )
        text_label.setText(
            self._manual_boundary_text_html(
                str(row.get("original_subtitle") or ""),
                highlight_tail=(
                    word_count
                    if side == "left" and source_selected and direction_capacity_ok
                    else 0
                ),
                highlight_head=(
                    word_count
                    if side == "right" and source_selected and direction_capacity_ok
                    else 0
                ),
                dark_theme=isDarkTheme(),
            )
        )
        if side == "left":
            self.manual_boundary_left_text_label = text_label
        else:
            self.manual_boundary_right_text_label = text_label
        layout.addWidget(text_label, 1)

        is_page_boundary = context["kind"] == "display"
        if side == "left":
            action_layout = QGridLayout()
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setHorizontalSpacing(8)
            action_layout.setVerticalSpacing(4)
            boundary_label = CaptionLabel(
                self.tr("视觉分页" if is_page_boundary else "正式边界"),
                widget,
            )
            boundary_label.setToolTip(
                self.tr(
                    "只调整这条父字幕内部的实际分页"
                    if is_page_boundary
                    else "调整两条父字幕的正式英文边界，保存时会重新规划分页"
                )
            )
            action_layout.addWidget(boundary_label, 0, 0)
            count_box = SpinBox(widget)
            count_box.setRange(
                1,
                max(
                    context["move_to_next_max"],
                    context["move_to_previous_max"],
                    1,
                ),
            )
            count_box.setValue(word_count)
            count_box.setSuffix(self.tr(" 词"))
            count_box.setFixedWidth(max(110, count_box.minimumSizeHint().width()))
            count_box.valueChanged.connect(
                self._on_manual_boundary_word_count_changed
            )
            self.manual_boundary_word_count = count_box
            action_layout.addWidget(count_box, 0, 1, Qt.AlignRight)
            move_button = PushButton(
                self.tr(
                    "移到下一屏"
                    if is_page_boundary
                    else "移到下一条"
                ),
                widget,
                icon=FIF.DOWN,
            )
            move_button.setEnabled(
                word_count <= context["move_to_next_max"]
            )
            move_button.setToolTip(
                self.tr("选择移动方向；此时不会修改字幕")
            )
            move_button.clicked.connect(
                lambda: self._choose_manual_boundary_direction("next")
            )
            self.manual_boundary_move_right_button = move_button
            action_layout.addWidget(move_button, 1, 0)
            confirm_button = PrimaryPushButton(
                self.tr(f"确认移动 {word_count} 个词"), widget, icon=FIF.ACCEPT
            )
            confirm_button.setEnabled(bool(direction) and direction_capacity_ok)
            confirm_button.clicked.connect(self._confirm_manual_boundary_move)
            self.manual_boundary_confirm_button = confirm_button
            action_layout.addWidget(confirm_button, 1, 1)
            cancel_button = PushButton(self.tr("取消"), widget, icon=FIF.CANCEL)
            cancel_button.clicked.connect(self._cancel_manual_boundary_edit)
            action_layout.addWidget(cancel_button, 2, 0)
            parent_id = str(row.get("manual_cue_id") or "")
            can_undo_for_parent = getattr(
                self.manual_final_session,
                "can_undo_for_parent",
                None,
            )
            undo_button = PushButton(self.tr("撤销"), widget, icon=FIF.SYNC)
            undo_button.setEnabled(
                bool(can_undo_for_parent(parent_id))
                if callable(can_undo_for_parent)
                else bool(self.manual_final_session.history)
            )
            undo_button.clicked.connect(
                lambda _checked=False, pid=parent_id: self.undo_manual_final_edit(
                    pid
                )
            )
            self.manual_boundary_undo_button = undo_button
            action_layout.addWidget(undo_button, 2, 1)
            action_layout.setColumnStretch(0, 1)
            action_layout.setColumnStretch(1, 1)
        else:
            action_layout = QHBoxLayout()
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(6)
            page_id = str(row.get("display_page_id") or "")
            target_text = (
                self.tr(f"目标屏 {page_id}")
                if is_page_boundary
                else self.tr("目标字幕（中文需同步检查）")
            )
            action_layout.addWidget(CaptionLabel(target_text, widget), 1)
            move_button = PushButton(
                self.tr(
                    "移到上一屏"
                    if is_page_boundary
                    else "移到上一条"
                ),
                widget,
                icon=FIF.UP,
            )
            move_button.setEnabled(
                word_count <= context["move_to_previous_max"]
            )
            move_button.setToolTip(
                self.tr("选择移动方向；此时不会修改字幕")
            )
            move_button.clicked.connect(
                lambda: self._choose_manual_boundary_direction("previous")
            )
            self.manual_boundary_move_left_button = move_button
            action_layout.addWidget(move_button)
        layout.addLayout(action_layout)
        text_width = max(self.subtitle_table.columnWidth(2) - 18, 160)
        text_height = text_label.fontMetrics().boundingRect(
            0,
            0,
            text_width,
            10000,
            int(Qt.TextWordWrap),
            str(row.get("original_subtitle") or ""),
        ).height()
        action_height = action_layout.sizeHint().height()
        widget.setProperty(
            "manualBoundaryRequiredHeight",
            max(86, int(text_height) + int(action_height) + 15),
        )
        return widget

    def _manual_boundary_entry_widget(self, context: dict) -> QWidget:
        row = context["left"]
        widget = QFrame(self.subtitle_table.viewport())
        widget.setObjectName("manualBoundaryEntryControl")
        if isDarkTheme():
            background = "#292929"
            border = "#675b31"
        else:
            background = "#fffdf5"
            border = "#d8bd57"
        widget.setStyleSheet(
            "#manualBoundaryEntryControl {"
            f"background:{background}; border:1px solid {border}; border-radius:4px;"
            "}"
        )
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(8)
        text_label = BodyLabel(str(row.get("original_subtitle") or ""), widget)
        text_label.setWordWrap(True)
        layout.addWidget(text_label, 1)
        is_page_boundary = context["kind"] == "display"
        left_row = int(context["left_row"])
        if left_row > 0:
            upper_context = self._manual_boundary_context(left_row - 1)
            if upper_context is not None:
                upper_is_page = upper_context["kind"] == "display"
                upper_button = PushButton(
                    self.tr(
                        "调整上方分页边界"
                        if upper_is_page
                        else "调整上方字幕边界"
                    ),
                    widget,
                    icon=FIF.UP,
                )
                upper_button.clicked.connect(
                    lambda _checked=False, row=left_row - 1: (
                        self._start_manual_boundary_edit(row)
                    )
                )
                layout.addWidget(upper_button)
        button = PushButton(
            self.tr(
                "调整与下一屏边界"
                if is_page_boundary
                else "调整与下一条边界"
            ),
            widget,
            icon=FIF.EDIT,
        )
        button.clicked.connect(self._toggle_manual_boundary_edit)
        layout.addWidget(button)
        text_width = max(self.subtitle_table.columnWidth(2) - 220, 160)
        text_height = text_label.fontMetrics().boundingRect(
            0,
            0,
            text_width,
            10000,
            int(Qt.TextWordWrap),
            str(row.get("original_subtitle") or ""),
        ).height()
        widget.setProperty(
            "manualBoundaryRequiredHeight",
            max(54, int(text_height) + 12),
        )
        return widget

    def _install_manual_boundary_entry_widget(self, context: dict) -> None:
        row = int(context["left_row"])
        header = self.subtitle_table.verticalHeader()
        self._manual_boundary_resized_rows[row] = header.sectionSize(row)
        widget = self._manual_boundary_entry_widget(context)
        required_height = int(widget.property("manualBoundaryRequiredHeight") or 54)
        row_height = max(header.sectionSize(row), required_height)
        header.resizeSection(row, row_height)
        widget.setFixedHeight(row_height)
        self.subtitle_table.doItemsLayout()
        index = self.model.index(row, 2)
        self.subtitle_table.setIndexWidget(index, widget)
        widget.setGeometry(self.subtitle_table.visualRect(index))
        self._manual_boundary_index_widgets.append((row, 2, widget))

    def _on_manual_boundary_word_count_changed(self, value: int) -> None:
        self._manual_boundary_word_count_value = max(int(value), 1)
        self._update_manual_boundary_preview()

    def _update_manual_boundary_preview(self) -> bool:
        if not getattr(self, "_manual_boundary_edit_active", False):
            return False
        context = self._manual_boundary_context(
            self._manual_boundary_table_left_row
        )
        if context is None:
            return False

        maximum = max(
            context["move_to_next_max"],
            context["move_to_previous_max"],
            1,
        )
        count = min(
            max(int(self._manual_boundary_word_count_value), 1),
            maximum,
        )
        direction = str(getattr(self, "_manual_boundary_move_direction", ""))
        expander = getattr(
            self.manual_final_session,
            "expanded_manual_boundary_word_count",
            None,
        )
        if direction in {"next", "previous"} and callable(expander):
            count = int(
                expander(
                    left_word_start=int(context["left"]["word_start"]),
                    left_word_end=int(context["left"]["word_end"]),
                    right_word_start=int(context["right"]["word_start"]),
                    right_word_end=int(context["right"]["word_end"]),
                    requested_word_count=count,
                    move_to_next=direction == "next",
                )
            )
        self._manual_boundary_word_count_value = count
        count_box = getattr(self, "manual_boundary_word_count", None)
        if count_box is not None and count_box.value() != count:
            blocked = count_box.blockSignals(True)
            count_box.setValue(count)
            count_box.blockSignals(blocked)

        next_allowed = count <= context["move_to_next_max"]
        previous_allowed = count <= context["move_to_previous_max"]
        left_label = getattr(self, "manual_boundary_left_text_label", None)
        if left_label is not None:
            left_label.setText(
                self._manual_boundary_text_html(
                    str(context["left"].get("original_subtitle") or ""),
                    highlight_tail=(
                        count if direction == "next" and next_allowed else 0
                    ),
                    dark_theme=isDarkTheme(),
                )
            )
        right_label = getattr(self, "manual_boundary_right_text_label", None)
        if right_label is not None:
            right_label.setText(
                self._manual_boundary_text_html(
                    str(context["right"].get("original_subtitle") or ""),
                    highlight_head=(
                        count
                        if direction == "previous" and previous_allowed
                        else 0
                    ),
                    dark_theme=isDarkTheme(),
                )
            )

        next_button = getattr(self, "manual_boundary_move_right_button", None)
        if next_button is not None:
            next_button.setEnabled(next_allowed)
        previous_button = getattr(self, "manual_boundary_move_left_button", None)
        if previous_button is not None:
            previous_button.setEnabled(previous_allowed)
        confirm_button = getattr(self, "manual_boundary_confirm_button", None)
        if confirm_button is not None:
            confirm_button.setText(self.tr(f"确认移动 {count} 个词"))
            confirm_button.setEnabled(
                (direction == "next" and next_allowed)
                or (direction == "previous" and previous_allowed)
            )
        return True

    def _refresh_manual_boundary_inspector(self, selected_row: int | None = None) -> None:
        if getattr(self, "_manual_boundary_refreshing", False):
            return
        self._manual_boundary_refreshing = True
        try:
            self._clear_manual_boundary_index_widgets()
            context = self._manual_boundary_context(selected_row)
            if context is None or self._manual_save_in_progress:
                self._manual_boundary_edit_active = False
                self._manual_boundary_move_direction = ""
                return
            maximum = max(
                context["move_to_next_max"],
                context["move_to_previous_max"],
                1,
            )
            count = min(
                max(int(self._manual_boundary_word_count_value), 1),
                maximum,
            )
            self._manual_boundary_word_count_value = count
            self._manual_boundary_kind = str(context["kind"])
            self._manual_boundary_left_page_id = str(context["left_page_id"])
            self._manual_boundary_table_left_row = int(context["left_row"])
            self._manual_boundary_parent_left_index = int(
                context["parent_left_index"]
            )
            self._manual_boundary_left_index_value = int(
                context["parent_left_index"]
            )
            if not self._manual_boundary_edit_active:
                self._install_manual_boundary_entry_widget(context)
                return
            header = self.subtitle_table.verticalHeader()
            row_widgets = []
            for side, row in (
                ("left", int(context["left_row"])),
                ("right", int(context["right_row"])),
            ):
                self._manual_boundary_resized_rows[row] = header.sectionSize(row)
                widget = self._manual_boundary_row_widget(
                    context,
                    side=side,
                    word_count=count,
                )
                required_height = int(
                    widget.property("manualBoundaryRequiredHeight") or 86
                )
                row_height = max(header.sectionSize(row), required_height)
                header.resizeSection(
                    row,
                    row_height,
                )
                widget.setFixedHeight(row_height)
                row_widgets.append((row, widget))
            self.subtitle_table.doItemsLayout()
            for row, widget in row_widgets:
                index = self.model.index(row, 2)
                self.subtitle_table.setIndexWidget(index, widget)
                widget.setGeometry(self.subtitle_table.visualRect(index))
                self._manual_boundary_index_widgets.append((row, 2, widget))
        finally:
            self._manual_boundary_refreshing = False

    def _select_manual_boundary_row(self, left_index: int) -> None:
        if (
            not self.model.rowCount()
            or not hasattr(self.subtitle_table, "setCurrentIndex")
            or not hasattr(self.subtitle_table, "selectRow")
        ):
            return
        row = min(max(int(left_index), 0), self.model.rowCount() - 1)
        target = self.model.index(row, 2)
        self.subtitle_table.setCurrentIndex(target)
        self.subtitle_table.selectRow(row)
        self.subtitle_table.scrollTo(target, QAbstractItemView.PositionAtCenter)

    def _manual_row_for_identity(
        self,
        *,
        parent_id: str,
        page_id: str = "",
        focus_word_id: int | None = None,
        following_parent_id: str = "",
    ) -> int | None:
        model = getattr(self, "model", None)
        rows = list(getattr(model, "_data", {}).values())
        if page_id:
            for index, row in enumerate(rows):
                if str(row.get("display_page_id") or "") == str(page_id):
                    return index
        if following_parent_id:
            for index in range(max(0, len(rows) - 1)):
                if (
                    str(rows[index].get("manual_cue_id") or "") == parent_id
                    and str(rows[index + 1].get("manual_cue_id") or "")
                    == following_parent_id
                ):
                    return index
        candidates = [
            (index, row)
            for index, row in enumerate(rows)
            if str(row.get("manual_cue_id") or "") == parent_id
        ]
        if focus_word_id is not None:
            for index, row in candidates:
                if int(row.get("word_start", -1)) <= int(
                    focus_word_id
                ) <= int(row.get("word_end", -2)):
                    return index
        return candidates[0][0] if candidates else None

    def _manual_state_fingerprint(self) -> str:
        session = self.manual_final_session
        if session is None:
            return ""
        fingerprint = getattr(session, "state_fingerprint", None)
        return str(fingerprint()) if callable(fingerprint) else ""

    def _set_manual_clean_checkpoint(self) -> None:
        self._manual_clean_state_fingerprint = self._manual_state_fingerprint()
        self._manual_model_has_pending_edits = False
        self._manual_has_unsaved_changes = False

    def _reconcile_manual_dirty_state(self) -> bool:
        current = self._manual_state_fingerprint()
        self._manual_has_unsaved_changes = bool(
            self._manual_model_has_pending_edits
            or not self._manual_clean_state_fingerprint
            or current != self._manual_clean_state_fingerprint
        )
        return self._manual_has_unsaved_changes

    def _mark_manual_final_dirty(self, *, invalidate_pages: bool = False) -> None:
        invalidate = getattr(self, "_invalidate_manual_final_save", None)
        if callable(invalidate):
            invalidate()
        else:
            SubtitleInterface._invalidate_manual_final_save(self)
        self._manual_package_manifest_path = ""
        self._manual_has_unsaved_changes = True
        if invalidate_pages:
            self._manual_parent_boundaries_dirty = True
            self._manual_page_view = False
        self.manual_final_synthesis_action.setEnabled(False)
        self.manual_final_synthesis_action.setVisible(True)
        SubtitleInterface._set_optional_action_tooltip(
            self.manual_final_synthesis_action,
            self.tr("当前编辑尚未保存"),
        )
        self.manual_draft_synthesis_action.setEnabled(False)
        self.manual_draft_synthesis_action.setVisible(True)
        SubtitleInterface._set_optional_action_tooltip(
            self.manual_draft_synthesis_action,
            self.tr("当前编辑尚未保存"),
        )

    def _apply_manual_boundary_move(
        self,
        left_index: int,
        word_count: int,
        *,
        move_to_next: bool,
        announce: bool = True,
    ) -> bool:
        if not self.manual_final_session:
            return False
        left_parent_id = str(
            self.manual_final_session.cues[left_index].get("cue_id") or ""
        )
        right_parent_id = str(
            self.manual_final_session.cues[left_index + 1].get("cue_id") or ""
        )
        affected_parent_ids = {
            str(value)
            for cue in self.manual_final_session.cues[
                left_index : left_index + 2
            ]
            for value in [
                cue.get("cue_id"),
                *(cue.get("source_subtitle_ids") or []),
            ]
            if str(value)
        }
        try:
            self._sync_manual_final_text_edits()
            if move_to_next:
                self.manual_final_session.move_suffix_to_next(left_index, word_count)
            else:
                self.manual_final_session.move_prefix_to_previous(
                    left_index + 1, word_count
                )
            self._manual_boundary_edit_active = False
            self._manual_boundary_move_direction = ""
            self._invalidate_manual_review_marks_for_parent_ids(
                affected_parent_ids
            )
            pages_preserved = bool(
                self.manual_final_session.has_display_page_model()
            )
            self._manual_parent_boundaries_dirty = not pages_preserved
            self._manual_page_view = pages_preserved
            self._mark_manual_final_dirty(invalidate_pages=not pages_preserved)
            self._apply_manual_final_session()
            identity_row = SubtitleInterface._manual_row_for_identity(
                self,
                parent_id=left_parent_id,
                following_parent_id=right_parent_id if pages_preserved else "",
            )
            selected_row = (
                identity_row if identity_row is not None else left_index
            )
            selector = getattr(self, "_select_manual_boundary_row", None)
            if callable(selector):
                selector(selected_row)
            else:
                SubtitleInterface._select_manual_boundary_row(self, selected_row)
            self.status_label.setText(
                self.tr(
                    "父字幕边界已更新；相邻分页中文已保留为待确认草稿"
                    if pages_preserved
                    else "父字幕边界已更新；保存终稿后重新计算实际分页"
                )
            )
            if announce:
                InfoBar.success(
                    self.tr("边界已更新"),
                    self.tr(
                        "两条英文和时间轴已同步；请检查相邻分页中文后保存。"
                        if pages_preserved
                        else "两条英文和时间轴已同步；请检查中文，保存后刷新实际分页。"
                    ),
                    duration=3500,
                    parent=self,
                )
            return True
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(
                self.tr("无法移动边界"), str(exc), duration=5000, parent=self
            )
            return False

    def _move_boundary_words_to_next(self) -> None:
        if self._manual_boundary_kind == "display":
            self._apply_manual_display_page_boundary_move(move_to_next=True)
            return
        self._apply_manual_boundary_move(
            self._manual_boundary_parent_left_index,
            self._manual_boundary_word_count_value,
            move_to_next=True,
            announce=False,
        )

    def _move_boundary_words_to_previous(self) -> None:
        if self._manual_boundary_kind == "display":
            self._apply_manual_display_page_boundary_move(move_to_next=False)
            return
        self._apply_manual_boundary_move(
            self._manual_boundary_parent_left_index,
            self._manual_boundary_word_count_value,
            move_to_next=False,
            announce=False,
        )

    def _apply_manual_display_page_boundary_move(
        self,
        *,
        move_to_next: bool,
    ) -> None:
        if not self.manual_final_session or not self._manual_boundary_left_page_id:
            return
        try:
            self._sync_manual_final_text_edits()
            result = self.manual_final_session.move_display_page_boundary(
                self._manual_boundary_left_page_id,
                self._manual_boundary_word_count_value,
                move_to_next=move_to_next,
            )
            self._manual_boundary_edit_active = False
            self._manual_boundary_move_direction = ""
            parent_id = str(result.get("parent_subtitle_id") or "")
            cue = next(
                (
                    item
                    for item in self.manual_final_session.cues
                    if str(item.get("cue_id") or "") == parent_id
                ),
                {},
            )
            self._invalidate_manual_review_marks_for_parent_ids(
                [parent_id, *(cue.get("source_subtitle_ids") or [])]
            )
            self._mark_manual_final_dirty(invalidate_pages=False)
            left_row = self._manual_boundary_table_left_row
            self._apply_manual_final_session()
            identity_row = SubtitleInterface._manual_row_for_identity(
                self,
                parent_id=parent_id,
                page_id=str(result.get("left_page_id") or ""),
            )
            self._select_manual_boundary_row(
                identity_row if identity_row is not None else left_row
            )
            warnings = list(result.get("warnings") or [])
            if warnings:
                issue_codes = sorted(
                    {
                        str(code)
                        for warning in warnings
                        for code in warning.get("issue_codes") or []
                        if str(code)
                    }
                )
                warning_text = ", ".join(issue_codes) or self.tr("语法或短页风险")
                self.status_label.setText(
                    self.tr("分页边界已按人工确认更新；逐页中文待补充")
                )
                InfoBar.warning(
                    self.tr("已接受人工分页复核项"),
                    self.tr("边界已保存为复核项：") + warning_text,
                    duration=6000,
                    parent=self,
                )
            else:
                self.status_label.setText(
                    self.tr("实际分页边界已更新；请检查这两屏中文后保存人工终稿")
                )
                InfoBar.success(
                    self.tr("分页边界已更新"),
                    self.tr("父字幕、固定 ID 和词时间未改变；保存时复用其他分页，只重建当前父字幕。"),
                    duration=4000,
                    parent=self,
                )
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(
                self.tr("无法移动分页边界"),
                str(exc),
                duration=6000,
                parent=self,
            )

    def _setup_bottom_layout(self):
        self.bottom_layout = QHBoxLayout()
        self.progress_bar = ProgressBar(self)
        self.manual_save_progress_bar = IndeterminateProgressBar(
            self,
            start=False,
        )
        self.manual_save_progress_bar.hide()
        self.status_label = BodyLabel(self.tr("请拖入字幕文件"), self)
        self.status_label.setMinimumWidth(100)
        self.status_label.setAlignment(Qt.AlignCenter)

        # 添加取消按钮
        self.cancel_button = PushButton(self.tr("取消"), self, icon=FIF.CANCEL)
        self.cancel_button.hide()  # 初始隐藏
        self.cancel_button.clicked.connect(self.cancel_optimization)

        self.bottom_layout.addWidget(self.progress_bar, 1)
        self.bottom_layout.addWidget(self.manual_save_progress_bar, 1)
        self.bottom_layout.addWidget(self.status_label)
        self.bottom_layout.addWidget(self.cancel_button)
        self.main_layout.addLayout(self.bottom_layout)

    def _setup_signals(self):
        self.review_marks_loaded.connect(self._apply_loaded_manual_review_marks)
        self.manual_final_save_progress.connect(
            self._apply_manual_final_save_progress
        )
        self.manual_final_save_finished.connect(self._apply_manual_final_save_result)
        self.model.dataChanged.connect(self._on_manual_table_data_changed)
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
        self._active_subtitle_attempt_id = self.subtitle_optimization_thread.attempt_id
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
        if self.task.need_next_task and not bool(
            getattr(
                self.task,
                "require_manual_review_before_synthesis",
                False,
            )
        ):
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
        checkpoint_loaded = self._load_manual_failure_checkpoint_from_output(
            str(getattr(self.task, "output_path", "") or "")
        )
        if checkpoint_loaded:
            InfoBar.warning(
                self.tr("自动分页未通过"),
                self.tr("完整字幕已加载到编辑器；问题字幕已标记，合成仍保持阻止。"),
                duration=10000,
                parent=self,
            )
            return
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
                f"疑似翻译腔 {translationese_count} 处；请按表格标色逐项复查"
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
            self.load_subtitle_file(file_path)

    def _confirm_discard_manual_edits(self, action_text: str) -> bool:
        commit_editor = getattr(self, "_commit_active_manual_table_editor", None)
        if callable(commit_editor):
            commit_editor()
        if not bool(getattr(self, "_manual_has_unsaved_changes", False)):
            return True
        dialog = MessageBox(
            self.tr("有未保存的人工修改"),
            self.tr(f"{action_text}会丢失尚未保存的字幕、分页或边界修改。"),
            self,
        )
        dialog.yesButton.setText(self.tr("放弃修改"))
        dialog.cancelButton.setText(self.tr("继续编辑"))
        return bool(dialog.exec())

    def can_close_with_manual_edits(self) -> bool:
        return self._confirm_discard_manual_edits(self.tr("关闭程序"))

    def on_save_format_clicked(self, format: str):
        """处理保存格式的选择"""
        if not self.subtitle_path:
            InfoBar.warning(
                self.tr("警告"), self.tr("请先加载字幕文件"), duration=3000, parent=self
            )
            return

        commit_editor = getattr(self, "_commit_active_manual_table_editor", None)
        if callable(commit_editor):
            commit_editor()

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
        target_dir = None
        manifest_path = Path(
            str(getattr(self, "_manual_package_manifest_path", "") or "")
        )
        if manifest_path.is_file():
            target_dir = manifest_path.parent
        elif self.manual_final_session is not None:
            session_subtitle = Path(self.manual_final_session.subtitle_path)
            if session_subtitle.is_file():
                target_dir = session_subtitle.parent
        if target_dir is None and self.task is not None:
            output_path = Path(self.task.output_path)
            target_dir = (
                output_path.parent
                if output_path.exists()
                else Path(self.task.subtitle_path).parent
            )
        if target_dir is None and self.subtitle_path:
            subtitle_path = Path(self.subtitle_path)
            if subtitle_path.is_file():
                target_dir = subtitle_path.parent
        if target_dir is None:
            InfoBar.warning(
                self.tr("警告"), self.tr("请先加载字幕文件"), duration=3000, parent=self
            )
            return
        target_dir = str(target_dir)
        if sys.platform == "win32":
            os.startfile(target_dir)
        elif sys.platform == "darwin":  # macOS
            subprocess.run(["open", target_dir])
        else:  # Linux
            subprocess.run(["xdg-open", target_dir])

    def load_subtitle_file(self, file_path) -> bool:
        """Load a subtitle file without leaving the table in an indeterminate state."""
        if bool(getattr(self, "_manual_save_in_progress", False)):
            InfoBar.warning(
                self.tr("正在保存人工终稿"),
                self.tr("保存完成前不能切换字幕文件。"),
                duration=3000,
                parent=self,
            )
            return False
        confirm_discard = getattr(self, "_confirm_discard_manual_edits", None)
        if callable(confirm_discard) and not confirm_discard(self.tr("导入其他字幕")):
            return False
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
        if self._manual_save_in_progress:
            return
        set_manual_mode = getattr(self, "_set_manual_editor_mode", None)
        if callable(set_manual_mode):
            set_manual_mode(False)
        self._invalidate_manual_final_save()
        self.manual_final_session = None
        self._manual_package_manifest_path = ""
        self._manual_review_mark_count = 0
        self._review_mark_rows = []
        self._manual_review_invalidated_ids = set()
        self._review_mark_request_id += 1
        self._manual_parent_boundaries_dirty = False
        self._manual_pending_page_split = None
        self.model.set_review_marks({})
        self.next_review_action.setEnabled(False)
        self.next_review_action.setVisible(False)
        self._manual_page_view = True
        if hasattr(self, "manual_page_view_action"):
            self.manual_page_view_action.setEnabled(False)
            self.manual_page_view_action.setVisible(False)
        self.manual_final_save_action.setEnabled(False)
        self.manual_final_save_action.setVisible(False)
        self.manual_final_undo_action.setEnabled(False)
        self.manual_final_undo_action.setVisible(False)
        self.manual_final_synthesis_action.setEnabled(False)
        self.manual_final_synthesis_action.setVisible(False)
        self.manual_draft_synthesis_action.setEnabled(False)
        self.manual_draft_synthesis_action.setVisible(False)
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
        self._set_manual_clean_checkpoint()
        import_notice = str(getattr(session, "import_notice", "") or "").strip()
        if import_notice and not session.has_display_page_model():
            self._manual_parent_boundaries_dirty = True
            self._manual_page_view = False
        self._load_manual_final_review_marks(session)
        self._apply_manual_final_session()
        self._restore_saved_manual_package_actions()
        if import_notice:
            self.status_label.setText(
                self.tr(
                    f"{import_notice}；当前显示 {self.model.rowCount()} 屏"
                )
            )
        else:
            self.status_label.setText(
                self.tr(
                    f"已加载 {self.model.rowCount()} 屏稳定终稿；正在检查高优先复查点"
                )
            )

    def _load_manual_final_session_from_output(self, output_path: str) -> None:
        if self._manual_save_in_progress:
            return
        manifest_path = Path(output_path).parent / "stable-final-manifest.json"
        if not manifest_path.exists():
            return
        set_manual_mode = getattr(self, "_set_manual_editor_mode", None)
        if callable(set_manual_mode):
            set_manual_mode(False)
        self._invalidate_manual_final_save()
        self.manual_final_session = None
        self._manual_package_manifest_path = ""
        self._manual_review_mark_count = 0
        self._review_mark_rows = []
        self._manual_review_invalidated_ids = set()
        self._review_mark_request_id += 1
        self._manual_parent_boundaries_dirty = False
        self._manual_pending_page_split = None
        self.model.set_review_marks({})
        self.next_review_action.setEnabled(False)
        self.next_review_action.setVisible(False)
        self._manual_page_view = True
        if hasattr(self, "manual_page_view_action"):
            self.manual_page_view_action.setEnabled(False)
            self.manual_page_view_action.setVisible(False)
        self.manual_final_save_action.setEnabled(False)
        self.manual_final_save_action.setVisible(False)
        self.manual_final_undo_action.setEnabled(False)
        self.manual_final_undo_action.setVisible(False)
        self.manual_final_synthesis_action.setEnabled(False)
        self.manual_final_synthesis_action.setVisible(False)
        self.manual_draft_synthesis_action.setEnabled(False)
        self.manual_draft_synthesis_action.setVisible(False)
        try:
            session = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
        except ManualFinalSubtitleEditError as exc:
            self.status_label.setText(self.tr("字幕已生成，但人工终稿编辑不可用：") + str(exc))
            return
        self.manual_final_session = session
        self.subtitle_path = str(session.subtitle_path)
        self._set_manual_clean_checkpoint()
        self._load_manual_final_review_marks(session)
        self._apply_manual_final_session()
        self._restore_saved_manual_package_actions()
        self.status_label.setText(
            self.tr(
                f"稳定终稿已就绪（{self.model.rowCount()} 条），可按词级时间手动调整边界；正在检查高优先复查点"
            )
        )

    def _load_manual_failure_checkpoint_from_output(self, output_path: str) -> bool:
        if self._manual_save_in_progress:
            return False
        if not output_path:
            return False
        failure_path = Path(output_path).parent / "stable-last-failure.json"
        if not failure_path.is_file():
            return False
        try:
            failure = json.loads(failure_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return False
        expected_attempt_id = str(
            getattr(self, "_active_subtitle_attempt_id", "") or ""
        )
        if (
            not expected_attempt_id
            or not isinstance(failure, dict)
            or str(failure.get("attempt_id") or "") != expected_attempt_id
        ):
            return False
        try:
            session = ManualFinalSubtitleSession.load_from_failure_record(
                failure_path
            )
        except ManualFinalSubtitleEditError as exc:
            self.status_label.setText(
                self.tr("自动处理失败，且无法加载编辑检查点：") + str(exc)
            )
            return False
        self._invalidate_manual_final_save()
        self.manual_final_session = session
        self._manual_package_manifest_path = ""
        self._manual_review_mark_count = 0
        self._review_mark_rows = []
        self._manual_review_invalidated_ids = set()
        self._review_mark_request_id += 1
        self._manual_parent_boundaries_dirty = False
        self._manual_pending_page_split = None
        self.model.set_review_marks({})
        self.next_review_action.setEnabled(False)
        self.next_review_action.setVisible(False)
        self._manual_page_view = True
        if hasattr(self, "manual_page_view_action"):
            self.manual_page_view_action.setEnabled(False)
            self.manual_page_view_action.setVisible(False)
        self.manual_final_synthesis_action.setEnabled(False)
        self.manual_final_synthesis_action.setVisible(False)
        self.manual_draft_synthesis_action.setEnabled(False)
        self.manual_draft_synthesis_action.setVisible(False)
        self.subtitle_path = str(session.subtitle_path)
        self._set_manual_clean_checkpoint()
        self._load_manual_final_review_marks(session)
        self._apply_manual_final_session()
        self.status_label.setText(
            self.tr(
                f"自动分页未通过；已加载 {self.model.rowCount()} 条完整字幕，问题字幕已标记，暂不允许合成"
            )
        )
        return True

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
            if review_marks_require_syntax_parser(
                artifact_dir
            ) and not syntax_review_parser_available():
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
            if not self._manual_save_in_progress:
                self.status_label.setText(
                    self.tr("稳定终稿已加载；高优先复查标记加载失败，字幕内容未受影响。")
                )
            return
        invalidated_ids = set(
            getattr(self, "_manual_review_invalidated_ids", set()) or set()
        )
        marks_by_subtitle_id = {
            str(subtitle_id): marks
            for subtitle_id, marks in marks_by_subtitle_id.items()
            if str(subtitle_id) not in invalidated_ids
        }
        self.model.set_review_marks(marks_by_subtitle_id)
        self._refresh_manual_review_rows()
        if self._manual_save_in_progress or bool(
            getattr(self, "_manual_has_unsaved_changes", False)
        ):
            return
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
        rows = []
        for row in range(self.model.rowCount()):
            segment = self.model._data.get(str(row + 1), {})
            if self.model._marks_for_segment(segment):
                rows.append(row)
        return rows

    def _refresh_manual_review_rows(self) -> None:
        marks = getattr(self.model, "_review_marks_by_subtitle_id", {}) or {}
        self._review_mark_rows = self._rows_with_review_marks(marks)
        unique_marks = {
            (
                mark.subtitle_id,
                mark.severity,
                mark.category,
                mark.target,
                mark.code,
                mark.reason,
            )
            for row in range(self.model.rowCount())
            for mark in self.model._marks_for_segment(
                self.model._data.get(str(row + 1), {})
            )
        }
        self._manual_review_mark_count = len(unique_marks)
        self.next_review_action.setEnabled(bool(self._review_mark_rows))
        self.next_review_action.setVisible(bool(self._review_mark_rows))

    def _invalidate_manual_review_marks_for_parent_ids(self, parent_ids) -> None:
        invalidated = {
            str(parent_id) for parent_id in parent_ids if str(parent_id)
        }
        if not invalidated:
            return
        invalidated_store = set(
            getattr(self, "_manual_review_invalidated_ids", set()) or set()
        )
        invalidated_store.update(invalidated)
        self._manual_review_invalidated_ids = invalidated_store
        self.model.remove_review_marks_for_subtitle_ids(invalidated)
        self._refresh_manual_review_rows()

    def _review_time_range(self, row: int) -> str:
        segment = self.model._data.get(str(row + 1), {})
        start = QTime(0, 0).addMSecs(int(segment.get("start_time") or 0))
        end = QTime(0, 0).addMSecs(int(segment.get("end_time") or 0))
        return f"{start.toString('hh:mm:ss.zzz')}–{end.toString('hh:mm:ss.zzz')}"

    def focus_next_review_mark(self) -> None:
        self._refresh_manual_review_rows()
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

    def _commit_active_manual_table_editor(self) -> None:
        """Commit the active Qt delegate before rebuilding the subtitle model."""
        table = getattr(self, "subtitle_table", None)
        if table is None or table.state() != QAbstractItemView.EditingState:
            return
        editor = QApplication.focusWidget()
        if (
            editor is None
            or editor is table
            or not table.isAncestorOf(editor)
        ):
            return
        table.commitData(editor)
        table.closeEditor(editor, QAbstractItemDelegate.NoHint)

    def _sync_manual_final_text_edits(
        self,
        *,
        allow_incomplete_page_chinese: bool = True,
    ) -> None:
        if not self.manual_final_session:
            return
        if bool(getattr(self, "_manual_save_in_progress", False)):
            raise ManualFinalSubtitleEditError(
                "人工终稿正在保存，完成前不能继续修改字幕。"
            )
        commit_editor = getattr(self, "_commit_active_manual_table_editor", None)
        if callable(commit_editor):
            commit_editor()
        first_row = self.model._data.get("1") or {}
        if first_row.get("display_page_view"):
            self.manual_final_session.apply_display_page_model_data(
                self.model._data,
                allow_incomplete_chinese=allow_incomplete_page_chinese,
            )
        else:
            apply_parent_rows = getattr(
                self.manual_final_session,
                "apply_parent_model_data",
                None,
            )
            if not callable(apply_parent_rows):
                raise ManualFinalSubtitleEditError(
                    "人工终稿会话不支持稳定父字幕写回。"
                )
            apply_parent_rows(self.model._data)
        self._manual_model_has_pending_edits = False
        reconcile = getattr(self, "_reconcile_manual_dirty_state", None)
        if callable(reconcile):
            reconcile()

    def _apply_manual_final_session(self) -> None:
        if not self.manual_final_session:
            return
        set_manual_mode = getattr(self, "_set_manual_editor_mode", None)
        if callable(set_manual_mode):
            set_manual_mode(True)
        self.subtitle_table.setToolTip(
            self.tr("选中字幕后，使用英文单元格内的按钮调整相邻边界")
        )
        clear_boundary_widgets = getattr(
            self,
            "_clear_manual_boundary_index_widgets",
            None,
        )
        if callable(clear_boundary_widgets):
            clear_boundary_widgets()
        boundaries_dirty = bool(
            getattr(self, "_manual_parent_boundaries_dirty", False)
        )
        data = self.manual_final_session.to_model_data(
            prefer_display_pages=(
                self._manual_page_view and not boundaries_dirty
            )
        )
        self.model.update_all(data)
        self._manual_model_has_pending_edits = False
        refresh_review_rows = getattr(self, "_refresh_manual_review_rows", None)
        if callable(refresh_review_rows):
            refresh_review_rows()
        page_mode = bool(data and (data.get("1") or {}).get("display_page_view"))
        self._manual_page_view = page_mode
        has_page_artifact = self.manual_final_session.has_display_page_model()
        has_pages = has_page_artifact and not boundaries_dirty
        if hasattr(self, "manual_page_view_action"):
            self.manual_page_view_action.setEnabled(
                has_pages or boundaries_dirty
            )
            self.manual_page_view_action.setVisible(
                has_pages or boundaries_dirty
            )
            if hasattr(self.manual_page_view_action, "setText"):
                if boundaries_dirty:
                    self.manual_page_view_action.setText(self.tr("刷新实际分页"))
                else:
                    self.manual_page_view_action.setText(
                        self.tr("查看父字幕" if page_mode else "查看实际分页")
                    )
        self.manual_final_save_action.setEnabled(True)
        self.manual_final_save_action.setVisible(True)
        self.manual_final_undo_action.setEnabled(
            bool(self.manual_final_session.history)
            or bool(getattr(self, "_manual_model_has_pending_edits", False))
        )
        self.manual_final_undo_action.setVisible(False)
        self.manual_final_synthesis_action.setVisible(True)
        self.manual_draft_synthesis_action.setVisible(True)
        refresh = getattr(self, "_refresh_manual_boundary_inspector", None)
        if callable(refresh):
            refresh()

    def toggle_manual_page_view(self) -> None:
        if not self.manual_final_session:
            return
        if getattr(self, "_manual_parent_boundaries_dirty", False):
            self._manual_refresh_requested = True
            self.save_manual_final_output()
            return
        try:
            self._sync_manual_final_text_edits()
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(
                self.tr("无法切换视图"),
                str(exc),
                duration=5000,
                parent=self,
            )
            return
        self._manual_page_view = not self._manual_page_view
        self._apply_manual_final_session()

    def _restore_saved_manual_package_actions(self) -> None:
        """Restore synthesis actions when an imported SRT matches a saved package."""
        session = self.manual_final_session
        if (
            session is None
            or getattr(self, "_manual_parent_boundaries_dirty", False)
            or not session.manifest_path.is_file()
        ):
            return
        try:
            manifest = json.loads(
                session.manifest_path.read_text(encoding="utf-8-sig")
            )
        except (OSError, json.JSONDecodeError):
            return
        override = manifest.get("manual_final_override") or {}
        if not isinstance(override, dict) or int(override.get("schema_version") or 0) < 2:
            return

        blocked = bool(manifest.get("render_blocked"))
        try:
            resolve_synthesis_package_inputs(
                session.manifest_path,
                allow_manual_draft=blocked,
            )
        except RuntimeError:
            return

        self._manual_package_manifest_path = str(session.manifest_path)
        self.manual_final_synthesis_action.setEnabled(not blocked)
        self.manual_final_synthesis_action.setVisible(True)
        SubtitleInterface._set_optional_action_tooltip(
            self.manual_final_synthesis_action,
            "" if not blocked else self.tr("正式终稿仍有未通过的分页检查"),
        )
        self.manual_draft_synthesis_action.setEnabled(blocked)
        self.manual_draft_synthesis_action.setVisible(True)
        SubtitleInterface._set_optional_action_tooltip(
            self.manual_draft_synthesis_action,
            "" if blocked else self.tr("当前终稿已通过，可直接正式合成"),
        )

    @staticmethod
    def _set_optional_action_tooltip(action, text: str) -> None:
        setter = getattr(action, "setToolTip", None)
        if callable(setter):
            setter(str(text))

    def _on_manual_table_data_changed(self, top_left, bottom_right, roles=None) -> None:
        if not self.manual_final_session:
            return
        if bottom_right.column() < 2 or top_left.column() > 3:
            return
        changed_roles = set(roles or [])
        if changed_roles and Qt.EditRole not in changed_roles:
            return
        first_row = self.model._data.get("1") or {}
        page_view = bool(first_row.get("display_page_view"))
        english_changed = top_left.column() <= 2 <= bottom_right.column()
        changed_parent_ids = {
            str(value)
            for row in range(top_left.row(), bottom_right.row() + 1)
            for value in [
                (self.model._data.get(str(row + 1)) or {}).get(
                    "manual_cue_id"
                ),
                *((self.model._data.get(str(row + 1)) or {}).get(
                    "source_subtitle_ids"
                ) or []),
            ]
            if str(value)
        }
        self._invalidate_manual_review_marks_for_parent_ids(changed_parent_ids)
        self._manual_model_has_pending_edits = True
        self._mark_manual_final_dirty(
            invalidate_pages=not page_view and english_changed
        )
        self.manual_final_undo_action.setEnabled(True)
        refresh_review_rows = getattr(self, "_refresh_manual_review_rows", None)
        if callable(refresh_review_rows):
            refresh_review_rows()
        self._refresh_manual_boundary_inspector()

    def undo_manual_final_edit(self, parent_subtitle_id: str = "") -> None:
        if not self.manual_final_session:
            return
        expected_parent_id = (
            str(parent_subtitle_id).strip()
            if isinstance(parent_subtitle_id, str)
            else ""
        )
        try:
            self._sync_manual_final_text_edits()
            operation = str(
                (self.manual_final_session.history[-1] or {}).get("operation") or ""
            ) if self.manual_final_session.history else ""
            undo_for_parent = getattr(
                self.manual_final_session,
                "undo_for_parent",
                None,
            )
            undone = (
                undo_for_parent(expected_parent_id)
                if expected_parent_id and callable(undo_for_parent)
                else self.manual_final_session.undo()
            )
            if undone:
                boundary_change = operation in {
                    "move_suffix_to_next",
                    "move_prefix_to_previous",
                    "merge_adjacent",
                }
                if boundary_change:
                    self._manual_parent_boundaries_dirty = not bool(
                        self.manual_final_session.has_display_page_model()
                    )
                self._manual_model_has_pending_edits = False
                dirty = self._reconcile_manual_dirty_state()
                if dirty:
                    self._mark_manual_final_dirty(invalidate_pages=False)
                else:
                    self._manual_parent_boundaries_dirty = False
                self._apply_manual_final_session()
                if expected_parent_id:
                    identity_row = SubtitleInterface._manual_row_for_identity(
                        self,
                        parent_id=expected_parent_id,
                    )
                    if identity_row is not None:
                        self._select_manual_boundary_row(identity_row)
                if not dirty:
                    self._restore_saved_manual_package_actions()
                    self.status_label.setText(
                        self.tr("已撤销到上次保存状态")
                    )
                elif boundary_change:
                    selector = getattr(self, "_select_manual_boundary_row", None)
                    left_index = int(
                        getattr(self, "_manual_boundary_left_index_value", 0) or 0
                    )
                    if callable(selector):
                        selector(left_index)
                    else:
                        SubtitleInterface._select_manual_boundary_row(
                            self, left_index
                        )
                    self.status_label.setText(
                        self.tr("已撤销上一步；保存人工终稿后刷新实际分页")
                    )
                else:
                    self.status_label.setText(
                        self.tr("已撤销上一步；请重新保存人工终稿")
                    )
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(self.tr("无法撤销"), str(exc), duration=5000, parent=self)

    def save_manual_final_output(self) -> int | None:
        if not self.manual_final_session:
            InfoBar.warning(
                self.tr("人工终稿不可用"),
                self.tr("请加载带稳定 artifacts 的最终双语字幕。"),
                duration=5000,
                parent=self,
            )
            return None
        if self._manual_save_in_progress:
            InfoBar.warning(
                self.tr("正在保存"),
                self.tr("人工终稿正在后台检查并保存，请稍候。"),
                duration=3000,
                parent=self,
            )
            return None
        try:
            self._sync_manual_final_text_edits(
                allow_incomplete_page_chinese=True
            )
            source_media_path = ""
            if self.task is not None:
                for candidate in (
                    getattr(self.task, "source_audio_path", None),
                    getattr(self.task, "video_path", None),
                ):
                    if candidate and Path(candidate).is_file():
                        source_media_path = str(Path(candidate).resolve())
                        break
            if (
                not source_media_path
                and getattr(
                    self.manual_final_session, "source_media_path", None
                ) is not None
                and self.manual_final_session.source_media_path.is_file()
            ):
                source_media_path = str(
                    self.manual_final_session.source_media_path.resolve()
                )
            self._manual_save_request_id += 1
            request_id = self._manual_save_request_id
            refresh_requested = bool(self._manual_refresh_requested)
            self._manual_refresh_requested = False
            self._manual_active_save_context = {
                "request_id": request_id,
                "refresh_requested": refresh_requested,
            }
            self._set_manual_final_save_busy(True)
            self.status_label.setText(
                self.tr(
                    "正在后台刷新实际分页并保存检查点..."
                    if refresh_requested
                    else "正在后台检查分页并保存人工终稿..."
                )
            )
            worker = Thread(
                target=self._save_manual_final_output_in_background,
                args=(request_id, self.manual_final_session, source_media_path),
                daemon=True,
            )
            _manual_final_save_worker_started()
            try:
                worker.start()
            except Exception:
                _manual_final_save_worker_finished()
                raise
            return request_id
        except ManualFinalSubtitleEditError as exc:
            self._manual_refresh_requested = False
            self._manual_active_save_context = None
            InfoBar.warning(self.tr("保存失败"), str(exc), duration=5000, parent=self)
        except Exception as exc:
            self._manual_refresh_requested = False
            self._manual_active_save_context = None
            if self._manual_save_in_progress:
                self._set_manual_final_save_busy(False)
            LOG.exception("Unable to start manual final subtitle save")
            InfoBar.warning(
                self.tr("保存失败"),
                str(exc),
                duration=5000,
                parent=self,
            )
        return None

    def manual_final_save_in_progress(self) -> bool:
        return manual_final_save_worker_active()

    def _set_manual_final_save_busy(self, busy: bool) -> None:
        self._manual_save_in_progress = bool(busy)
        self.subtitle_table.setEnabled(not busy)
        self.manual_final_save_action.setEnabled(
            not busy and self.manual_final_session is not None
        )
        self.manual_final_save_action.setText(
            self.tr("正在保存终稿...") if busy else self.tr("保存人工终稿")
        )
        self.manual_final_undo_action.setEnabled(
            not busy
            and self.manual_final_session is not None
            and (
                bool(self.manual_final_session.history)
                or bool(getattr(self, "_manual_model_has_pending_edits", False))
            )
        )
        if hasattr(self, "manual_page_view_action"):
            self.manual_page_view_action.setEnabled(
                not busy
                and self.manual_final_session is not None
                and (
                    bool(getattr(self, "_manual_parent_boundaries_dirty", False))
                    or self.manual_final_session.has_display_page_model()
                )
            )
        if busy:
            if hasattr(self, "progress_bar"):
                self.progress_bar.hide()
            if hasattr(self, "manual_save_progress_bar"):
                self.manual_save_progress_bar.show()
                self.manual_save_progress_bar.start()
            self.manual_final_synthesis_action.setEnabled(False)
            self.manual_final_synthesis_action.setVisible(True)
            self.manual_draft_synthesis_action.setEnabled(False)
            self.manual_draft_synthesis_action.setVisible(True)
        else:
            if hasattr(self, "manual_save_progress_bar"):
                self.manual_save_progress_bar.stop()
                self.manual_save_progress_bar.hide()
            if hasattr(self, "progress_bar"):
                self.progress_bar.show()
            refresh = getattr(self, "_refresh_manual_boundary_inspector", None)
            if callable(refresh):
                refresh()

    def _invalidate_manual_final_save(self) -> None:
        if bool(getattr(self, "_manual_save_in_progress", False)):
            return
        self._manual_save_request_id = (
            int(getattr(self, "_manual_save_request_id", 0) or 0) + 1
        )
        self._manual_save_in_progress = False
        self._manual_refresh_requested = False
        self._manual_active_save_context = None
        self._manual_pending_page_split = None
        table = getattr(self, "subtitle_table", None)
        if table is not None:
            table.setEnabled(True)

    def _save_manual_final_output_in_background(
        self,
        request_id: int,
        session: ManualFinalSubtitleSession,
        source_media_path: str,
    ) -> None:
        try:
            with _MANUAL_FINAL_SAVE_LOCK:
                session_snapshot = copy.deepcopy(session)

                def report_progress(percent: int, stage: str) -> None:
                    self.manual_final_save_progress.emit(
                        request_id,
                        int(percent),
                        str(stage),
                    )

                paths = session_snapshot.save_to_source_folder(
                    source_media_path=source_media_path or None,
                    progress_callback=report_progress,
                )
            error = ""
        except Exception as exc:
            LOG.exception("Unable to save manual final subtitle package")
            paths = {}
            error = str(exc)
        finally:
            _manual_final_save_worker_finished()
        try:
            self.manual_final_save_finished.emit(request_id, paths, error)
        except RuntimeError:
            LOG.info("Manual final save completed after the editor was closed")

    def _apply_manual_final_save_progress(
        self,
        request_id: int,
        percent: int,
        stage: str,
    ) -> None:
        if request_id != self._manual_save_request_id or not self._manual_save_in_progress:
            return
        self.status_label.setText(
            self.tr(f"保存人工终稿 {max(0, min(int(percent), 100))}%：{stage}")
        )

    def _apply_manual_final_save_result(
        self,
        request_id: int,
        paths: dict,
        error: str,
    ) -> None:
        if request_id != self._manual_save_request_id:
            return
        save_context = getattr(self, "_manual_active_save_context", None) or {}
        refreshed_by_request = bool(
            int(save_context.get("request_id") or request_id) == int(request_id)
            and save_context.get("refresh_requested")
        )
        if not save_context:
            refreshed_by_request = bool(
                getattr(self, "_manual_refresh_requested", False)
            )
        self._manual_active_save_context = None
        self._manual_refresh_requested = False
        self._set_manual_final_save_busy(False)
        pending_split = getattr(self, "_manual_pending_page_split", None)
        pending_for_request = bool(
            pending_split
            and len(pending_split) == 3
            and int(pending_split[2]) == int(request_id)
        )
        if error:
            if pending_for_request:
                self._manual_pending_page_split = None
            self.status_label.setText(self.tr("人工终稿保存失败"))
            InfoBar.warning(
                self.tr("保存失败"),
                error,
                duration=5000,
                parent=self,
            )
            return

        manifest_path = str(
            paths.get("manifest_path") if isinstance(paths, dict) else ""
        ).strip()
        try:
            if not manifest_path:
                raise ManualFinalSubtitleEditError(
                    "保存结果缺少稳定终稿清单。"
                )
            refreshed_session = ManualFinalSubtitleSession.load_from_manifest(
                manifest_path
            )
        except Exception:
            LOG.exception("Unable to reload saved manual final subtitle package")
            if pending_for_request:
                self._manual_pending_page_split = None
            self._manual_package_manifest_path = ""
            self._manual_has_unsaved_changes = True
            self.status_label.setText(
                self.tr("检查点已写入但重新校验失败；当前编辑内容仍保留")
            )
            InfoBar.warning(
                self.tr("刷新实际分页失败"),
                self.tr(
                    "人工终稿包已经写入，但重新载入校验失败。"
                    "当前实际分页和未保存编辑均已保留；请再次保存，"
                    "不要重新导入或重跑音频。"
                ),
                duration=5000,
                parent=self,
            )
            return
        else:
            self._manual_package_manifest_path = manifest_path
            self.manual_final_session = refreshed_session
            self.subtitle_path = str(refreshed_session.subtitle_path)
            self._manual_parent_boundaries_dirty = False
            self._manual_page_view = True
            self._review_mark_request_id = int(
                getattr(self, "_review_mark_request_id", 0) or 0
            ) + 1
            self._manual_review_invalidated_ids = set()
            set_review_marks = getattr(
                getattr(self, "model", None), "set_review_marks", None
            )
            if callable(set_review_marks):
                set_review_marks({})
            set_clean = getattr(self, "_set_manual_clean_checkpoint", None)
            if callable(set_clean):
                set_clean()
            self._apply_manual_final_session()
            load_review_marks = getattr(
                self, "_load_manual_final_review_marks", None
            )
            if callable(load_review_marks):
                load_review_marks(refreshed_session)
        if pending_for_request:
            parent_id, page_count, _ = pending_split
            self._manual_pending_page_split = None
            self._split_parent_into_display_pages(str(parent_id), int(page_count))
            return
        can_synthesize = not bool(paths["render_blocked"])
        can_synthesize_draft = (
            bool(paths["render_blocked"])
            and str(paths.get("render_block_reason") or "")
            in MANUAL_DRAFT_ALLOWED_BLOCK_REASONS
            and bool(paths.get("manual_draft_ready"))
        )
        self.manual_final_synthesis_action.setEnabled(can_synthesize)
        self.manual_final_synthesis_action.setVisible(True)
        self.manual_draft_synthesis_action.setEnabled(can_synthesize_draft)
        self.manual_draft_synthesis_action.setVisible(True)
        review_summary = dict(paths.get("display_page_review_summary") or {})
        chinese_count = int(
            review_summary.get("unconfirmed_chinese_count") or 0
        )
        boundary_count = int(
            review_summary.get("boundary_review_count") or 0
        )
        hard_count = int(review_summary.get("hard_page_count") or 0)
        review_text = self.tr(
            f"{chinese_count}条分页中文未确认，"
            f"{boundary_count}个分页边界待复核"
        )
        chinese_positions = [
            str(value)
            for value in review_summary.get("unconfirmed_chinese_pages") or []
        ]
        boundary_positions = [
            str(value)
            for value in review_summary.get("boundary_review_pages") or []
        ]
        soft_position_text = self.tr("；中文位置：") + "、".join(
            chinese_positions[:8]
        )
        if len(chinese_positions) > 8:
            soft_position_text += self.tr("等")
        soft_position_text += self.tr("；边界位置：") + "、".join(
            boundary_positions[:8]
        )
        if len(boundary_positions) > 8:
            soft_position_text += self.tr("等")
        SubtitleInterface._set_optional_action_tooltip(
            self.manual_final_synthesis_action,
            "" if can_synthesize else review_text,
        )
        SubtitleInterface._set_optional_action_tooltip(
            self.manual_draft_synthesis_action,
            "" if can_synthesize_draft else self.tr("当前检查点不能安全合成草稿"),
        )
        if can_synthesize:
            self.status_label.setText(
                self.tr(
                    "实际分页已刷新并保存，可直接前往视频合成"
                    if refreshed_by_request
                    else "人工终稿包已保存，可直接前往视频合成"
                )
            )
            InfoBar.success(
                self.tr("人工终稿包已保存"),
                self.tr("清单：") + paths["manifest_path"],
                duration=5000,
                parent=self,
            )
        elif can_synthesize_draft:
            self.status_label.setText(
                review_text + self.tr("；可合成草稿")
            )
            InfoBar.warning(
                self.tr("人工终稿尚未通过正式合成检查"),
                review_text
                + soft_position_text
                + self.tr(
                    "。无需重跑音频；在实际分页中右键可确认当前项或全部非阻断提醒，"
                    "也可先合成草稿。"
                ),
                duration=6000,
                parent=self,
            )
        else:
            self.status_label.setText(
                self.tr(
                    f"编辑进度已保存；{hard_count}个结构问题仍阻止合成："
                )
                + str(paths.get("render_block_reason") or "unknown")
            )
            InfoBar.warning(
                self.tr("人工终稿仍有结构错误"),
                self.tr("阻止原因：")
                + str(paths.get("render_block_reason") or "unknown")
                + self.tr("；位置：")
                + "、".join(
                    str(value)
                    for value in review_summary.get("hard_pages") or []
                )[:300],
                duration=6000,
                parent=self,
            )

    def open_manual_final_in_synthesis(self) -> None:
        manifest_path = self._manual_package_manifest_path
        if not manifest_path or not Path(manifest_path).is_file():
            InfoBar.warning(
                self.tr("人工终稿包不可用"),
                self.tr("请先保存通过检查的人工终稿。"),
                duration=4000,
                parent=self,
            )
            return
        source_media_path = ""
        if self.task is not None:
            for candidate in (
                getattr(self.task, "source_audio_path", None),
                getattr(self.task, "video_path", None),
            ):
                if candidate and Path(candidate).is_file():
                    source_media_path = str(Path(candidate).resolve())
                    break
        if (
            not source_media_path
            and self.manual_final_session is not None
            and getattr(self.manual_final_session, "source_media_path", None)
            is not None
            and self.manual_final_session.source_media_path.is_file()
        ):
            source_media_path = str(
                self.manual_final_session.source_media_path.resolve()
            )
        self.manual_final_ready.emit(source_media_path, manifest_path)

    def open_manual_draft_in_synthesis(self) -> None:
        manifest_path = self._manual_package_manifest_path
        if not manifest_path or not Path(manifest_path).is_file():
            InfoBar.warning(
                self.tr("人工草稿包不可用"),
                self.tr("请先保存当前人工终稿检查点。"),
                duration=4000,
                parent=self,
            )
            return
        dialog = MessageBox(
            self.tr("合成未通过分页检查的草稿？"),
            self.tr(
                "草稿视频可能仍有过长页面、待复核分页或未完成的逐页中文。"
                "正式合成门禁不会被关闭，输出文件会带“【人工草稿】”前缀且不会覆盖正式视频。"
            ),
            self,
        )
        dialog.yesButton.setText(self.tr("继续合成草稿"))
        dialog.cancelButton.setText(self.tr("返回编辑"))
        if not dialog.exec():
            return
        source_media_path = ""
        if self.task is not None:
            for candidate in (
                getattr(self.task, "source_audio_path", None),
                getattr(self.task, "video_path", None),
            ):
                if candidate and Path(candidate).is_file():
                    source_media_path = str(Path(candidate).resolve())
                    break
        if (
            not source_media_path
            and self.manual_final_session is not None
            and getattr(self.manual_final_session, "source_media_path", None)
            is not None
            and self.manual_final_session.source_media_path.is_file()
        ):
            source_media_path = str(
                self.manual_final_session.source_media_path.resolve()
            )
        self.manual_draft_ready.emit(source_media_path, manifest_path)

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
        if self._manual_save_in_progress:
            event.ignore()
            return
        if not self.can_close_with_manual_edits():
            event.ignore()
            return
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
        selected_data = [
            self.model._data.get(str(row + 1)) or {} for row in rows
        ]
        page_rows = any(
            (self.model._data.get(str(row + 1)) or {}).get("display_page_view")
            for row in rows
        )
        if len(rows) > 1 and rows_are_contiguous and not page_rows:
            merge_action = Action(FIF.LINK, self.tr("合并相邻字幕"))
            menu.addAction(merge_action)
            merge_action.setShortcut("Ctrl+M")
            merge_action.triggered.connect(lambda: self.merge_selected_rows(rows))
        elif (
            len(rows) == 2
            and rows_are_contiguous
            and all(row.get("display_page_view") for row in selected_data)
        ):
            parent_ids = {
                str(row.get("manual_cue_id") or "") for row in selected_data
            }
            label = (
                "合并所选相邻分屏"
                if len(parent_ids) == 1
                else "合并相邻父字幕"
            )
            merge_action = Action(FIF.LINK, self.tr(label))
            menu.addAction(merge_action)
            merge_action.setShortcut("Ctrl+M")
            merge_action.triggered.connect(lambda: self.merge_selected_rows(rows))

        if self.manual_final_session and len(rows) == 1:
            selected_row = rows[0]
            selected = self.model._data.get(str(selected_row + 1)) or {}
            parent_id = str(selected.get("manual_cue_id") or "")
            selected_is_page = bool(
                selected.get("display_page_view")
                and selected.get("display_page_id")
                and not selected.get("display_page_unavailable")
            )
            if parent_id and selected_is_page:
                menu.addSeparator()
                next_row = self.model._data.get(str(selected_row + 2)) or {}
                if (
                    str(next_row.get("manual_cue_id") or "") == parent_id
                    and next_row.get("display_page_view")
                    and next_row.get("display_page_id")
                    and not next_row.get("display_page_unavailable")
                ):
                    merge_page_action = Action(
                        FIF.LINK,
                        self.tr("与下一屏合并"),
                    )
                    merge_page_action.triggered.connect(
                        lambda _checked=False, pid=str(
                            selected.get("display_page_id") or ""
                        ): self._merge_display_page_with_next(pid)
                    )
                    menu.addAction(merge_page_action)
                current_parent_page_count = sum(
                    1
                    for row in self.model._data.values()
                    if str(row.get("manual_cue_id") or "") == parent_id
                    and row.get("display_page_id")
                    and not row.get("display_page_unavailable")
                )
                current_parent_page_count = max(current_parent_page_count, 1)
                focus_word_id = int(selected.get("word_start"))
                for target_parent_page_count in range(
                    current_parent_page_count + 1,
                    5,
                ):
                    split_action = Action(
                        FIF.EDIT,
                        self.tr(
                            f"整条字幕调整为 {target_parent_page_count} 屏"
                        ),
                    )
                    split_action.triggered.connect(
                        lambda _checked=False,
                        pid=parent_id,
                        count=target_parent_page_count,
                        focus=focus_word_id: (
                            self._split_parent_into_display_pages(
                                pid,
                                count,
                                focus_word_id=focus,
                            )
                        )
                    )
                    menu.addAction(split_action)

                menu.addSeparator()
                page_id = str(selected.get("display_page_id") or "")
                confirm_chinese_action = Action(
                    FIF.ACCEPT,
                    self.tr("确认当前中文"),
                )
                if hasattr(confirm_chinese_action, "setEnabled"):
                    confirm_chinese_action.setEnabled(
                        bool(str(selected.get("translated_subtitle") or "").strip())
                        and not bool(
                            selected.get("display_page_chinese_confirmed")
                        )
                    )
                confirm_chinese_action.triggered.connect(
                    lambda _checked=False, pid=page_id: (
                        self._confirm_current_display_page_chinese(pid)
                    )
                )
                menu.addAction(confirm_chinese_action)

                confirm_boundary_action = Action(
                    FIF.ACCEPT,
                    self.tr("确认当前分页边界"),
                )
                if hasattr(confirm_boundary_action, "setEnabled"):
                    confirm_boundary_action.setEnabled(
                        bool(selected.get("display_page_review_required"))
                        and str(
                            selected.get(
                                "display_page_boundary_classification"
                            )
                            or ""
                        )
                        != "hard"
                    )
                confirm_boundary_action.triggered.connect(
                    lambda _checked=False, pid=page_id: (
                        self._confirm_current_display_page_boundary(pid)
                    )
                )
                menu.addAction(confirm_boundary_action)

                confirm_all_action = Action(
                    FIF.ACCEPT,
                    self.tr("确认全部非阻断提醒"),
                )
                confirm_all_action.triggered.connect(
                    self._confirm_all_nonblocking_display_page_reviews
                )
                menu.addAction(confirm_all_action)

        if self.manual_final_session and len(rows) == 1:
            row = rows[0]
            selected = self.model._data.get(str(row + 1)) or {}
            selected_page_id = str(selected.get("display_page_id") or "")
            tail_target_available = bool(
                selected_page_id or not selected.get("display_page_view")
            )
            menu.addSeparator()
            preview_trim_action = Action(
                FIF.PLAY,
                self.tr(
                    "试听从当前页删除的切点"
                    if selected_page_id
                    else "试听尾部删除切点"
                ),
            )
            preview_trim_action.setEnabled(row > 0 and tail_target_available)
            preview_trim_action.triggered.connect(
                lambda: self._preview_manual_tail_trim(row)
            )
            menu.addAction(preview_trim_action)
            trim_tail_action = Action(
                FIF.DELETE,
                self.tr(
                    "从当前页删除到结尾"
                    if selected_page_id
                    else "从这里删除到结尾"
                ),
            )
            trim_tail_action.setEnabled(row > 0 and tail_target_available)
            trim_tail_action.triggered.connect(
                lambda: self._delete_manual_tail_from_row(row)
            )
            menu.addAction(trim_tail_action)

        # 显示菜单
        menu.exec(self.subtitle_table.viewport().mapToGlobal(pos))

    def _confirm_current_display_page_chinese(self, page_id: str) -> None:
        if not self.manual_final_session:
            return
        try:
            self._sync_manual_final_text_edits(
                allow_incomplete_page_chinese=True
            )
            result = self.manual_final_session.confirm_display_page_chinese(
                page_id
            )
            if result.get("changed"):
                self._mark_manual_final_dirty(invalidate_pages=False)
                self._apply_manual_final_session()
            self.status_label.setText(self.tr(f"{page_id} 中文已确认"))
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(
                self.tr("无法确认当前中文"),
                str(exc),
                duration=5000,
                parent=self,
            )

    def _confirm_current_display_page_boundary(self, page_id: str) -> None:
        if not self.manual_final_session:
            return
        try:
            self._sync_manual_final_text_edits(
                allow_incomplete_page_chinese=True
            )
            result = self.manual_final_session.confirm_display_page_boundary(
                page_id
            )
            if result.get("changed"):
                self._mark_manual_final_dirty(invalidate_pages=False)
                self._apply_manual_final_session()
            self.status_label.setText(self.tr(f"{page_id} 分页边界已确认"))
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(
                self.tr("无法确认当前分页边界"),
                str(exc),
                duration=5000,
                parent=self,
            )

    def _confirm_all_nonblocking_display_page_reviews(
        self,
        _checked: bool = False,
    ) -> None:
        if not self.manual_final_session:
            return
        try:
            self._sync_manual_final_text_edits(
                allow_incomplete_page_chinese=True
            )
            result = (
                self.manual_final_session
                .confirm_all_nonblocking_display_page_reviews()
            )
            if result.get("changed"):
                self._mark_manual_final_dirty(invalidate_pages=False)
                self._apply_manual_final_session()
            self.status_label.setText(
                self.tr(
                    f"已确认 {int(result.get('chinese_count') or 0)} 条中文和 "
                    f"{int(result.get('boundary_count') or 0)} 个分页边界；"
                    "保存人工终稿后更新合成状态"
                )
            )
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(
                self.tr("无法批量确认"),
                str(exc),
                duration=5000,
                parent=self,
            )

    def _merge_display_page_with_next(self, left_page_id: str) -> None:
        if not self.manual_final_session:
            return
        page_id = str(left_page_id or "").strip()
        if not page_id:
            return
        try:
            self._sync_manual_final_text_edits()
            result = self.manual_final_session.merge_display_page_with_next(
                page_id
            )
            parent_id = str(result["parent_subtitle_id"])
            cue = next(
                (
                    item
                    for item in self.manual_final_session.cues
                    if str(item.get("cue_id") or "") == parent_id
                ),
                {},
            )
            self._invalidate_manual_review_marks_for_parent_ids(
                [parent_id, *(cue.get("source_subtitle_ids") or [])]
            )
            self._manual_boundary_edit_active = False
            self._manual_boundary_move_direction = ""
            self._manual_parent_boundaries_dirty = False
            self._manual_page_view = True
            self._mark_manual_final_dirty(invalidate_pages=False)
            self._apply_manual_final_session()
            merged_page_id = str(result.get("merged_page_id") or "")
            target_row = next(
                (
                    index
                    for index, row in enumerate(self.model._data.values())
                    if str(row.get("display_page_id") or "")
                    == merged_page_id
                ),
                0,
            )
            self._select_manual_boundary_row(target_row)
            self.status_label.setText(
                self.tr(
                    f"已删除词 {result['removed_boundary_word_id']} 前的分页边界；"
                    f"{parent_id} 现为 {result['page_count']} 屏"
                )
            )
            InfoBar.success(
                self.tr("分屏已合并"),
                self.tr("父字幕、固定词范围和时间轴均未改变。"),
                duration=3500,
                parent=self,
            )
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(
                self.tr("无法合并分屏"),
                str(exc),
                duration=5000,
                parent=self,
            )

    def _split_parent_into_display_pages(
        self,
        parent_subtitle_id: str,
        page_count: int,
        *,
        focus_word_id: int | None = None,
    ) -> None:
        if not self.manual_final_session:
            return
        parent_id = str(parent_subtitle_id or "").strip()
        requested = int(page_count)
        if not any(
            str(cue.get("cue_id") or "") == parent_id
            for cue in self.manual_final_session.cues
        ) or requested not in {2, 3, 4}:
            InfoBar.warning(
                self.tr("无法拆分实际分页"),
                self.tr("所选父字幕或页数已经失效，请重新选择。"),
                duration=5000,
                parent=self,
            )
            return
        if getattr(self, "_manual_parent_boundaries_dirty", False):
            if self._manual_save_in_progress:
                InfoBar.warning(
                    self.tr("正在刷新实际分页"),
                    self.tr("请等待当前刷新完成后再发起新的分屏。"),
                    duration=3000,
                    parent=self,
                )
                return
            expected_request_id = int(self._manual_save_request_id) + 1
            self._manual_pending_page_split = (
                parent_id,
                requested,
                expected_request_id,
            )
            self._manual_refresh_requested = True
            request_id = self.save_manual_final_output()
            if request_id != expected_request_id:
                self._manual_pending_page_split = None
                self._manual_refresh_requested = False
                return
            self.status_label.setText(
                self.tr(
                    f"正在刷新实际分页；完成后将 {parent_id} 分为 {requested} 屏"
                )
            )
            return
        try:
            self._sync_manual_final_text_edits()
            result = self.manual_final_session.split_parent_into_display_pages(
                parent_id,
                requested,
            )
            if result.get("changed") is False:
                self.status_label.setText(
                    self.tr(f"{parent_id} 已经是 {requested} 屏，字幕未发生变化")
                )
                InfoBar.info(
                    self.tr("分页没有变化"),
                    self.tr("所选父字幕已经采用相同页数，无需重复重建。"),
                    duration=4000,
                    parent=self,
                )
                return
            self._manual_boundary_edit_active = False
            self._manual_boundary_move_direction = ""
            cue = next(
                (
                    item
                    for item in self.manual_final_session.cues
                    if str(item.get("cue_id") or "") == parent_id
                ),
                {},
            )
            self._invalidate_manual_review_marks_for_parent_ids(
                [parent_id, *(cue.get("source_subtitle_ids") or [])]
            )
            self._mark_manual_final_dirty(invalidate_pages=False)
            self._manual_page_view = True
            self._apply_manual_final_session()
            target_row = next(
                (
                    index
                    for index, row in enumerate(self.model._data.values())
                    if str(row.get("manual_cue_id") or "")
                    == parent_id
                    and (
                        focus_word_id is None
                        or int(row.get("word_start", -1))
                        <= int(focus_word_id)
                        <= int(row.get("word_end", -2))
                    )
                ),
                0,
            )
            self._select_manual_boundary_row(target_row)
            self.status_label.setText(
                self.tr(
                    f"{parent_subtitle_id} 已拆成 {result['page_count']} 屏；"
                    "请逐屏填写中文后保存人工终稿"
                )
            )
            InfoBar.success(
                self.tr("实际分页已重建"),
                self.tr(
                    "英文切点已按停顿和意群规划；新页面中文留空，必须人工确认。"
                ),
                duration=5000,
                parent=self,
            )
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(
                self.tr("无法拆分实际分页"),
                str(exc),
                duration=6000,
                parent=self,
            )

    def _manual_session_source_media(self) -> Path | None:
        session = self.manual_final_session
        if session is None:
            return None
        if session.source_media_path is not None and session.source_media_path.is_file():
            return session.source_media_path
        inferred_media = session._tail_trim_source_media_path()
        if inferred_media is not None and inferred_media.is_file():
            session.source_media_path = inferred_media.resolve()
            return session.source_media_path
        if self.task is not None:
            for candidate in (
                getattr(self.task, "source_audio_path", None),
                getattr(self.task, "video_path", None),
            ):
                if candidate and Path(candidate).is_file():
                    session.source_media_path = Path(candidate).resolve()
                    return session.source_media_path
        return None

    def _manual_tail_trim_target(self, row_index: int) -> tuple[str, str | int]:
        if not self.manual_final_session:
            raise ManualFinalSubtitleEditError("人工终稿会话不存在。")
        row = self.model._data.get(str(int(row_index) + 1)) or {}
        page_id = str(row.get("display_page_id") or "").strip()
        if page_id and row.get("display_page_view"):
            return "page", page_id
        parent_id = str(row.get("manual_cue_id") or "").strip()
        cue_index = next(
            (
                index
                for index, cue in enumerate(self.manual_final_session.cues)
                if str(cue.get("cue_id") or "") == parent_id
            ),
            -1,
        )
        if cue_index < 0:
            raise ManualFinalSubtitleEditError("找不到当前行对应的父字幕。")
        return "cue", cue_index

    def _manual_tail_trim_preview_for_row(
        self,
        row_index: int,
    ) -> dict:
        target_kind, target = self._manual_tail_trim_target(row_index)
        if target_kind == "page":
            return self.manual_final_session.preview_tail_trim_from_display_page(
                str(target)
            )
        return self.manual_final_session.preview_tail_trim(int(target))

    def _apply_manual_tail_trim_for_row(self, row_index: int) -> dict:
        target_kind, target = self._manual_tail_trim_target(row_index)
        if target_kind == "page":
            return self.manual_final_session.trim_tail_from_display_page(
                str(target)
            )
        return self.manual_final_session.trim_tail_from_cue(int(target))

    def _preview_manual_tail_trim(self, first_removed_row: int) -> None:
        if not self.manual_final_session:
            return
        try:
            self._sync_manual_final_text_edits()
            self._manual_session_source_media()
            preview = self._manual_tail_trim_preview_for_row(first_removed_row)
            signalBus.play_video_segment(
                int(preview["preview_start_ms"]),
                int(preview["preview_end_ms"]),
            )
            cut_time = QTime(0, 0).addMSecs(int(preview["cut_ms"]))
            self.status_label.setText(
                self.tr(
                    "正在试听尾部切点 "
                    + cut_time.toString("hh:mm:ss.zzz")
                    + "；切点后的内容将被删除"
                )
            )
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(
                self.tr("无法试听尾部切点"),
                str(exc),
                duration=5000,
                parent=self,
            )

    def _delete_manual_tail_from_row(self, first_removed_row: int) -> None:
        if not self.manual_final_session:
            return
        try:
            self._sync_manual_final_text_edits()
            self._manual_session_source_media()
            preview = self._manual_tail_trim_preview_for_row(first_removed_row)
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(
                self.tr("无法删除尾部"), str(exc), duration=5000, parent=self
            )
            return
        cut_time = QTime(0, 0).addMSecs(int(preview["cut_ms"]))
        partial_page_text = (
            self.tr(
                f"将保留 {preview['kept_last_subtitle_id']} 在当前页之前的内容，"
                f"从 {preview['first_removed_display_page_id']} 起删除后续音频和字幕。\n"
            )
            if preview.get("partial_parent_trim")
            else self.tr(
                f"将保留到 {preview['kept_last_subtitle_id']}，从 "
                f"{preview['first_removed_subtitle_id']} 起删除 "
                f"{len(preview['removed_subtitle_ids'])} 条字幕。\n"
            )
        )
        dialog = MessageBox(
            self.tr("从当前字幕删除到结尾？"),
            partial_page_text
            + self.tr(
                f"音频将在 {cut_time.toString('hh:mm:ss.zzz')} 生成派生裁剪副本；"
                "原始音频不会被修改。"
            ),
            self,
        )
        dialog.yesButton.setText(self.tr("确认删除尾部"))
        dialog.cancelButton.setText(self.tr("取消"))
        if not dialog.exec():
            return
        try:
            result = self._apply_manual_tail_trim_for_row(first_removed_row)
            self._manual_boundary_edit_active = False
            self._manual_boundary_move_direction = ""
            self._manual_page_view = bool(
                self.manual_final_session.has_display_page_model()
            )
            self._mark_manual_final_dirty(invalidate_pages=False)
            self._apply_manual_final_session()
            self._select_manual_boundary_row(
                max(0, len(self.manual_final_session.cues) - 1)
            )
            self.status_label.setText(
                self.tr(
                    f"已从 {result['first_removed_subtitle_id']} 删除到结尾；"
                    "保存人工终稿时生成裁剪音频副本"
                )
            )
        except ManualFinalSubtitleEditError as exc:
            InfoBar.warning(
                self.tr("无法删除尾部"), str(exc), duration=5000, parent=self
            )

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
            selected_data = [
                self.model._data.get(str(row + 1)) or {} for row in rows
            ]
            page_mode = all(
                row.get("display_page_view") and row.get("display_page_id")
                for row in selected_data
            )
            if page_mode:
                parent_ids = list(
                    dict.fromkeys(
                        str(row.get("manual_cue_id") or "")
                        for row in selected_data
                    )
                )
                if len(parent_ids) == 1:
                    if len(rows) != 2:
                        InfoBar.warning(
                            self.tr("无法合并分屏"),
                            self.tr("每次请选择同一父字幕内相邻的两屏。"),
                            duration=4000,
                            parent=self,
                        )
                        return
                    self._merge_display_page_with_next(
                        str(selected_data[0].get("display_page_id") or "")
                    )
                    return
                cue_index_by_id = {
                    str(cue.get("cue_id") or ""): index
                    for index, cue in enumerate(self.manual_final_session.cues)
                }
                try:
                    cue_indexes = [cue_index_by_id[parent_id] for parent_id in parent_ids]
                except KeyError:
                    cue_indexes = []
                expected_cue_indexes = (
                    list(range(cue_indexes[0], cue_indexes[-1] + 1))
                    if cue_indexes
                    else []
                )
                if not cue_indexes or cue_indexes != expected_cue_indexes:
                    InfoBar.warning(
                        self.tr("无法合并父字幕"),
                        self.tr("所选页面不属于连续相邻的父字幕。"),
                        duration=4000,
                        parent=self,
                    )
                    return
                first_cue_index = cue_indexes[0]
                last_cue_index = cue_indexes[-1]
            else:
                first_cue_index = rows[0]
                last_cue_index = rows[-1]
            try:
                self._sync_manual_final_text_edits()
                affected_parent_ids = {
                    str(value)
                    for cue in self.manual_final_session.cues[
                        first_cue_index : last_cue_index + 1
                    ]
                    for value in [
                        cue.get("cue_id"),
                        *(
                            cue.get("source_subtitle_ids")
                            or []
                        ),
                    ]
                    if str(value)
                }
                retained_parent_id = str(
                    self.manual_final_session.cues[first_cue_index].get(
                        "cue_id"
                    )
                    or ""
                )
                self.manual_final_session.merge_adjacent(
                    first_cue_index,
                    last_cue_index,
                )
                self._invalidate_manual_review_marks_for_parent_ids(
                    affected_parent_ids
                )
                pages_preserved = bool(
                    self.manual_final_session.has_display_page_model()
                )
                self._manual_parent_boundaries_dirty = not pages_preserved
                self._manual_page_view = pages_preserved
                self._mark_manual_final_dirty(invalidate_pages=not pages_preserved)
                self._apply_manual_final_session()
                target_row = next(
                    (
                        index
                        for index, row in enumerate(self.model._data.values())
                        if str(row.get("manual_cue_id") or "")
                        == retained_parent_id
                    ),
                    first_cue_index,
                )
                self._select_manual_boundary_row(target_row)
                InfoBar.success(
                    self.tr("合并成功"),
                    self.tr(
                        "已合并父字幕并局部重建实际分页；请检查合并后的中文。"
                        if pages_preserved
                        else "已合并父字幕；保存后刷新实际分页。"
                    ),
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
