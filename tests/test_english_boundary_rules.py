"""Fixture-backed contracts for local stable English boundary legality."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.bk_asr.asr_data import ASRDataSeg
from app.core.subtitle_processor.screen_editor import ScreenSubtitleEditor


CASES_PATH = ROOT / "tests" / "fixtures" / "stable_boundaries" / "syntax_boundary_contract.json"


def _boundary_editor(words):
    editor = ScreenSubtitleEditor.__new__(ScreenSubtitleEditor)
    editor.max_english_words = 16
    editor._syntax_protected_cuts = set()
    editor._syntax_hard_cut_issues = {}
    editor._syntax_nlp = None
    editor._active_word_entries = [
        {
            "token": ScreenSubtitleEditor._word_tokens(word)[0],
            "surface": word,
            "start_time": index * 200,
            "end_time": index * 200 + 120,
        }
        for index, word in enumerate(words)
    ]
    editor._active_source_word_spans = {
        index + 1: (index, index) for index in range(len(words))
    }
    editor._active_source_segments_by_id = {
        index + 1: ASRDataSeg(word, index * 200, index * 200 + 120, "")
        for index, word in enumerate(words)
    }
    return editor


def test_fixture_backed_stable_boundary_contracts():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        editor = _boundary_editor(case["words"])
        if case.get("manual_syntax_issue"):
            editor._record_syntax_hard_issue_for_indices(
                case["manual_syntax_indices"],
                case["manual_syntax_issue"],
            )
        for cut_after in case["cut_after_indices"]:
            evaluation = editor._evaluate_stable_cut_boundary(cut_after, cut_after + 1)
            assert evaluation["legal"] is case["expected_legal"], (case["id"], evaluation)
            if case["expected_issue"]:
                assert case["expected_issue"] in evaluation["hard_issues"], (
                    case["id"],
                    evaluation,
                )
            else:
                assert evaluation["hard_issues"] == [], (case["id"], evaluation)


if __name__ == "__main__":
    test_fixture_backed_stable_boundary_contracts()
    print("English boundary rule tests passed.")
