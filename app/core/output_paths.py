from pathlib import Path


MEDIA_RESULT_DIR_SUFFIX = "-处理结果"


def media_result_dir(
    media_path: str | Path,
    *,
    output_anchor: str | Path | None = None,
) -> Path:
    """Return one media-named result directory at the selected output anchor."""
    media = Path(media_path)
    anchor = Path(output_anchor) if output_anchor is not None else media
    for parent in anchor.parents:
        if parent.name.endswith(MEDIA_RESULT_DIR_SUFFIX):
            return parent
    return anchor.parent / f"{media.stem}{MEDIA_RESULT_DIR_SUFFIX}"
