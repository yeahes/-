import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)


def run_step(name: str, args: list[str], allow_warning_exit: bool = False) -> int:
    print(f"\n== {name} ==")
    result = subprocess.run(
        [str(PYTHON), *args],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 and not allow_warning_exit:
        print(f"FAILED: {name} exited with {result.returncode}")
    return result.returncode


def main() -> int:
    failures = []

    checks = [
        (
            "final cue timeline",
            ["tests/test_final_cue_timeline.py"],
            False,
        ),
        (
            "stable caption smoke tests",
            ["tests/test_stable_caption_rules.py"],
            False,
        ),
        (
            "stable boundary finalization",
            ["tests/test_stable_boundary_finalization.py"],
            False,
        ),
        (
            "English boundary rules",
            ["tests/test_english_boundary_rules.py"],
            False,
        ),
        (
            "rule regression library",
            ["tests/test_rule_regression_library.py"],
            False,
        ),
        (
            "allocation-only replay contract",
            ["tests/test_allocation_only_replay.py"],
            False,
        ),
        (
            "allocation quality policy",
            ["tests/test_allocation_quality.py"],
            False,
        ),
        (
            "stable artifact helpers",
            ["tests/test_stable_artifacts.py"],
            False,
        ),
        (
            "frozen run comparison",
            ["tests/test_frozen_run_comparison.py"],
            False,
        ),
        (
            "golden subtitle evaluation",
            ["tests/test_golden_subtitle_evaluation.py"],
            False,
        ),
        (
            "manual final subtitle editor",
            ["tests/test_manual_final_subtitle_editor.py"],
            False,
        ),
        (
            "subtitle review marks",
            ["tests/test_subtitle_review_marks.py"],
            False,
        ),
        (
            "qa review queue",
            ["tests/test_qa_review_queue.py"],
            False,
        ),
        (
            "stable run state",
            ["tests/test_stable_run_state.py"],
            False,
        ),
        (
            "syntax check",
            [
                "-m",
                "py_compile",
                "app/thread/subtitle_thread.py",
                "app/thread/video_synthesis_thread.py",
                "app/core/subtitle_processor/screen_editor.py",
                "app/core/subtitle_processor/final_cue_timeline.py",
                "app/core/subtitle_processor/stable_ts_alignment.py",
                "tests/test_stable_caption_rules.py",
                "tests/test_final_cue_timeline.py",
                "tests/test_english_boundary_rules.py",
                "tests/test_rule_regression_library.py",
                "tests/test_allocation_only_replay.py",
                "tests/test_allocation_quality.py",
                "tests/test_stable_artifacts.py",
                "tests/test_frozen_run_comparison.py",
                "tests/test_golden_subtitle_evaluation.py",
                "tests/test_manual_final_subtitle_editor.py",
                "tests/test_subtitle_review_marks.py",
                "tests/test_qa_review_queue.py",
                "scripts/build_qa_summary.py",
                "scripts/compare_frozen_mainline_runs.py",
                "scripts/evaluate_golden_subtitles.py",
                "app/core/subtitle_processor/manual_final_subtitle_editor.py",
                "app/core/subtitle_processor/allocation_quality.py",
                "app/core/subtitle_processor/stable_artifacts.py",
                "app/core/subtitle_processor/stable_english_boundaries.py",
                "app/core/subtitle_processor/subtitle_review_marks.py",
                "app/core/subtitle_processor/stable_run_state.py",
                "app/view/subtitle_interface.py",
                "tests/test_stable_run_state.py",
                "tests/audit_stable_outputs.py",
            ],
            False,
        ),
        (
            "known output audit",
            ["tests/audit_stable_outputs.py", "222", "777", "999"],
            True,
        ),
    ]

    for name, args, allow_warning_exit in checks:
        code = run_step(name, args, allow_warning_exit=allow_warning_exit)
        if code != 0 and not allow_warning_exit:
            failures.append(name)

    if failures:
        print("\nRegression failed:")
        for name in failures:
            print(f"- {name}")
        return 1

    print("\nRegression command completed.")
    print("Note: output audit may report ERROR for stale local work-dir samples.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
