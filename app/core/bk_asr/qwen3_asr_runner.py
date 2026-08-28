import argparse
import json
import re
from pathlib import Path


LANGUAGE_MAP = {
    "en": "English",
    "zh": "Chinese",
    "yue": "Cantonese",
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "ru": "Russian",
    "it": "Italian",
    "nl": "Dutch",
    "sv": "Swedish",
    "pl": "Polish",
    "tr": "Turkish",
    "th": "Thai",
    "vi": "Vietnamese",
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args()


def torch_dtype(dtype_name: str, device: str):
    import torch

    dtype_name = (dtype_name or "").lower()
    if device == "cpu":
        return torch.float32
    if dtype_name in {"bfloat16", "bf16"}:
        return torch.bfloat16
    if dtype_name in {"float32", "fp32"}:
        return torch.float32
    return torch.float16


def audio_duration_ms(audio_path: str) -> int:
    try:
        import librosa

        duration_ms = int(librosa.get_duration(path=audio_path) * 1000)
    except Exception as exc:
        raise RuntimeError("Unable to determine source audio duration") from exc
    if duration_ms <= 0:
        raise RuntimeError("Source audio duration must be positive")
    return duration_ms


def proportional_word_segments(text: str, duration_ms: int):
    words = re.findall(
        r"[A-Za-z]+(?:[-'’][A-Za-z]+)*(?:[.,!?;:]+)?"
        r"|\d+(?:[.,]\d+)*(?:%?)(?:[.,!?;:]+)?|\S",
        text,
    )
    if not words:
        return []
    if duration_ms < len(words):
        raise ValueError(
            "Source audio duration is too short for non-overlapping proportional timing"
        )
    segments = []
    for index, word in enumerate(words):
        start = int(duration_ms * index / len(words))
        end = int(duration_ms * (index + 1) / len(words))
        segments.append(
            {
                "text": word,
                "start_time": start,
                "end_time": end,
                "timing_source": "proportional_text_fallback",
                "word_timing_trusted": False,
            }
        )
    return segments


def main():
    args = parse_args()
    payload = json.loads(Path(args.input_json).read_text(encoding="utf-8-sig"))

    audio_path = payload["audio_path"]
    asr_model = payload.get("asr_model") or "Qwen/Qwen3-ASR-0.6B"
    aligner_model = payload.get("aligner_model") or "Qwen/Qwen3-ForcedAligner-0.6B"
    need_word_time_stamp = bool(payload.get("need_word_time_stamp", False))
    device = payload.get("device") or "cuda"
    dtype_name = payload.get("dtype") or "float16"
    language_code = str(payload.get("language") or "").strip().lower()
    if language_code == "english":
        language_code = "en"
    if language_code not in LANGUAGE_MAP:
        raise ValueError(f"Unsupported Qwen3-ASR language code: {language_code!r}")
    language = LANGUAGE_MAP[language_code]

    import torch
    from qwen_asr import Qwen3ASRModel

    dtype = torch_dtype(dtype_name, device)
    device_map = "cuda:0" if device == "cuda" else "cpu"
    common_kwargs = {
        "device_map": device_map,
        "dtype": dtype,
    }
    if device == "cuda":
        common_kwargs["low_cpu_mem_usage"] = True

    model = Qwen3ASRModel.from_pretrained(
        asr_model,
        forced_aligner=aligner_model if need_word_time_stamp else None,
        forced_aligner_kwargs=common_kwargs if need_word_time_stamp else None,
        max_inference_batch_size=1,
        max_new_tokens=2048,
        **common_kwargs,
    )

    results = model.transcribe(
        audio_path,
        language=language,
        return_time_stamps=need_word_time_stamp,
    )
    result = results[0]
    text = (result.text or "").strip()
    duration_ms = audio_duration_ms(audio_path)

    segments = []
    timing_source = "segment_timestamps"
    word_timing_trusted = False
    if need_word_time_stamp and result.time_stamps:
        timing_source = "qwen3_forced_aligner"
        word_timing_trusted = True
        for item in result.time_stamps:
            item_text = str(item.text).strip()
            if not item_text:
                continue
            start_ms = int(round(float(item.start_time) * 1000))
            end_ms = int(round(float(item.end_time) * 1000))
            segments.append(
                {
                    "text": item_text,
                    "start_time": max(0, start_ms),
                    "end_time": max(start_ms + 1, end_ms),
                    "timing_source": timing_source,
                    "word_timing_trusted": True,
                }
            )
    if not segments:
        if need_word_time_stamp:
            segments = proportional_word_segments(text, duration_ms)
            timing_source = "proportional_text_fallback"
            word_timing_trusted = False
        elif text:
            segments = [
                {
                    "text": text,
                    "start_time": 0,
                    "end_time": duration_ms,
                    "timing_source": timing_source,
                    "word_timing_trusted": False,
                }
            ]

    output = {
        "language": result.language,
        "text": text,
        "duration_ms": duration_ms,
        "segments": segments,
        "timing_source": timing_source,
        "word_timing_trusted": word_timing_trusted,
    }
    Path(args.output_json).write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
