# coding: utf-8
"""Rounded background subtitle renderer.

This is a small, old-codebase-compatible port of the upstream rounded subtitle
feature. It avoids adding Pillow/fontTools because this fork already ships PyQt5.
"""

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter

from app.core.bk_asr.asr_data import ASRData
from app.core.utils.logger import setup_logger

logger = setup_logger("rounded_subtitle")


@dataclass
class RoundedBgStyle:
    font_name: str = ""
    font_size: int = 28
    text_color: str = "#FFFFFF"
    cjk_font_name: str = ""
    cjk_font_size: int = 28
    cjk_text_color: str = "#FFFFFF"
    bg_color: str = "#191919C8"
    corner_radius: int = 14
    padding_h: int = 18
    padding_v: int = 12
    margin_bottom: int = 40
    line_spacing: int = 8
    letter_spacing: int = 0


_NO_SPACE_LANGUAGES = re.compile(
    r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af"
    r"\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff\u0900-\u0dff]"
)


def _get_video_info(video_path: str) -> Tuple[int, int, float]:
    result = subprocess.run(
        ["ffmpeg", "-i", video_path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )

    if match := re.search(r"Stream.*Video:.* (\d{2,5})x(\d{2,5})", result.stderr):
        width, height = int(match.group(1)), int(match.group(2))
    else:
        raise ValueError(f"Cannot get video resolution: {video_path}")

    duration = 0.0
    if match := re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr):
        h, m, s = match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)

    return width, height, duration


def _qcolor(hex_color: str) -> QColor:
    value = (hex_color or "").strip().lstrip("#")
    if len(value) == 8:
        return QColor(
            int(value[0:2], 16),
            int(value[2:4], 16),
            int(value[4:6], 16),
            int(value[6:8], 16),
        )
    if len(value) == 6:
        return QColor(f"#{value}")
    return QColor(25, 25, 25, 200)


def _font(style: RoundedBgStyle) -> QFont:
    font = QFont(style.font_name or "Arial")
    font.setPixelSize(max(8, int(style.font_size)))
    font.setHintingPreference(QFont.PreferFullHinting)
    if style.letter_spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, style.letter_spacing)
    return font


def _cjk_font(style: RoundedBgStyle) -> QFont:
    font = QFont(style.cjk_font_name or style.font_name or "Microsoft YaHei")
    font.setPixelSize(max(8, int(style.cjk_font_size or style.font_size)))
    font.setHintingPreference(QFont.PreferFullHinting)
    if style.letter_spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, style.letter_spacing)
    return font


def _text_width(metrics: QFontMetrics, text: str, spacing: int = 0) -> int:
    if not text:
        return 0
    width = metrics.horizontalAdvance(text)
    if spacing > 0 and len(text) > 1:
        width += spacing * (len(text) - 1)
    return width


def _is_mainly_cjk(text: str, threshold: float = 0.5) -> bool:
    compact = "".join(text.split())
    if not compact:
        return False
    return len(_NO_SPACE_LANGUAGES.findall(text)) / len(compact) > threshold


def _wrap_text(text: str, metrics: QFontMetrics, max_width: int, padding_h: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    available_width = max(80, max_width - padding_h * 2 - int(max_width * 0.1))
    if _text_width(metrics, text) <= available_width:
        return [text]

    units = list(text) if _is_mainly_cjk(text) else text.split()
    lines: List[str] = []
    current = ""

    for unit in units:
        candidate = current + unit if _is_mainly_cjk(text) else f"{current} {unit}".strip()
        if current and _text_width(metrics, candidate) > available_width:
            lines.append(current)
            current = unit
        else:
            current = candidate

    if current:
        lines.append(current)

    if len(lines) <= 1:
        return lines

    return _balance_lines(lines, units, metrics, available_width, _is_mainly_cjk(text))


def _balance_lines(
    greedy_lines: List[str],
    units: List[str],
    metrics: QFontMetrics,
    available_width: int,
    cjk: bool,
) -> List[str]:
    line_count = len(greedy_lines)
    if line_count <= 1:
        return greedy_lines

    joiner = "" if cjk else " "
    total_width = _text_width(metrics, joiner.join(units))
    target = total_width / line_count
    lines: List[str] = []
    current = ""

    for index, unit in enumerate(units):
        candidate = current + unit if cjk else f"{current} {unit}".strip()
        should_break = False
        if current and _text_width(metrics, candidate) > available_width:
            should_break = True
        elif current and len(lines) + 1 < line_count and _text_width(metrics, candidate) >= target * 0.92:
            if index + 1 < len(units):
                next_candidate = candidate + units[index + 1] if cjk else f"{candidate} {units[index + 1]}".strip()
                should_break = _text_width(metrics, next_candidate) > target * 1.08

        if should_break:
            lines.append(current)
            current = unit
        else:
            current = candidate

    if current:
        lines.append(current)
    return lines


def _block_size(metrics: QFontMetrics, lines: List[str], style: RoundedBgStyle) -> Tuple[int, int]:
    if not lines:
        return 0, 0
    width = max(_text_width(metrics, line, style.letter_spacing) for line in lines)
    line_height = metrics.height()
    height = line_height * len(lines) + style.line_spacing * (len(lines) - 1)
    return width + style.padding_h * 2, height + style.padding_v * 2


def _draw_text_block(
    painter: QPainter,
    metrics: QFontMetrics,
    lines: List[str],
    center_x: int,
    top_y: float,
    style: RoundedBgStyle,
    font: QFont,
    text_color: str,
) -> float:
    if not lines:
        return 0

    bg_width, bg_height = _block_size(metrics, lines, style)
    bg_left = center_x - bg_width / 2
    rect = QRectF(bg_left, top_y, bg_width, bg_height)

    painter.setPen(Qt.NoPen)
    painter.setBrush(_qcolor(style.bg_color))
    painter.drawRoundedRect(rect, style.corner_radius, style.corner_radius)

    painter.setFont(font)
    painter.setPen(_qcolor(text_color))
    line_height = metrics.height()
    y = top_y + style.padding_v
    for line in lines:
        text_width = _text_width(metrics, line, style.letter_spacing)
        x = center_x - text_width / 2
        painter.drawText(QRectF(x, y, text_width + 2, line_height), Qt.AlignCenter, line)
        y += line_height + style.line_spacing

    return bg_height


def render_subtitle_image(
    primary_text: str,
    secondary_text: str,
    width: int,
    height: int,
    style: RoundedBgStyle,
) -> QImage:
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    default_font = _font(style)
    cjk_font = _cjk_font(style)

    primary_is_cjk = _is_mainly_cjk(primary_text)
    secondary_is_cjk = _is_mainly_cjk(secondary_text)
    primary_font = cjk_font if primary_is_cjk else default_font
    secondary_font = cjk_font if secondary_is_cjk else default_font
    primary_metrics = QFontMetrics(primary_font)
    secondary_metrics = QFontMetrics(secondary_font)

    primary_lines = _wrap_text(primary_text, primary_metrics, width, style.padding_h)
    secondary_lines = _wrap_text(secondary_text, secondary_metrics, width, style.padding_h)

    primary_w, primary_h = _block_size(primary_metrics, primary_lines, style)
    secondary_w, secondary_h = _block_size(secondary_metrics, secondary_lines, style)
    gap = style.line_spacing if primary_h and secondary_h else 0
    total_h = primary_h + gap + secondary_h

    y = height - style.margin_bottom - total_h
    center_x = width // 2
    if primary_lines:
        y += _draw_text_block(
            painter,
            primary_metrics,
            primary_lines,
            center_x,
            y,
            style,
            primary_font,
            style.cjk_text_color if primary_is_cjk else style.text_color,
        ) + gap
    if secondary_lines:
        _draw_text_block(
            painter,
            secondary_metrics,
            secondary_lines,
            center_x,
            y,
            style,
            secondary_font,
            style.cjk_text_color if secondary_is_cjk else style.text_color,
        )

    painter.end()
    return image


def render_preview(
    primary_text: str,
    secondary_text: str = "",
    width: int = 1280,
    height: int = 720,
    style: Optional[RoundedBgStyle] = None,
    bg_image_path: Optional[str] = None,
    reference_height: int = 720,
) -> str:
    style = style or RoundedBgStyle()
    background = QImage(str(bg_image_path)) if bg_image_path and Path(bg_image_path).exists() else QImage()
    if background.isNull():
        background = QImage(width, height, QImage.Format_RGB32)
        background.fill(QColor(20, 20, 20))
    else:
        background = background.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        if background.width() != width or background.height() != height:
            background = background.copy(
                max(0, (background.width() - width) // 2),
                max(0, (background.height() - height) // 2),
                width,
                height,
            )

    scale = height / reference_height
    if scale != 1.0:
        style = _scale_style(style, scale)

    subtitle_img = render_subtitle_image(primary_text, secondary_text, width, height, style)
    painter = QPainter(background)
    painter.drawImage(0, 0, subtitle_img)
    painter.end()

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as tmp:
        path = tmp.name
    background.save(path, "PNG")
    return path


def _scale_style(style: RoundedBgStyle, scale: float) -> RoundedBgStyle:
    return replace(
        style,
        font_size=max(8, int(style.font_size * scale)),
        cjk_font_size=max(8, int(style.cjk_font_size * scale)),
        corner_radius=max(0, int(style.corner_radius * scale)),
        padding_h=max(0, int(style.padding_h * scale)),
        padding_v=max(0, int(style.padding_v * scale)),
        margin_bottom=max(0, int(style.margin_bottom * scale)),
        line_spacing=max(0, int(style.line_spacing * scale)),
        letter_spacing=max(0, int(style.letter_spacing * scale)),
    )


def _texts_for_layout(seg, layout: str) -> Tuple[str, str]:
    original = seg.text or ""
    translated = seg.translated_text or ""
    if layout == "仅原文":
        return original, ""
    if layout == "仅译文":
        return translated or original, ""
    if layout == "译文在上":
        return translated or original, original if translated else ""
    return original, translated


def render_rounded_video(
    video_path: str,
    asr_data: ASRData,
    output_path: str,
    rounded_style: Optional[dict] = None,
    layout: str = "原文在上",
    crf: int = 23,
    preset: str = "medium",
    progress_callback: Optional[Callable] = None,
    reference_height: int = 720,
) -> None:
    if not asr_data or not asr_data.segments:
        raise ValueError("Empty subtitle data, cannot render rounded subtitles")

    width, height, duration = _get_video_info(video_path)
    style = RoundedBgStyle(**(rounded_style or {}))
    scale = height / reference_height
    if scale != 1.0:
        style = _scale_style(style, scale)

    with tempfile.TemporaryDirectory(prefix="rounded_subtitle_") as tmp_dir:
        temp_path = Path(tmp_dir)
        frames = []
        for i, seg in enumerate(asr_data.segments):
            primary, secondary = _texts_for_layout(seg, layout)
            image = render_subtitle_image(primary, secondary, width, height, style)
            png_path = temp_path / f"subtitle_{i:06d}.png"
            image.save(str(png_path), "PNG")
            frames.append((png_path, seg.start_time / 1000, seg.end_time / 1000))
            if progress_callback and i % 10 == 0:
                progress_callback(int(i / max(1, len(asr_data.segments)) * 30), "正在生成圆角字幕")

        current_input = video_path
        batch_size = 50
        batch_count = (len(frames) + batch_size - 1) // batch_size
        intermediate_files = []

        for batch_index in range(batch_count):
            batch = frames[batch_index * batch_size : (batch_index + 1) * batch_size]
            is_last = batch_index == batch_count - 1
            batch_output = output_path if is_last else str(temp_path / f"batch_{batch_index:03d}.mp4")

            cmd = ["ffmpeg", "-y", "-i", current_input]
            for png_path, _, _ in batch:
                cmd.extend(["-i", str(png_path)])

            filter_parts = []
            previous = "[0:v]"
            for overlay_index, (_, start, end) in enumerate(batch):
                output_label = f"[v{overlay_index}]"
                enable = f"between(t\\,{start:.3f}\\,{end:.3f})"
                filter_parts.append(f"{previous}[{overlay_index + 1}:v]overlay=0:0:enable='{enable}'{output_label}")
                previous = output_label

            cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", previous, "-map", "0:a?"])
            if duration:
                cmd.extend(["-t", f"{duration:.3f}"])
            cmd.extend(["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-c:a", "copy", batch_output])

            logger.info("圆角字幕合成命令: %s", subprocess.list2cmdline(cmd))
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr[-2000:])

            if not is_last:
                intermediate_files.append(batch_output)
                current_input = batch_output

            if progress_callback:
                progress_callback(30 + int((batch_index + 1) / batch_count * 70), "正在叠加圆角字幕")

        for file_path in intermediate_files:
            try:
                Path(file_path).unlink(missing_ok=True)
            except Exception:
                logger.warning("无法删除圆角字幕临时文件: %s", file_path)
