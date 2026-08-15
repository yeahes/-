from pathlib import Path


MEDIA_RESULT_DIR_SUFFIX = "-处理结果"
MEDIA_RESULT_SUBTITLE_DIR = "字幕文件"
MEDIA_RESULT_QUALITY_DIR = "质检报告"
MEDIA_RESULT_VIDEO_DIR = "视频成片"
MEDIA_RESULT_MANUAL_PACKAGE_DIR = "人工终稿字幕包"


def media_result_dir(
    media_path: str | Path,
    *,
    output_anchor: str | Path | None = None,
) -> Path:
    """Return one media-named result directory at the selected output anchor."""
    media = Path(media_path)
    anchor = Path(output_anchor) if output_anchor is not None else media
    for node in (anchor, *anchor.parents):
        if node.name.endswith(MEDIA_RESULT_DIR_SUFFIX):
            return node
    return anchor.parent / f"{media.stem}{MEDIA_RESULT_DIR_SUFFIX}"


def containing_media_result_dir(path: str | Path) -> Path | None:
    """Return an owned result ancestor without guessing from a sibling name."""
    candidate = Path(path)
    for node in (candidate, *candidate.parents):
        if node.name.endswith(MEDIA_RESULT_DIR_SUFFIX):
            return node
    return None


def media_result_subtitle_dir(
    media_path: str | Path,
    *,
    output_anchor: str | Path | None = None,
) -> Path:
    """Return the user-facing subtitle directory for one media item."""
    return media_result_dir(media_path, output_anchor=output_anchor) / MEDIA_RESULT_SUBTITLE_DIR


def media_result_quality_dir(
    media_path: str | Path,
    *,
    output_anchor: str | Path | None = None,
) -> Path:
    """Return the user-facing validation and review directory."""
    return media_result_dir(media_path, output_anchor=output_anchor) / MEDIA_RESULT_QUALITY_DIR


def media_result_video_dir(
    media_path: str | Path,
    *,
    output_anchor: str | Path | None = None,
) -> Path:
    """Return the user-facing rendered-video directory."""
    return media_result_dir(media_path, output_anchor=output_anchor) / MEDIA_RESULT_VIDEO_DIR


def media_result_manual_package_dir(
    media_path: str | Path,
    *,
    output_anchor: str | Path | None = None,
) -> Path:
    """Return the manifest-owned manual-final package directory."""
    return media_result_dir(media_path, output_anchor=output_anchor) / MEDIA_RESULT_MANUAL_PACKAGE_DIR
