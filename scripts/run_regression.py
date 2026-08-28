import argparse
import atexit
import datetime as _datetime
import os
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)
REGRESSION_LOG_DIR = ROOT / "output" / "regression-logs"
REGRESSION_SITE_CUSTOMIZE = ROOT / "sitecustomize.py"
_FAILURE_MARKERS = re.compile(r"AssertionError|Error:|FAILED|Traceback")
_LOG_NOISE = re.compile(r"logging|WinError 32", re.IGNORECASE)
_SITE_CUSTOMIZE_INSTALLED = False


def _regression_environment() -> dict[str, str]:
    """Keep test-only logging behavior out of the production logger config."""
    global _SITE_CUSTOMIZE_INSTALLED
    environment = os.environ.copy()
    environment["VC_REGRESSION_DISABLE_LOG_ROTATION"] = "1"
    owns_sitecustomize = environment.get("VC_REGRESSION_SITE_OWNER") != "1"
    if owns_sitecustomize:
        environment["VC_REGRESSION_SITE_OWNER"] = "1"
    if owns_sitecustomize and not _SITE_CUSTOMIZE_INSTALLED:
        REGRESSION_SITE_CUSTOMIZE.write_text(
            """import logging.handlers\nimport os\n\n\nif os.environ.get(\"VC_REGRESSION_DISABLE_LOG_ROTATION\") == \"1\":\n\n    class _RegressionFileHandler(logging.FileHandler):\n        def __init__(self, filename, mode=\"a\", encoding=None, delay=False, errors=None, **_):\n            super().__init__(filename, mode=mode, encoding=encoding, delay=delay, errors=errors)\n\n    logging.handlers.RotatingFileHandler = _RegressionFileHandler\n""",
            encoding="utf-8",
        )
        _SITE_CUSTOMIZE_INSTALLED = True
        atexit.register(_remove_test_sitecustomize)
    return environment


def _remove_test_sitecustomize() -> None:
    if _SITE_CUSTOMIZE_INSTALLED and REGRESSION_SITE_CUSTOMIZE.exists():
        REGRESSION_SITE_CUSTOMIZE.unlink()


def _write_step_log(name: str, output: str) -> Path:
    REGRESSION_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = _datetime.datetime.now().strftime("%Y%m%dT%H%M%S.%f")
    path = REGRESSION_LOG_DIR / f"{_slug(name)}-{timestamp}.log"
    path.write_text(output, encoding="utf-8")
    return path


def _failure_excerpt(output: str) -> list[str]:
    lines = [line for line in output.splitlines() if not _LOG_NOISE.search(line)]
    tail = lines[-30:]
    markers = [line for line in lines if _FAILURE_MARKERS.search(line)]
    return tail + [line for line in markers if line not in tail]


def run_step(
    name: str,
    args: list[str],
    allow_warning_exit: bool = False,
    *,
    verbose: bool = False,
) -> tuple[int, float]:
    print(f"\n== {name} ==")
    started = time.perf_counter()
    command = [str(PYTHON), *args]
    if verbose:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_regression_environment(),
        )
        output_parts: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            output_parts.append(line)
        result_code = process.wait()
        output = "".join(output_parts)
    else:
        result = subprocess.run(
            command,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_regression_environment(),
        )
        result_code = result.returncode
        output = result.stdout or ""
    elapsed = time.perf_counter() - started
    log_path = _write_step_log(name, output)
    if result_code != 0 and not allow_warning_exit:
        print(f"FAILED: {name} exited with {result_code}")
        for line in _failure_excerpt(output):
            print(line)
        print(f"Full log: {log_path}")
    print(f"{name}: {('PASS' if result_code == 0 else 'WARN' if allow_warning_exit else 'FAIL')} ({elapsed:.2f}s)")
    return result_code, elapsed


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the subtitle regression suite with reproducible profiles."
    )
    parser.add_argument(
        "--profile",
        choices=("fast", "pipeline", "full"),
        default="full",
        help="fast=stage-local checks, pipeline=core pipeline checks, full=all checks (default)",
    )
    parser.add_argument(
        "--only",
        help="comma-separated check slugs to run, for example stable-run-state,syntax-check",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="stop after the first failed check",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list check slugs and exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="stream each check's captured output to the terminal",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    options = _parse_args(argv)
    failures = []

    checks = [
        (
            "regression runner contract",
            ["tests/test_regression_runner.py"],
            False,
        ),
        (
            "ASR trust contract",
            ["tests/test_asr_trust_contract.py"],
            False,
        ),
        (
            "startup update security",
            ["tests/test_version_manager_security.py"],
            False,
        ),
        (
            "video synthesis publication safety",
            ["tests/test_video_synthesis_safety.py"],
            False,
        ),
        (
            "stable subtitle publication",
            ["tests/test_stable_publication.py"],
            False,
        ),
        (
            "article context state",
            ["tests/test_article_context_state.py"],
            False,
        ),
        (
            "task context contract",
            ["tests/test_task_context_contract.py"],
            False,
        ),
        (
            "LLM service configuration",
            ["tests/test_llm_service_config.py"],
            False,
        ),
        (
            "database reliability",
            ["tests/test_database_reliability.py"],
            False,
        ),
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
            "stable English global optimizer",
            ["tests/test_stable_english_optimizer.py"],
            False,
        ),
        (
            "English boundary rules",
            ["tests/test_english_boundary_rules.py"],
            False,
        ),
        (
            "historical boundary ratchet",
            ["tests/test_historical_boundary_ratchet.py"],
            False,
        ),
        (
            "historical empty display pages",
            ["tests/test_historical_empty_display_pages.py"],
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
            "stable display page translation contract",
            ["tests/test_stable_page_translation_contract.py"],
            False,
        ),
        (
            "article display readability contract",
            ["tests/test_article_display_readability_contract.py"],
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
            "user-facing issue text",
            ["tests/test_user_facing_issue_text.py"],
            False,
        ),
        (
            "qa review queue",
            ["tests/test_qa_review_queue.py"],
            False,
        ),
        (
            "translation review suggestions",
            ["tests/test_translation_review_suggestions.py"],
            False,
        ),
        (
            "fixed-ID translation quality audit",
            ["tests/test_translation_quality_audit.py"],
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
                "app/thread/transcript_thread.py",
                "app/thread/video_synthesis_thread.py",
                "app/thread/version_manager_thread.py",
                "app/thread/batch_process_thread.py",
                "app/view/main_window.py",
                "app/view/home_interface.py",
                "app/view/setting_interface.py",
                "app/view/task_creation_interface.py",
                "app/components/article_context_panel.py",
                "app/core/article_context.py",
                "app/core/entities.py",
                "app/core/llm_service_config.py",
                "app/core/task_factory.py",
                "app/core/storage/database.py",
                "app/core/bk_asr/base.py",
                "app/core/bk_asr/faster_whisper.py",
                "app/core/bk_asr/qwen3_asr_runner.py",
                "app/core/bk_asr/whisper_api.py",
                "app/core/bk_asr/whisper_cpp.py",
                "app/core/utils/video_utils.py",
                "app/core/utils/podcast_learning_video.py",
                "app/core/subtitle_processor/screen_editor.py",
                "app/core/subtitle_processor/final_cue_timeline.py",
                "app/core/subtitle_processor/stable_ts_alignment.py",
                "tests/test_stable_caption_rules.py",
                "tests/test_historical_boundary_ratchet.py",
                "tests/test_historical_empty_display_pages.py",
                "tests/test_asr_trust_contract.py",
                "tests/test_version_manager_security.py",
                "tests/test_video_synthesis_safety.py",
                "tests/test_stable_publication.py",
                "tests/test_article_context_state.py",
                "tests/test_task_context_contract.py",
                "tests/test_llm_service_config.py",
                "tests/test_database_reliability.py",
                "tests/test_final_cue_timeline.py",
                "tests/test_english_boundary_rules.py",
                "tests/test_rule_regression_library.py",
                "tests/test_allocation_only_replay.py",
                "tests/test_allocation_quality.py",
                "tests/test_stable_artifacts.py",
                "tests/test_stable_page_translation_contract.py",
                "tests/test_article_display_readability_contract.py",
                "tests/test_frozen_run_comparison.py",
                "tests/test_golden_subtitle_evaluation.py",
                "tests/test_manual_final_subtitle_editor.py",
                "tests/test_subtitle_review_marks.py",
                "tests/test_qa_review_queue.py",
                "tests/test_translation_review_suggestions.py",
                "scripts/build_qa_summary.py",
                "scripts/compare_frozen_mainline_runs.py",
                "scripts/evaluate_golden_subtitles.py",
                "scripts/run_allocation_only_replay.py",
                "app/core/subtitle_processor/manual_final_subtitle_editor.py",
                "app/core/subtitle_processor/authoritative_parent_chinese.py",
                "app/core/subtitle_processor/allocation_quality.py",
                "app/core/subtitle_processor/stable_artifacts.py",
                "app/core/subtitle_processor/stable_english_boundaries.py",
                "app/core/subtitle_processor/stable_english_optimizer.py",
                "app/core/subtitle_processor/subtitle_review_marks.py",
                "app/core/subtitle_processor/translation_quality_audit.py",
                "scripts/audit_opencode_translation_quality.py",
                "tests/test_translation_quality_audit.py",
                "app/core/subtitle_processor/user_facing_issue_text.py",
                "app/core/subtitle_processor/stable_run_state.py",
                "app/view/subtitle_interface.py",
                "tests/test_stable_run_state.py",
                "tests/test_stable_english_optimizer.py",
                "tests/test_user_facing_issue_text.py",
                "tests/test_regression_runner.py",
                "tests/audit_stable_outputs.py",
            ],
            False,
        ),
    ]

    available = {_slug(name): name for name, _, _ in checks}
    if options.list:
        for slug, name in available.items():
            print(f"{slug}\t{name}")
        return 0

    profile_keys = {
        "fast": {
            "regression-runner-contract",
            "stable-run-state",
            "stable-artifact-helpers",
            "article-context-state",
            "task-context-contract",
            "database-reliability",
            "golden-subtitle-evaluation",
            "syntax-check",
        },
        "pipeline": {
            "asr-trust-contract",
            "stable-subtitle-publication",
            "article-context-state",
            "task-context-contract",
            "final-cue-timeline",
            "stable-caption-smoke-tests",
            "stable-boundary-finalization",
            "stable-english-global-optimizer",
            "english-boundary-rules",
            "allocation-only-replay-contract",
            "allocation-quality-policy",
            "stable-artifact-helpers",
            "stable-display-page-translation-contract",
            "article-display-readability-contract",
            "manual-final-subtitle-editor",
            "subtitle-review-marks",
            "qa-review-queue",
            "translation-review-suggestions",
            "stable-run-state",
            "syntax-check",
        },
    }
    if options.only:
        requested = {_slug(item) for item in options.only.split(",") if item.strip()}
        unknown = sorted(requested - set(available))
        if unknown:
            print("Unknown checks: " + ", ".join(unknown), file=sys.stderr)
            print("Use --list to see available check slugs.", file=sys.stderr)
            return 2
        selected = requested
    elif options.profile == "full":
        selected = set(available)
    else:
        selected = profile_keys[options.profile]

    selected_checks = [check for check in checks if _slug(check[0]) in selected]
    print(
        f"Regression profile={options.profile} checks={len(selected_checks)} "
        f"fail_fast={options.fail_fast}"
    )
    started_all = time.perf_counter()
    for name, args, allow_warning_exit in selected_checks:
        code, _elapsed = run_step(
            name,
            args,
            allow_warning_exit=allow_warning_exit,
            verbose=options.verbose,
        )
        if code != 0 and not allow_warning_exit:
            failures.append(name)
            if options.fail_fast:
                break

    print(f"Regression elapsed: {time.perf_counter() - started_all:.2f}s")

    if failures:
        print("\nRegression failed:")
        for name in failures:
            print(f"- {name}")
        return 1

    print("\nRegression command completed.")
    print("Note: generated-output audits require an explicit fresh work-dir sample.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
