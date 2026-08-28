import unittest
from unittest.mock import patch

from app.components.article_context_panel import ArticleContextPanel


class _TextEdit:
    def __init__(self, text):
        self.text = text

    def toPlainText(self):
        return self.text


class _Switch:
    def __init__(self, checked):
        self.checked = checked

    def isChecked(self):
        return self.checked


class _Dialog:
    def __init__(self):
        self.stylesheet = ""

    def setStyleSheet(self, stylesheet):
        self.stylesheet = stylesheet


class ArticleContextStateTests(unittest.TestCase):
    def test_changed_article_text_invalidates_previous_analysis(self):
        panel = ArticleContextPanel.__new__(ArticleContextPanel)
        panel.text_edit = _TextEdit("Article B")
        panel.article_source_text = "Article A"
        panel.article_context_data = {"summary": "Analysis for A"}
        panel.asr_switch = _Switch(True)
        panel.translation_switch = _Switch(True)

        state = panel.get_state()

        self.assertEqual(state["article_source_text"], "Article B")
        self.assertEqual(state["article_context_data"]["summary"], "")
        self.assertTrue(state["use_article_reference_assist"])

    def test_unchanged_article_text_keeps_analysis(self):
        panel = ArticleContextPanel.__new__(ArticleContextPanel)
        panel.text_edit = _TextEdit("Article A")
        panel.article_source_text = "Article A"
        panel.article_context_data = {"summary": "Analysis for A"}
        panel.asr_switch = _Switch(False)
        panel.translation_switch = _Switch(True)

        state = panel.get_state()

        self.assertEqual(state["article_context_data"]["summary"], "Analysis for A")

    def test_article_analysis_dialog_uses_dark_palette_colors(self):
        panel = ArticleContextPanel.__new__(ArticleContextPanel)
        panel._content_dialog = _Dialog()

        with patch(
            "app.components.article_context_panel.isDarkTheme", return_value=True
        ):
            panel._apply_content_dialog_theme()

        self.assertIn("background-color: #202020", panel._content_dialog.stylesheet)
        self.assertIn("background-color: #292929", panel._content_dialog.stylesheet)
        self.assertIn("color: #F3F3F3", panel._content_dialog.stylesheet)
        self.assertIn("rgba(255, 255, 255, 0.14)", panel._content_dialog.stylesheet)

    def test_theme_change_invalidates_cached_panel_theme(self):
        panel = ArticleContextPanel.__new__(ArticleContextPanel)
        panel._last_theme_is_dark = False
        with patch.object(panel, "_apply_theme") as apply_theme:
            panel._on_theme_changed()

        self.assertIsNone(panel._last_theme_is_dark)
        apply_theme.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
