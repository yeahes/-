import unittest

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


if __name__ == "__main__":
    unittest.main()
