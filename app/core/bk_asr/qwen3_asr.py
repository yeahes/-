import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from app.core.utils.logger import setup_logger

from .asr_data import ASRDataSeg
from .base import BaseASR

logger = setup_logger("qwen3_asr")


class Qwen3ASR(BaseASR):
    """Local Qwen3-ASR adapter executed in an isolated Python subprocess."""

    def __init__(
        self,
        audio_path: str,
        use_cache: bool = False,
        need_word_time_stamp: bool = False,
        python_path: Optional[str] = None,
        asr_model: str = "Qwen/Qwen3-ASR-0.6B",
        aligner_model: str = "Qwen/Qwen3-ForcedAligner-0.6B",
        language: str = "en",
        device: str = "cuda",
        dtype: str = "float16",
    ):
        super().__init__(
            audio_path=audio_path,
            use_cache=use_cache,
            need_word_time_stamp=need_word_time_stamp,
        )
        self.need_word_time_stamp = need_word_time_stamp
        self.python_path = python_path or sys.executable
        self.asr_model = asr_model
        self.aligner_model = aligner_model
        self.language = language
        self.device = device
        self.dtype = dtype

    def _get_key(self):
        return "-".join(
            [
                self.crc32_hex,
                str(self.need_word_time_stamp),
                self.asr_model,
                self.aligner_model if self.need_word_time_stamp else "",
                self.language,
                self.device,
                self.dtype,
            ]
        )

    def _run(self, callback=None, **kwargs) -> dict:
        if callback:
            callback(5, "Qwen3-ASR识别")

        python_path = Path(self.python_path)
        if not python_path.exists():
            raise RuntimeError(
                f"Qwen3-ASR Python不存在: {python_path}\n"
                "请先安装独立运行环境，或在Qwen3-ASR设置中填写正确的python.exe路径。"
            )

        runner_path = Path(__file__).with_name("qwen3_asr_runner.py")
        with tempfile.TemporaryDirectory(prefix="qwen3_asr_") as temp_dir:
            temp_dir_path = Path(temp_dir)
            input_path = temp_dir_path / "input.json"
            output_path = temp_dir_path / "output.json"
            input_path.write_text(
                json.dumps(
                    {
                        "audio_path": str(self.audio_path),
                        "asr_model": self.asr_model,
                        "aligner_model": self.aligner_model,
                        "language": self.language,
                        "need_word_time_stamp": self.need_word_time_stamp,
                        "device": self.device,
                        "dtype": self.dtype,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            cmd = [
                str(python_path),
                str(runner_path),
                "--input-json",
                str(input_path),
                "--output-json",
                str(output_path),
            ]
            logger.info("Qwen3-ASR执行命令: %s", " ".join(cmd))
            env = os.environ.copy()
            env.setdefault(
                "HF_HOME",
                str(Path(__file__).resolve().parents[3] / "qwen3-cache"),
            )
            env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if completed.stdout:
                logger.info("Qwen3-ASR输出: %s", completed.stdout.strip())
            if completed.returncode != 0:
                logger.error("Qwen3-ASR错误: %s", completed.stderr.strip())
                raise RuntimeError(
                    "Qwen3-ASR执行失败。\n"
                    f"返回码: {completed.returncode}\n"
                    f"错误: {completed.stderr.strip()}"
                )
            if not output_path.exists():
                raise RuntimeError("Qwen3-ASR未生成输出文件")
            if callback:
                callback(95, "Qwen3-ASR完成")
            return json.loads(output_path.read_text(encoding="utf-8"))

    def _make_segments(self, resp_data: dict) -> list[ASRDataSeg]:
        segments = []
        for item in resp_data.get("segments", []):
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            start_time = int(max(0, float(item.get("start_time", 0))))
            end_time = int(max(start_time + 1, float(item.get("end_time", start_time + 1))))
            segments.append(
                ASRDataSeg(
                    text=text,
                    start_time=start_time,
                    end_time=end_time,
                )
            )
        if not segments and resp_data.get("text"):
            segments.append(
                ASRDataSeg(
                    text=str(resp_data["text"]).strip(),
                    start_time=0,
                    end_time=max(1, int(resp_data.get("duration_ms", 1))),
                )
            )
        return segments
