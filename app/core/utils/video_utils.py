import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Iterator, Literal, Optional

from app.core.bk_asr.asr_data import ASRData

from ..utils.logger import setup_logger
from ..utils.ass_auto_wrap import auto_wrap_ass_file
from ..utils.rounded_subtitle import render_rounded_video

logger = setup_logger("video_utils")


class MediaSynthesisCancelled(RuntimeError):
    """Raised when a caller cancels an active media synthesis process."""


@contextmanager
def staged_media_output(output: str | Path) -> Iterator[Path]:
    """Publish a non-empty media file atomically without destroying an old output."""
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}.",
        suffix=output_path.suffix or ".tmp",
        dir=str(output_path.parent),
    )
    os.close(descriptor)
    staged_path = Path(temp_name)
    staged_path.unlink(missing_ok=True)
    try:
        yield staged_path
        if not staged_path.is_file() or staged_path.stat().st_size <= 0:
            raise RuntimeError(
                f"媒体合成未生成有效输出文件：{staged_path}"
            )
        os.replace(staged_path, output_path)
    finally:
        staged_path.unlink(missing_ok=True)


def terminate_media_process(process, timeout_seconds: float = 2.0) -> None:
    """Terminate and reap a child process without masking the caller's error."""
    if process is None:
        return
    try:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout_seconds)
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        logger.warning("无法完整终止媒体子进程", exc_info=True)


def _cancel_requested(cancel_check: Optional[Callable[[], bool]]) -> bool:
    return bool(cancel_check and cancel_check())


def _run_ffmpeg_process(
    command: list[str],
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    process_callback: Optional[Callable[[object | None], None]] = None,
    stderr_line_callback: Optional[Callable[[str], None]] = None,
) -> None:
    """Run ffmpeg with live cancellation and retain its diagnostic stderr."""
    process = None
    stderr_lines: list[str] = []
    stderr_queue: queue.Queue[str] = queue.Queue()
    stderr_done = threading.Event()
    reader = None

    def read_stderr() -> None:
        try:
            while True:
                line = process.stderr.readline()
                if not line:
                    break
                stderr_lines.append(line)
                stderr_queue.put(line)
        finally:
            stderr_done.set()

    try:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )
        except Exception as exc:
            raise RuntimeError(f"无法启动 FFmpeg：{exc}") from exc

        if process_callback:
            process_callback(process)
        reader = threading.Thread(target=read_stderr, daemon=True)
        reader.start()

        while process.poll() is None or not stderr_done.is_set():
            if _cancel_requested(cancel_check):
                raise MediaSynthesisCancelled("视频合成已取消")
            try:
                line = stderr_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if stderr_line_callback:
                stderr_line_callback(line)

        reader.join(timeout=1.0)
        while True:
            try:
                line = stderr_queue.get_nowait()
            except queue.Empty:
                break
            if stderr_line_callback:
                stderr_line_callback(line)

        return_code = process.wait()
        if _cancel_requested(cancel_check):
            raise MediaSynthesisCancelled("视频合成已取消")
        if return_code != 0:
            detail = "".join(stderr_lines).strip()
            suffix = f"：{detail[-4000:]}" if detail else ""
            raise RuntimeError(f"FFmpeg 失败，退出码 {return_code}{suffix}")
    finally:
        terminate_media_process(process)
        if reader is not None:
            reader.join(timeout=1.0)
        if process is not None and process.stderr is not None:
            try:
                process.stderr.close()
            except OSError:
                logger.warning("无法关闭 FFmpeg 错误输出流", exc_info=True)
        if process_callback:
            process_callback(None)


def video2audio(input_file: str, output: str = "") -> bool:
    """使用ffmpeg将视频转换为音频"""
    # 创建output目录
    try:
        with staged_media_output(output) as staged_output:
            cmd = [
                "ffmpeg",
                "-i",
                input_file,
                "-map",
                "0:a",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-af",
                "aresample=async=1",  # 处理音频同步问题
                "-y",
                str(staged_output),
            ]
            logger.info("转换为音频执行命令: %s", subprocess.list2cmdline(cmd))
            _run_ffmpeg_process(cmd)
        return True
    except Exception as e:
        logger.exception(f"音频转换出错: {str(e)}")
        return False


def check_cuda_available() -> bool:
    """检查CUDA是否可用"""
    logger.info("检查CUDA是否可用")
    try:
        # 首先检查ffmpeg是否支持cuda
        result = subprocess.run(
            ["ffmpeg", "-hwaccels"],
            capture_output=True,
            text=True,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
        if "cuda" not in result.stdout.lower():
            logger.info("CUDA不在支持的硬件加速器列表中")
            return False

        # 进一步检查CUDA设备信息
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-init_hw_device", "cuda"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        # 如果stderr中包含"Cannot load cuda" 或 "Failed to load"等错误信息，说明CUDA不可用
        if any(
            error in result.stderr.lower()
            for error in ["cannot load cuda", "failed to load", "error"]
        ):
            logger.info("CUDA设备初始化失败")
            return False

        logger.info("CUDA可用")
        return True

    except Exception as e:
        logger.exception(f"检查CUDA出错: {str(e)}")
        return False


def add_subtitles(
    input_file: str,
    subtitle_file: str,
    output: str,
    quality: Literal[
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    ] = "medium",
    vcodec: str = "libx264",
    soft_subtitle: bool = False,
    render_mode: str = "ASS样式",
    subtitle_layout: str = "译文在上",
    rounded_style: Optional[dict] = None,
    progress_callback: callable = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    process_callback: Optional[Callable[[object | None], None]] = None,
) -> None:
    assert Path(input_file).is_file(), "输入文件不存在"
    assert Path(subtitle_file).is_file(), "字幕文件不存在"
    suffix = Path(subtitle_file).suffix.lower()
    if _cancel_requested(cancel_check):
        raise MediaSynthesisCancelled("视频合成已取消")

    with tempfile.TemporaryDirectory(prefix="VideoCaptioner-subtitle-") as temp_dir:
        temp_subtitle = Path(temp_dir) / f"subtitle{suffix}"
        shutil.copy2(subtitle_file, temp_subtitle)
        prepared_subtitle = str(temp_subtitle)

        if suffix == ".ass":
            prepared_subtitle = auto_wrap_ass_file(prepared_subtitle)

        if Path(output).suffix.lower() == ".webm":
            soft_subtitle = False
            logger.info("WebM格式视频，强制使用硬字幕")

        if not soft_subtitle and render_mode == "圆角背景":
            logger.info("使用圆角背景硬字幕渲染")
            asr_data = ASRData.from_subtitle_file(prepared_subtitle)
            with staged_media_output(output) as staged_output:
                render_rounded_video(
                    input_file,
                    asr_data,
                    str(staged_output),
                    rounded_style=rounded_style,
                    layout=subtitle_layout,
                    preset=quality,
                    progress_callback=progress_callback,
                )
                if _cancel_requested(cancel_check):
                    raise MediaSynthesisCancelled("视频合成已取消")
            return

        with staged_media_output(output) as staged_output:
            if soft_subtitle:
                cmd = [
                    "ffmpeg",
                    "-i",
                    input_file,
                    "-i",
                    prepared_subtitle,
                    "-c:v",
                    "copy",
                    "-c:a",
                    "copy",
                    "-c:s",
                    "mov_text",
                    "-y",
                    str(staged_output),
                ]
                logger.info(
                    "添加软字幕执行命令: %s", subprocess.list2cmdline(cmd)
                )
                _run_ffmpeg_process(
                    cmd,
                    cancel_check=cancel_check,
                    process_callback=process_callback,
                )
                if progress_callback:
                    progress_callback(100, "合成完成")
                return

            logger.info("使用硬字幕")
            filter_subtitle = Path(prepared_subtitle).as_posix().replace(":", r"\:")
            if Path(output).suffix.lower() == ".ass":
                vf = f"ass='{filter_subtitle}'"
            else:
                vf = f"subtitles='{filter_subtitle}'"

            if Path(output).suffix.lower() == ".webm":
                vcodec = "libvpx-vp9"
                logger.info("WebM格式视频，使用libvpx-vp9编码器")

            use_cuda = check_cuda_available()
            if _cancel_requested(cancel_check):
                raise MediaSynthesisCancelled("视频合成已取消")
            cmd = ["ffmpeg"]
            if use_cuda:
                logger.info("使用CUDA加速")
                cmd.extend(["-hwaccel", "cuda"])
            cmd.extend(
                [
                    "-i",
                    input_file,
                    "-acodec",
                    "copy",
                    "-vcodec",
                    vcodec,
                    "-preset",
                    quality,
                    "-vf",
                    vf,
                    "-y",
                    str(staged_output),
                ]
            )

            logger.info("添加硬字幕执行命令: %s", subprocess.list2cmdline(cmd))
            total_duration = None

            def handle_stderr_line(output_line: str) -> None:
                nonlocal total_duration
                if not progress_callback:
                    return
                if total_duration is None:
                    duration_match = re.search(
                        r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d{2})",
                        output_line,
                    )
                    if duration_match:
                        h, m, s = map(float, duration_match.groups())
                        total_duration = h * 3600 + m * 60 + s
                        logger.info("视频总时长: %s秒", total_duration)

                time_match = re.search(
                    r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})", output_line
                )
                if time_match and total_duration:
                    h, m, s = map(float, time_match.groups())
                    current_time = h * 3600 + m * 60 + s
                    progress_callback(
                        min(99, round(current_time / total_duration * 100)),
                        "正在合成",
                    )

            _run_ffmpeg_process(
                cmd,
                cancel_check=cancel_check,
                process_callback=process_callback,
                stderr_line_callback=handle_stderr_line,
            )
            if progress_callback:
                progress_callback(100, "合成完成")


def get_video_info(file_path: str) -> Optional[Dict]:
    """获取视频信息"""
    try:
        cmd = ["ffmpeg", "-i", file_path]

        # logger.info(f"获取视频信息执行命令: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
        info = result.stderr

        video_info_dict = {
            "file_name": Path(file_path).stem,
            "file_path": file_path,
            "duration_seconds": 0,
            "bitrate_kbps": 0,
            "video_codec": "",
            "width": 0,
            "height": 0,
            "fps": 0,
            "audio_codec": "",
            "audio_sampling_rate": 0,
            "thumbnail_path": "",
        }

        # 提取时长
        if duration_match := re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", info):
            hours, minutes, seconds = map(float, duration_match.groups())
            video_info_dict["duration_seconds"] = hours * 3600 + minutes * 60 + seconds

        # 提取比特率
        if bitrate_match := re.search(r"bitrate: (\d+) kb/s", info):
            video_info_dict["bitrate_kbps"] = int(bitrate_match.group(1))

        # 提取视频流信息
        if video_stream_match := re.search(
            r"Stream #.*?Video: (\w+)(?:\s*\([^)]*\))?.* (\d+)x(\d+).*?(?:(\d+(?:\.\d+)?)\s*(?:fps|tb[rn]))",
            info,
            re.DOTALL,
        ):
            video_info_dict.update(
                {
                    "video_codec": video_stream_match.group(1),
                    "width": int(video_stream_match.group(2)),
                    "height": int(video_stream_match.group(3)),
                    "fps": float(video_stream_match.group(4)),
                }
            )
        else:
            logger.warning("未找到视频流信息")

        return video_info_dict
    except Exception as e:
        logger.exception(f"获取视频信息时出错: {str(e)}")
        return None
