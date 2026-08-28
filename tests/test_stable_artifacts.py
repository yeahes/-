import json
import tempfile
from enum import Enum
from pathlib import Path

from app.core.subtitle_processor.stable_artifacts import (
    stable_artifact_dir,
    write_json_artifact,
    write_json_artifact_set,
)


def test_stable_artifact_dir_uses_the_coverage_report_stem():
    assert stable_artifact_dir(Path("C:/subtitle/example-coverage-report.txt")) == Path(
        "C:/subtitle/example-artifacts"
    )


def test_stable_artifact_dir_keeps_an_ordinary_report_stem():
    assert stable_artifact_dir(Path("C:/subtitle/validation.txt")) == Path(
        "C:/subtitle/validation-artifacts"
    )


def test_write_json_artifact_preserves_unicode_and_indentation():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "artifact.json"
        write_json_artifact(path, {"title": "中文字幕", "items": [1, 2]})

        assert json.loads(path.read_text(encoding="utf-8")) == {
            "title": "中文字幕",
            "items": [1, 2],
        }
        assert "中文字幕" in path.read_text(encoding="utf-8")


def test_write_json_artifact_serializes_enum_configuration_values():
    class Target(Enum):
        CHINESE = "简体中文"

    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "enum.json"
        write_json_artifact(path, {"target_language": Target.CHINESE})

        assert json.loads(path.read_text(encoding="utf-8")) == {
            "target_language": "简体中文"
        }


def test_write_json_artifact_compact_mode_remains_readable():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "draft.json"
        payload = {"title": "恢复草稿", "items": [1, 2, 3]}

        write_json_artifact(path, payload, compact=True)

        raw = path.read_text(encoding="utf-8")
        assert json.loads(raw) == payload
        assert "\n" not in raw
        assert ": " not in raw


def test_write_json_artifact_set_preserves_the_given_filenames_and_payloads():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        write_json_artifact_set(
            artifact_dir,
            (
                ("run-manifest.json", {"schema": 2}),
                ("allocation-final.json", {"S0001": "中文"}),
            ),
        )

        assert json.loads((artifact_dir / "run-manifest.json").read_text(encoding="utf-8")) == {
            "schema": 2
        }
        assert json.loads(
            (artifact_dir / "allocation-final.json").read_text(encoding="utf-8")
        ) == {"S0001": "中文"}


def test_single_and_batch_writers_use_the_same_json_serialization():
    with tempfile.TemporaryDirectory() as temp_dir:
        artifact_dir = Path(temp_dir)
        direct_path = artifact_dir / "direct.json"
        write_json_artifact(direct_path, {"title": "验证", "items": [1]})
        write_json_artifact_set(
            artifact_dir,
            (("batch.json", {"title": "验证", "items": [1]}),),
        )

        assert direct_path.read_text(encoding="utf-8") == (
            artifact_dir / "batch.json"
        ).read_text(encoding="utf-8")


if __name__ == "__main__":
    test_stable_artifact_dir_uses_the_coverage_report_stem()
    test_stable_artifact_dir_keeps_an_ordinary_report_stem()
    test_write_json_artifact_preserves_unicode_and_indentation()
    test_write_json_artifact_serializes_enum_configuration_values()
    test_write_json_artifact_compact_mode_remains_readable()
    test_write_json_artifact_set_preserves_the_given_filenames_and_payloads()
    test_single_and_batch_writers_use_the_same_json_serialization()
    print("stable artifact helper tests passed")
