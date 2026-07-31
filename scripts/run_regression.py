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
            "stable caption smoke tests",
            ["tests/test_stable_caption_rules.py"],
            False,
        ),
        (
            "rule regression library",
            ["tests/test_rule_regression_library.py"],
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
                "tests/test_stable_caption_rules.py",
                "tests/test_rule_regression_library.py",
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
