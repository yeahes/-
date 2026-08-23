import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock, patch

from PyQt5.QtCore import QEvent, QItemSelectionModel, QPointF, Qt
from PyQt5.QtGui import QColor, QMouseEvent
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractButton,
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QTableView,
)
from qfluentwidgets import isDarkTheme

from app.core.bk_asr.asr_data import ASRData, ASRDataSeg
from app.core.entities import SubtitleConfig, SubtitleTask
from app.core.output_paths import media_result_dir, media_result_subtitle_dir
from app.core.task_factory import TaskFactory
from app.core.subtitle_processor.manual_final_subtitle_editor import (
    ManualFinalSubtitleEditError,
    ManualFinalSubtitleSession,
)
from app.core.subtitle_processor.stable_pipeline_contracts import stable_payload_hash
from app.core.subtitle_processor.review_evidence_identity import (
    build_review_source_identity,
)
from app.core.subtitle_processor.subtitle_review_marks import SubtitleReviewMark
from app.core.subtitle_processor.translation_review_suggestions import (
    current_chinese_hash,
)
from app.core.utils import podcast_learning_video
from app.thread.subtitle_thread import SubtitleThread
from app.thread.video_synthesis_thread import resolve_podcast_template_subtitle
from app.view.main_window import MainWindow
from app.view.home_interface import HomeInterface
from app.view.subtitle_interface import (
    SUBTITLE_TIME_COLUMN_WIDTH,
    SubtitleInterface,
    SubtitleTableModel,
)


class StablePublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._qt_app = QApplication.instance() or QApplication([])
        cls._qt_app.setQuitOnLastWindowClosed(False)
        cls._manual_boundary_interfaces = []

    @classmethod
    def tearDownClass(cls):
        for interface in cls._manual_boundary_interfaces:
            interface.close()
        cls._manual_boundary_interfaces.clear()
        super().tearDownClass()

    def test_manual_editor_vertical_header_uses_stable_subtitle_identity(self):
        model = SubtitleTableModel(
            {
                "1": {
                    "manual_cue_id": "S0079",
                    "display_page_id": "S0079.P02",
                },
                "2": {"manual_cue_id": "S0080"},
                "3": {},
            }
        )

        self.assertEqual(
            model.headerData(0, Qt.Vertical, Qt.DisplayRole),
            "S0079.P02",
        )
        self.assertEqual(
            model.headerData(1, Qt.Vertical, Qt.DisplayRole),
            "S0080",
        )
        self.assertEqual(model.headerData(2, Qt.Vertical, Qt.DisplayRole), "3")

    def _manual_boundary_interaction_fixture(self):
        app = self._qt_app

        class Session:
            def __init__(self):
                self.cues = [{}, {}]
                self.history = [{"kind": "existing-manual-edit"}]

            @staticmethod
            def has_display_page_model():
                return True

        interface = SubtitleInterface()
        interface.setAttribute(Qt.WA_DontShowOnScreen, True)
        interface.resize(1200, 700)
        interface.manual_final_session = Session()
        interface._manual_page_view = True
        interface.model.update_all(
            {
                "1": {
                    "start_time": 0,
                    "end_time": 1000,
                    "original_subtitle": "alpha beta gamma",
                    "translated_subtitle": "甲乙丙",
                    "display_page_view": True,
                    "display_page_id": "S0001.P01",
                    "manual_cue_id": "S0001",
                    "parent_cue_index": 0,
                    "word_start": 0,
                    "word_end": 2,
                },
                "2": {
                    "start_time": 1000,
                    "end_time": 2000,
                    "original_subtitle": "delta epsilon zeta",
                    "translated_subtitle": "丁戊己",
                    "display_page_view": True,
                    "display_page_id": "S0001.P02",
                    "manual_cue_id": "S0001",
                    "parent_cue_index": 0,
                    "word_start": 3,
                    "word_end": 5,
                },
                "3": {
                    "start_time": 2000,
                    "end_time": 3000,
                    "original_subtitle": "eta theta iota",
                    "translated_subtitle": "庚辛壬",
                    "display_page_view": True,
                    "display_page_id": "S0002.P01",
                    "manual_cue_id": "S0002",
                    "parent_cue_index": 1,
                    "word_start": 6,
                    "word_end": 8,
                },
            }
        )
        moves = []
        interface._apply_manual_display_page_boundary_move = (
            lambda *, move_to_next: moves.append(("display", move_to_next))
        )
        interface._apply_manual_boundary_move = (
            lambda left_index, word_count, **kwargs: moves.append(
                (
                    "parent",
                    left_index,
                    word_count,
                    kwargs["move_to_next"],
                )
            )
        )
        interface.show()
        app.processEvents()
        interface.subtitle_table.clearSelection()
        interface.subtitle_table.selectionModel().clearCurrentIndex()
        app.processEvents()
        self._manual_boundary_interfaces.append(interface)
        return app, interface, moves

    def _select_manual_boundary_row(self, app, interface, row):
        target = interface.model.index(row, 2)
        interface.subtitle_table.setCurrentIndex(target)
        interface.subtitle_table.selectRow(row)
        interface.on_subtitle_clicked(target)
        app.processEvents()

    def _manual_boundary_button(self, interface, row, text):
        widget = interface.subtitle_table.indexWidget(interface.model.index(row, 2))
        self.assertIsNotNone(widget, f"row {row + 1} has no inline control")
        matches = [
            button
            for button in widget.findChildren(QAbstractButton)
            if button.text() == text
        ]
        self.assertEqual(
            len(matches),
            1,
            f"row {row + 1} expected one {text!r} button",
        )
        return matches[0]

    @staticmethod
    def _manual_boundary_rich_text(interface, row):
        widget = interface.subtitle_table.indexWidget(interface.model.index(row, 2))
        if widget is None:
            return ""
        labels = [
            label
            for label in widget.findChildren(QLabel)
            if label.textFormat() == Qt.RichText
        ]
        return labels[0].text() if labels else ""

    @staticmethod
    def _manual_page_boundary_session(root: Path) -> ManualFinalSubtitleSession:
        from tests.test_manual_final_subtitle_editor import (
            _session_fixture,
            _write_json,
        )

        session, _, _ = _session_fixture(root)
        for index, word in enumerate(session.word_ledger):
            word["start_ms"] = index * 400
            word["end_ms"] = index * 400 + 300
        session.source_word_ledger_hash = stable_payload_hash(
            session._ledger_payload(session.word_ledger)
        )
        _write_json(
            session.artifact_dir / "word-ledger.json",
            {"words": session.word_ledger},
        )
        evidence_path = session.artifact_dir / "display-boundary-evidence.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["word_ledger_hash"] = session._formal_word_ledger_hash(
            session.word_ledger
        )
        _write_json(evidence_path, evidence)

        for cue in session.cues:
            cue["start_time"] = session._word_start_time(int(cue["word_start"]))
            cue["end_time"] = session._word_end_time(int(cue["word_end"]))
        session._rebuild_authoritative_cue_timeline()
        session.cues[0]["translated_subtitle"] = "系统可靠，人工可控。"

        boundary_items = dict(evidence["boundaries"])
        plans = []
        translations_by_parent = {
            "S0001": {
                "S0001.P01": "系统可靠，",
                "S0001.P02": "人工可控。",
            },
            "S0002": {"S0002.P01": "中文二"},
        }
        ranges_by_parent = {
            "S0001": [(0, 3), (4, 8)],
            "S0002": [(9, 11)],
        }
        for cue_index, cue in enumerate(session.cues):
            parent_id = str(cue["cue_id"])
            ranges = ranges_by_parent[parent_id]
            source_plan = {
                "pages": [
                    {
                        "display_page_id": f"{parent_id}.P{page_index:02d}",
                    }
                    for page_index in range(1, len(ranges) + 1)
                ]
            }
            plan = podcast_learning_video.rebuild_article_frozen_page_plan_from_word_ranges(
                session._article_render_cue(cue_index, boundary_items),
                source_plan,
                ranges,
                translations_by_parent[parent_id],
            )
            for page in plan["pages"]:
                chinese = translations_by_parent[parent_id][
                    page["display_page_id"]
                ]
                page["chinese"] = chinese
                page["zh"] = chinese
            plans.append(plan)
        _write_json(
            session.artifact_dir / "display-page-translations.json",
            {
                "status": "PASS",
                "parents": [
                    {
                        "parent_subtitle_id": "S0001",
                        "aggregate_chinese": "系统可靠，人工可控。",
                        "pages": [
                            {
                                "display_page_id": "S0001.P01",
                                "word_start": 0,
                                "word_end": 3,
                                "english": "Right. It means our",
                                "zh": "系统可靠，",
                            },
                            {
                                "display_page_id": "S0001.P02",
                                "word_start": 4,
                                "word_end": 8,
                                "english": "mental model is just completely",
                                "zh": "人工可控。",
                            },
                        ],
                    }
                ],
                "render_plans": plans,
            },
        )
        return session

    def test_interactive_home_flow_stays_in_editor_until_explicit_synthesis(self):
        created_task = SubtitleTask()
        subtitle_interface = MagicMock()
        home = SimpleNamespace(
            _last_transcribe_task=SimpleNamespace(
                article_reference_text="Article",
                article_context_data={"title": "Article"},
                use_article_reference_assist=True,
                use_article_translation_terms=True,
                source_audio_path="episode.m4a",
            ),
            subtitle_optimization_interface=subtitle_interface,
            stackedWidget=MagicMock(),
            pivot=MagicMock(),
        )
        with patch.object(
            TaskFactory,
            "create_subtitle_task",
            return_value=created_task,
        ) as create_task:
            HomeInterface.switch_to_subtitle_optimization(
                home,
                "transcript.srt",
                "episode.m4a",
            )

        self.assertTrue(
            create_task.call_args.kwargs["require_manual_review_before_synthesis"]
        )
        subtitle_interface.set_task.assert_called_once_with(created_task)
        subtitle_interface.process.assert_called_once_with()

        interface = SubtitleInterface()
        interface.setAttribute(Qt.WA_DontShowOnScreen, True)
        self._manual_boundary_interfaces.append(interface)
        emissions = []
        interface.finished.connect(lambda *args: emissions.append(args))
        interface.task = SubtitleTask(
            need_next_task=True,
            require_manual_review_before_synthesis=True,
        )
        with patch.object(
            interface,
            "_load_manual_final_session_from_output",
        ), patch.object(interface, "check_quality_report"), patch(
            "app.view.subtitle_interface.InfoBar.success"
        ):
            interface.on_subtitle_optimization_finished(
                "episode.m4a",
                "stable-final-original-top.srt",
            )
        self.assertEqual(emissions, [])

        interface.task.require_manual_review_before_synthesis = False
        with patch.object(
            interface,
            "_load_manual_final_session_from_output",
        ), patch.object(interface, "check_quality_report"), patch(
            "app.view.subtitle_interface.InfoBar.success"
        ):
            interface.on_subtitle_optimization_finished(
                "episode.m4a",
                "stable-final-original-top.srt",
            )
        self.assertEqual(
            emissions,
            [("episode.m4a", "stable-final-original-top.srt")],
        )

    def test_manual_final_package_does_not_create_or_replace_baseline_exports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session = self._manual_page_boundary_session(root / "work")
            source = root / "episode.m4a"
            source.write_bytes(b"audio")

            paths = session.save_to_source_folder(source_media_path=source)
            result_dir = media_result_dir(source)

            self.assertEqual(Path(paths["manifest_path"]).parent.parent, result_dir)
            self.assertEqual(paths["source_bilingual_original_top_srt"], "")
            self.assertEqual(paths["source_display_page_srt_path"], "")

    def test_subtitle_table_keeps_time_columns_compact_without_page_status_column(self):
        class Header:
            def __init__(self):
                self.default_mode = None
                self.section_modes = {}

            def setSectionResizeMode(self, *args):
                if len(args) == 1:
                    self.default_mode = args[0]
                else:
                    self.section_modes[args[0]] = args[1]

        class Table:
            def __init__(self):
                self.header = Header()
                self.widths = {}

            def horizontalHeader(self):
                return self.header

            def setColumnWidth(self, column, width):
                self.widths[column] = width

        table = Table()
        interface = SimpleNamespace(
            subtitle_table=table,
            model=SimpleNamespace(columnCount=lambda: 4),
        )

        SubtitleInterface._apply_subtitle_table_column_layout(interface)

        self.assertEqual(table.header.default_mode, QHeaderView.Stretch)
        self.assertEqual(
            table.header.section_modes,
            {0: QHeaderView.Fixed, 1: QHeaderView.Fixed},
        )
        self.assertEqual(
            table.widths,
            {
                0: SUBTITLE_TIME_COLUMN_WIDTH,
                1: SUBTITLE_TIME_COLUMN_WIDTH,
            },
        )

        model = SubtitleTableModel(
            {
                "1": {
                    "start_time": 0,
                    "end_time": 1000,
                    "original_subtitle": "English",
                    "translated_subtitle": "中文",
                    "display_page_id": "S0001.P01",
                    "display_page_view": True,
                }
            }
        )
        self.assertEqual(model.columnCount(), 4)
        self.assertTrue(model.flags(model.index(0, 2)) & Qt.ItemIsEditable)
        self.assertTrue(model.flags(model.index(0, 3)) & Qt.ItemIsEditable)

        stale_model = SubtitleTableModel(
            {
                "1": {
                    "start_time": 0,
                    "end_time": 1000,
                    "original_subtitle": "English",
                    "translated_subtitle": "旧分页中文",
                    "manual_cue_id": "S0001",
                    "display_page_id": "S0001.P01",
                    "display_page_view": True,
                    "display_page_chinese_stale": True,
                    "display_page_chinese_confirmed": False,
                }
            }
        )
        self.assertTrue(
            stale_model.setData(
                stale_model.index(0, 3),
                "旧分页中文",
                Qt.EditRole,
            )
        )
        self.assertTrue(
            stale_model._data["1"]["display_page_chinese_confirmed"]
        )

    def test_subtitle_table_copies_selected_english_without_mutating_rows(self):
        interface = SubtitleInterface()
        try:
            interface.model.update_all(
                {
                    "1": {
                        "start_time": 0,
                        "end_time": 1000,
                        "original_subtitle": "First English page.",
                        "translated_subtitle": "第一页。",
                    },
                    "2": {
                        "start_time": 1000,
                        "end_time": 2000,
                        "original_subtitle": "Second English page.",
                        "translated_subtitle": "第二页。",
                    },
                }
            )
            before = json.loads(json.dumps(interface.model._data, ensure_ascii=False))
            selection = interface.subtitle_table.selectionModel()
            selection.select(
                interface.model.index(1, 0),
                QItemSelectionModel.Select | QItemSelectionModel.Rows,
            )
            selection.select(
                interface.model.index(0, 0),
                QItemSelectionModel.Select | QItemSelectionModel.Rows,
            )
            clipboard = MagicMock()

            with patch.object(QApplication, "clipboard", return_value=clipboard):
                copied = interface.copy_selected_english()

            self.assertEqual(
                copied,
                "First English page.\nSecond English page.",
            )
            clipboard.setText.assert_called_once_with(copied)
            self.assertEqual(interface.model._data, before)
            self.assertEqual(
                interface.subtitle_table.selectionBehavior(),
                QAbstractItemView.SelectRows,
            )
            self.assertEqual(
                interface.subtitle_table.selectionMode(),
                QAbstractItemView.ExtendedSelection,
            )
        finally:
            interface.close()

    def test_review_mark_roles_do_not_invalidate_saved_manual_package(self):
        class Toggle:
            def __init__(self):
                self.enabled = True
                self.visible = True

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setVisible(self, value):
                self.visible = bool(value)

        def make_interface():
            class TableToggle:
                def setEnabled(self, _value):
                    pass

            model = SubtitleTableModel(
                {
                    "1": {
                        "subtitle_id": "S0001",
                        "start_time": 0,
                        "end_time": 1000,
                        "original_subtitle": "English",
                        "translated_subtitle": "中文",
                        "display_pages": [],
                    }
                }
            )
            interface = SimpleNamespace(
                model=model,
                manual_final_session=SimpleNamespace(display_page_edits=[]),
                _manual_page_view=True,
                _manual_parent_boundaries_dirty=False,
                _manual_package_manifest_path="saved-manual-manifest.json",
                _manual_save_request_id=0,
                _manual_save_in_progress=False,
                subtitle_table=TableToggle(),
                manual_final_undo_action=Toggle(),
                manual_final_synthesis_action=Toggle(),
                manual_draft_synthesis_action=Toggle(),
                tr=lambda value: value,
                _refresh_manual_boundary_inspector=lambda: None,
                _invalidate_manual_review_marks_for_parent_ids=lambda _ids: None,
            )
            interface._invalidate_manual_final_save = MethodType(
                SubtitleInterface._invalidate_manual_final_save,
                interface,
            )
            interface._mark_manual_final_dirty = MethodType(
                SubtitleInterface._mark_manual_final_dirty,
                interface,
            )
            model.dataChanged.connect(
                lambda top_left, bottom_right, roles: (
                    SubtitleInterface._on_manual_table_data_changed(
                        interface,
                        top_left,
                        bottom_right,
                        roles,
                    )
                )
            )
            return interface

        review_interface = make_interface()
        review_interface.model.set_review_marks({"S0001": []})

        self.assertEqual(
            review_interface._manual_package_manifest_path,
            "saved-manual-manifest.json",
        )
        self.assertTrue(review_interface.manual_final_synthesis_action.enabled)
        self.assertTrue(review_interface.manual_final_synthesis_action.visible)
        self.assertTrue(review_interface.manual_draft_synthesis_action.enabled)
        self.assertTrue(review_interface.manual_draft_synthesis_action.visible)

        for column, value in ((2, "Edited English"), (3, "修改后的中文")):
            edit_interface = make_interface()

            self.assertTrue(
                edit_interface.model.setData(
                    edit_interface.model.index(0, column),
                    value,
                    Qt.EditRole,
                )
            )
            self.assertEqual(edit_interface._manual_package_manifest_path, "")
            self.assertFalse(edit_interface.manual_final_synthesis_action.enabled)
            self.assertTrue(edit_interface.manual_final_synthesis_action.visible)
            self.assertFalse(edit_interface.manual_draft_synthesis_action.enabled)
            self.assertTrue(edit_interface.manual_draft_synthesis_action.visible)

    def test_manual_synthesis_actions_stay_visible_and_follow_saved_state(self):
        class Session:
            subtitle_path = Path("saved.srt")
            history = []

            @staticmethod
            def has_display_page_model():
                return True

            @staticmethod
            def state_fingerprint():
                return "saved-state"

            @staticmethod
            def to_model_data(*, prefer_display_pages=False):
                return {
                    "1": {
                        "start_time": 0,
                        "end_time": 1000,
                        "original_subtitle": "English",
                        "translated_subtitle": "中文",
                        "display_page_view": bool(prefer_display_pages),
                        "display_page_id": (
                            "S0001.P01" if prefer_display_pages else ""
                        ),
                        "manual_cue_id": "S0001",
                        "parent_cue_index": 0,
                        "word_start": 0,
                        "word_end": 0,
                    }
                }

        interface = SubtitleInterface()
        interface.setAttribute(Qt.WA_DontShowOnScreen, True)
        interface.manual_final_session = Session()
        interface._load_manual_final_review_marks = lambda _session: None
        interface._refresh_manual_boundary_inspector = lambda *args: None
        self.addCleanup(
            lambda: (interface.close(), self._qt_app.processEvents())
        )

        for page_view in (False, True):
            interface._manual_page_view = page_view
            interface._manual_parent_boundaries_dirty = False
            interface._apply_manual_final_session()
            self.assertTrue(interface.manual_final_synthesis_action.isVisible())
            self.assertTrue(interface.manual_draft_synthesis_action.isVisible())

        interface.manual_final_synthesis_action.setEnabled(True)
        interface.manual_draft_synthesis_action.setEnabled(True)
        interface._manual_package_manifest_path = "saved-manifest.json"
        interface._mark_manual_final_dirty()
        self.assertTrue(interface.manual_final_synthesis_action.isVisible())
        self.assertFalse(interface.manual_final_synthesis_action.isEnabled())
        self.assertEqual(
            interface.manual_final_synthesis_action.toolTip(),
            "当前编辑尚未保存",
        )
        self.assertTrue(interface.manual_draft_synthesis_action.isVisible())
        self.assertFalse(interface.manual_draft_synthesis_action.isEnabled())
        self.assertEqual(
            interface.manual_draft_synthesis_action.toolTip(),
            "当前编辑尚未保存",
        )

        cases = (
            (
                {
                    "render_blocked": False,
                    "render_block_reason": "",
                    "manual_draft_ready": False,
                    "display_page_review_summary": {},
                },
                True,
                False,
            ),
            (
                {
                    "render_blocked": True,
                    "render_block_reason": "manual_page_translation_required",
                    "manual_draft_ready": True,
                    "display_page_review_summary": {
                        "unconfirmed_chinese_count": 1,
                        "unconfirmed_chinese_pages": ["S0001.P01"],
                    },
                },
                False,
                True,
            ),
            (
                {
                    "render_blocked": True,
                    "render_block_reason": "final_timeline_invalid",
                    "manual_draft_ready": False,
                    "display_page_review_summary": {
                        "hard_page_count": 1,
                        "hard_pages": ["S0003.P02"],
                    },
                },
                False,
                False,
            ),
        )
        for index, (state, final_enabled, draft_enabled) in enumerate(cases, 1):
            paths = {"manifest_path": f"saved-{index}.json", **state}
            interface._manual_save_request_id = index
            interface._manual_save_in_progress = True
            interface._manual_active_save_context = None
            interface._manual_refresh_requested = False
            interface._manual_pending_page_split = None
            with patch.object(
                ManualFinalSubtitleSession,
                "load_from_manifest",
                return_value=Session(),
            ), patch("app.view.subtitle_interface.InfoBar.success"), patch(
                "app.view.subtitle_interface.InfoBar.warning"
            ) as warning:
                interface._apply_manual_final_save_result(index, paths, "")

            self.assertTrue(interface.manual_final_synthesis_action.isVisible())
            self.assertEqual(
                interface.manual_final_synthesis_action.isEnabled(),
                final_enabled,
            )
            self.assertTrue(interface.manual_draft_synthesis_action.isVisible())
            self.assertEqual(
                interface.manual_draft_synthesis_action.isEnabled(),
                draft_enabled,
            )
            if state["render_block_reason"] == "final_timeline_invalid":
                self.assertIn("最终字幕时间轴未通过检查", interface.status_label.text())
                self.assertNotIn("final_timeline_invalid", interface.status_label.text())
                warning_text = str(warning.call_args.args[1])
                self.assertIn("最终字幕时间轴未通过检查", warning_text)
                self.assertNotIn("final_timeline_invalid", warning_text)
                self.assertIn("S0003.P02", warning_text)

    def test_manual_blocker_summary_prefers_actionable_page_and_focuses_it(self):
        interface = SubtitleInterface()
        interface.setAttribute(Qt.WA_DontShowOnScreen, True)
        interface.manual_final_session = SimpleNamespace(
            history=[],
            has_display_page_model=lambda: True,
            to_model_data=lambda *, prefer_display_pages=False: {
                "1": {
                    "start_time": 0,
                    "end_time": 1000,
                    "original_subtitle": "First page",
                    "translated_subtitle": "第一页",
                    "display_page_view": bool(prefer_display_pages),
                    "display_page_id": "S0003.P01" if prefer_display_pages else "",
                    "manual_cue_id": "S0003",
                    "parent_cue_index": 0,
                    "word_start": 0,
                    "word_end": 1,
                },
                "2": {
                    "start_time": 1000,
                    "end_time": 2000,
                    "original_subtitle": "Second page",
                    "translated_subtitle": "",
                    "display_page_view": bool(prefer_display_pages),
                    "display_page_id": "S0003.P02" if prefer_display_pages else "",
                    "manual_cue_id": "S0003",
                    "parent_cue_index": 0,
                    "word_start": 2,
                    "word_end": 3,
                },
            },
        )
        interface._manual_page_view = False
        interface._manual_parent_boundaries_dirty = False
        interface._load_manual_final_review_marks = lambda _session: None
        interface._refresh_manual_boundary_inspector = lambda *args: None
        self.addCleanup(
            lambda: (interface.close(), self._qt_app.processEvents())
        )

        summary = SubtitleInterface._manual_publication_issue_summary(
            "manual_page_translation_required",
            {
                "unconfirmed_chinese_count": 1,
                "unconfirmed_chinese_pages": ["S0003.P02"],
                "boundary_review_count": 1,
                "boundary_review_pages": ["S0004.P01"],
                "hard_page_count": 0,
                "hard_pages": [],
            },
        )
        focused = interface._focus_manual_problem_position(summary["first_position"])

        self.assertEqual(summary["positions"], ["S0003.P02", "S0004.P01"])
        self.assertIn("S0003.P02", summary["message"])
        self.assertTrue(focused)
        self.assertTrue(interface._manual_page_view)
        self.assertEqual(interface.subtitle_table.currentIndex().row(), 1)

    def test_failed_manual_save_keeps_edits_and_focuses_actionable_page(self):
        interface = SubtitleInterface()
        interface.setAttribute(Qt.WA_DontShowOnScreen, True)
        interface.manual_final_session = SimpleNamespace(
            history=[],
            has_display_page_model=lambda: True,
            display_page_review_summary=lambda: {
                "unconfirmed_chinese_count": 1,
                "unconfirmed_chinese_pages": ["S0003.P02"],
            },
        )
        interface._manual_save_request_id = 7
        interface._manual_save_in_progress = True
        interface._manual_active_save_context = None
        interface._manual_refresh_requested = False
        interface._manual_pending_page_split = None
        focused = []
        interface._focus_manual_problem_position = lambda value: (
            focused.append(value) or True
        )
        self.addCleanup(
            lambda: (interface.close(), self._qt_app.processEvents())
        )

        with patch("app.view.subtitle_interface.InfoBar.warning") as warning:
            interface._apply_manual_final_save_result(
                7,
                {},
                "manual_page_translation_required",
            )

        self.assertEqual(focused, ["S0003.P02"])
        self.assertIn("S0003.P02", interface.status_label.text())
        self.assertIn("当前编辑仍保留", warning.call_args.args[0])
        self.assertIn("已定位到第一处问题", warning.call_args.args[1])

    def test_manual_save_preflight_error_uses_same_actionable_location(self):
        interface = SubtitleInterface()
        interface.setAttribute(Qt.WA_DontShowOnScreen, True)
        interface.manual_final_session = SimpleNamespace(
            display_page_review_summary=lambda: {
                "hard_page_count": 1,
                "hard_pages": ["S0012.P01"],
            },
        )
        interface._sync_manual_final_text_edits = MagicMock(
            side_effect=ManualFinalSubtitleEditError(
                "render_structural_overflow"
            )
        )
        focused = []
        interface._focus_manual_problem_position = lambda value: (
            focused.append(value) or True
        )
        self.addCleanup(
            lambda: (interface.close(), self._qt_app.processEvents())
        )

        with patch("app.view.subtitle_interface.InfoBar.warning") as warning:
            request_id = interface.save_manual_final_output()

        self.assertIsNone(request_id)
        self.assertEqual(focused, ["S0012.P01"])
        self.assertIn("S0012.P01", interface.status_label.text())
        self.assertIn("已定位到第一处问题", warning.call_args.args[1])

    def test_blocked_synthesis_entry_focuses_manifest_problem_position(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "stable-final-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "render_blocked": True,
                        "render_block_reason": "manual_page_translation_invalid",
                        "display_page_review_summary": {
                            "unconfirmed_chinese_count": 1,
                            "unconfirmed_chinese_pages": ["S0008.P02"],
                        },
                        "manual_final_override": {
                            "schema_version": 2,
                            "render_block_reason": "manual_page_translation_invalid",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            interface = SubtitleInterface()
            interface.setAttribute(Qt.WA_DontShowOnScreen, True)
            interface.manual_final_session = SimpleNamespace(
                manifest_path=manifest_path,
                state_fingerprint=lambda: "saved-state",
            )
            interface._manual_parent_boundaries_dirty = False
            interface._manual_package_manifest_path = str(manifest_path)
            interface._set_manual_clean_checkpoint()
            focused = []
            interface._focus_manual_problem_position = lambda value: (
                focused.append(value) or True
            )
            self.addCleanup(
                lambda: (interface.close(), self._qt_app.processEvents())
            )

            with patch(
                "app.view.subtitle_interface.resolve_synthesis_package_inputs",
                side_effect=RuntimeError("manual_page_translation_invalid"),
            ), patch("app.view.subtitle_interface.InfoBar.warning") as warning:
                interface.open_manual_final_in_synthesis()

            self.assertEqual(focused, ["S0008.P02"])
            self.assertIn("S0008.P02", warning.call_args.args[1])
            self.assertIn("已定位到第一处问题", warning.call_args.args[1])

    def test_manual_translation_review_action_tracks_queue_artifact(self):
        class Session:
            history = []

            def __init__(self, artifact_dir: Path | None = None):
                if artifact_dir is not None:
                    self.artifact_dir = artifact_dir

            @staticmethod
            def has_display_page_model():
                return True

            @staticmethod
            def to_model_data(*, prefer_display_pages=False):
                return {
                    "1": {
                        "start_time": 0,
                        "end_time": 1000,
                        "original_subtitle": "English",
                        "translated_subtitle": "中文",
                        "display_page_view": bool(prefer_display_pages),
                        "display_page_id": (
                            "S0001.P01" if prefer_display_pages else ""
                        ),
                        "manual_cue_id": "S0001",
                        "parent_cue_index": 0,
                        "word_start": 0,
                        "word_end": 0,
                    }
                }

        interface = SubtitleInterface()
        interface.setAttribute(Qt.WA_DontShowOnScreen, True)
        interface._refresh_manual_boundary_inspector = lambda *args: None
        interface._manual_page_view = True
        interface._manual_parent_boundaries_dirty = False
        self.addCleanup(
            lambda: (interface.close(), self._qt_app.processEvents())
        )

        interface.manual_final_session = Session()
        interface._apply_manual_final_session()
        self.assertFalse(interface.manual_translation_review_action.isVisible())

        with tempfile.TemporaryDirectory() as temp_dir:
            artifact_dir = Path(temp_dir)
            word_ledger = {"hash": "queue-ledger", "words": []}
            subtitle_spans = [
                {
                    "subtitle_id": "S0001",
                    "original": "English",
                    "word_start": 0,
                    "word_end": 0,
                }
            ]
            (artifact_dir / "word-ledger.json").write_text(
                json.dumps(word_ledger),
                encoding="utf-8",
            )
            (artifact_dir / "subtitle-spans.json").write_text(
                json.dumps(subtitle_spans),
                encoding="utf-8",
            )
            (artifact_dir / "semantic-review-queue.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "source_run": build_review_source_identity(
                            word_ledger,
                            subtitle_spans,
                        ),
                        "items": [],
                    }
                ),
                encoding="utf-8",
            )
            interface.manual_final_session = Session(artifact_dir)
            interface._apply_manual_final_session()
            self.assertTrue(interface.manual_translation_review_action.isVisible())
            self.assertTrue(interface.manual_translation_review_action.isEnabled())

            subtitle_spans[0]["original"] = "Different English"
            (artifact_dir / "subtitle-spans.json").write_text(
                json.dumps(subtitle_spans),
                encoding="utf-8",
            )
            interface._apply_manual_final_session()
            self.assertFalse(interface.manual_translation_review_action.isVisible())
            self.assertFalse(interface.manual_translation_review_action.isEnabled())

    def test_fixed_id_translation_suggestion_rejects_an_active_new_chinese_edit(self):
        captured = {}
        model = SubtitleTableModel(
            {
                "1": {
                    "manual_cue_id": "S0001",
                    "subtitle_id": "S0001",
                    "start_time": 100,
                    "end_time": 900,
                    "word_start": 3,
                    "word_end": 7,
                    "original_subtitle": "The old sentence.",
                    "translated_subtitle": "旧译文",
                    "display_page_view": False,
                },
                "2": {
                    "manual_cue_id": "S0002",
                    "subtitle_id": "S0002",
                    "start_time": 1000,
                    "end_time": 1800,
                    "word_start": 8,
                    "word_end": 11,
                    "original_subtitle": "The untouched sentence.",
                    "translated_subtitle": "未改译文",
                    "display_page_view": False,
                },
            }
        )

        class Session:
            @staticmethod
            def apply_parent_model_data(_rows):
                captured["applied"] = True

        interface = SimpleNamespace(
            model=model,
            manual_final_session=Session(),
            _manual_page_view=False,
            _sync_manual_final_text_edits=lambda **_kwargs: model._data["1"].__setitem__(
                "translated_subtitle", "用户刚输入的新译文"
            ),
            _mark_manual_final_dirty=lambda **_kwargs: captured.setdefault("dirty", True),
            _apply_manual_final_session=lambda: captured.setdefault("refreshed", True),
        )

        with self.assertRaisesRegex(
            ManualFinalSubtitleEditError,
            "suggestion_current_chinese_mismatch",
        ):
            SubtitleInterface._apply_fixed_id_translation_suggestions(
                interface,
                [
                    {
                        "subtitle_id": "S0001",
                        "source_english": "The old sentence.",
                        "current_chinese_hash": current_chinese_hash("旧译文"),
                        "suggested_chinese": "旧建议",
                    }
                ],
            )

        self.assertNotIn("applied", captured)
        self.assertEqual(
            model._data["1"]["translated_subtitle"],
            "用户刚输入的新译文",
        )
        self.assertEqual(model._data["2"]["translated_subtitle"], "未改译文")

    def test_reset_manual_editor_invalidates_translation_review_worker(self):
        class Toggle:
            def setEnabled(self, _value):
                pass

            def setVisible(self, _value):
                pass

        model = SubtitleTableModel({})
        interface = SimpleNamespace(
            model=model,
            manual_final_session=SimpleNamespace(),
            _manual_save_in_progress=False,
            _translation_review_suggestion_request_id=7,
            _translation_review_suggestion_in_progress=True,
            _translation_review_suggestion_context={"request_id": 7},
            _manual_draft_request_id=0,
            _review_mark_request_id=0,
            _invalidate_manual_final_save=lambda: None,
            _disarm_manual_boundary_editor=lambda **_kwargs: None,
            _set_manual_editor_mode=lambda _value: None,
        )
        for name in (
            "next_review_action",
            "manual_page_view_action",
            "manual_final_save_action",
            "manual_final_undo_action",
            "manual_final_synthesis_action",
            "manual_draft_synthesis_action",
            "manual_translation_review_action",
        ):
            setattr(interface, name, Toggle())

        SubtitleInterface._reset_manual_editor_state(interface)

        self.assertEqual(interface._translation_review_suggestion_request_id, 8)
        self.assertFalse(interface._translation_review_suggestion_in_progress)
        self.assertIsNone(interface._translation_review_suggestion_context)

    def test_translation_review_result_merges_only_the_unchanged_queue_item(self):
        class Label:
            def __init__(self):
                self.value = ""

            def setText(self, value):
                self.value = str(value)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            queue_path = root / "semantic-review-queue.json"
            target = {
                "code": "translation_fluency_review",
                "subtitle_ids": ["S0001"],
                "reason": "翻译腔",
                "details": {},
            }
            other = {
                "code": "semantic_translation_review",
                "subtitle_ids": ["S0002"],
                "reason": "语义复核",
                "details": {"kept": True},
            }
            payload = {"schema_version": 1, "items": [target, other]}
            queue_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            key = SubtitleInterface._translation_review_queue_item_key(target)
            snapshot = SubtitleInterface._translation_review_queue_item_snapshot(target)
            status = Label()
            interface = SimpleNamespace(
                manual_final_session=SimpleNamespace(artifact_dir=root),
                _translation_review_suggestion_context={
                    "request_id": 3,
                    "artifact_dir": str(root.resolve()),
                    "queue_path": str(queue_path.resolve()),
                    "queue_item_key": key,
                    "queue_item_snapshot": snapshot,
                    "session_fingerprint": "same-state",
                },
                _translation_review_suggestion_in_progress=True,
                _manual_state_fingerprint=lambda: "same-state",
                _translation_review_queue_item_key=(
                    SubtitleInterface._translation_review_queue_item_key
                ),
                _translation_review_queue_item_snapshot=(
                    SubtitleInterface._translation_review_queue_item_snapshot
                ),
                status_label=status,
                tr=lambda value: value,
            )
            suggestion = {
                "subtitle_id": "S0001",
                "source_english": "English.",
                "current_chinese_hash": current_chinese_hash("旧译文"),
                "suggested_chinese": "新译文",
            }
            with patch("app.view.subtitle_interface.InfoBar.success"):
                SubtitleInterface._apply_generated_translation_review_suggestions(
                    interface,
                    {"request_id": 3, "suggestions": [suggestion]},
                    "",
                )

            stored = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(
                stored["items"][0]["details"]["suggestions"], [suggestion]
            )
            self.assertEqual(stored["items"][1], other)
            self.assertFalse(interface._translation_review_suggestion_in_progress)

    def test_translation_review_result_does_not_overwrite_a_changed_queue_item(self):
        class Label:
            def __init__(self):
                self.value = ""

            def setText(self, value):
                self.value = str(value)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            queue_path = root / "semantic-review-queue.json"
            original = {
                "code": "translation_fluency_review",
                "subtitle_ids": ["S0001"],
                "reason": "旧原因",
                "details": {},
            }
            changed = {**original, "reason": "后台期间重新生成的新原因"}
            queue_path.write_text(
                json.dumps({"items": [changed]}, ensure_ascii=False),
                encoding="utf-8",
            )
            status = Label()
            interface = SimpleNamespace(
                manual_final_session=SimpleNamespace(artifact_dir=root),
                _translation_review_suggestion_context={
                    "request_id": 4,
                    "artifact_dir": str(root.resolve()),
                    "queue_path": str(queue_path.resolve()),
                    "queue_item_key": SubtitleInterface._translation_review_queue_item_key(original),
                    "queue_item_snapshot": SubtitleInterface._translation_review_queue_item_snapshot(original),
                    "session_fingerprint": "same-state",
                },
                _translation_review_suggestion_in_progress=True,
                _manual_state_fingerprint=lambda: "same-state",
                _translation_review_queue_item_key=(
                    SubtitleInterface._translation_review_queue_item_key
                ),
                _translation_review_queue_item_snapshot=(
                    SubtitleInterface._translation_review_queue_item_snapshot
                ),
                status_label=status,
                tr=lambda value: value,
            )

            SubtitleInterface._apply_generated_translation_review_suggestions(
                interface,
                {
                    "request_id": 4,
                    "suggestions": [
                        {
                            "subtitle_id": "S0001",
                            "suggested_chinese": "不应写入",
                        }
                    ],
                },
                "",
            )

            stored = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(stored, {"items": [changed]})
            self.assertIn("队列已变化", status.value)

    def test_restore_saved_blocked_package_requires_valid_draft_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "stable-final-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "render_blocked": True,
                        "validation_error_codes": [
                            "manual_page_translation_required"
                        ],
                        "manual_final_override": {
                            "schema_version": 2,
                            "render_block_reason": (
                                "manual_page_translation_required"
                            ),
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            interface = SubtitleInterface()
            interface.setAttribute(Qt.WA_DontShowOnScreen, True)
            interface.manual_final_session = SimpleNamespace(
                manifest_path=manifest_path
            )
            interface._manual_parent_boundaries_dirty = False
            interface._manual_package_manifest_path = ""
            interface.manual_final_synthesis_action.setEnabled(False)
            interface.manual_draft_synthesis_action.setEnabled(False)
            self.addCleanup(
                lambda: (interface.close(), self._qt_app.processEvents())
            )

            interface._restore_saved_manual_package_actions()

            self.assertEqual(interface._manual_package_manifest_path, "")
            self.assertFalse(interface.manual_final_synthesis_action.isEnabled())
            self.assertFalse(interface.manual_draft_synthesis_action.isEnabled())

    def test_open_manual_final_synthesis_recovers_clean_session_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "stable-final-manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            interface = SubtitleInterface()
            interface.setAttribute(Qt.WA_DontShowOnScreen, True)
            interface.manual_final_session = SimpleNamespace(
                manifest_path=manifest_path,
                source_media_path=None,
                state_fingerprint=lambda: "saved-state",
            )
            interface.task = None
            interface._manual_parent_boundaries_dirty = False
            interface._manual_package_manifest_path = ""
            interface._set_manual_clean_checkpoint()
            emitted = []
            interface.manual_final_ready.connect(
                lambda media, manifest: emitted.append((media, manifest))
            )
            self.addCleanup(
                lambda: (interface.close(), self._qt_app.processEvents())
            )

            with patch(
                "app.view.subtitle_interface.resolve_synthesis_package_inputs",
                return_value=("audio.m4a", str(manifest_path)),
            ) as resolver:
                interface.open_manual_final_in_synthesis()

            self.assertEqual(
                interface._manual_package_manifest_path,
                str(manifest_path),
            )
            self.assertEqual(emitted, [("audio.m4a", str(manifest_path))])
            resolver.assert_called_once_with(manifest_path)

    def test_open_manual_final_synthesis_does_not_reuse_manifest_with_unsaved_edits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "stable-final-manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            fingerprint = {"value": "saved-state"}
            interface = SubtitleInterface()
            interface.setAttribute(Qt.WA_DontShowOnScreen, True)
            interface.manual_final_session = SimpleNamespace(
                manifest_path=manifest_path,
                source_media_path=None,
                state_fingerprint=lambda: fingerprint["value"],
            )
            interface.task = None
            interface._manual_parent_boundaries_dirty = False
            interface._manual_package_manifest_path = str(manifest_path)
            interface._set_manual_clean_checkpoint()
            fingerprint["value"] = "edited-state"
            emitted = []
            interface.manual_final_ready.connect(
                lambda media, manifest: emitted.append((media, manifest))
            )
            def close_interface():
                fingerprint["value"] = "saved-state"
                interface._set_manual_clean_checkpoint()
                interface.close()
                self._qt_app.processEvents()

            self.addCleanup(close_interface)

            with patch(
                "app.view.subtitle_interface.resolve_synthesis_package_inputs"
            ) as resolver, patch("app.view.subtitle_interface.InfoBar.warning"):
                interface.open_manual_final_in_synthesis()

            self.assertEqual(emitted, [])
            resolver.assert_not_called()

    def test_async_review_marks_do_not_restore_invalidated_edited_ids(self):
        class Toggle:
            def __init__(self):
                self.enabled = False
                self.visible = False

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setVisible(self, value):
                self.visible = bool(value)

        def mark(subtitle_id, code):
            return SubtitleReviewMark(
                subtitle_id=subtitle_id,
                severity="REVIEW",
                category="chinese_allocation",
                target="chinese",
                code=code,
                reason=f"review {subtitle_id}",
            )

        stale_first = mark("S0001", "stale_first")
        current_second = mark("S0002", "current_second")
        model = SubtitleTableModel(
            {
                "1": {
                    "subtitle_id": "S0001",
                    "source_subtitle_ids": ["S0001"],
                    "start_time": 0,
                    "end_time": 1000,
                    "original_subtitle": "First",
                    "translated_subtitle": "第一条",
                },
                "2": {
                    "subtitle_id": "S0002",
                    "source_subtitle_ids": ["S0002"],
                    "start_time": 1000,
                    "end_time": 2000,
                    "original_subtitle": "Second",
                    "translated_subtitle": "第二条",
                },
            }
        )
        model.set_review_marks(
            {"S0001": [stale_first], "S0002": [current_second]}
        )
        interface = SimpleNamespace(
            model=model,
            manual_final_session=object(),
            _review_mark_request_id=9,
            _manual_review_invalidated_ids=set(),
            _manual_save_in_progress=False,
            _manual_has_unsaved_changes=True,
            _review_mark_rows=[],
            _manual_review_mark_count=0,
            next_review_action=Toggle(),
            status_label=SimpleNamespace(setText=lambda _value: None),
            tr=lambda value: value,
        )
        interface._rows_with_review_marks = MethodType(
            SubtitleInterface._rows_with_review_marks,
            interface,
        )
        interface._refresh_manual_review_rows = MethodType(
            SubtitleInterface._refresh_manual_review_rows,
            interface,
        )

        SubtitleInterface._invalidate_manual_review_marks_for_parent_ids(
            interface,
            ["S0001"],
        )
        SubtitleInterface._apply_loaded_manual_review_marks(
            interface,
            9,
            {"S0001": [stale_first], "S0002": [current_second]},
            "",
        )

        self.assertEqual(interface._manual_review_invalidated_ids, {"S0001"})
        self.assertNotIn("S0001", model._review_marks_by_subtitle_id)
        self.assertEqual(
            model._review_marks_by_subtitle_id,
            {"S0002": [current_second]},
        )
        self.assertEqual(interface._review_mark_rows, [1])
        self.assertEqual(interface._manual_review_mark_count, 1)
        self.assertTrue(interface.next_review_action.enabled)
        self.assertTrue(interface.next_review_action.visible)

    def test_dynamic_page_risks_are_included_in_next_review_queue(self):
        class Toggle:
            def __init__(self):
                self.enabled = False
                self.visible = False

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setVisible(self, value):
                self.visible = bool(value)

        model = SubtitleTableModel(
            {
                "1": {
                    "manual_cue_id": "S0001",
                    "start_time": 0,
                    "end_time": 1000,
                    "original_subtitle": "Unavailable page",
                    "translated_subtitle": "分页不可用",
                    "display_page_unavailable": True,
                },
                "2": {
                    "manual_cue_id": "S0002",
                    "start_time": 1000,
                    "end_time": 2000,
                    "original_subtitle": "Review page",
                    "translated_subtitle": "分页待复查",
                    "display_page_review_required": True,
                    "display_page_boundary_classification": "review",
                    "display_page_issue_codes": ["grammar_boundary_review"],
                },
                "3": {
                    "manual_cue_id": "S0003",
                    "start_time": 2000,
                    "end_time": 3000,
                    "original_subtitle": "Clean page",
                    "translated_subtitle": "正常分页",
                },
                "4": {
                    "manual_cue_id": "S0004",
                    "start_time": 3000,
                    "end_time": 4000,
                    "original_subtitle": "Local proposal",
                    "translated_subtitle": "本地建议稿",
                    "display_page_chinese_stale": True,
                    "display_page_chinese_confirmed": False,
                    "display_page_chinese_draft_kind": (
                        "local_parent_split_proposal"
                    ),
                },
            }
        )
        interface = SimpleNamespace(
            model=model,
            _review_mark_rows=[],
            _manual_review_mark_count=0,
            next_review_action=Toggle(),
        )
        interface._rows_with_review_marks = MethodType(
            SubtitleInterface._rows_with_review_marks,
            interface,
        )

        SubtitleInterface._refresh_manual_review_rows(interface)

        unavailable_marks = model._marks_for_segment(model._data["1"])
        review_marks = model._marks_for_segment(model._data["2"])
        proposal_marks = model._marks_for_segment(model._data["4"])
        self.assertEqual(interface._review_mark_rows, [0, 1, 3])
        self.assertEqual(interface._manual_review_mark_count, 3)
        self.assertTrue(interface.next_review_action.enabled)
        self.assertTrue(interface.next_review_action.visible)
        self.assertEqual(
            [(item.code, item.severity) for item in unavailable_marks],
            [("display_page_unavailable", "BLOCKER")],
        )
        self.assertEqual(
            [(item.code, item.severity) for item in review_marks],
            [("grammar_boundary_review", "REVIEW")],
        )
        self.assertEqual(
            [(item.code, item.severity) for item in proposal_marks],
            [("local_parent_split_proposal", "REVIEW")],
        )
        self.assertIn("本地建议稿", proposal_marks[0].reason)

    @staticmethod
    def _thread(root: Path) -> SubtitleThread:
        thread = SubtitleThread.__new__(SubtitleThread)
        thread.task = SubtitleTask(
            subtitle_path=str(root / "source.srt"),
            output_path=str(root / "output.srt"),
        )
        return thread

    @staticmethod
    def _config() -> SubtitleConfig:
        return SubtitleConfig(
            need_screen_subtitle_edit=True,
            screen_subtitle_stable_mode=True,
            subtitle_layout="original_top",
        )

    @staticmethod
    def _data(text: str = "English line.") -> ASRData:
        segment = ASRDataSeg(text, 0, 1000, "中文行。")
        segment.subtitle_id = "S0001"
        return ASRData([segment])

    def test_success_publishes_immutable_hashed_run_and_snapshots_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "source-coverage-report.txt"
            report.write_text("PASS", encoding="utf-8")
            artifact_dir = root / "source-artifacts"
            artifact_dir.mkdir()
            timeline = artifact_dir / "final-cue-timeline.json"
            timeline.write_text('{"validation":{"status":"PASS"}}', encoding="utf-8")
            (artifact_dir / "word-ledger.json").write_text(
                '{"words":[{"surface":"English","start_ms":0,"end_ms":1000}]}',
                encoding="utf-8",
            )

            thread = self._thread(root)
            thread._save_stable_subtitle_outputs(
                self._data(),
                self._config(),
                coverage_report_path=str(report),
                validation_status="passed",
                manifest_meta={"final_cue_timeline_path": str(timeline)},
            )

            manifest_path = root / "stable-final-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            stable_path = Path(manifest["paths"]["original_top_srt"])
            run_dir = Path(manifest["stable_run_dir"])
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(stable_path.parent, run_dir)
            self.assertTrue((run_dir / "stable-final-manifest.json").is_file())
            self.assertEqual(
                hashlib.sha256(stable_path.read_bytes()).hexdigest(),
                manifest["paths_sha256"]["original_top_srt"],
            )
            self.assertEqual(
                Path(manifest["final_cue_timeline_path"]).parent,
                run_dir / "source-artifacts",
            )
            self.assertEqual(
                Path(manifest["coverage_report"]),
                run_dir / report.name,
            )
            self.assertTrue((root / "output.srt").is_file())

    def test_display_page_export_is_named_from_original_audio_and_keeps_parent_link(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            source_dir.mkdir()
            audio = source_dir / "节目.m4a"
            audio.write_bytes(b"audio")
            parent = source_dir / "节目-原文在上双语字幕.srt"
            parent.write_text("parent", encoding="utf-8")
            manifest = root / "stable-final-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            thread = self._thread(root)
            thread.task.source_audio_path = str(audio)
            thread.task.video_path = str(root / "temporary.wav")

            class Session:
                def export_display_page_subtitles(
                    self,
                    srt_path,
                    map_path,
                    *,
                    source_parent_subtitle_path=None,
                ):
                    self.parent = Path(source_parent_subtitle_path)
                    Path(srt_path).write_text("pages", encoding="utf-8")
                    Path(map_path).write_text("{}", encoding="utf-8")
                    return {"srt": str(srt_path), "map": str(map_path)}

            session = Session()
            with patch.object(
                ManualFinalSubtitleSession,
                "load_from_manifest",
                return_value=session,
            ):
                paths = thread._write_source_audio_display_page_exports(
                    manifest,
                    {"named_bilingual_original_top_srt": str(parent)},
                )

            self.assertEqual(
                Path(paths["display_page_bilingual_srt"]),
                root / "节目-处理结果" / "字幕文件" / "节目-实际分页双语字幕.srt",
            )
            self.assertEqual(
                Path(paths["display_page_map"]),
                root / "节目-处理结果" / "字幕文件" / "节目-实际分页映射.json",
            )
            self.assertEqual(session.parent, parent)

    def test_display_page_export_failure_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            source_dir.mkdir()
            audio = source_dir / "节目.m4a"
            audio.write_bytes(b"audio")
            manifest = root / "stable-final-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            thread = self._thread(root)
            thread.task.source_audio_path = str(audio)

            with patch.object(
                ManualFinalSubtitleSession,
                "load_from_manifest",
                side_effect=ManualFinalSubtitleEditError("ledger mismatch"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "stable_display_page_export_failed: ledger mismatch",
                ):
                    thread._write_source_audio_display_page_exports(
                        manifest,
                        {},
                    )

    def test_display_page_export_requires_nonempty_srt_and_map_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            source_dir.mkdir()
            audio = source_dir / "节目.m4a"
            audio.write_bytes(b"audio")
            manifest = root / "stable-final-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            thread = self._thread(root)
            thread.task.source_audio_path = str(audio)

            class Session:
                def export_display_page_subtitles(self, srt_path, map_path, **_kwargs):
                    Path(srt_path).write_text("pages", encoding="utf-8")
                    return {"srt": str(srt_path), "map": str(map_path)}

            with patch.object(
                ManualFinalSubtitleSession,
                "load_from_manifest",
                return_value=Session(),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "missing_or_empty_export_pair",
                ):
                    thread._write_source_audio_display_page_exports(manifest, {})

    def test_critical_display_page_failure_preserves_previous_root_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            thread = self._thread(root)
            previous_manifest = root / "stable-final-manifest.json"
            previous_manifest.write_bytes(b'{"stable_run_id":"previous"}')
            runs_dir = root / "stable-runs"

            with patch.object(
                thread,
                "_write_source_audio_display_page_exports",
                side_effect=RuntimeError("stable_display_page_export_failed: broken"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "stable_display_page_export_failed: broken",
                ):
                    thread._save_stable_subtitle_outputs(
                        self._data("New attempt."),
                        self._config(),
                        validation_status="passed",
                        manifest_meta={
                            "display_page_translation_status": "PASS",
                            "display_page_translation_path": "display-pages.json",
                        },
                    )

            self.assertEqual(
                previous_manifest.read_bytes(),
                b'{"stable_run_id":"previous"}',
            )
            if runs_dir.exists():
                self.assertEqual(list(runs_dir.iterdir()), [])

    def test_compatibility_source_export_failure_does_not_skip_display_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            thread = self._thread(root)
            display_srt = root / "display.srt"
            display_map = root / "display.json"
            display_srt.write_text("pages", encoding="utf-8")
            display_map.write_text("{}", encoding="utf-8")

            with patch.object(
                thread,
                "_write_source_audio_subtitle_exports",
                return_value={},
            ), patch.object(
                thread,
                "_write_source_audio_display_page_exports",
                return_value={
                    "display_page_bilingual_srt": str(display_srt),
                    "display_page_map": str(display_map),
                },
            ) as display_export:
                thread._save_stable_subtitle_outputs(
                    self._data(),
                    self._config(),
                    validation_status="passed",
                    manifest_meta={
                        "display_page_translation_status": "PASS",
                        "display_page_translation_path": "display-pages.json",
                    },
                )

            display_export.assert_called_once()
            manifest = json.loads(
                (root / "stable-final-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["source_subtitle_paths"]["display_page_bilingual_srt"],
                str(display_srt),
            )
            self.assertEqual(
                manifest["source_subtitle_paths"]["display_page_map"],
                str(display_map),
            )

    def test_failed_attempt_preserves_previous_success_and_writes_failure_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            thread = self._thread(root)
            thread._save_stable_subtitle_outputs(
                self._data("First success."),
                self._config(),
                validation_status="passed",
            )
            manifest_path = root / "stable-final-manifest.json"
            manifest_before = manifest_path.read_bytes()
            manifest = json.loads(manifest_before.decode("utf-8"))
            stable_path = Path(manifest["paths"]["original_top_srt"])
            stable_before = stable_path.read_bytes()
            output_before = (root / "output.srt").read_bytes()

            thread._save_stable_subtitle_outputs(
                self._data("Rejected attempt."),
                self._config(),
                validation_status="failed",
                validation_summary={
                    "status": "ERROR",
                    "errors": [{"code": "final_timeline_invalid"}],
                },
            )

            self.assertEqual(manifest_path.read_bytes(), manifest_before)
            self.assertEqual(stable_path.read_bytes(), stable_before)
            self.assertEqual((root / "output.srt").read_bytes(), output_before)
            failure = json.loads(
                (root / "stable-last-failure.json").read_text(encoding="utf-8")
            )
            self.assertTrue(failure["render_blocked"])
            self.assertEqual(
                failure["validation_error_codes"],
                ["final_timeline_invalid"],
            )

    def test_stable_snapshot_keeps_only_identity_bound_semantic_review_queue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "source-coverage-report.txt"
            report.write_text("PASS", encoding="utf-8")
            artifact_dir = root / "source-artifacts"
            artifact_dir.mkdir()
            word_ledger = {
                "hash": "current-ledger",
                "words": [
                    {
                        "word_id": 0,
                        "surface": "Current.",
                        "start_ms": 0,
                        "end_ms": 500,
                    }
                ],
            }
            subtitle_spans = [
                {
                    "subtitle_id": "S0001",
                    "original": "Current.",
                    "word_start": 0,
                    "word_end": 0,
                }
            ]
            (artifact_dir / "word-ledger.json").write_text(
                json.dumps(word_ledger),
                encoding="utf-8",
            )
            (artifact_dir / "subtitle-spans.json").write_text(
                json.dumps(subtitle_spans),
                encoding="utf-8",
            )
            queue_path = artifact_dir / "semantic-review-queue.json"

            def write_queue(source_run):
                queue_path.write_text(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "source_run": source_run,
                            "items": [
                                {
                                    "subtitle_ids": ["S0001"],
                                    "context": [
                                        {
                                            "subtitle_id": "S0001",
                                            "english": "Current.",
                                            "word_start": 0,
                                            "word_end": 0,
                                        }
                                    ],
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

            write_queue(build_review_source_identity(word_ledger, subtitle_spans))
            valid_run = root / "valid-run"
            valid_run.mkdir()
            _, _, valid_artifacts = SubtitleThread._snapshot_stable_validation_artifacts(
                str(report),
                valid_run,
            )
            self.assertTrue(
                (valid_artifacts / "semantic-review-queue.json").is_file()
            )

            write_queue(
                {
                    **build_review_source_identity(word_ledger, subtitle_spans),
                    "frozen_span_hash": "stale-span",
                }
            )
            stale_run = root / "stale-run"
            stale_run.mkdir()
            _, _, stale_artifacts = SubtitleThread._snapshot_stable_validation_artifacts(
                str(report),
                stale_run,
            )
            self.assertFalse(
                (stale_artifacts / "semantic-review-queue.json").exists()
            )
            self.assertTrue(queue_path.is_file())

    def test_display_page_failure_writes_complete_editable_blocked_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "source-coverage-report.txt"
            report.write_text("PASS", encoding="utf-8")
            artifact_dir = root / "source-artifacts"
            artifact_dir.mkdir()
            audit_cache_dir = artifact_dir / "translation-quality-audit-cache"
            audit_cache_dir.mkdir()
            (audit_cache_dir / ("a" * 64 + ".json")).write_text(
                '{"cache": true}',
                encoding="utf-8",
            )
            words = ["The", "first", "line.", "Second", "line."]
            (artifact_dir / "word-ledger.json").write_text(
                json.dumps(
                    {
                        "words": [
                            {
                                "word_id": index,
                                "surface": word,
                                "start_ms": index * 200,
                                "end_ms": (index + 1) * 200,
                            }
                            for index, word in enumerate(words)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (artifact_dir / "subtitle-spans.json").write_text(
                json.dumps(
                    [
                        {
                            "subtitle_id": "S0001",
                            "word_start": 0,
                            "word_end": 2,
                            "original": "The first line.",
                        },
                        {
                            "subtitle_id": "S0002",
                            "word_start": 3,
                            "word_end": 4,
                            "original": "Second line.",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            timeline = artifact_dir / "final-cue-timeline.json"
            timeline.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "subtitle_id": "S0001",
                                "word_start": 0,
                                "word_end": 2,
                                "word_envelope_start_ms": 0,
                                "word_envelope_end_ms": 600,
                                "start_ms": 0,
                                "end_ms": 600,
                            },
                            {
                                "subtitle_id": "S0002",
                                "word_start": 3,
                                "word_end": 4,
                                "word_envelope_start_ms": 600,
                                "word_envelope_end_ms": 1000,
                                "start_ms": 600,
                                "end_ms": 1000,
                            },
                        ],
                        "validation": {
                            "status": "PASS",
                            "errors": [],
                            "expected_subtitle_ids": ["S0001", "S0002"],
                            "returned_subtitle_ids": ["S0001", "S0002"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            (artifact_dir / "translation-structure-errors.json").write_text(
                json.dumps(
                    [
                        {
                            "code": "display_page_blueprint_invalid",
                            "subtitle_ids": ["S0002"],
                            "message": "render_structural_overflow",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            data = ASRData(
                [
                    ASRDataSeg("The first line.", 0, 600, "第一行。"),
                    ASRDataSeg("Second line.", 600, 1000, "第二行。"),
                ]
            )
            for segment, subtitle_id, word_start, word_end in (
                (data.segments[0], "S0001", 0, 2),
                (data.segments[1], "S0002", 3, 4),
            ):
                segment.subtitle_id = subtitle_id
                segment.word_start = word_start
                segment.word_end = word_end

            thread = self._thread(root)
            thread._save_stable_subtitle_outputs(
                data,
                self._config(),
                coverage_report_path=str(report),
                validation_status="failed",
                validation_summary={
                    "status": "ERROR",
                    "errors": [
                        {
                            "code": "display_page_translation_invalid",
                            "message": "render_structural_overflow: cue=2",
                            "items": [
                                {
                                    "subtitle_id": "S0002",
                                    "reason": "hard_page_boundary",
                                }
                            ],
                        }
                    ],
                    "warnings": [],
                    "info": [],
                },
                manifest_meta={"final_cue_timeline_path": str(timeline)},
            )

            failure_path = root / "stable-last-failure.json"
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            checkpoint_path = Path(failure["editable_checkpoint_manifest_path"])
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertTrue(checkpoint["render_blocked"])
            self.assertEqual(checkpoint["validation_status"], "failed")
            self.assertEqual(checkpoint["subtitle_count"], 2)
            self.assertEqual(checkpoint["attempt_id"], failure["attempt_id"])
            self.assertTrue(Path(checkpoint["paths"]["original_top_srt"]).is_file())
            checkpoint_artifact_dir = checkpoint_path.parent / artifact_dir.name
            self.assertFalse(
                (checkpoint_artifact_dir / "translation-quality-audit-cache").exists()
            )
            self.assertFalse((root / "stable-final-manifest.json").exists())
            session = ManualFinalSubtitleSession.load_from_failure_record(failure_path)
            self.assertEqual(len(session.cues), 2)
            self.assertEqual(
                [cue["cue_id"] for cue in session.cues],
                ["S0001", "S0002"],
            )
            self._assert_blocked_checkpoint_ui_loads(
                root,
                failure,
                checkpoint_path,
            )

    def test_duration_failure_uses_same_structural_editable_checkpoint_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "source-coverage-report.txt"
            report.write_text("PASS", encoding="utf-8")
            artifact_dir = root / "source-artifacts"
            artifact_dir.mkdir()
            (artifact_dir / "word-ledger.json").write_text(
                json.dumps(
                    {
                        "words": [
                            {
                                "word_id": 0,
                                "surface": "Precisely.",
                                "start_ms": 1000,
                                "end_ms": 1120,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (artifact_dir / "subtitle-spans.json").write_text(
                json.dumps(
                    [
                        {
                            "subtitle_id": "S0001",
                            "word_start": 0,
                            "word_end": 0,
                            "original": "Precisely.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            timeline = artifact_dir / "final-cue-timeline.json"
            timeline.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "subtitle_id": "S0001",
                                "word_start": 0,
                                "word_end": 0,
                                "word_envelope_start_ms": 1000,
                                "word_envelope_end_ms": 1120,
                                "start_ms": 960,
                                "end_ms": 1220,
                            }
                        ],
                        "validation": {
                            "status": "PASS",
                            "errors": [],
                            "expected_subtitle_ids": ["S0001"],
                            "returned_subtitle_ids": ["S0001"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            data = ASRData([ASRDataSeg("Precisely.", 960, 1220, "正是如此。")])
            data.segments[0].subtitle_id = "S0001"
            data.segments[0].word_start = 0
            data.segments[0].word_end = 0

            thread = self._thread(root)
            thread._save_stable_subtitle_outputs(
                data,
                self._config(),
                coverage_report_path=str(report),
                validation_status="failed",
                validation_summary={
                    "status": "ERROR",
                    "errors": [{"code": "subtitle_duration_invalid"}],
                },
                manifest_meta={"final_cue_timeline_path": str(timeline)},
            )

            failure_path = root / "stable-last-failure.json"
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            self.assertIn("editable_checkpoint_manifest_path", failure)
            session = ManualFinalSubtitleSession.load_from_failure_record(failure_path)
            self.assertEqual([cue["cue_id"] for cue in session.cues], ["S0001"])

    def test_invalid_final_timeline_never_becomes_an_editable_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "source-coverage-report.txt"
            report.write_text("PASS", encoding="utf-8")
            artifact_dir = root / "source-artifacts"
            artifact_dir.mkdir()
            (artifact_dir / "word-ledger.json").write_text(
                json.dumps(
                    {
                        "words": [
                            {
                                "word_id": 0,
                                "surface": "English",
                                "start_ms": 0,
                                "end_ms": 500,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (artifact_dir / "subtitle-spans.json").write_text(
                json.dumps(
                    [
                        {
                            "subtitle_id": "S0001",
                            "word_start": 0,
                            "word_end": 0,
                            "original": "English",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            timeline = artifact_dir / "final-cue-timeline.json"
            timeline.write_text(
                json.dumps(
                    {
                        "records": [],
                        "validation": {
                            "status": "ERROR",
                            "errors": [{"code": "final_timeline_subtitle_id_missing"}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            thread = self._thread(root)
            thread._save_stable_subtitle_outputs(
                self._data("English"),
                self._config(),
                coverage_report_path=str(report),
                validation_status="failed",
                validation_summary={
                    "status": "ERROR",
                    "errors": [{"code": "subtitle_duration_invalid"}],
                },
                manifest_meta={"final_cue_timeline_path": str(timeline)},
            )

            failure = json.loads(
                (root / "stable-last-failure.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("editable_checkpoint_manifest_path", failure)

    def _assert_blocked_checkpoint_ui_loads(
        self,
        root: Path,
        failure: dict,
        checkpoint_path: Path,
    ) -> None:

        class Toggle:
            def __init__(self):
                self.enabled = False
                self.visible = False
                self.tooltip = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setVisible(self, value):
                self.visible = bool(value)

            def setToolTip(self, value):
                self.tooltip = str(value)

        class StatusLabel:
            def __init__(self):
                self.text = ""

            def setText(self, value):
                self.text = str(value)

        interface = SimpleNamespace(
            manual_final_session=None,
            _manual_package_manifest_path="",
            _manual_save_in_progress=False,
            _manual_review_mark_count=0,
            _review_mark_rows=[],
            _review_mark_request_id=0,
            _active_subtitle_attempt_id=failure["attempt_id"],
            model=SubtitleTableModel({}),
            next_review_action=Toggle(),
            manual_final_save_action=Toggle(),
            manual_final_undo_action=Toggle(),
            manual_final_synthesis_action=Toggle(),
            manual_draft_synthesis_action=Toggle(),
            subtitle_table=Toggle(),
            subtitle_path="",
            status_label=StatusLabel(),
            tr=lambda value: value,
            _load_manual_final_review_marks=lambda _session: None,
        )
        interface._apply_manual_final_session = MethodType(
            SubtitleInterface._apply_manual_final_session,
            interface,
        )
        interface._manual_state_fingerprint = MethodType(
            SubtitleInterface._manual_state_fingerprint,
            interface,
        )
        interface._set_manual_clean_checkpoint = MethodType(
            SubtitleInterface._set_manual_clean_checkpoint,
            interface,
        )
        interface._invalidate_manual_final_save = MethodType(
            SubtitleInterface._invalidate_manual_final_save,
            interface,
        )

        loaded = SubtitleInterface._load_manual_failure_checkpoint_from_output(
                interface,
                str(root / "output.srt"),
            )

        self.assertTrue(loaded)
        self.assertEqual(interface.model.rowCount(), 2)
        self.assertEqual(
            [
                interface.model._data[str(index)]["source_subtitle_ids"]
                for index in (1, 2)
            ],
            [["S0001"], ["S0002"]],
        )
        self.assertFalse(interface.manual_final_synthesis_action.enabled)
        self.assertTrue(interface.manual_final_synthesis_action.visible)
        self.assertFalse(interface.manual_draft_synthesis_action.enabled)
        self.assertTrue(interface.manual_draft_synthesis_action.visible)

        interface._active_subtitle_attempt_id = "different-attempt"
        self.assertFalse(
            SubtitleInterface._load_manual_failure_checkpoint_from_output(
                interface,
                str(root / "output.srt"),
            )
        )
        with self.assertRaisesRegex(RuntimeError, "阻止.*合成"):
            resolve_podcast_template_subtitle(
                str(root / "audio.m4a"),
                str(checkpoint_path),
            )

    def test_manifest_hash_mismatch_blocks_synthesis_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            thread = self._thread(root)
            thread._save_stable_subtitle_outputs(
                self._data(),
                self._config(),
                validation_status="passed",
            )
            manifest = json.loads(
                (root / "stable-final-manifest.json").read_text(encoding="utf-8")
            )
            stable_path = Path(manifest["paths"]["original_top_srt"])
            stable_path.write_text("tampered", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "清单未指向可用终稿"):
                resolve_podcast_template_subtitle(
                    str(root / "audio.m4a"),
                    str(root / "output.srt"),
                )

    def test_manual_final_save_dispatches_page_planning_off_gui_thread(self):
        class Toggle:
            def __init__(self):
                self.enabled = True
                self.visible = True
                self.text = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setVisible(self, value):
                self.visible = bool(value)

            def setText(self, value):
                self.text = str(value)

        class TableToggle:
            def __init__(self):
                self.enabled = True
                self.tooltip = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setToolTip(self, value):
                self.tooltip = str(value)

        class StatusLabel:
            def __init__(self):
                self.text = ""

            def setText(self, value):
                self.text = str(value)

        class Signal:
            def __init__(self):
                self.calls = []

            def emit(self, *args):
                self.calls.append(args)

        class Session:
            save_calls = 0
            deepcopy_calls = 0

            def __init__(self):
                self.history = []

            def __deepcopy__(self, memo):
                Session.deepcopy_calls += 1
                return self

            def save_to_source_folder(
                self,
                *,
                source_media_path=None,
                progress_callback=None,
            ):
                Session.save_calls += 1
                if progress_callback is not None:
                    progress_callback(5, "正在核对冻结字幕和词时间账本")
                    progress_callback(70, "实际分页检查完成，正在写入双语字幕")
                return {
                    "manifest_path": "manual-manifest.json",
                    "render_blocked": False,
                }

        started_threads = []

        class CapturedThread:
            def __init__(self, *, target, args, daemon):
                self.target = target
                self.args = args
                self.daemon = daemon

            def start(self):
                started_threads.append(self)

        interface = SimpleNamespace(
            manual_final_session=Session(),
            _manual_save_in_progress=False,
            _manual_save_request_id=0,
            _manual_refresh_requested=False,
            task=None,
            subtitle_table=TableToggle(),
            manual_final_save_action=Toggle(),
            manual_final_undo_action=Toggle(),
            manual_final_synthesis_action=Toggle(),
            manual_draft_synthesis_action=Toggle(),
            status_label=StatusLabel(),
            manual_final_save_progress=Signal(),
            manual_final_save_finished=Signal(),
            tr=lambda value: value,
            _sync_manual_final_text_edits=lambda **_kwargs: None,
        )
        interface._set_manual_final_save_busy = MethodType(
            SubtitleInterface._set_manual_final_save_busy,
            interface,
        )
        interface._save_manual_final_output_in_background = MethodType(
            SubtitleInterface._save_manual_final_output_in_background,
            interface,
        )

        with patch("app.view.subtitle_interface.Thread", CapturedThread):
            SubtitleInterface.save_manual_final_output(interface)

        self.assertEqual(Session.save_calls, 0)
        self.assertEqual(
            Session.deepcopy_calls,
            0,
            "the GUI thread must not copy a large manual session before dispatch",
        )
        self.assertEqual(len(started_threads), 1)
        self.assertFalse(interface.subtitle_table.enabled)
        self.assertFalse(interface.manual_final_save_action.enabled)
        self.assertFalse(interface.manual_final_synthesis_action.enabled)
        self.assertTrue(interface.manual_final_synthesis_action.visible)
        self.assertFalse(interface.manual_draft_synthesis_action.enabled)
        self.assertTrue(interface.manual_draft_synthesis_action.visible)
        self.assertIn("后台", interface.status_label.text)
        self.assertTrue(SubtitleInterface.manual_final_save_in_progress(interface))

        SubtitleInterface._invalidate_manual_final_save(interface)
        self.assertTrue(interface._manual_save_in_progress)
        self.assertFalse(interface.subtitle_table.enabled)
        self.assertTrue(SubtitleInterface.manual_final_save_in_progress(interface))

        worker = started_threads[0]
        worker.target(*worker.args)
        self.assertEqual(Session.deepcopy_calls, 1)
        self.assertEqual(Session.save_calls, 1)
        self.assertFalse(SubtitleInterface.manual_final_save_in_progress(interface))
        self.assertEqual(len(interface.manual_final_save_finished.calls), 1)
        request_id, paths, error = interface.manual_final_save_finished.calls[0]
        self.assertEqual(request_id, 1)
        self.assertEqual(paths["manifest_path"], "manual-manifest.json")
        self.assertEqual(error, "")
        self.assertEqual(
            interface.manual_final_save_progress.calls,
            [
                (1, 5, "正在核对冻结字幕和词时间账本"),
                (1, 70, "实际分页检查完成，正在写入双语字幕"),
            ],
        )
        interface._manual_save_request_id = 1
        interface._manual_save_in_progress = True
        SubtitleInterface._apply_manual_final_save_progress(
            interface,
            0,
            99,
            "过期请求",
        )
        self.assertNotIn("过期请求", interface.status_label.text)
        SubtitleInterface._apply_manual_final_save_progress(
            interface,
            1,
            70,
            "实际分页检查完成，正在写入双语字幕",
        )
        self.assertIn("70%", interface.status_label.text)
        self.assertIn("实际分页检查完成", interface.status_label.text)

        class FailingThread(CapturedThread):
            def start(self):
                raise RuntimeError("thread start failed")

        SubtitleInterface._set_manual_final_save_busy(interface, False)
        with patch("app.view.subtitle_interface.Thread", FailingThread), patch(
            "app.view.subtitle_interface.InfoBar.warning"
        ):
            SubtitleInterface.save_manual_final_output(interface)
        self.assertFalse(interface._manual_save_in_progress)
        self.assertTrue(interface.subtitle_table.enabled)
        self.assertTrue(interface.manual_final_save_action.enabled)

    def test_main_window_blocks_exit_while_manual_final_save_is_running(self):
        class Button:
            def __init__(self):
                self.text = ""
                self.hidden = False

            def setText(self, value):
                self.text = str(value)

            def hide(self):
                self.hidden = True

        class FakeMessageBox:
            instances = []

            def __init__(self, title, content, parent):
                self.title = title
                self.content = content
                self.parent = parent
                self.yesButton = Button()
                self.cancelButton = Button()
                self.executed = False
                FakeMessageBox.instances.append(self)

            def exec(self):
                self.executed = True

        class Event:
            def __init__(self):
                self.ignored = False

            def ignore(self):
                self.ignored = True

        subtitle_interface = SimpleNamespace(
            manual_final_save_in_progress=lambda: True,
        )
        window = SimpleNamespace(
            homeInterface=SimpleNamespace(
                subtitle_optimization_interface=subtitle_interface,
            ),
            tr=lambda value: value,
        )
        event = Event()
        with patch("app.view.main_window.MessageBox", FakeMessageBox):
            MainWindow.closeEvent(window, event)

        self.assertTrue(event.ignored)
        self.assertEqual(len(FakeMessageBox.instances), 1)
        self.assertTrue(FakeMessageBox.instances[0].executed)
        self.assertTrue(FakeMessageBox.instances[0].cancelButton.hidden)

    def test_manual_boundary_inspector_maps_parent_rows_to_adjacent_boundaries(self):
        self.assertEqual(
            SubtitleInterface._manual_boundary_left_index(4, 0),
            0,
        )
        self.assertEqual(
            SubtitleInterface._manual_boundary_left_index(4, 1),
            1,
        )
        self.assertEqual(
            SubtitleInterface._manual_boundary_left_index(4, 2),
            2,
        )
        self.assertEqual(
            SubtitleInterface._manual_boundary_left_index(4, 3),
            2,
        )

    def test_manual_boundary_highlight_escapes_html_and_marks_only_requested_words(self):
        text = "alpha <beta> gamma &delta"

        tail_html = SubtitleInterface._manual_boundary_text_html(
            text,
            highlight_tail=2,
        )
        self.assertEqual(tail_html.count("<span"), 1)
        self.assertTrue(tail_html.startswith("alpha &lt;beta&gt; <span"))
        self.assertTrue(tail_html.endswith(">gamma &amp;delta</span>"))

        head_html = SubtitleInterface._manual_boundary_text_html(
            text,
            highlight_head=2,
        )
        self.assertEqual(head_html.count("<span"), 1)
        self.assertTrue(head_html.startswith("<span"))
        self.assertIn(">alpha &lt;beta&gt;</span> gamma &amp;delta", head_html)
        for rendered in (tail_html, head_html):
            self.assertNotIn("<beta>", rendered)
            self.assertNotIn("&delta", rendered)

    def test_manual_boundary_move_invalidates_saved_synthesis_and_stale_pages(self):
        class Toggle:
            def __init__(self):
                self.enabled = True
                self.visible = True
                self.text = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setVisible(self, value):
                self.visible = bool(value)

            def setText(self, value):
                self.text = str(value)

        class TableToggle:
            def __init__(self):
                self.enabled = True
                self.tooltip = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setToolTip(self, value):
                self.tooltip = str(value)

        class StatusLabel:
            def __init__(self):
                self.text = ""

            def setText(self, value):
                self.text = str(value)

        class Session:
            def __init__(self):
                self.cues = [
                    {
                        "subtitle_id": "S0001",
                        "start_time": 0,
                        "end_time": 200,
                        "word_start": 0,
                        "word_end": 1,
                        "original_subtitle": "one two",
                        "translated_subtitle": "一二",
                    },
                    {
                        "subtitle_id": "S0002",
                        "start_time": 200,
                        "end_time": 400,
                        "word_start": 2,
                        "word_end": 3,
                        "original_subtitle": "three four",
                        "translated_subtitle": "三四",
                    },
                ]
                self.history = []
                self.display_page_edits = [
                    {
                        "display_page_id": "S0001.P01",
                        "parent_subtitle_id": "S0001",
                    }
                ]
                self.moves = []

            def move_suffix_to_next(self, left_index, word_count):
                self.moves.append(("next", left_index, word_count))
                self.history.append({"before": [dict(cue) for cue in self.cues]})
                self.cues[0]["word_end"] = 0
                self.cues[0]["original_subtitle"] = "one"
                self.cues[1]["word_start"] = 1
                self.cues[1]["original_subtitle"] = "two three four"
                self.display_page_edits = []

            def has_display_page_model(self):
                return bool(self.display_page_edits)

            def to_model_data(self, *, prefer_display_pages=False):
                if prefer_display_pages and self.display_page_edits:
                    return {
                        "1": {
                            "display_page_view": True,
                            "display_page_id": "S0001.P01",
                            "original_subtitle": "stale page",
                            "translated_subtitle": "旧分页",
                        }
                    }
                return {
                    str(index): dict(cue)
                    for index, cue in enumerate(self.cues, 1)
                }

        session = Session()
        interface = SimpleNamespace(
            manual_final_session=session,
            model=SubtitleTableModel({}),
            _manual_page_view=True,
            _manual_parent_boundaries_dirty=False,
            _manual_package_manifest_path="saved-manual-manifest.json",
            _manual_save_request_id=0,
            _manual_save_in_progress=False,
            subtitle_table=TableToggle(),
            manual_page_view_action=Toggle(),
            manual_final_save_action=Toggle(),
            manual_final_undo_action=Toggle(),
            manual_final_synthesis_action=Toggle(),
            manual_draft_synthesis_action=Toggle(),
            status_label=StatusLabel(),
            tr=lambda value: value,
            _sync_manual_final_text_edits=lambda: None,
            _invalidate_manual_review_marks_for_parent_ids=lambda _ids: None,
            _refresh_manual_boundary_inspector=lambda selected_row=None: None,
            _select_manual_boundary_row=lambda _left_index: None,
        )
        interface._apply_manual_final_session = MethodType(
            SubtitleInterface._apply_manual_final_session,
            interface,
        )
        interface._invalidate_manual_final_save = MethodType(
            SubtitleInterface._invalidate_manual_final_save,
            interface,
        )
        interface._mark_manual_final_dirty = MethodType(
            SubtitleInterface._mark_manual_final_dirty,
            interface,
        )

        with patch("app.view.subtitle_interface.InfoBar.success"), patch(
            "app.view.subtitle_interface.InfoBar.warning"
        ):
            SubtitleInterface._apply_manual_boundary_move(
                interface,
                0,
                1,
                move_to_next=True,
                announce=False,
            )

        self.assertEqual(session.moves, [("next", 0, 1)])
        self.assertTrue(interface._manual_parent_boundaries_dirty)
        self.assertEqual(interface._manual_package_manifest_path, "")
        self.assertFalse(interface._manual_page_view)
        self.assertFalse(session.display_page_edits)
        self.assertTrue(interface.manual_page_view_action.enabled)
        self.assertEqual(interface.manual_page_view_action.text, "刷新实际分页")
        self.assertFalse(interface.manual_final_synthesis_action.enabled)
        self.assertTrue(interface.manual_final_synthesis_action.visible)
        self.assertFalse(interface.manual_draft_synthesis_action.enabled)
        self.assertTrue(interface.manual_draft_synthesis_action.visible)
        self.assertEqual(interface.model.rowCount(), 2)
        self.assertFalse(
            any(
                row.get("display_page_view")
                for row in interface.model._data.values()
            )
        )

    def test_manual_boundary_undo_restores_parent_boundary_but_still_requires_save(self):
        class Toggle:
            def __init__(self):
                self.enabled = True
                self.visible = True
                self.text = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setVisible(self, value):
                self.visible = bool(value)

            def setText(self, value):
                self.text = str(value)

        class TableToggle:
            def setEnabled(self, _value):
                pass

            def setToolTip(self, _value):
                pass

        class StatusLabel:
            def __init__(self):
                self.text = ""

            def setText(self, value):
                self.text = str(value)

        original_cues = [
            {
                "subtitle_id": "S0001",
                "start_time": 0,
                "end_time": 200,
                "word_start": 0,
                "word_end": 1,
                "original_subtitle": "one two",
                "translated_subtitle": "一二",
            },
            {
                "subtitle_id": "S0002",
                "start_time": 200,
                "end_time": 400,
                "word_start": 2,
                "word_end": 3,
                "original_subtitle": "three four",
                "translated_subtitle": "三四",
            },
        ]

        class Session:
            def __init__(self):
                self.cues = [dict(cue) for cue in original_cues]
                self.history = []
                self.display_page_edits = [{"display_page_id": "S0001.P01"}]

            def move_suffix_to_next(self, left_index, word_count):
                self.history.append(
                    {
                        "operation": "move_suffix_to_next",
                        "before": [dict(cue) for cue in self.cues],
                        "before_display_page_edits": list(self.display_page_edits),
                    }
                )
                self.cues[0]["word_end"] = 0
                self.cues[0]["original_subtitle"] = "one"
                self.cues[1]["word_start"] = 1
                self.cues[1]["original_subtitle"] = "two three four"
                self.display_page_edits = []

            def undo(self):
                if not self.history:
                    return False
                before = self.history.pop()
                self.cues = [dict(cue) for cue in before["before"]]
                self.display_page_edits = list(before["before_display_page_edits"])
                return True

            def has_display_page_model(self):
                return bool(self.display_page_edits)

            def to_model_data(self, *, prefer_display_pages=False):
                if prefer_display_pages and self.display_page_edits:
                    return {
                        "1": {
                            "display_page_view": True,
                            "display_page_id": "S0001.P01",
                            "original_subtitle": "stale page",
                            "translated_subtitle": "旧分页",
                        }
                    }
                return {
                    str(index): dict(cue)
                    for index, cue in enumerate(self.cues, 1)
                }

        session = Session()
        interface = SimpleNamespace(
            manual_final_session=session,
            model=SubtitleTableModel({}),
            _manual_page_view=True,
            _manual_parent_boundaries_dirty=False,
            _manual_boundary_left_index_value=0,
            _manual_package_manifest_path="saved-manual-manifest.json",
            _manual_save_request_id=0,
            _manual_save_in_progress=False,
            _manual_clean_state_fingerprint="saved-state",
            _manual_model_has_pending_edits=False,
            _manual_has_unsaved_changes=False,
            subtitle_table=TableToggle(),
            manual_page_view_action=Toggle(),
            manual_final_save_action=Toggle(),
            manual_final_undo_action=Toggle(),
            manual_final_synthesis_action=Toggle(),
            manual_draft_synthesis_action=Toggle(),
            status_label=StatusLabel(),
            tr=lambda value: value,
            _sync_manual_final_text_edits=lambda: None,
            _invalidate_manual_review_marks_for_parent_ids=lambda _ids: None,
            _refresh_manual_boundary_inspector=lambda selected_row=None: None,
            _select_manual_boundary_row=lambda _left_index: None,
        )
        interface._apply_manual_final_session = MethodType(
            SubtitleInterface._apply_manual_final_session,
            interface,
        )
        interface._mark_manual_final_dirty = MethodType(
            SubtitleInterface._mark_manual_final_dirty,
            interface,
        )
        interface._invalidate_manual_final_save = MethodType(
            SubtitleInterface._invalidate_manual_final_save,
            interface,
        )
        interface._manual_state_fingerprint = MethodType(
            SubtitleInterface._manual_state_fingerprint,
            interface,
        )
        interface._reconcile_manual_dirty_state = MethodType(
            SubtitleInterface._reconcile_manual_dirty_state,
            interface,
        )

        with patch("app.view.subtitle_interface.InfoBar.success"), patch(
            "app.view.subtitle_interface.InfoBar.warning"
        ):
            SubtitleInterface._apply_manual_boundary_move(
                interface,
                0,
                1,
                move_to_next=True,
                announce=False,
            )
            SubtitleInterface.undo_manual_final_edit(interface)

        self.assertEqual(session.cues, original_cues)
        self.assertFalse(interface._manual_parent_boundaries_dirty)
        self.assertEqual(interface._manual_package_manifest_path, "")
        self.assertFalse(interface._manual_page_view)
        self.assertEqual(
            session.display_page_edits,
            [{"display_page_id": "S0001.P01"}],
        )
        self.assertTrue(interface.manual_page_view_action.enabled)
        self.assertEqual(interface.manual_page_view_action.text, "查看实际分页")
        self.assertFalse(interface.manual_final_synthesis_action.enabled)
        self.assertFalse(interface.manual_draft_synthesis_action.enabled)
        self.assertTrue(interface.manual_final_save_action.enabled)
        self.assertIn("保存", interface.status_label.text)
        self.assertFalse(
            any(
                row.get("display_page_view")
                for row in interface.model._data.values()
            )
        )

    def test_manual_boundary_ui_routes_same_parent_pages_without_parent_dirty(self):
        page_model = SubtitleTableModel(
            {
                "1": {
                    "display_page_view": True,
                    "display_page_id": "S0001.P01",
                    "manual_cue_id": "S0001",
                    "parent_cue_index": 0,
                    "word_start": 0,
                    "word_end": 2,
                },
                "2": {
                    "display_page_view": True,
                    "display_page_id": "S0001.P02",
                    "manual_cue_id": "S0001",
                    "parent_cue_index": 0,
                    "word_start": 3,
                    "word_end": 5,
                },
                "3": {
                    "display_page_view": True,
                    "display_page_id": "S0002.P01",
                    "manual_cue_id": "S0002",
                    "parent_cue_index": 1,
                    "word_start": 6,
                    "word_end": 8,
                },
            }
        )
        context_interface = SimpleNamespace(
            manual_final_session=SimpleNamespace(cues=[{}, {}]),
            model=page_model,
        )
        same_parent = SubtitleInterface._manual_boundary_context(
            context_interface,
            0,
        )
        cross_parent = SubtitleInterface._manual_boundary_context(
            context_interface,
            1,
        )
        self.assertEqual(same_parent["kind"], "display")
        self.assertEqual(same_parent["left_page_id"], "S0001.P01")
        self.assertEqual(cross_parent["kind"], "parent")
        self.assertEqual(cross_parent["parent_left_index"], 0)

        last_row = SubtitleInterface._manual_boundary_context(
            context_interface,
            2,
        )
        self.assertEqual(last_row["left_row"], 1)
        self.assertEqual(last_row["right_row"], 2)

        single_parent_interface = SimpleNamespace(
            manual_final_session=SimpleNamespace(cues=[{"cue_id": "S0001"}]),
            model=SubtitleTableModel(
                {
                    "1": {
                        "display_page_view": True,
                        "display_page_id": "S0001.P01",
                        "manual_cue_id": "S0001",
                        "parent_cue_index": 0,
                        "word_start": 0,
                        "word_end": 2,
                    },
                    "2": {
                        "display_page_view": True,
                        "display_page_id": "S0001.P02",
                        "manual_cue_id": "S0001",
                        "parent_cue_index": 0,
                        "word_start": 3,
                        "word_end": 5,
                    },
                }
            ),
        )
        single_parent_last = SubtitleInterface._manual_boundary_context(
            single_parent_interface,
            1,
        )
        self.assertEqual(single_parent_last["kind"], "display")
        self.assertEqual(single_parent_last["left_page_id"], "S0001.P01")

        class Toggle:
            def __init__(self):
                self.enabled = True
                self.visible = True

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setVisible(self, value):
                self.visible = bool(value)

        class TableToggle:
            def setEnabled(self, _value):
                pass

        class StatusLabel:
            def __init__(self):
                self.text = ""

            def setText(self, value):
                self.text = str(value)

        class Session:
            def __init__(self):
                self.cues = [
                    {
                        "cue_id": "S0001",
                        "source_subtitle_ids": ["S0001"],
                    }
                ]
                self.display_page_edits = [{"display_page_id": "S0001.P01"}]
                self.calls = []

            def move_display_page_boundary(
                self,
                left_page_id,
                word_count,
                *,
                move_to_next,
            ):
                self.calls.append((left_page_id, word_count, move_to_next))
                return {
                    "warnings": [],
                    "parent_subtitle_id": "S0001",
                }

        selected_rows = []
        session = Session()
        interface = SimpleNamespace(
            manual_final_session=session,
            _manual_boundary_kind="display",
            _manual_boundary_left_page_id="S0001.P01",
            _manual_boundary_word_count_value=1,
            _manual_boundary_table_left_row=0,
            _manual_parent_boundaries_dirty=False,
            _manual_page_view=True,
            _manual_package_manifest_path="saved-manual-manifest.json",
            _manual_save_request_id=0,
            _manual_save_in_progress=False,
            subtitle_table=TableToggle(),
            manual_final_undo_action=Toggle(),
            manual_final_synthesis_action=Toggle(),
            manual_draft_synthesis_action=Toggle(),
            status_label=StatusLabel(),
            tr=lambda value: value,
            _sync_manual_final_text_edits=lambda: None,
            _invalidate_manual_review_marks_for_parent_ids=lambda _ids: None,
            _apply_manual_final_session=lambda: None,
            _select_manual_boundary_row=lambda row: selected_rows.append(row),
            _apply_manual_boundary_move=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("same-parent pages must not use the parent move")
            ),
        )
        interface._invalidate_manual_final_save = MethodType(
            SubtitleInterface._invalidate_manual_final_save,
            interface,
        )
        interface._mark_manual_final_dirty = MethodType(
            SubtitleInterface._mark_manual_final_dirty,
            interface,
        )
        interface._apply_manual_display_page_boundary_move = MethodType(
            SubtitleInterface._apply_manual_display_page_boundary_move,
            interface,
        )

        with patch("app.view.subtitle_interface.InfoBar.success"), patch(
            "app.view.subtitle_interface.InfoBar.warning"
        ):
            SubtitleInterface._move_boundary_words_to_next(interface)

        self.assertEqual(session.calls, [("S0001.P01", 1, True)])
        self.assertFalse(interface._manual_parent_boundaries_dirty)
        self.assertTrue(interface._manual_page_view)
        self.assertEqual(
            session.display_page_edits,
            [{"display_page_id": "S0001.P01"}],
        )
        self.assertEqual(selected_rows, [0])
        self.assertFalse(interface.manual_final_synthesis_action.enabled)
        self.assertFalse(interface.manual_draft_synthesis_action.enabled)

        parent_calls = []
        cross_interface = SimpleNamespace(
            _manual_boundary_kind="parent",
            _manual_boundary_parent_left_index=0,
            _manual_boundary_word_count_value=2,
            _apply_manual_display_page_boundary_move=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("cross-parent pages must not use the display move")
            ),
            _apply_manual_boundary_move=lambda left_index, word_count, **kwargs: (
                parent_calls.append((left_index, word_count, kwargs))
            ),
        )
        SubtitleInterface._move_boundary_words_to_next(cross_interface)
        self.assertEqual(
            parent_calls,
            [(0, 2, {"move_to_next": True, "announce": False})],
        )

    def test_manual_boundary_selection_requires_explicit_adjustment(self):
        app, interface, moves = self._manual_boundary_interaction_fixture()

        self._select_manual_boundary_row(app, interface, 0)

        selected_rows = sorted(
            {index.row() for index in interface.subtitle_table.selectedIndexes()}
        )
        self.assertEqual(selected_rows, [0])
        self.assertIsNone(
            interface.subtitle_table.indexWidget(interface.model.index(1, 2)),
            "ordinary selection must not install controls on the next row",
        )
        self._manual_boundary_button(
            interface,
            0,
            "调整与下一屏边界",
        )
        self.assertEqual(moves, [])

        self._select_manual_boundary_row(app, interface, 1)

        selected_rows = sorted(
            {index.row() for index in interface.subtitle_table.selectedIndexes()}
        )
        self.assertEqual(selected_rows, [1])
        self.assertIsNone(
            interface.subtitle_table.indexWidget(interface.model.index(0, 2)),
        )
        self.assertIsNone(
            interface.subtitle_table.indexWidget(interface.model.index(2, 2)),
            "cross-parent selection must not install controls on the next row",
        )
        self._manual_boundary_button(
            interface,
            1,
            "调整与下一条边界",
        )
        self.assertEqual(moves, [])

    def test_manual_boundary_editor_opens_disarmed_and_blank_click_exits(self):
        app, interface, _moves = self._manual_boundary_interaction_fixture()

        self.assertFalse(interface._manual_boundary_row_armed)
        self.assertTrue(
            all(
                interface.subtitle_table.indexWidget(interface.model.index(row, 2))
                is None
                for row in range(interface.model.rowCount())
            )
        )

        self._select_manual_boundary_row(app, interface, 0)
        self.assertTrue(interface._manual_boundary_row_armed)
        self.assertIsNotNone(
            interface.subtitle_table.indexWidget(interface.model.index(0, 2))
        )

        viewport = interface.subtitle_table.viewport()
        blank_point = QPointF(viewport.width() // 2, viewport.height() - 2)
        QApplication.sendEvent(
            viewport,
            QMouseEvent(
                QEvent.MouseButtonPress,
                blank_point,
                Qt.LeftButton,
                Qt.LeftButton,
                Qt.NoModifier,
            ),
        )
        app.processEvents()

        self.assertFalse(interface._manual_boundary_row_armed)
        self.assertTrue(
            all(
                interface.subtitle_table.indexWidget(interface.model.index(row, 2))
                is None
                for row in range(interface.model.rowCount())
            )
        )

    def test_inline_undo_is_bound_to_the_selected_parent_subtitle(self):
        app, interface, _moves = self._manual_boundary_interaction_fixture()
        calls = []
        interface.manual_final_session.can_undo_for_parent = (
            lambda parent_id: parent_id == "S0001"
        )
        interface.undo_manual_final_edit = lambda parent_id="": calls.append(parent_id)

        self._select_manual_boundary_row(app, interface, 0)
        self._manual_boundary_button(interface, 0, "调整与下一屏边界").click()
        app.processEvents()
        undo = self._manual_boundary_button(interface, 0, "撤销")
        self.assertTrue(undo.isEnabled())
        undo.click()
        app.processEvents()

        self.assertEqual(calls, ["S0001"])

    def test_manual_editor_removes_redundant_legacy_controls(self):
        _app, interface, _moves = self._manual_boundary_interaction_fixture()

        self.assertFalse(hasattr(interface, "quality_report_action"))
        self.assertFalse(hasattr(interface, "manual_boundary_edit_action"))
        self.assertFalse(hasattr(interface, "manual_boundary_panel"))

    def test_manual_editor_mode_keeps_export_and_removes_upstream_menu_actions(self):
        app, interface, _moves = self._manual_boundary_interaction_fixture()

        def command_button(action):
            matches = [
                button
                for button in interface.command_bar.commandButtons
                if button.action() is action
            ]
            self.assertEqual(len(matches), 1)
            return matches[0]

        interface._set_manual_editor_mode(True)
        app.processEvents()

        self.assertFalse(interface.save_button.isHidden())
        self.assertTrue(interface.save_button.property("commandBarAvailable"))
        self.assertEqual(interface.save_button.text(), "导出字幕")
        self.assertIn(
            "txt",
            [action.text() for action in interface.save_button.menu().menuActions()],
        )
        for widget in (
            interface.layout_button,
            interface.target_language_button,
        ):
            self.assertTrue(widget.isHidden())
            self.assertFalse(widget.property("commandBarAvailable"))
        self.assertTrue(interface.start_button.isHidden())
        self.assertFalse(interface.translate_button.isVisible())
        self.assertTrue(command_button(interface.translate_button).isHidden())
        self.assertEqual(
            interface.more_menu.menuActions(),
            [
                interface.subtitle_settings_action,
                interface.open_folder_action,
                interface.import_subtitle_action,
            ],
        )
        self.assertTrue(interface.subtitle_settings_action.isVisible())
        self.assertTrue(interface.open_folder_action.isVisible())
        self.assertTrue(interface.import_subtitle_action.isVisible())
        self.assertEqual(interface.more_button.text(), "文件")
        self.assertEqual(interface.open_folder_action.text(), "打开终稿文件夹")

        interface._set_manual_editor_mode(True)
        self.assertEqual(
            interface.more_menu.menuActions(),
            [
                interface.subtitle_settings_action,
                interface.open_folder_action,
                interface.import_subtitle_action,
            ],
        )

        interface.manual_final_synthesis_action.setVisible(True)
        interface.manual_draft_synthesis_action.setVisible(False)
        app.processEvents()
        self.assertFalse(command_button(interface.manual_final_synthesis_action).isHidden())
        self.assertTrue(command_button(interface.manual_draft_synthesis_action).isHidden())

        interface.manual_final_synthesis_action.setVisible(False)
        interface.manual_draft_synthesis_action.setVisible(True)
        app.processEvents()
        self.assertTrue(command_button(interface.manual_final_synthesis_action).isHidden())
        self.assertFalse(command_button(interface.manual_draft_synthesis_action).isHidden())

        interface._set_manual_editor_mode(False)
        app.processEvents()

        self.assertFalse(interface.save_button.isHidden())
        self.assertTrue(interface.save_button.property("commandBarAvailable"))
        self.assertEqual(interface.save_button.text(), "保存")
        for widget in (
            interface.layout_button,
            interface.target_language_button,
        ):
            self.assertFalse(widget.isHidden())
            self.assertTrue(widget.property("commandBarAvailable"))
        self.assertFalse(interface.start_button.isHidden())
        self.assertTrue(interface.translate_button.isVisible())
        self.assertFalse(command_button(interface.translate_button).isHidden())
        self.assertEqual(
            interface.more_menu.menuActions(),
            [
                interface.optimize_button,
                interface.prompt_button,
                interface.subtitle_settings_action,
                interface.open_folder_action,
                interface.import_subtitle_action,
            ],
        )
        self.assertTrue(interface.subtitle_settings_action.isVisible())
        self.assertEqual(interface.more_button.text(), "更多")

        interface._set_manual_editor_mode(False)
        self.assertEqual(
            interface.more_menu.menuActions(),
            [
                interface.optimize_button,
                interface.prompt_button,
                interface.subtitle_settings_action,
                interface.open_folder_action,
                interface.import_subtitle_action,
            ],
        )

    def test_failed_manual_session_load_restores_processing_controls(self):
        _app, interface, _moves = self._manual_boundary_interaction_fixture()
        interface._set_manual_editor_mode(True)

        with patch.object(
            ManualFinalSubtitleSession,
            "load_for_subtitle",
            side_effect=ManualFinalSubtitleEditError("not a stable package"),
        ):
            interface._load_manual_final_session(Path("standalone.srt"))

        self.assertFalse(interface.save_button.isHidden())
        self.assertFalse(interface.start_button.isHidden())
        self.assertTrue(interface.translate_button.isVisible())
        self.assertEqual(interface.more_button.text(), "更多")
        self.assertEqual(interface.open_folder_action.text(), "打开输出文件夹")

    def test_failed_manual_session_load_clears_previous_manual_runtime_state(self):
        app, interface, _moves = self._manual_boundary_interaction_fixture()
        self._select_manual_boundary_row(app, interface, 0)
        interface._toggle_manual_boundary_edit()
        interface._choose_manual_boundary_direction("next")
        interface._manual_model_has_pending_edits = True
        interface._manual_has_unsaved_changes = True
        interface._manual_clean_state_fingerprint = "old-session"

        with patch.object(
            ManualFinalSubtitleSession,
            "load_for_subtitle",
            side_effect=ManualFinalSubtitleEditError("not a stable package"),
        ):
            interface._load_manual_final_session(Path("standalone.srt"))

        self.assertIsNone(interface.manual_final_session)
        self.assertFalse(interface._manual_model_has_pending_edits)
        self.assertFalse(interface._manual_has_unsaved_changes)
        self.assertEqual(interface._manual_clean_state_fingerprint, "")
        self.assertFalse(interface._manual_boundary_row_armed)
        self.assertFalse(interface._manual_boundary_edit_active)
        self.assertEqual(interface._manual_boundary_move_direction, "")
        self.assertEqual(interface._manual_boundary_index_widgets, [])
        self.assertTrue(interface._confirm_discard_manual_edits("继续导入"))
        for action in (
            interface.manual_page_view_action,
            interface.manual_final_save_action,
            interface.manual_final_undo_action,
            interface.manual_final_synthesis_action,
            interface.manual_draft_synthesis_action,
        ):
            self.assertFalse(action.isEnabled())
            self.assertFalse(action.isVisible())

    def test_open_folder_uses_manual_manifest_without_a_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "manual-package"
            package_dir.mkdir()
            manifest_path = package_dir / "stable-final-manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            interface = SimpleNamespace(
                task=None,
                manual_final_session=None,
                subtitle_path="",
                _manual_package_manifest_path=str(manifest_path),
                tr=lambda value: value,
            )

            with patch("app.view.subtitle_interface.os.startfile") as open_folder:
                SubtitleInterface.on_open_folder_clicked(interface)

            open_folder.assert_called_once_with(str(package_dir))

    def test_open_folder_uses_result_root_outside_manual_editor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result_dir = Path(temp_dir) / "episode-处理结果"
            package_dir = result_dir / "人工终稿字幕包"
            package_dir.mkdir(parents=True)
            manifest_path = package_dir / "stable-final-manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            interface = SimpleNamespace(
                task=None,
                manual_final_session=None,
                subtitle_path="",
                _manual_package_manifest_path=str(manifest_path),
                tr=lambda value: value,
            )

            with patch("app.view.subtitle_interface.os.startfile") as open_folder:
                SubtitleInterface.on_open_folder_clicked(interface)

            open_folder.assert_called_once_with(str(result_dir))

    def test_manual_boundary_entry_widget_paints_opaque_theme_background(self):
        app, interface, _ = self._manual_boundary_interaction_fixture()
        self._select_manual_boundary_row(app, interface, 0)

        widget = interface.subtitle_table.indexWidget(interface.model.index(0, 2))
        self.assertIsNotNone(widget)
        style = widget.styleSheet().replace(" ", "").lower()
        self.assertIn("background:", style)
        self.assertNotIn("background:transparent", style)

        image = widget.grab().toImage()
        sample = image.pixelColor(image.width() // 2, image.height() - 6)
        expected = QColor("#292929" if isDarkTheme() else "#fffdf5")
        self.assertEqual(sample.alpha(), 255)
        self.assertLessEqual(abs(sample.red() - expected.red()), 8)
        self.assertLessEqual(abs(sample.green() - expected.green()), 8)
        self.assertLessEqual(abs(sample.blue() - expected.blue()), 8)

    def test_manual_boundary_widgets_hide_immediately_before_model_switch(self):
        app, interface, _ = self._manual_boundary_interaction_fixture()
        self._select_manual_boundary_row(app, interface, 0)
        self._manual_boundary_button(
            interface,
            0,
            "调整与下一屏边界",
        ).click()
        app.processEvents()

        old_widgets = [
            entry[2]
            for entry in interface._manual_boundary_index_widgets
            if len(entry) > 2
        ]
        self.assertEqual(len(old_widgets), 2)
        self.assertTrue(all(widget.isVisible() for widget in old_widgets))

        interface._clear_manual_boundary_index_widgets()
        interface.model.update_all(
            {
                "1": {
                    "start_time": 0,
                    "end_time": 1500,
                    "original_subtitle": "new parent subtitle",
                    "translated_subtitle": "新父字幕",
                },
                "2": {
                    "start_time": 1500,
                    "end_time": 3000,
                    "original_subtitle": "next parent subtitle",
                    "translated_subtitle": "下一条父字幕",
                },
            }
        )

        self.assertTrue(all(not widget.isVisible() for widget in old_widgets))
        self.assertIsNone(
            interface.subtitle_table.indexWidget(interface.model.index(0, 2))
        )
        self.assertIsNone(
            interface.subtitle_table.indexWidget(interface.model.index(1, 2))
        )
        self.assertEqual(interface._manual_boundary_index_widgets, [])

    def test_manual_boundary_direction_preview_and_cancel_are_non_mutating(self):
        app, interface, moves = self._manual_boundary_interaction_fixture()
        self._select_manual_boundary_row(app, interface, 0)

        self._manual_boundary_button(
            interface,
            0,
            "调整与下一屏边界",
        ).click()
        app.processEvents()

        self.assertIsNotNone(
            interface.subtitle_table.indexWidget(interface.model.index(1, 2)),
            "explicit adjustment must enter the two-row mode",
        )
        self.assertNotIn(
            "<span",
            self._manual_boundary_rich_text(interface, 0),
            "no source words are highlighted before choosing a direction",
        )
        self.assertNotIn(
            "<span",
            self._manual_boundary_rich_text(interface, 1),
            "no target words are highlighted before choosing a direction",
        )
        self.assertTrue(
            self._manual_boundary_button(interface, 0, "撤销").isEnabled(),
        )

        self._manual_boundary_button(interface, 0, "移到下一屏").click()
        app.processEvents()

        self.assertEqual(moves, [], "choosing a direction must not move words")
        self.assertIn(
            "<span",
            self._manual_boundary_rich_text(interface, 0),
            "move-to-next highlights only the left/source suffix",
        )
        self.assertNotIn(
            "<span",
            self._manual_boundary_rich_text(interface, 1),
            "move-to-next must not highlight the target row",
        )

        self._manual_boundary_button(interface, 0, "取消").click()
        app.processEvents()

        self.assertEqual(moves, [], "cancel must leave subtitle boundaries unchanged")
        self.assertIsNone(
            interface.subtitle_table.indexWidget(interface.model.index(1, 2)),
            "cancel returns to the single-row entry state",
        )

    def test_manual_boundary_direction_and_word_count_refresh_source_highlight(self):
        app, interface, moves = self._manual_boundary_interaction_fixture()
        self._select_manual_boundary_row(app, interface, 0)
        self._manual_boundary_button(
            interface,
            0,
            "调整与下一屏边界",
        ).click()
        app.processEvents()

        self._manual_boundary_button(interface, 0, "移到下一屏").click()
        app.processEvents()
        count_box = interface.manual_boundary_word_count
        left_widget = interface.subtitle_table.indexWidget(
            interface.model.index(0, 2)
        )
        right_widget = interface.subtitle_table.indexWidget(
            interface.model.index(1, 2)
        )
        count_box.setFocus()
        count_box.stepUp()
        app.processEvents()

        self.assertIs(interface.manual_boundary_word_count, count_box)
        self.assertIs(
            interface.subtitle_table.indexWidget(interface.model.index(0, 2)),
            left_widget,
        )
        self.assertIs(
            interface.subtitle_table.indexWidget(interface.model.index(1, 2)),
            right_widget,
        )
        self.assertTrue(interface._manual_boundary_edit_active)
        self._manual_boundary_button(interface, 0, "确认移动 2 个词")
        left_html = self._manual_boundary_rich_text(interface, 0)
        right_html = self._manual_boundary_rich_text(interface, 1)
        self.assertIn(">beta gamma</span>", left_html)
        self.assertNotIn("<span", right_html)
        self.assertEqual(moves, [], "preview changes must not move words")

        self._manual_boundary_button(interface, 1, "移到上一屏").click()
        app.processEvents()

        left_html = self._manual_boundary_rich_text(interface, 0)
        right_html = self._manual_boundary_rich_text(interface, 1)
        self.assertEqual(interface.manual_boundary_word_count.value(), 1)
        self.assertNotIn("<span", left_html)
        self.assertIn(">delta</span>", right_html)
        self.assertNotIn(">delta epsilon</span>", right_html)
        self.assertEqual(moves, [], "changing direction must stay non-mutating")

    def test_manual_boundary_preview_highlights_the_expanded_numeric_phrase(self):
        app, interface, moves = self._manual_boundary_interaction_fixture()
        interface.manual_final_session.expanded_manual_boundary_word_count = (
            lambda **kwargs: 2
            if kwargs["move_to_next"] and kwargs["requested_word_count"] == 1
            else kwargs["requested_word_count"]
        )
        self._select_manual_boundary_row(app, interface, 0)
        self._manual_boundary_button(
            interface,
            0,
            "调整与下一屏边界",
        ).click()
        app.processEvents()

        self._manual_boundary_button(interface, 0, "移到下一屏").click()
        app.processEvents()

        self.assertEqual(interface.manual_boundary_word_count.value(), 2)
        self.assertIn(
            ">beta gamma</span>",
            self._manual_boundary_rich_text(interface, 0),
        )
        self._manual_boundary_button(interface, 0, "确认移动 2 个词")
        self.assertEqual(moves, [])

    def test_dirty_parent_page_refresh_dispatches_save_then_reuses_frozen_blueprint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = self._manual_page_boundary_session(Path(temp_dir))
            session.move_suffix_to_next(0, 1)
            save_requests = []
            interface = SimpleNamespace(
                manual_final_session=session,
                _manual_parent_boundaries_dirty=True,
                _manual_refresh_requested=False,
                save_manual_final_output=lambda: save_requests.append("refresh"),
            )

            SubtitleInterface.toggle_manual_page_view(interface)

            self.assertTrue(interface._manual_refresh_requested)
            self.assertEqual(save_requests, ["refresh"])

            first_paths = session.save_to_source_folder()
            first_manifest = json.loads(
                Path(first_paths["manifest_path"]).read_text(encoding="utf-8")
            )
            refreshed = ManualFinalSubtitleSession.load_from_manifest(
                Path(first_paths["manifest_path"])
            )
            with patch.object(
                podcast_learning_video,
                "build_article_display_page_blueprint",
                side_effect=AssertionError(
                    "a refreshed parent-boundary plan must be reused on follow-up save"
                ),
            ):
                second_paths = refreshed.save_to_source_folder()
            second_manifest = json.loads(
                Path(second_paths["manifest_path"]).read_text(encoding="utf-8")
            )

            self.assertEqual(
                second_paths["render_blocked"],
                first_paths["render_blocked"],
            )
            self.assertEqual(
                second_manifest["display_page_translation_sha256"],
                first_manifest["display_page_translation_sha256"],
            )

    def test_dirty_parent_split_queues_one_refresh_before_mutating(self):
        split_calls = []
        save_calls = []
        statuses = []

        class Session:
            cues = [{"cue_id": "S0001"}]

            @staticmethod
            def split_parent_into_display_pages(parent_id, page_count):
                split_calls.append((parent_id, page_count))

        interface = SimpleNamespace(
            manual_final_session=Session(),
            _manual_parent_boundaries_dirty=True,
            _manual_save_in_progress=False,
            _manual_save_request_id=7,
            _manual_pending_page_split=None,
            _manual_refresh_requested=False,
            status_label=SimpleNamespace(
                setText=lambda value: statuses.append(str(value))
            ),
            tr=lambda value: value,
        )

        def save_once():
            save_calls.append("save")
            interface._manual_save_request_id += 1
            return interface._manual_save_request_id

        interface.save_manual_final_output = save_once

        with patch("app.view.subtitle_interface.InfoBar.warning"):
            SubtitleInterface._split_parent_into_display_pages(
                interface,
                "S0001",
                3,
            )

        self.assertEqual(save_calls, ["save"])
        self.assertEqual(interface._manual_pending_page_split, ("S0001", 3, 8))
        self.assertTrue(interface._manual_refresh_requested)
        self.assertEqual(split_calls, [])
        self.assertIn("完成后将 S0001 分为 3 屏", statuses[-1])

    def test_pending_split_runs_once_after_matching_refresh(self):
        split_calls = []
        refreshed_session = SimpleNamespace(subtitle_path=Path("refreshed.srt"))
        interface = SimpleNamespace(
            manual_final_session=SimpleNamespace(subtitle_path=Path("old.srt")),
            subtitle_path="old.srt",
            _manual_save_request_id=12,
            _manual_save_in_progress=True,
            _manual_pending_page_split=("S0001", 4, 12),
            _manual_refresh_requested=True,
            _manual_parent_boundaries_dirty=True,
            _manual_page_view=False,
            _manual_package_manifest_path="",
            _set_manual_final_save_busy=lambda busy: None,
            _apply_manual_final_session=lambda: None,
            _split_parent_into_display_pages=lambda parent_id, page_count: (
                split_calls.append(
                    (
                        parent_id,
                        page_count,
                        interface._manual_parent_boundaries_dirty,
                    )
                )
            ),
            status_label=SimpleNamespace(setText=lambda _value: None),
            tr=lambda value: value,
        )

        with patch.object(
            ManualFinalSubtitleSession,
            "load_from_manifest",
            return_value=refreshed_session,
        ):
            SubtitleInterface._apply_manual_final_save_result(
                interface,
                12,
                {"manifest_path": "refreshed-manifest.json"},
                "",
            )

        self.assertEqual(split_calls, [("S0001", 4, False)])
        self.assertIsNone(interface._manual_pending_page_split)
        self.assertFalse(interface._manual_refresh_requested)
        self.assertIs(interface.manual_final_session, refreshed_session)

    def test_pending_split_is_cleared_when_save_or_reload_fails(self):
        def make_interface():
            split_calls = []
            interface = SimpleNamespace(
                manual_final_session=SimpleNamespace(subtitle_path=Path("old.srt")),
                _manual_save_request_id=5,
                _manual_save_in_progress=True,
                _manual_pending_page_split=("S0001", 2, 5),
                _manual_refresh_requested=True,
                _manual_parent_boundaries_dirty=True,
                _manual_package_manifest_path="",
                _set_manual_final_save_busy=lambda busy: None,
                _split_parent_into_display_pages=lambda *args: split_calls.append(args),
                status_label=SimpleNamespace(setText=lambda _value: None),
                tr=lambda value: value,
            )
            return interface, split_calls

        failed, failed_split_calls = make_interface()
        with patch("app.view.subtitle_interface.InfoBar.warning"):
            SubtitleInterface._apply_manual_final_save_result(
                failed,
                5,
                {},
                "save failed",
            )
        self.assertIsNone(failed._manual_pending_page_split)
        self.assertFalse(failed._manual_refresh_requested)
        self.assertTrue(failed._manual_parent_boundaries_dirty)
        self.assertEqual(failed_split_calls, [])

        reload_failed, reload_split_calls = make_interface()
        with patch.object(
            ManualFinalSubtitleSession,
            "load_from_manifest",
            side_effect=ManualFinalSubtitleEditError("reload failed"),
        ), patch("app.view.subtitle_interface.InfoBar.warning"):
            SubtitleInterface._apply_manual_final_save_result(
                reload_failed,
                5,
                {"manifest_path": "broken-manifest.json"},
                "",
            )
        self.assertIsNone(reload_failed._manual_pending_page_split)
        self.assertFalse(reload_failed._manual_refresh_requested)
        self.assertTrue(reload_failed._manual_parent_boundaries_dirty)
        self.assertEqual(reload_split_calls, [])

    def test_reload_failure_keeps_current_actual_page_session_and_view(self):
        current_session = SimpleNamespace(subtitle_path=Path("current.srt"))
        apply_calls = []
        interface = SimpleNamespace(
            manual_final_session=current_session,
            _manual_save_request_id=9,
            _manual_save_in_progress=True,
            _manual_pending_page_split=None,
            _manual_refresh_requested=False,
            _manual_active_save_context={
                "request_id": 9,
                "refresh_requested": False,
            },
            _manual_parent_boundaries_dirty=False,
            _manual_page_view=True,
            _manual_has_unsaved_changes=True,
            _manual_package_manifest_path="",
            _set_manual_final_save_busy=lambda _busy: None,
            _apply_manual_final_session=lambda: apply_calls.append(True),
            status_label=SimpleNamespace(setText=lambda _value: None),
            tr=lambda value: value,
        )

        with patch.object(
            ManualFinalSubtitleSession,
            "load_from_manifest",
            side_effect=ManualFinalSubtitleEditError("reload failed"),
        ), patch("app.view.subtitle_interface.InfoBar.warning"):
            SubtitleInterface._apply_manual_final_save_result(
                interface,
                9,
                {"manifest_path": "broken-manifest.json"},
                "",
            )

        self.assertIs(interface.manual_final_session, current_session)
        self.assertTrue(interface._manual_page_view)
        self.assertFalse(interface._manual_parent_boundaries_dirty)
        self.assertTrue(interface._manual_has_unsaved_changes)
        self.assertEqual(apply_calls, [])

    def test_manual_sync_rejects_mutation_while_save_snapshot_is_running(self):
        interface = SimpleNamespace(
            manual_final_session=object(),
            _manual_save_in_progress=True,
        )

        with self.assertRaisesRegex(
            ManualFinalSubtitleEditError,
            "正在保存",
        ):
            SubtitleInterface._sync_manual_final_text_edits(interface)

    def test_clean_parent_split_runs_immediately_without_refresh(self):
        split_calls = []
        dirty_calls = []
        selected_rows = []

        class Session:
            cues = [{"cue_id": "S0001"}]

            @staticmethod
            def split_parent_into_display_pages(parent_id, page_count):
                split_calls.append((parent_id, page_count))
                return {"page_count": page_count}

        interface = SimpleNamespace(
            manual_final_session=Session(),
            _manual_parent_boundaries_dirty=False,
            _manual_save_in_progress=False,
            _manual_boundary_edit_active=True,
            _manual_boundary_move_direction="next",
            _manual_page_view=False,
            _sync_manual_final_text_edits=lambda: None,
            _invalidate_manual_review_marks_for_parent_ids=lambda _ids: None,
            _mark_manual_final_dirty=lambda **kwargs: dirty_calls.append(kwargs),
            _apply_manual_final_session=lambda: None,
            _select_manual_boundary_row=lambda row: selected_rows.append(row),
            save_manual_final_output=lambda: (_ for _ in ()).throw(
                AssertionError("clean split must not save before splitting")
            ),
            model=SimpleNamespace(
                _data={"1": {"manual_cue_id": "S0001"}}
            ),
            status_label=SimpleNamespace(setText=lambda _value: None),
            tr=lambda value: value,
        )

        with patch("app.view.subtitle_interface.InfoBar.success"), patch(
            "app.view.subtitle_interface.InfoBar.warning"
        ):
            SubtitleInterface._split_parent_into_display_pages(
                interface,
                "S0001",
                2,
            )

        self.assertEqual(split_calls, [("S0001", 2)])
        self.assertEqual(dirty_calls, [{"invalidate_pages": False}])
        self.assertEqual(selected_rows, [0])
        self.assertTrue(interface._manual_page_view)

    def test_parent_split_retries_only_after_high_risk_confirmation(self):
        split_calls = []
        warning_messages = []

        class Session:
            cues = [{"cue_id": "S0001"}]

            @staticmethod
            def split_parent_into_display_pages(
                parent_id,
                page_count,
                *,
                allow_high_risk=False,
            ):
                split_calls.append((parent_id, page_count, allow_high_risk))
                if not allow_high_risk:
                    raise ManualFinalSubtitleEditError(
                        "没有安全切点",
                        code=(
                            "manual_high_risk_page_split_"
                            "confirmation_required"
                        ),
                    )
                return {
                    "changed": True,
                    "page_count": page_count,
                    "high_risk_override": True,
                }

        interface = SimpleNamespace(
            manual_final_session=Session(),
            _manual_parent_boundaries_dirty=False,
            _manual_save_in_progress=False,
            _manual_boundary_edit_active=True,
            _manual_boundary_move_direction="next",
            _manual_page_view=False,
            _sync_manual_final_text_edits=lambda: None,
            _confirm_high_risk_manual_page_split=lambda _target, _count: True,
            _queue_manual_structure_action=(
                lambda callback, *args, **kwargs: callback(*args, **kwargs)
            ),
            _invalidate_manual_review_marks_for_parent_ids=lambda _ids: None,
            _mark_manual_final_dirty=lambda **_kwargs: None,
            _apply_manual_final_session=lambda: None,
            _select_manual_boundary_row=lambda _row: None,
            model=SimpleNamespace(
                _data={"1": {"manual_cue_id": "S0001"}}
            ),
            status_label=SimpleNamespace(setText=lambda _value: None),
            tr=lambda value: value,
        )
        interface._split_parent_into_display_pages = MethodType(
            SubtitleInterface._split_parent_into_display_pages,
            interface,
        )

        with patch("app.view.subtitle_interface.InfoBar.success"), patch(
            "app.view.subtitle_interface.InfoBar.warning",
            side_effect=lambda title, content, **_kwargs: warning_messages.append(
                (str(title), str(content))
            ),
        ):
            interface._split_parent_into_display_pages("S0001", 2)

        self.assertEqual(
            split_calls,
            [("S0001", 2, False), ("S0001", 2, True)],
        )
        self.assertTrue(
            any("人工兜底分屏" in title for title, _ in warning_messages)
        )

    def test_parent_row_context_menu_offers_page_count_actions(self):
        class Index:
            @staticmethod
            def isValid():
                return True

            @staticmethod
            def row():
                return 0

        index = Index()

        class Table:
            @staticmethod
            def indexAt(_pos):
                return index

            @staticmethod
            def selectedIndexes():
                return [index]

            @staticmethod
            def clearSelection():
                pass

            @staticmethod
            def selectRow(_row):
                pass

            @staticmethod
            def viewport():
                return SimpleNamespace(mapToGlobal=lambda pos: pos)

        class Signal:
            def __init__(self):
                self.callback = None

            def connect(self, callback):
                self.callback = callback

        class ActionDouble:
            def __init__(self, _icon, text):
                self.text = str(text)
                self.triggered = Signal()
                self.enabled = True

            def setShortcut(self, _shortcut):
                pass

            def setEnabled(self, value):
                self.enabled = bool(value)

        menus = []

        class MenuDouble:
            def __init__(self, parent=None):
                self.actions = []
                menus.append(self)

            def addAction(self, action):
                self.actions.append(action)

            def addSeparator(self):
                pass

            def exec(self, _pos):
                pass

        interface = SimpleNamespace(
            subtitle_table=Table(),
            model=SimpleNamespace(
                _data={
                    "1": {
                        "manual_cue_id": "S0001",
                        "display_page_view": False,
                    }
                }
            ),
            manual_final_session=SimpleNamespace(
                cues=[{"cue_id": "S0001", "word_start": 0, "word_end": 2}]
            ),
            tr=lambda value: value,
            merge_selected_rows=lambda _rows: None,
            _split_parent_into_display_pages=lambda *_args: None,
            _move_suffix_to_next=lambda _row: None,
            _move_prefix_to_previous=lambda _row: None,
            _preview_manual_tail_trim=lambda _row: None,
            _delete_manual_tail_from_row=lambda _row: None,
        )

        with patch("app.view.subtitle_interface.Action", ActionDouble), patch(
            "app.view.subtitle_interface.RoundMenu",
            MenuDouble,
        ):
            SubtitleInterface.show_context_menu(interface, object())

        action_texts = [action.text for action in menus[0].actions]
        self.assertFalse(any("整条字幕调整为" in text for text in action_texts))
        self.assertNotIn("将 S0001 拆成 2 屏", action_texts)
        self.assertNotIn("将 S0001 拆成 3 屏", action_texts)
        self.assertNotIn("将 S0001 拆成 4 屏", action_texts)
        self.assertNotIn("合并相邻字幕", action_texts)
        self.assertNotIn("将末尾词移到下一条", action_texts)
        self.assertNotIn("将开头词移到上一条", action_texts)
        self.assertIn("修正当前英文（保持时间轴）", action_texts)
        self.assertIn("隐藏这条字幕（保留音频）", action_texts)
        self.assertIn("隐藏整条字幕并静音这段", action_texts)

    def test_context_menu_keeps_merge_for_contiguous_parent_rows(self):
        class Index:
            def __init__(self, row):
                self._row = row

            def isValid(self):
                return True

            def row(self):
                return self._row

        indexes = [Index(0), Index(1)]

        class Table:
            @staticmethod
            def indexAt(_pos):
                return indexes[0]

            @staticmethod
            def selectedIndexes():
                return indexes

            @staticmethod
            def clearSelection():
                pass

            @staticmethod
            def selectRow(_row):
                pass

            @staticmethod
            def viewport():
                return SimpleNamespace(mapToGlobal=lambda pos: pos)

        class Signal:
            def connect(self, _callback):
                pass

        class ActionDouble:
            def __init__(self, _icon, text):
                self.text = str(text)
                self.triggered = Signal()

            def setEnabled(self, _enabled):
                pass

            def setShortcut(self, _shortcut):
                pass

        menus = []

        class MenuDouble:
            def __init__(self, parent=None):
                self.actions = []
                menus.append(self)

            def addAction(self, action):
                self.actions.append(action)

            def exec(self, _pos):
                pass

        interface = SimpleNamespace(
            subtitle_table=Table(),
            model=SimpleNamespace(
                _data={
                    "1": {"display_page_view": False},
                    "2": {"display_page_view": False},
                }
            ),
            manual_final_session=None,
            tr=lambda value: value,
            merge_selected_rows=lambda _rows: None,
        )

        with patch("app.view.subtitle_interface.Action", ActionDouble), patch(
            "app.view.subtitle_interface.RoundMenu",
            MenuDouble,
        ):
            SubtitleInterface.show_context_menu(interface, object())

        self.assertEqual(
            [action.text for action in menus[0].actions],
            ["复制英文", "合并相邻字幕"],
        )

    def test_manual_parent_merge_is_queued_by_stable_ids(self):
        class Index:
            def __init__(self, row):
                self._row = row

            def isValid(self):
                return True

            def row(self):
                return self._row

        indexes = [Index(0), Index(1)]

        class Table:
            @staticmethod
            def indexAt(_pos):
                return indexes[0]

            @staticmethod
            def selectedIndexes():
                return indexes

            @staticmethod
            def clearSelection():
                pass

            @staticmethod
            def selectRow(_row):
                pass

            @staticmethod
            def viewport():
                return SimpleNamespace(mapToGlobal=lambda pos: pos)

        class Signal:
            def __init__(self):
                self.callback = None

            def connect(self, callback):
                self.callback = callback

        class ActionDouble:
            def __init__(self, _icon, text):
                self.text = str(text)
                self.triggered = Signal()

            def setShortcut(self, _shortcut):
                pass

        menus = []

        class MenuDouble:
            def __init__(self, parent=None):
                self.actions = []
                menus.append(self)

            def addAction(self, action):
                self.actions.append(action)

            def exec(self, _pos):
                pass

        scheduled = []
        stable_calls = []
        direct_calls = []
        interface = SimpleNamespace(
            subtitle_table=Table(),
            model=SimpleNamespace(
                _data={
                    "1": {
                        "manual_cue_id": "S0001",
                        "display_page_view": False,
                    },
                    "2": {
                        "manual_cue_id": "S0002",
                        "display_page_view": False,
                    },
                }
            ),
            manual_final_session=SimpleNamespace(cues=[]),
            tr=lambda value: value,
            merge_selected_rows=lambda rows: direct_calls.append(rows),
            _merge_manual_rows_by_stable_ids=(
                lambda stable_ids, page_mode: stable_calls.append(
                    (stable_ids, page_mode)
                )
            ),
            _queue_manual_structure_action=(
                lambda callback, *args, **kwargs: scheduled.append(
                    lambda: callback(*args, **kwargs)
                )
            ),
        )

        with patch("app.view.subtitle_interface.Action", ActionDouble), patch(
            "app.view.subtitle_interface.RoundMenu",
            MenuDouble,
        ):
            SubtitleInterface.show_context_menu(interface, object())

        merge_action = next(
            action
            for action in menus[0].actions
            if action.text == "合并相邻字幕"
        )
        merge_action.triggered.callback()
        self.assertEqual(direct_calls, [])
        self.assertEqual(len(scheduled), 1)
        scheduled[0]()
        self.assertEqual(stable_calls, [(('S0001', 'S0002'), False)])

    def test_manual_merge_stable_ids_are_resolved_after_queueing(self):
        merge_calls = []
        interface = SimpleNamespace(
            model=SimpleNamespace(
                _data={
                    "1": {
                        "manual_cue_id": "S0000",
                        "display_page_view": False,
                    },
                    "2": {
                        "manual_cue_id": "S0001",
                        "display_page_view": False,
                    },
                    "3": {
                        "manual_cue_id": "S0002",
                        "display_page_view": False,
                    },
                }
            ),
            merge_selected_rows=lambda rows: merge_calls.append(rows),
            tr=lambda value: value,
        )

        SubtitleInterface._merge_manual_rows_by_stable_ids(
            interface,
            ("S0001", "S0002"),
            False,
        )

        self.assertEqual(merge_calls, [[1, 2]])

    def test_actual_page_context_menu_splits_selected_page_not_existing_parent_count(self):
        class Index:
            @staticmethod
            def isValid():
                return True

            @staticmethod
            def row():
                return 0

        index = Index()

        class Table:
            @staticmethod
            def indexAt(_pos):
                return index

            @staticmethod
            def selectedIndexes():
                return [index]

            @staticmethod
            def clearSelection():
                pass

            @staticmethod
            def selectRow(_row):
                pass

            @staticmethod
            def viewport():
                return SimpleNamespace(mapToGlobal=lambda pos: pos)

        class Signal:
            def __init__(self):
                self.callback = None

            def connect(self, callback):
                self.callback = callback

        class ActionDouble:
            def __init__(self, _icon, text):
                self.text = str(text)
                self.triggered = Signal()

            def setEnabled(self, _enabled):
                pass

        menus = []

        class MenuDouble:
            def __init__(self, parent=None):
                self.actions = []
                menus.append(self)

            def addAction(self, action):
                self.actions.append(action)

            def addSeparator(self):
                pass

            def exec(self, _pos):
                pass

        split_calls = []
        split_page_calls = []
        merge_page_calls = []
        confirm_calls = []
        boundary_calls = []
        confirm_all_calls = []
        scheduled = []
        interface = SimpleNamespace(
            subtitle_table=Table(),
            model=SimpleNamespace(
                _data={
                    "1": {
                        "manual_cue_id": "S0216",
                        "display_page_view": True,
                        "display_page_id": "S0216.P01",
                        "word_start": 100,
                        "word_end": 108,
                    },
                    "2": {
                        "manual_cue_id": "S0216",
                        "display_page_view": True,
                        "display_page_id": "S0216.P02",
                        "word_start": 109,
                        "word_end": 130,
                    },
                }
            ),
            manual_final_session=SimpleNamespace(cues=[{"cue_id": "S0216"}]),
            tr=lambda value: value,
            merge_selected_rows=lambda _rows: None,
            _merge_display_page_with_next=lambda page_id: merge_page_calls.append(
                page_id
            ),
            _split_display_page=lambda page_id: split_page_calls.append(page_id),
            _split_parent_into_display_pages=(
                lambda parent_id, page_count, **kwargs: split_calls.append(
                    (parent_id, page_count, kwargs.get("focus_word_id"))
                )
            ),
            _confirm_current_display_page_chinese=lambda page_id: confirm_calls.append(page_id),
            _confirm_current_display_page_boundary=lambda page_id: boundary_calls.append(page_id),
            _confirm_all_nonblocking_display_page_reviews=lambda: confirm_all_calls.append(True),
            _queue_manual_structure_action=(
                lambda callback, *args, **kwargs: scheduled.append(
                    lambda: callback(*args, **kwargs)
                )
            ),
        )

        with patch("app.view.subtitle_interface.Action", ActionDouble), patch(
            "app.view.subtitle_interface.RoundMenu",
            MenuDouble,
        ):
            SubtitleInterface.show_context_menu(interface, object())

        action_texts = [action.text for action in menus[0].actions]
        self.assertIn("整条字幕调整为 3 屏", action_texts)
        self.assertIn("整条字幕调整为 4 屏", action_texts)
        self.assertIn("整条字幕调整为 5 屏", action_texts)
        self.assertIn("整条字幕调整为 6 屏", action_texts)
        self.assertIn("仅将当前屏拆为 2 屏", action_texts)
        self.assertIn("与下一屏合并", action_texts)
        self.assertNotIn("试听从当前页删除的切点", action_texts)
        self.assertIn("从当前页删除到结尾", action_texts)
        self.assertIn("确认当前中文", action_texts)
        self.assertIn("确认当前分页边界", action_texts)
        self.assertIn("确认全部非阻断提醒", action_texts)
        by_text = {action.text: action for action in menus[0].actions}
        by_text["与下一屏合并"].triggered.callback()
        by_text["确认当前中文"].triggered.callback()
        by_text["确认当前分页边界"].triggered.callback()
        by_text["确认全部非阻断提醒"].triggered.callback()
        self.assertEqual(merge_page_calls, [])
        self.assertEqual(confirm_calls, ["S0216.P01"])
        self.assertEqual(boundary_calls, ["S0216.P01"])
        self.assertEqual(confirm_all_calls, [True])
        scheduled.pop(0)()
        self.assertEqual(merge_page_calls, ["S0216.P01"])
        by_text["整条字幕调整为 3 屏"].triggered.callback()
        by_text["仅将当前屏拆为 2 屏"].triggered.callback()
        self.assertEqual(split_calls, [])
        self.assertEqual(split_page_calls, [])
        while scheduled:
            scheduled.pop(0)()
        self.assertEqual(split_calls, [("S0216", 3, 100)])
        self.assertEqual(split_page_calls, ["S0216.P01"])

    def test_long_caption_queue_restores_parent_identity_or_nearest_row(self):
        interface = SimpleNamespace(
            _manual_long_caption_parent_id="S0106",
            _manual_long_caption_queue_row=2,
        )
        queue = [
            {"parent_subtitle_id": "S0005"},
            {"parent_subtitle_id": "S0106"},
            {"parent_subtitle_id": "S0147"},
        ]

        self.assertEqual(
            SubtitleInterface._manual_long_caption_initial_row(interface, queue),
            1,
        )

        interface._manual_long_caption_parent_id = "S0093"
        self.assertEqual(
            SubtitleInterface._manual_long_caption_initial_row(interface, queue),
            2,
        )

        interface._manual_long_caption_queue_row = 99
        self.assertEqual(
            SubtitleInterface._manual_long_caption_initial_row(interface, queue),
            2,
        )
        self.assertEqual(
            SubtitleInterface._manual_long_caption_initial_row(interface, []),
            -1,
        )

    def test_manual_review_dialog_uses_dark_native_widget_palette(self):
        interface = SubtitleInterface()
        interface.setAttribute(Qt.WA_DontShowOnScreen, True)
        dialog = QDialog(interface)
        listing = QListWidget(dialog)
        self.addCleanup(
            lambda: (
                dialog.close(),
                interface.close(),
                self._qt_app.processEvents(),
            )
        )

        with patch("app.view.subtitle_interface.isDarkTheme", return_value=True):
            interface._style_manual_review_dialog(dialog, listing)

        style = dialog.styleSheet()
        self.assertEqual(dialog.objectName(), "manualReviewDialog")
        self.assertEqual(listing.objectName(), "manualReviewList")
        self.assertTrue(listing.wordWrap())
        self.assertEqual(listing.textElideMode(), Qt.ElideNone)
        self.assertEqual(
            listing.horizontalScrollBarPolicy(),
            Qt.ScrollBarAlwaysOff,
        )
        self.assertIn("background-color: #202020", style)
        self.assertIn("background-color: #292929", style)
        self.assertIn("color: #f2f2f2", style)

    def test_boundary_editor_requires_an_explicit_row_click_and_can_be_disarmed(self):
        calls = []

        class Current:
            @staticmethod
            def row():
                return 7

        class Table:
            @staticmethod
            def clearSelection():
                calls.append("selection_cleared")

        interface = SimpleNamespace(
            subtitle_table=Table(),
            _manual_boundary_row_armed=False,
            _manual_boundary_edit_active=True,
            _manual_boundary_move_direction="next",
            _clear_manual_boundary_index_widgets=lambda: calls.append(
                "widgets_cleared"
            ),
            _refresh_manual_boundary_inspector=lambda row: calls.append(
                ("refreshed", row)
            ),
        )

        SubtitleInterface._on_subtitle_current_row_changed(
            interface,
            Current(),
            None,
        )
        self.assertEqual(calls, ["widgets_cleared"])

        interface._manual_boundary_row_armed = True
        SubtitleInterface._on_subtitle_current_row_changed(
            interface,
            Current(),
            None,
        )
        self.assertEqual(calls[-1], ("refreshed", 7))

        SubtitleInterface._disarm_manual_boundary_editor(
            interface,
            clear_selection=True,
        )
        self.assertFalse(interface._manual_boundary_row_armed)
        self.assertFalse(interface._manual_boundary_edit_active)
        self.assertEqual(interface._manual_boundary_move_direction, "")
        self.assertEqual(calls[-2:], ["widgets_cleared", "selection_cleared"])

    def test_merge_selected_actual_pages_uses_page_boundary_operation(self):
        calls = []
        interface = SimpleNamespace(
            manual_final_session=object(),
            model=SimpleNamespace(
                _data={
                    "1": {
                        "manual_cue_id": "S0001",
                        "display_page_view": True,
                        "display_page_id": "S0001.P01",
                    },
                    "2": {
                        "manual_cue_id": "S0001",
                        "display_page_view": True,
                        "display_page_id": "S0001.P02",
                    },
                }
            ),
            _merge_display_page_with_next=lambda page_id: calls.append(page_id),
            tr=lambda value: value,
        )

        SubtitleInterface.merge_selected_rows(interface, [0, 1])

        self.assertEqual(calls, ["S0001.P01"])

    def test_merge_selected_pages_from_two_parents_is_one_atomic_page_operation(self):
        merge_calls = []
        dirty_calls = []
        selected_rows = []

        class Session:
            cues = [
                {
                    "cue_id": "S0001",
                    "source_subtitle_ids": ["S0001"],
                },
                {
                    "cue_id": "S0002",
                    "source_subtitle_ids": ["S0002"],
                },
            ]

            @staticmethod
            def merge_adjacent_display_pages(left_page_id, right_page_id):
                merge_calls.append((left_page_id, right_page_id))
                return {
                    "parent_subtitle_id": "S0001",
                    "affected_parent_ids": ["S0001", "S0002"],
                    "merged_page_id": "S0001.P02",
                    "page_count": 2,
                    "parent_merge": True,
                }

            @staticmethod
            def has_display_page_model():
                return True

        interface = SimpleNamespace(
            manual_final_session=Session(),
            model=SimpleNamespace(
                _data={
                    "1": {
                        "manual_cue_id": "S0001",
                        "display_page_view": True,
                        "display_page_id": "S0001.P02",
                    },
                    "2": {
                        "manual_cue_id": "S0002",
                        "display_page_view": True,
                        "display_page_id": "S0002.P01",
                    },
                }
            ),
            _sync_manual_final_text_edits=lambda: None,
            _invalidate_manual_review_marks_for_parent_ids=lambda _ids: None,
            _mark_manual_final_dirty=lambda **kwargs: dirty_calls.append(kwargs),
            _apply_manual_final_session=lambda: None,
            _select_manual_boundary_row=lambda row: selected_rows.append(row),
            _manual_parent_boundaries_dirty=True,
            _manual_page_view=False,
            _manual_boundary_edit_active=True,
            _manual_boundary_move_direction="next",
            tr=lambda value: value,
        )

        with patch("app.view.subtitle_interface.InfoBar.success"):
            SubtitleInterface.merge_selected_rows(interface, [0, 1])

        self.assertEqual(merge_calls, [("S0001.P02", "S0002.P01")])
        self.assertEqual(dirty_calls, [{"invalidate_pages": False}])
        self.assertFalse(interface._manual_parent_boundaries_dirty)
        self.assertTrue(interface._manual_page_view)
        self.assertEqual(selected_rows, [0])

    def test_manual_identity_lookup_survives_page_row_count_changes(self):
        interface = SimpleNamespace(
            model=SimpleNamespace(
                _data={
                    "1": {
                        "manual_cue_id": "S0001",
                        "display_page_id": "S0001.P01",
                        "word_start": 0,
                        "word_end": 3,
                    },
                    "2": {
                        "manual_cue_id": "S0005",
                        "display_page_id": "S0005.P01",
                        "word_start": 40,
                        "word_end": 47,
                    },
                    "3": {
                        "manual_cue_id": "S0005",
                        "display_page_id": "S0005.P02",
                        "word_start": 48,
                        "word_end": 55,
                    },
                    "4": {
                        "manual_cue_id": "S0006",
                        "display_page_id": "S0006.P01",
                        "word_start": 56,
                        "word_end": 63,
                    },
                }
            )
        )

        self.assertEqual(
            SubtitleInterface._manual_row_for_identity(
                interface,
                parent_id="S0005",
                page_id="S0005.P02",
            ),
            2,
        )
        self.assertEqual(
            SubtitleInterface._manual_row_for_identity(
                interface,
                parent_id="S0005",
                following_parent_id="S0006",
            ),
            2,
        )
        self.assertEqual(
            SubtitleInterface._manual_row_for_identity(
                interface,
                parent_id="S0005",
                focus_word_id=45,
            ),
            1,
        )

    def test_repeated_parent_page_count_is_reported_as_no_change(self):
        class Session:
            cues = [{"cue_id": "S0216"}]

            @staticmethod
            def split_parent_into_display_pages(_parent_id, page_count):
                return {"page_count": page_count, "changed": False}

        selected_rows = []
        dirty_calls = []
        interface = SimpleNamespace(
            manual_final_session=Session(),
            model=SimpleNamespace(
                _data={
                    "1": {
                        "manual_cue_id": "S0216",
                        "word_start": 100,
                        "word_end": 108,
                    },
                    "2": {
                        "manual_cue_id": "S0216",
                        "word_start": 109,
                        "word_end": 130,
                    },
                }
            ),
            _manual_parent_boundaries_dirty=False,
            _manual_save_in_progress=False,
            _manual_boundary_edit_active=True,
            _manual_boundary_move_direction="next",
            _manual_page_view=True,
            _sync_manual_final_text_edits=lambda: None,
            _apply_manual_final_session=lambda: None,
            _select_manual_boundary_row=lambda row: selected_rows.append(row),
            _mark_manual_final_dirty=lambda **kwargs: dirty_calls.append(kwargs),
            status_label=SimpleNamespace(setText=lambda _value: None),
            tr=lambda value: value,
        )

        with patch("app.view.subtitle_interface.InfoBar.info") as info, patch(
            "app.view.subtitle_interface.InfoBar.success"
        ) as success:
            SubtitleInterface._split_parent_into_display_pages(
                interface,
                "S0216",
                2,
                focus_word_id=109,
            )

        self.assertEqual(selected_rows, [])
        self.assertEqual(dirty_calls, [])
        info.assert_called_once()
        success.assert_not_called()

    def test_manual_boundary_confirm_is_the_only_action_that_moves_words(self):
        app, interface, moves = self._manual_boundary_interaction_fixture()
        self._select_manual_boundary_row(app, interface, 0)
        self._manual_boundary_button(
            interface,
            0,
            "调整与下一屏边界",
        ).click()
        app.processEvents()
        self._manual_boundary_button(interface, 0, "移到下一屏").click()
        app.processEvents()

        self.assertEqual(moves, [])
        self.assertTrue(
            self._manual_boundary_button(interface, 0, "撤销").isEnabled(),
        )

        self._manual_boundary_button(interface, 0, "确认移动 1 个词").click()
        app.processEvents()

        self.assertEqual(moves, [("display", True)])

    def test_manual_display_page_boundary_move_undo_and_reload_are_idempotent(self):
        def parent_signature(session):
            return [
                {
                    key: cue.get(key)
                    for key in (
                        "cue_id",
                        "source_subtitle_ids",
                        "word_start",
                        "word_end",
                        "start_time",
                        "end_time",
                        "original_subtitle",
                        "translated_subtitle",
                    )
                }
                for cue in session.cues
            ]

        def page_signature(session):
            return [
                tuple(
                    row.get(key)
                    for key in (
                        "display_page_id",
                        "manual_cue_id",
                        "word_start",
                        "word_end",
                        "original_subtitle",
                        "translated_subtitle",
                        "start_time",
                        "end_time",
                        "english_font_size",
                    )
                )
                for row in session.to_model_data(prefer_display_pages=True).values()
            ]

        with tempfile.TemporaryDirectory() as temp_dir:
            session = self._manual_page_boundary_session(Path(temp_dir))
            original_parents = parent_signature(session)
            original_pages = page_signature(session)
            original_chinese = [
                row[5] for row in original_pages
            ]

            session.move_display_page_boundary(
                "S0001.P01",
                1,
                move_to_next=True,
            )
            self.assertEqual(session.display_page_boundary_overrides, {"S0001": [3]})
            self.assertEqual(parent_signature(session), original_parents)
            moved_next_pages = page_signature(session)
            self.assertEqual(
                [(row[2], row[3]) for row in moved_next_pages[:2]],
                [(0, 2), (3, 8)],
            )
            self.assertTrue(all(row[5] for row in moved_next_pages[:2]))
            self.assertEqual(
                "".join(row[5] for row in moved_next_pages[:2]),
                original_parents[0]["translated_subtitle"],
            )
            self.assertEqual(moved_next_pages[2][5], original_chinese[2])
            self.assertTrue(session.undo())
            self.assertEqual(session.display_page_boundary_overrides, {})
            self.assertEqual(page_signature(session), original_pages)
            self.assertEqual(parent_signature(session), original_parents)

            session.move_display_page_boundary(
                "S0001.P01",
                1,
                move_to_next=False,
            )
            self.assertEqual(session.display_page_boundary_overrides, {"S0001": [5]})
            moved_previous_pages = page_signature(session)
            self.assertEqual(
                [(row[2], row[3]) for row in moved_previous_pages[:2]],
                [(0, 4), (5, 8)],
            )
            self.assertTrue(all(row[5] for row in moved_previous_pages[:2]))
            self.assertEqual(
                "".join(row[5] for row in moved_previous_pages[:2]),
                original_parents[0]["translated_subtitle"],
            )
            self.assertEqual(moved_previous_pages[2][5], original_chinese[2])
            self.assertEqual(parent_signature(session), original_parents)
            self.assertTrue(session.undo())
            self.assertEqual(session.display_page_boundary_overrides, {})
            self.assertEqual(page_signature(session), original_pages)

            session.move_display_page_boundary(
                "S0001.P01",
                1,
                move_to_next=True,
            )
            saved_paths = session.save_to_source_folder()
            reloaded = ManualFinalSubtitleSession.load_from_manifest(
                Path(saved_paths["manifest_path"])
            )
            expected_pages = page_signature(session)
            self.assertEqual(
                reloaded.display_page_boundary_overrides,
                {"S0001": [3]},
            )
            self.assertEqual(parent_signature(reloaded), original_parents)
            self.assertEqual(page_signature(reloaded), expected_pages)

            second_paths = reloaded.save_to_source_folder()
            reloaded_again = ManualFinalSubtitleSession.load_from_manifest(
                Path(second_paths["manifest_path"])
            )
            self.assertEqual(
                reloaded_again.display_page_boundary_overrides,
                {"S0001": [3]},
            )
            self.assertEqual(parent_signature(reloaded_again), original_parents)
            self.assertEqual(page_signature(reloaded_again), expected_pages)

            reloaded_again.display_page_boundary_overrides["S0001"] = [0]
            with self.assertRaisesRegex(
                ManualFinalSubtitleEditError,
                "人工分页边界超出父字幕的冻结词范围",
            ):
                reloaded_again.save_to_source_folder()

    def test_manual_parent_noop_save_reuses_frozen_blueprint_and_rejects_invalid_loaded_override(
        self,
    ):
        from tests.test_manual_final_subtitle_editor import _write_json

        with tempfile.TemporaryDirectory() as temp_dir:
            session = self._manual_page_boundary_session(Path(temp_dir))
            self.assertFalse(session.display_page_edits)
            self.assertFalse(session.display_page_boundary_overrides)

            with patch.object(
                podcast_learning_video,
                "build_article_display_page_blueprint",
                side_effect=AssertionError(
                    "an unchanged parent save must reuse the frozen blueprint"
                ),
            ):
                saved_paths = session.save_to_source_folder()

            self.assertFalse(saved_paths["render_blocked"])
            manifest_path = Path(saved_paths["manifest_path"])
            reloaded = ManualFinalSubtitleSession.load_from_manifest(manifest_path)
            self.assertEqual(reloaded.cues, session.cues)

            edit_path = Path(saved_paths["edit_artifact_path"])
            edit_payload = json.loads(edit_path.read_text(encoding="utf-8"))
            edit_payload["display_page_boundary_overrides"] = {"S0001": [0]}
            _write_json(edit_path, edit_payload)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["manual_final_override"]["edit_artifact_sha256"] = (
                hashlib.sha256(edit_path.read_bytes()).hexdigest()
            )
            _write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                ManualFinalSubtitleEditError,
                "人工分页边界超出父字幕的冻结词范围",
            ):
                ManualFinalSubtitleSession.load_from_manifest(manifest_path)

    def test_split_commits_active_chinese_delegate_before_rebuilding_pages(self):
        split_calls = []

        class Session:
            def __init__(self):
                self.cues = [
                    {
                        "cue_id": "S0001",
                        "subtitle_id": "S0001",
                        "start_time": 0,
                        "end_time": 3000,
                        "word_start": 0,
                        "word_end": 5,
                        "original_subtitle": (
                            "alpha beta gamma delta epsilon zeta"
                        ),
                        "translated_subtitle": "旧中文",
                    }
                ]
                self.history = []
                self.display_page_edits = []

            @staticmethod
            def has_display_page_model():
                return False

            def apply_parent_model_data(self, model_data):
                row = model_data["1"]
                self.cues[0]["original_subtitle"] = str(
                    row["original_subtitle"]
                )
                self.cues[0]["translated_subtitle"] = str(
                    row["translated_subtitle"]
                )

            def split_parent_into_display_pages(self, parent_id, page_count):
                split_calls.append(
                    (
                        parent_id,
                        page_count,
                        self.cues[0]["translated_subtitle"],
                    )
                )
                return {"page_count": page_count}

        model = SubtitleTableModel(
            {
                "1": {
                    **Session().cues[0],
                    "manual_cue_id": "S0001",
                    "parent_cue_index": 0,
                }
            }
        )
        table = QTableView()
        table.setAttribute(Qt.WA_DontShowOnScreen, True)
        table.resize(900, 240)
        table.setModel(model)
        table.show()
        self._qt_app.processEvents()
        self.addCleanup(
            lambda: (table.close(), self._qt_app.processEvents())
        )
        interface = SimpleNamespace(
            manual_final_session=Session(),
            model=model,
            subtitle_table=table,
            _manual_parent_boundaries_dirty=False,
            _manual_save_in_progress=False,
            _manual_save_request_id=0,
            _manual_pending_page_split=None,
            _manual_refresh_requested=False,
            _manual_page_view=False,
            _apply_manual_final_session=lambda: None,
            _mark_manual_final_dirty=lambda **_kwargs: None,
            _invalidate_manual_review_marks_for_parent_ids=lambda _ids: None,
            _select_manual_boundary_row=lambda _row: None,
            status_label=SimpleNamespace(setText=lambda _value: None),
            tr=lambda value: value,
        )
        interface._commit_active_manual_table_editor = MethodType(
            SubtitleInterface._commit_active_manual_table_editor,
            interface,
        )
        interface._sync_manual_final_text_edits = MethodType(
            SubtitleInterface._sync_manual_final_text_edits,
            interface,
        )

        chinese_index = model.index(0, 3)
        table.setCurrentIndex(chinese_index)
        table.edit(chinese_index)
        self._qt_app.processEvents()
        editor = table.indexWidget(chinese_index)
        self.assertIsInstance(editor, QLineEdit)
        editor.setFocus()
        editor.setText("未提交的新中文")
        self._qt_app.processEvents()
        self.assertEqual(
            model._data["1"]["translated_subtitle"],
            "旧中文",
            "the fixture must retain an uncommitted delegate value",
        )

        with patch.object(
            QApplication,
            "focusWidget",
            return_value=editor,
        ), patch("app.view.subtitle_interface.InfoBar.success"), patch(
            "app.view.subtitle_interface.InfoBar.warning"
        ):
            SubtitleInterface._split_parent_into_display_pages(
                interface,
                "S0001",
                2,
            )

        self.assertEqual(
            split_calls,
            [("S0001", 2, "未提交的新中文")],
        )
        self.assertEqual(
            interface.manual_final_session.cues[0]["translated_subtitle"],
            "未提交的新中文",
        )

    def test_consecutive_parent_splits_defer_save_and_keep_first_parent_chinese(
        self,
    ):
        split_calls = []
        save_calls = []

        class Session:
            def __init__(self):
                self.cues = [
                    {
                        "cue_id": "S0001",
                        "start_time": 0,
                        "end_time": 4000,
                        "word_start": 0,
                        "word_end": 7,
                        "original_subtitle": "one two three four five six seven eight",
                        "translated_subtitle": "父一",
                    },
                    {
                        "cue_id": "S0002",
                        "start_time": 4000,
                        "end_time": 8000,
                        "word_start": 8,
                        "word_end": 15,
                        "original_subtitle": (
                            "nine ten eleven twelve thirteen fourteen fifteen sixteen"
                        ),
                        "translated_subtitle": "父二",
                    },
                ]
                self.history = []
                self.pages = {
                    cue["cue_id"]: self._make_pages(cue, 1)
                    for cue in self.cues
                }
                self.display_page_edits = self._all_pages()

            @staticmethod
            def _page_chinese(parent_id, page_index, page_count):
                return f"{parent_id}-中文" if page_count == 1 else ""

            def _make_pages(self, cue, page_count):
                words = cue["original_subtitle"].split()
                word_start = int(cue["word_start"])
                word_end = int(cue["word_end"])
                page_size = (word_end - word_start + 1) // page_count
                pages = []
                cursor = word_start
                for page_index in range(1, page_count + 1):
                    page_end = (
                        word_end
                        if page_index == page_count
                        else cursor + page_size - 1
                    )
                    local_start = cursor - word_start
                    local_end = page_end - word_start
                    pages.append(
                        {
                            "start_time": cue["start_time"]
                            + local_start * 500,
                            "end_time": cue["start_time"]
                            + (local_end + 1) * 500,
                            "original_subtitle": " ".join(
                                words[local_start : local_end + 1]
                            ),
                            "translated_subtitle": self._page_chinese(
                                cue["cue_id"], page_index, page_count
                            ),
                            "display_page_view": True,
                            "display_page_id": (
                                f"{cue['cue_id']}.P{page_index:02d}"
                            ),
                            "manual_cue_id": cue["cue_id"],
                            "parent_cue_index": self.cues.index(cue),
                            "word_start": cursor,
                            "word_end": page_end,
                        }
                    )
                    cursor = page_end + 1
                return pages

            def _all_pages(self):
                return [
                    dict(page)
                    for cue in self.cues
                    for page in self.pages[cue["cue_id"]]
                ]

            def has_display_page_model(self):
                return True

            def to_model_data(self, *, prefer_display_pages=False):
                return {
                    str(index): dict(page)
                    for index, page in enumerate(self._all_pages(), 1)
                }

            def apply_display_page_model_data(
                self,
                model_data,
                *,
                allow_incomplete_chinese=True,
            ):
                chinese_by_id = {
                    str(row.get("display_page_id") or ""): str(
                        row.get("translated_subtitle") or ""
                    )
                    for row in model_data.values()
                }
                for pages in self.pages.values():
                    for page in pages:
                        page_id = page["display_page_id"]
                        if page_id in chinese_by_id:
                            page["translated_subtitle"] = chinese_by_id[page_id]
                self.display_page_edits = self._all_pages()

            def split_parent_into_display_pages(self, parent_id, page_count):
                split_calls.append((parent_id, page_count))
                cue = next(
                    cue for cue in self.cues if cue["cue_id"] == parent_id
                )
                self.pages[parent_id] = self._make_pages(cue, page_count)
                self.display_page_edits = self._all_pages()
                self.history.append(
                    {"operation": "split_parent_into_display_pages"}
                )
                return {"page_count": page_count}

        session = Session()
        interface = SimpleNamespace(
            manual_final_session=session,
            model=SubtitleTableModel(
                session.to_model_data(prefer_display_pages=True)
            ),
            _manual_parent_boundaries_dirty=False,
            _manual_save_in_progress=False,
            _manual_page_view=True,
            _manual_refresh_requested=False,
            _manual_pending_page_split=None,
            _sync_manual_final_text_edits=None,
            _mark_manual_final_dirty=lambda **_kwargs: None,
            _invalidate_manual_review_marks_for_parent_ids=lambda _ids: None,
            _apply_manual_final_session=None,
            _select_manual_boundary_row=lambda _row: None,
            save_manual_final_output=lambda: save_calls.append("save"),
            status_label=SimpleNamespace(setText=lambda _value: None),
            tr=lambda value: value,
        )
        interface._sync_manual_final_text_edits = MethodType(
            SubtitleInterface._sync_manual_final_text_edits,
            interface,
        )

        def apply_session():
            interface.model.update_all(
                session.to_model_data(prefer_display_pages=True)
            )

        interface._apply_manual_final_session = apply_session

        with patch("app.view.subtitle_interface.InfoBar.success"), patch(
            "app.view.subtitle_interface.InfoBar.warning"
        ):
            SubtitleInterface._split_parent_into_display_pages(
                interface,
                "S0001",
                2,
            )
            first_parent_rows = [
                row
                for row in interface.model._data.values()
                if row["manual_cue_id"] == "S0001"
            ]
            first_parent_rows[0]["translated_subtitle"] = "甲上"
            first_parent_rows[1]["translated_subtitle"] = "甲下"
            SubtitleInterface._split_parent_into_display_pages(
                interface,
                "S0002",
                2,
            )

        self.assertEqual(
            split_calls,
            [("S0001", 2), ("S0002", 2)],
        )
        self.assertEqual(save_calls, [])
        self.assertFalse(interface._manual_refresh_requested)
        self.assertIsNone(interface._manual_pending_page_split)
        self.assertEqual(
            [
                page["translated_subtitle"]
                for page in session.pages["S0001"]
            ],
            ["甲上", "甲下"],
        )

    def test_manual_final_save_allows_empty_page_chinese_to_reach_blocked_writer(
        self,
    ):
        class Toggle:
            def __init__(self):
                self.enabled = True
                self.visible = True
                self.text = ""

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setVisible(self, value):
                self.visible = bool(value)

            def setText(self, value):
                self.text = str(value)

        class TableToggle:
            def setEnabled(self, _value):
                pass

        class StatusLabel:
            def setText(self, _value):
                pass

        class Signal:
            def __init__(self):
                self.calls = []

            def emit(self, *args):
                self.calls.append(args)

        class Session:
            history = []

            @staticmethod
            def save_to_source_folder(
                *,
                source_media_path=None,
                progress_callback=None,
            ):
                return {
                    "manifest_path": "blocked-manifest.json",
                    "render_blocked": True,
                    "render_block_reason": "manual_page_translation_required",
                }

        started_threads = []

        class CapturedThread:
            def __init__(self, *, target, args, daemon):
                self.target = target
                self.args = args
                self.daemon = daemon

            def start(self):
                started_threads.append(self)

        sync_calls = []
        interface = SimpleNamespace(
            manual_final_session=Session(),
            _manual_save_in_progress=False,
            _manual_save_request_id=0,
            _manual_refresh_requested=False,
            task=None,
            subtitle_table=TableToggle(),
            manual_final_save_action=Toggle(),
            manual_final_undo_action=Toggle(),
            manual_final_synthesis_action=Toggle(),
            manual_draft_synthesis_action=Toggle(),
            status_label=StatusLabel(),
            manual_final_save_progress=Signal(),
            manual_final_save_finished=Signal(),
            tr=lambda value: value,
            _sync_manual_final_text_edits=lambda **kwargs: sync_calls.append(
                kwargs
            ),
        )
        interface._set_manual_final_save_busy = MethodType(
            SubtitleInterface._set_manual_final_save_busy,
            interface,
        )
        interface._save_manual_final_output_in_background = MethodType(
            SubtitleInterface._save_manual_final_output_in_background,
            interface,
        )

        with patch("app.view.subtitle_interface.Thread", CapturedThread):
            request_id = SubtitleInterface.save_manual_final_output(interface)

        self.assertEqual(request_id, 1)
        self.assertEqual(len(started_threads), 1)
        worker = started_threads[0]
        worker.target(*worker.args)
        self.assertEqual(
            interface.manual_final_save_finished.calls[0][1][
                "render_block_reason"
            ],
            "manual_page_translation_required",
        )
        self.assertEqual(
            sync_calls,
            [{"allow_incomplete_page_chinese": True}],
        )

    def test_stale_actual_page_import_exposes_refresh_action_in_ui(self):
        class Session:
            subtitle_path = Path("current-parent.srt")
            history = []
            import_notice = (
                "导入的实际分页已被后续保存淘汰；已自动打开最新人工终稿，"
                "请刷新实际分页后继续编辑"
            )

            @staticmethod
            def has_display_page_model():
                return False

            @staticmethod
            def to_model_data(*, prefer_display_pages=False):
                return {
                    "1": {
                        "start_time": 0,
                        "end_time": 1000,
                        "original_subtitle": "current parent",
                        "translated_subtitle": "",
                        "display_page_view": False,
                        "manual_cue_id": "S0001",
                        "parent_cue_index": 0,
                        "word_start": 0,
                        "word_end": 1,
                    }
                }

        interface = SubtitleInterface()
        interface.setAttribute(Qt.WA_DontShowOnScreen, True)
        interface._load_manual_final_review_marks = lambda _session: None
        interface._restore_saved_manual_package_actions = lambda: None
        interface._refresh_manual_boundary_inspector = lambda *args: None
        self.addCleanup(
            lambda: (interface.close(), self._qt_app.processEvents())
        )

        with patch.object(
            ManualFinalSubtitleSession,
            "load_for_subtitle",
            return_value=Session(),
        ):
            interface._load_manual_final_session(Path("stale-pages.srt"))

        self.assertFalse(interface._manual_page_view)
        self.assertTrue(interface.manual_page_view_action.isVisible())
        self.assertTrue(interface.manual_page_view_action.isEnabled())
        self.assertEqual(
            interface.manual_page_view_action.text(),
            "刷新实际分页",
        )
        self.assertIn("请刷新实际分页", interface.status_label.text())

    def test_stale_import_with_current_pages_keeps_page_view_and_notice(self):
        class Session:
            subtitle_path = Path("current-parent.srt")
            history = []
            import_notice = (
                "导入的实际分页已被后续保存淘汰；已自动打开最新人工终稿，"
                "请刷新实际分页后继续编辑"
            )

            @staticmethod
            def has_display_page_model():
                return True

            @staticmethod
            def to_model_data(*, prefer_display_pages=False):
                return {
                    "1": {
                        "start_time": 0,
                        "end_time": 1000,
                        "original_subtitle": "current page",
                        "translated_subtitle": "当前中文",
                        "display_page_view": True,
                        "display_page_id": "S0001.P01",
                        "manual_cue_id": "S0001",
                        "parent_cue_index": 0,
                        "word_start": 0,
                        "word_end": 1,
                    }
                }

        interface = SubtitleInterface()
        interface.setAttribute(Qt.WA_DontShowOnScreen, True)
        interface._load_manual_final_review_marks = lambda _session: None
        interface._restore_saved_manual_package_actions = lambda: None
        interface._refresh_manual_boundary_inspector = lambda *args: None
        self.addCleanup(
            lambda: (interface.close(), self._qt_app.processEvents())
        )

        with patch.object(
            ManualFinalSubtitleSession,
            "load_for_subtitle",
            return_value=Session(),
        ):
            interface._load_manual_final_session(Path("stale-pages.srt"))

        self.assertTrue(interface._manual_page_view)
        self.assertTrue(interface.manual_page_view_action.isVisible())
        self.assertTrue(interface.manual_page_view_action.isEnabled())
        self.assertEqual(
            interface.manual_page_view_action.text(),
            "查看父字幕",
        )
        self.assertIn("请刷新实际分页", interface.status_label.text())

    def test_failed_refresh_keeps_refresh_action_visible_and_retryable(self):
        class Session:
            def __init__(self):
                self.cues = [
                    {
                        "cue_id": "S0001",
                        "start_time": 0,
                        "end_time": 1000,
                        "word_start": 0,
                        "word_end": 1,
                        "original_subtitle": "one two",
                        "translated_subtitle": "一二",
                    }
                ]
                self.history = []
                self.display_page_edits = []

            @staticmethod
            def has_display_page_model():
                return False

            def to_model_data(self, *, prefer_display_pages=False):
                return {
                    "1": {
                        **self.cues[0],
                        "manual_cue_id": "S0001",
                        "parent_cue_index": 0,
                    }
                }

        interface = SubtitleInterface()
        interface.setAttribute(Qt.WA_DontShowOnScreen, True)
        interface.manual_final_session = Session()
        interface._manual_parent_boundaries_dirty = True
        interface._manual_page_view = False
        interface._manual_refresh_requested = True
        interface._manual_pending_page_split = None
        interface._manual_save_request_id = 4
        interface._refresh_manual_boundary_inspector = lambda *args: None
        interface._apply_manual_final_session()
        interface._set_manual_final_save_busy(True)
        self.addCleanup(
            lambda: (interface.close(), self._qt_app.processEvents())
        )

        with patch("app.view.subtitle_interface.InfoBar.warning"):
            interface._apply_manual_final_save_result(
                4,
                {},
                "injected save failure",
            )

        self.assertTrue(interface._manual_parent_boundaries_dirty)
        self.assertFalse(interface._manual_refresh_requested)
        self.assertTrue(interface.manual_page_view_action.isVisible())
        self.assertTrue(interface.manual_page_view_action.isEnabled())
        self.assertEqual(
            interface.manual_page_view_action.text(),
            "刷新实际分页",
        )

    def test_manual_parent_english_and_chinese_are_editable(self):
        model = SubtitleTableModel(
            {
                "1": {
                    "start_time": 0,
                    "end_time": 1000,
                    "original_subtitle": "Frozen English",
                    "translated_subtitle": "中文",
                    "display_page_view": False,
                    "manual_cue_id": "S0001",
                }
            }
        )

        self.assertTrue(model.flags(model.index(0, 2)) & Qt.ItemIsEditable)
        self.assertTrue(model.flags(model.index(0, 3)) & Qt.ItemIsEditable)

    def test_explicit_manual_english_edit_uses_actual_page_contract(self):
        captured = {}

        class Session:
            @staticmethod
            def apply_display_page_model_data(rows, *, allow_incomplete_chinese):
                captured["rows"] = rows
                captured["allow_incomplete_chinese"] = allow_incomplete_chinese
                return True

        class Toggle:
            def setEnabled(self, value):
                captured["undo_enabled"] = bool(value)

        class Label:
            def setText(self, value):
                captured["status"] = str(value)

        model = SubtitleTableModel(
            {
                "1": {
                    "start_time": 110494,
                    "end_time": 117449,
                    "original_subtitle": (
                        "known literally OnlyFans Stifler's Mom."
                    ),
                    "translated_subtitle": "名叫斯蒂夫勒的妈妈。",
                    "display_page_view": True,
                    "display_page_id": "S0028.P02",
                    "manual_cue_id": "S0028",
                    "word_start": 345,
                    "word_end": 355,
                }
            }
        )
        interface = SimpleNamespace(
            model=model,
            manual_final_session=Session(),
            manual_final_undo_action=Toggle(),
            status_label=Label(),
            tr=lambda value: value,
            _sync_manual_final_text_edits=lambda **kwargs: captured.setdefault(
                "sync", kwargs
            ),
            _invalidate_manual_review_marks_for_parent_ids=lambda ids: captured.setdefault(
                "invalidated", list(ids)
            ),
            _mark_manual_final_dirty=lambda **kwargs: captured.setdefault(
                "dirty", kwargs
            ),
            _apply_manual_final_session=lambda: captured.setdefault(
                "refreshed", True
            ),
            _manual_row_for_identity=lambda **kwargs: captured.setdefault(
                "identity", kwargs
            )
            and 0,
            _select_manual_boundary_row=lambda row: captured.setdefault(
                "selected_row", row
            ),
        )

        changed = SubtitleInterface._apply_manual_english_replacement(
            interface,
            0,
            "known literally only as Stifler's Mom.",
        )

        self.assertTrue(changed)
        self.assertEqual(
            captured["rows"]["1"]["original_subtitle"],
            "known literally only as Stifler's Mom.",
        )
        self.assertTrue(captured["allow_incomplete_chinese"])
        self.assertEqual(captured["invalidated"], ["S0028"])
        self.assertEqual(captured["dirty"], {"invalidate_pages": False})
        self.assertEqual(captured["identity"]["page_id"], "S0028.P02")
        self.assertEqual(captured["selected_row"], 0)
        self.assertIn("词 ID 和时间轴未改变", captured["status"])

    def test_explicit_manual_english_edit_routes_many_words_to_one_surface_span(self):
        captured = {}

        class Session:
            @staticmethod
            def _display_word_spans(start, end):
                captured["row_range"] = (start, end)
                return [
                    {
                        "word_start": 100 + index,
                        "word_end": 100 + index,
                        "surface": surface,
                    }
                    for index, surface in enumerate(
                        ["They", "call", "it", "New", "Ally", "today."]
                    )
                ]

            @staticmethod
            def replace_english_surface_span(**kwargs):
                captured["span"] = kwargs
                return True

            @staticmethod
            def apply_display_page_model_data(*_args, **_kwargs):
                raise AssertionError("many-to-one edit must use the span contract")

        class Toggle:
            def setEnabled(self, value):
                captured["undo_enabled"] = bool(value)

        class Label:
            def setText(self, value):
                captured["status"] = str(value)

        model = SubtitleTableModel(
            {
                "1": {
                    "start_time": 1000,
                    "end_time": 3000,
                    "original_subtitle": "They call it New Ally today.",
                    "translated_subtitle": "他们称之为牛来。",
                    "display_page_view": True,
                    "display_page_id": "S0007.P01",
                    "manual_cue_id": "S0007",
                    "word_start": 100,
                    "word_end": 105,
                }
            }
        )
        interface = SimpleNamespace(
            model=model,
            manual_final_session=Session(),
            manual_final_undo_action=Toggle(),
            status_label=Label(),
            tr=lambda value: value,
            _sync_manual_final_text_edits=lambda **kwargs: None,
            _invalidate_manual_review_marks_for_parent_ids=lambda ids: None,
            _mark_manual_final_dirty=lambda **kwargs: None,
            _apply_manual_final_session=lambda: None,
            _manual_row_for_identity=lambda **kwargs: 0,
            _select_manual_boundary_row=lambda row: None,
        )
        interface._apply_manual_multiword_surface_replacement = MethodType(
            SubtitleInterface._apply_manual_multiword_surface_replacement,
            interface,
        )

        changed = SubtitleInterface._apply_manual_english_replacement(
            interface,
            0,
            "They call it Niulai today.",
        )

        self.assertTrue(changed)
        self.assertEqual(captured["row_range"], (100, 105))
        self.assertEqual(
            captured["span"],
            {
                "parent_subtitle_id": "S0007",
                "word_start": 103,
                "word_end": 104,
                "replacement_text": "Niulai",
            },
        )
        self.assertTrue(captured["undo_enabled"])

    def test_parent_chinese_edit_marks_local_dirty_without_invalidating_pages(self):
        class Toggle:
            def __init__(self):
                self.enabled = True
                self.visible = True

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setVisible(self, value):
                self.visible = bool(value)

        class TableToggle:
            def setEnabled(self, _value):
                pass

        saved_pages = [{"display_page_id": "S0001.P01"}]
        model = SubtitleTableModel(
            {
                "1": {
                    "subtitle_id": "S0001",
                    "start_time": 0,
                    "end_time": 1000,
                    "original_subtitle": "Frozen English",
                    "translated_subtitle": "旧中文",
                    "display_page_view": False,
                }
            }
        )
        session = SimpleNamespace(display_page_edits=list(saved_pages))
        interface = SimpleNamespace(
            model=model,
            manual_final_session=session,
            _manual_page_view=False,
            _manual_parent_boundaries_dirty=False,
            _manual_package_manifest_path="saved-manual-manifest.json",
            _manual_save_request_id=0,
            _manual_save_in_progress=False,
            _manual_pending_page_split=None,
            subtitle_table=TableToggle(),
            manual_final_undo_action=Toggle(),
            manual_final_synthesis_action=Toggle(),
            manual_draft_synthesis_action=Toggle(),
            tr=lambda value: value,
            _refresh_manual_boundary_inspector=lambda: None,
            _invalidate_manual_review_marks_for_parent_ids=lambda _ids: None,
        )
        interface._invalidate_manual_final_save = MethodType(
            SubtitleInterface._invalidate_manual_final_save,
            interface,
        )
        interface._mark_manual_final_dirty = MethodType(
            SubtitleInterface._mark_manual_final_dirty,
            interface,
        )
        model.dataChanged.connect(
            lambda top_left, bottom_right, roles: (
                SubtitleInterface._on_manual_table_data_changed(
                    interface,
                    top_left,
                    bottom_right,
                    roles,
                )
            )
        )

        self.assertTrue(
            model.setData(
                model.index(0, 3),
                "新中文",
                Qt.EditRole,
            )
        )

        self.assertEqual(interface._manual_package_manifest_path, "")
        self.assertFalse(interface._manual_parent_boundaries_dirty)
        self.assertEqual(session.display_page_edits, saved_pages)
        self.assertFalse(interface.manual_final_synthesis_action.enabled)
        self.assertFalse(interface.manual_draft_synthesis_action.enabled)

    def test_discard_confirmation_commits_active_delegate_before_unsaved_check(self):
        class Toggle:
            def __init__(self):
                self.enabled = True
                self.visible = True

            def setEnabled(self, value):
                self.enabled = bool(value)

            def setVisible(self, value):
                self.visible = bool(value)

        class Session:
            @staticmethod
            def state_fingerprint():
                return "saved-state"

        class Button:
            def __init__(self):
                self.text = ""

            def setText(self, value):
                self.text = str(value)

        model = SubtitleTableModel(
            {
                "1": {
                    "subtitle_id": "S0001",
                    "start_time": 0,
                    "end_time": 1000,
                    "original_subtitle": "English",
                    "translated_subtitle": "旧中文",
                    "display_pages": [],
                }
            }
        )
        table = QTableView()
        table.setAttribute(Qt.WA_DontShowOnScreen, True)
        table.resize(900, 240)
        table.setModel(model)
        table.show()
        self._qt_app.processEvents()
        self.addCleanup(
            lambda: (table.close(), self._qt_app.processEvents())
        )
        interface = SimpleNamespace(
            manual_final_session=Session(),
            model=model,
            subtitle_table=table,
            _manual_page_view=False,
            _manual_parent_boundaries_dirty=False,
            _manual_package_manifest_path="saved-manual-manifest.json",
            _manual_save_request_id=0,
            _manual_save_in_progress=False,
            _manual_clean_state_fingerprint="saved-state",
            _manual_model_has_pending_edits=False,
            _manual_has_unsaved_changes=False,
            manual_final_undo_action=Toggle(),
            manual_final_synthesis_action=Toggle(),
            manual_draft_synthesis_action=Toggle(),
            _refresh_manual_boundary_inspector=lambda: None,
            _invalidate_manual_review_marks_for_parent_ids=lambda _ids: None,
            tr=lambda value: value,
        )
        interface._commit_active_manual_table_editor = MethodType(
            SubtitleInterface._commit_active_manual_table_editor,
            interface,
        )
        interface._manual_state_fingerprint = MethodType(
            SubtitleInterface._manual_state_fingerprint,
            interface,
        )
        interface._reconcile_manual_dirty_state = MethodType(
            SubtitleInterface._reconcile_manual_dirty_state,
            interface,
        )
        interface._invalidate_manual_final_save = MethodType(
            SubtitleInterface._invalidate_manual_final_save,
            interface,
        )
        interface._mark_manual_final_dirty = MethodType(
            SubtitleInterface._mark_manual_final_dirty,
            interface,
        )
        model.dataChanged.connect(
            lambda top_left, bottom_right, roles: (
                SubtitleInterface._on_manual_table_data_changed(
                    interface,
                    top_left,
                    bottom_right,
                    roles,
                )
            )
        )

        chinese_index = model.index(0, 3)
        table.setCurrentIndex(chinese_index)
        table.edit(chinese_index)
        self._qt_app.processEvents()
        editor = table.indexWidget(chinese_index)
        self.assertIsInstance(editor, QLineEdit)
        editor.setFocus()
        editor.setText("尚未失焦的新中文")
        self._qt_app.processEvents()
        self.assertEqual(model._data["1"]["translated_subtitle"], "旧中文")
        self.assertFalse(interface._manual_has_unsaved_changes)

        observed_before_dialog = []

        class FakeMessageBox:
            def __init__(self, _title, _content, _parent):
                observed_before_dialog.append(
                    (
                        model._data["1"]["translated_subtitle"],
                        interface._manual_has_unsaved_changes,
                    )
                )
                self.yesButton = Button()
                self.cancelButton = Button()

            @staticmethod
            def exec():
                return 0

        with patch.object(
            QApplication,
            "focusWidget",
            return_value=editor,
        ), patch("app.view.subtitle_interface.MessageBox", FakeMessageBox):
            confirmed = SubtitleInterface._confirm_discard_manual_edits(
                interface,
                "导入其他字幕",
            )

        self.assertFalse(confirmed)
        self.assertEqual(
            observed_before_dialog,
            [("尚未失焦的新中文", True)],
        )
        self.assertTrue(interface._manual_model_has_pending_edits)

    def test_regular_export_commits_active_delegate_before_serializing_model(self):
        model = SubtitleTableModel(
            {
                "1": {
                    "subtitle_id": "S0001",
                    "start_time": 0,
                    "end_time": 1000,
                    "original_subtitle": "English",
                    "translated_subtitle": "旧中文",
                }
            }
        )
        table = QTableView()
        table.setAttribute(Qt.WA_DontShowOnScreen, True)
        table.resize(900, 240)
        table.setModel(model)
        table.show()
        self._qt_app.processEvents()
        self.addCleanup(
            lambda: (table.close(), self._qt_app.processEvents())
        )
        interface = SimpleNamespace(
            subtitle_path="source.srt",
            subtitle_table=table,
            model=model,
            tr=lambda value: value,
        )
        interface._commit_active_manual_table_editor = MethodType(
            SubtitleInterface._commit_active_manual_table_editor,
            interface,
        )

        chinese_index = model.index(0, 3)
        table.setCurrentIndex(chinese_index)
        table.edit(chinese_index)
        self._qt_app.processEvents()
        editor = table.indexWidget(chinese_index)
        self.assertIsInstance(editor, QLineEdit)
        editor.setFocus()
        editor.setText("普通导出的新中文")
        self._qt_app.processEvents()
        self.assertEqual(model._data["1"]["translated_subtitle"], "旧中文")

        serialized_rows = []
        save_calls = []

        class ExportData:
            def save(self, file_path, *, layout):
                save_calls.append((file_path, layout))

        def from_json(payload):
            serialized_rows.append(dict(payload["1"]))
            return ExportData()

        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = str(Path(temp_dir) / "export.srt")
            with patch.object(
                QApplication,
                "focusWidget",
                return_value=editor,
            ), patch(
                "app.view.subtitle_interface.QFileDialog.getSaveFileName",
                return_value=(export_path, ""),
            ), patch.object(
                ASRData,
                "from_json",
                side_effect=from_json,
            ), patch(
                "app.view.subtitle_interface.InfoBar.success"
            ), patch(
                "app.view.subtitle_interface.InfoBar.error"
            ):
                SubtitleInterface.on_save_format_clicked(interface, "srt")

        self.assertEqual(
            serialized_rows[0]["translated_subtitle"],
            "普通导出的新中文",
        )
        self.assertEqual(save_calls[0][0], export_path)

    def test_import_is_rejected_while_manual_final_save_is_running(self):
        class ImportedData:
            @staticmethod
            def to_json():
                return {
                    "1": {
                        "start_time": 0,
                        "end_time": 1000,
                        "original_subtitle": "new",
                        "translated_subtitle": "新",
                    }
                }

        original_model = {
            "1": {
                "start_time": 0,
                "end_time": 1000,
                "original_subtitle": "old",
                "translated_subtitle": "旧",
            }
        }
        loaded_sessions = []
        interface = SimpleNamespace(
            _manual_save_in_progress=True,
            subtitle_path="old.srt",
            model=SubtitleTableModel(dict(original_model)),
            status_label=SimpleNamespace(setText=lambda _value: None),
            tr=lambda value: value,
            _load_manual_final_session=lambda path: loaded_sessions.append(path),
        )

        with patch.object(
            ASRData,
            "from_subtitle_file",
            return_value=ImportedData(),
        ) as parser, patch("app.view.subtitle_interface.InfoBar.warning"), patch(
            "app.view.subtitle_interface.InfoBar.error"
        ):
            loaded = SubtitleInterface.load_subtitle_file(
                interface,
                "new.srt",
            )

        self.assertFalse(loaded)
        parser.assert_not_called()
        self.assertEqual(interface.subtitle_path, "old.srt")
        self.assertEqual(interface.model._data, original_model)
        self.assertEqual(loaded_sessions, [])

    def test_failed_subtitle_import_preserves_existing_path_and_model(self):
        original_model = {
            "1": {
                "start_time": 0,
                "end_time": 1000,
                "original_subtitle": "old",
                "translated_subtitle": "旧",
            }
        }
        status_messages = []
        interface = SimpleNamespace(
            _manual_save_in_progress=False,
            subtitle_path="old.srt",
            model=SubtitleTableModel(dict(original_model)),
            status_label=SimpleNamespace(
                setText=lambda value: status_messages.append(str(value))
            ),
            tr=lambda value: value,
        )

        with patch.object(
            ASRData,
            "from_subtitle_file",
            side_effect=ValueError("invalid subtitle"),
        ), patch("app.view.subtitle_interface.InfoBar.error"):
            loaded = SubtitleInterface.load_subtitle_file(
                interface,
                "broken.srt",
            )

        self.assertFalse(loaded)
        self.assertEqual(interface.subtitle_path, "old.srt")
        self.assertEqual(interface.model._data, original_model)
        self.assertIn("invalid subtitle", status_messages[-1])


if __name__ == "__main__":
    unittest.main()
