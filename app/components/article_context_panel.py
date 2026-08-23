from pathlib import Path

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    InfoBar,
    PrimaryPushButton,
    PushButton,
    SwitchButton,
    TextEdit,
)
from qfluentwidgets.common.config import isDarkTheme, qconfig

from app.common.config import cfg
from app.core.article_context import (
    ARTICLE_ANALYSIS_META_KEY,
    ArticleContextThread,
    ArticleLLMConfig,
    build_translation_context_prompt,
    empty_article_context,
)
from app.core.llm_service_config import resolve_llm_service_config


class ArticleContextPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.article_source_text = ""
        self.article_context_data = empty_article_context()
        self.article_analysis_thread = None
        self._applying_theme = False
        self._last_theme_is_dark = None
        self._content_expanded = False
        self._content_dialog = None

        self.setObjectName("ArticleContextPanel")
        self._setup_ui()
        # qfluentwidgets updates its registered styles from this signal. The
        # dialog also owns custom colors, so refresh those after the global
        # theme stylesheet has finished applying.
        qconfig.themeChangedFinished.connect(self._on_theme_changed)
        self._apply_theme()

    def _on_theme_changed(self) -> None:
        self._last_theme_is_dark = None
        self._apply_theme()

    def _apply_theme(self):
        if self._applying_theme:
            return
        is_dark = isDarkTheme()
        if self._last_theme_is_dark is is_dark:
            return
        self._applying_theme = True
        self._last_theme_is_dark = is_dark
        if is_dark:
            border = "rgba(255, 255, 255, 0.12)"
            background = "rgba(32, 32, 32, 0.72)"
            muted = "rgba(255, 255, 255, 0.62)"
        else:
            border = "rgba(0, 0, 0, 0.08)"
            background = "rgba(255, 255, 255, 0.88)"
            muted = "#888888"
        try:
            self.setStyleSheet(
                f"""
                QFrame#ArticleContextPanel {{
                    border: 1px solid {border};
                    border-radius: 10px;
                    background: {background};
                }}
                """
            )
            if hasattr(self, "status_label"):
                self.status_label.setStyleSheet(f"color: {muted};")
            if hasattr(self, "summary_label"):
                self.summary_label.setStyleSheet(f"color: {muted};")
            self._apply_content_dialog_theme(
                dark=is_dark,
                text=("#F3F3F3" if is_dark else "#202020"),
                muted=muted,
            )
        finally:
            self._applying_theme = False

    def _apply_content_dialog_theme(
        self,
        *,
        dark: bool | None = None,
        text: str | None = None,
        muted: str | None = None,
    ) -> None:
        dialog = self._content_dialog
        if dialog is None:
            return
        is_dark = isDarkTheme() if dark is None else bool(dark)
        foreground = text or ("#F3F3F3" if is_dark else "#202020")
        secondary = muted or (
            "rgba(255, 255, 255, 0.62)" if is_dark else "#666666"
        )
        background = "#202020" if is_dark else "#FFFFFF"
        editor_background = "#292929" if is_dark else "#FFFFFF"
        border = "rgba(255, 255, 255, 0.14)" if is_dark else "rgba(0, 0, 0, 0.12)"
        dialog.setStyleSheet(
            f"""
            QDialog#ArticleContextDialog {{
                background-color: {background};
                color: {foreground};
            }}
            QDialog#ArticleContextDialog QLabel {{
                color: {foreground};
            }}
            QDialog#ArticleContextDialog QTextEdit {{
                background-color: {editor_background};
                color: {foreground};
                border: 1px solid {border};
            }}
            QDialog#ArticleContextDialog QLabel#ArticleContextStatus {{
                color: {secondary};
            }}
            """
        )

    def changeEvent(self, event):
        if event.type() in (QEvent.PaletteChange, QEvent.ApplicationPaletteChange):
            self._apply_theme()
        super().changeEvent(event)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = BodyLabel(self.tr("参考原文（可选）"), self)
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        self.summary_label = BodyLabel(self.tr("未使用"), self)
        self.summary_label.setStyleSheet("color: #888888;")
        self.expand_button = QToolButton(self)
        self.expand_button.setArrowType(Qt.RightArrow)
        self.expand_button.setToolTip(self.tr("展开参考原文设置"))
        self.expand_button.setAutoRaise(True)
        self.expand_button.clicked.connect(self._toggle_content)
        header.addWidget(title)
        header.addWidget(self.summary_label)
        header.addStretch(1)
        header.addWidget(self.expand_button)
        layout.addLayout(header)

        self.content_widget = QWidget(self)
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 4, 0, 4)
        content_layout.setSpacing(10)

        self.text_edit = TextEdit(self)
        self.text_edit.setPlaceholderText(self.tr("粘贴英文参考文章，用于专名识别和翻译术语统一"))
        self.text_edit.setFixedHeight(180)
        content_layout.addWidget(self.text_edit)

        switch_row = QHBoxLayout()
        switch_row.setSpacing(18)
        self.asr_switch = SwitchButton(self)
        self.translation_switch = SwitchButton(self)
        self.asr_switch.setChecked(False)
        self.translation_switch.setChecked(False)
        switch_row.addWidget(BodyLabel(self.tr("使用原文辅助识别"), self))
        switch_row.addWidget(self.asr_switch)
        switch_row.addSpacing(18)
        switch_row.addWidget(BodyLabel(self.tr("使用原文统一翻译术语"), self))
        switch_row.addWidget(self.translation_switch)
        switch_row.addStretch(1)
        content_layout.addLayout(switch_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.analyze_button = PrimaryPushButton(self.tr("分析原文"), self)
        self.clear_button = PushButton(self.tr("清空"), self)
        button_row.addWidget(self.analyze_button)
        button_row.addWidget(self.clear_button)
        button_row.addStretch(1)
        content_layout.addLayout(button_row)

        self.status_label = BodyLabel(self.tr("未分析"), self)
        content_layout.addWidget(self.status_label)
        self.analyze_button.clicked.connect(self.analyze_article)
        self.clear_button.clicked.connect(self.clear_article)
        self._set_content_expanded(False)

    def _toggle_content(self) -> None:
        self._set_content_expanded(not self._content_expanded)

    def _set_content_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if expanded:
            self._open_content_dialog()
            return
        self._close_content_dialog()

    def _open_content_dialog(self) -> None:
        if self._content_dialog is not None:
            self._content_dialog.show()
            self._content_dialog.raise_()
            self._content_dialog.activateWindow()
            self._content_expanded = True
            return

        dialog = QDialog(self.window())
        dialog.setObjectName("ArticleContextDialog")
        dialog.setWindowTitle(self.tr("文章分析"))
        dialog.setModal(False)
        dialog.setAttribute(Qt.WA_DeleteOnClose, False)
        dialog.setMinimumSize(560, 360)
        dialog.resize(680, 470)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(16, 16, 16, 16)
        dialog_layout.addWidget(self.content_widget)
        self.content_widget.show()

        dialog.finished.connect(self._on_content_dialog_finished)
        self._content_dialog = dialog
        self._apply_content_dialog_theme()
        self._content_expanded = True
        self.expand_button.setArrowType(
            Qt.DownArrow
        )
        self.expand_button.setToolTip(self.tr("关闭文章分析窗口"))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _close_content_dialog(self) -> None:
        dialog = self._content_dialog
        if dialog is None:
            self._content_expanded = False
            self.expand_button.setArrowType(Qt.RightArrow)
            self.expand_button.setToolTip(self.tr("展开参考原文设置"))
            self.content_widget.hide()
            return
        dialog.close()

    def _on_content_dialog_finished(self, _result: int) -> None:
        dialog = self._content_dialog
        if dialog is None:
            return
        dialog_layout = dialog.layout()
        if dialog_layout is not None:
            dialog_layout.removeWidget(self.content_widget)
        self.content_widget.setParent(self)
        self.content_widget.hide()
        self._content_dialog = None
        self._content_expanded = False
        self.expand_button.setArrowType(Qt.RightArrow)
        self.expand_button.setToolTip(self.tr("展开参考原文设置"))
        dialog.deleteLater()

    def get_state(self):
        current_text = self.text_edit.toPlainText().strip()
        analysis_is_current = current_text == self.article_source_text.strip()
        return {
            "article_source_text": current_text,
            "article_context_data": (
                self.article_context_data
                if analysis_is_current
                else empty_article_context()
            ),
            "use_article_reference_assist": self.asr_switch.isChecked(),
            "use_article_translation_terms": self.translation_switch.isChecked(),
        }

    def clear_article(self):
        self.text_edit.clear()
        self.article_source_text = ""
        self.article_context_data = empty_article_context()
        self.status_label.setText(self.tr("已清空"))
        self.summary_label.setText(self.tr("未使用"))

    def analyze_article(self):
        article_text = self.text_edit.toPlainText().strip()
        if not article_text:
            self.clear_article()
            return
        if self.article_analysis_thread and self.article_analysis_thread.isRunning():
            InfoBar.warning(self.tr("提示"), self.tr("原文分析正在进行中"), duration=2000, parent=self)
            return

        self.article_source_text = article_text
        self.status_label.setText(self.tr("正在分析原文..."))
        self.summary_label.setText(self.tr("正在分析"))
        self.analyze_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        llm_runtime = resolve_llm_service_config()
        llm_config = ArticleLLMConfig(
            base_url=llm_runtime.base_url,
            api_key=llm_runtime.api_key,
            model=llm_runtime.model,
        )
        self.article_analysis_thread = ArticleContextThread(
            article_text,
            llm_config,
            output_dir=Path(cfg.work_dir.value) / "_article_context_preview",
        )
        self.article_analysis_thread.finished.connect(self._on_analysis_finished)
        self.article_analysis_thread.error.connect(self._on_analysis_error)
        self.article_analysis_thread.start()

    def _on_analysis_finished(self, context: dict, paths: dict):
        if self.text_edit.toPlainText().strip() != self.article_source_text.strip():
            self.article_context_data = empty_article_context()
            self.analyze_button.setEnabled(True)
            self.clear_button.setEnabled(True)
            self.status_label.setText(self.tr("原文已修改，需要重新分析"))
            self.summary_label.setText(self.tr("分析结果已失效"))
            return
        self.article_context_data = context
        self.analyze_button.setEnabled(True)
        self.clear_button.setEnabled(True)
        summary = context.get("summary", "").strip()
        glossary = build_translation_context_prompt(context)
        meta = context.get(ARTICLE_ANALYSIS_META_KEY) or {}
        cache_used = bool(meta.get("cache_used"))
        prefix = self.tr("命中缓存：") if cache_used else self.tr("新分析完成：")
        if summary:
            self.status_label.setText(prefix + summary[:80])
        elif glossary:
            self.status_label.setText(
                self.tr("命中缓存，已生成辅助词表")
                if cache_used
                else self.tr("新分析完成，已生成辅助词表")
            )
        else:
            self.status_label.setText(
                self.tr("命中缓存，分析完成")
                if cache_used
                else self.tr("新分析完成")
            )
        self.summary_label.setText(
            self.tr("已加载缓存词表") if cache_used else self.tr("已生成辅助词表")
        )
        InfoBar.success(
            self.tr("分析完成"),
            self.tr("命中缓存，已加载原文分析结果")
            if cache_used
            else self.tr("新文章分析完成"),
            duration=2000,
            parent=self,
        )

    def _on_analysis_error(self, error: str):
        self.article_context_data = empty_article_context()
        self.analyze_button.setEnabled(True)
        self.clear_button.setEnabled(True)
        self.status_label.setText(self.tr("分析失败，已回退原流程"))
        self.summary_label.setText(self.tr("分析失败，未使用"))
        InfoBar.warning(
            self.tr("分析失败"),
            self.tr("原文分析失败，字幕生成将继续使用原有流程"),
            duration=3000,
            parent=self,
        )
