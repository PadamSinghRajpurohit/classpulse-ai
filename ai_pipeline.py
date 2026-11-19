"""Privacy-conscious, offline-friendly classroom signal analysis.

The module produces group-level proxy metrics only. It never identifies a person,
infers emotions, or writes source media to project storage. Gemini is opt-in and,
when configured, receives only the aggregate metrics returned by this module.
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import tempfile
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any, BinaryIO

MAX_MEDIA_BYTES = 100 * 1024 * 1024
MAX_VIDEO_FRAMES = 48
MAX_AUDIO_SECONDS = 300


def _read_upload(source: Any, limit: int = MAX_MEDIA_BYTES) -> tuple[bytes | None, str | None, str | None]:
    """Return in-memory upload bytes, an optional original path, and a safe error."""
    if source is None:
        return None, None, None
    if isinstance(source, (str, os.PathLike)):
        path = Path(source)
        try:
            if not path.is_file():
                return None, None, "The selected media file could not be opened."
            if path.stat().st_size > limit:
                return None, None, "Media exceeds the 100 MB processing limit."
            return None, str(path), None
        except OSError:
            return None, None, "The selected media file could not be opened."
    read = getattr(source, "read", None)
    if not callable(read):
        return None, None, "Unsupported media input. Use an upload or a local file path."
    old_position = None
    try:
        tell = getattr(source, "tell", None)
        seek = getattr(source, "seek", None)
        if callable(tell):
            old_position = tell()
        if callable(seek):
            seek(0)
        payload = read(limit + 1)
        if isinstance(payload, str):
            return None, None, "Media upload must be binary."
        payload = bytes(payload)
        if len(payload) > limit:
            return None, None, "Media exceeds the 100 MB processing limit."
        name = getattr(source, "name", "")
        suffix = Path(str(name)).suffix.lower()
        return payload, suffix, None
    except Exception:
        return None, None, "The selected media file could not be read."
    finally:
        if old_position is not None:
            try:
                source.seek(old_position)
            except Exception:
                pass


def _video_signals(data: bytes | None, path_or_suffix: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "sampled_frames": 0,
        "peak_visible_faces": None,
        "presence_consistency_pct": None,
        "mean_brightness": None,
        "quality": "unavailable",
        "note": "Add a video to estimate group-level on-screen presence.",
    }
    if data is None and not path_or_suffix:
        return result
    try:
        import cv2  # Optional dependency; imported only when video is supplied.
    except Exception:
        result["note"] = "OpenCV is not installed; video analysis is unavailable."
        return result

    tmp_path: str | None = None
    capture = None
    try:
        source_path = path_or_suffix if data is None else None
        suffix = Path(path_or_suffix or "video.mp4").suffix or ".mp4"
        if data is not None:
            with tempfile.NamedTemporaryFile(prefix="classpulse-", suffix=suffix, delete=False) as temp:
                temp.write(data)
                tmp_path = temp.name
            source_path = tmp_path
        if source_path is None:
            result["note"] = "The video source was not available."
            return result
        capture = cv2.VideoCapture(source_path)
        if not capture.isOpened():
            result["note"] = "The video could not be decoded by the installed OpenCV codecs."
            return result
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        stride = max(1, math.ceil(frame_count / MAX_VIDEO_FRAMES)) if frame_count else 15
        cascade_path = getattr(getattr(cv2, "data", None), "haarcascades", "")
        detector = cv2.CascadeClassifier(os.path.join(cascade_path, "haarcascade_frontalface_default.xml")) if cascade_path else None
        if detector is None or detector.empty():
            result["note"] = "The face-presence detector is unavailable; install OpenCV data files."
            return result

        counts: list[int] = []
        brightness: list[float] = []
        frame_index = 0
        while len(counts) < MAX_VIDEO_FRAMES:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % stride == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                brightness.append(float(gray.mean()))
                # Downsample to speed up local detection and reduce accidental detail use.
                reduced = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
                faces = detector.detectMultiScale(reduced, scaleFactor=1.15, minNeighbors=5, minSize=(20, 20))
                counts.append(int(len(faces)))
            frame_index += 1
        if not counts:
            result["note"] = "No readable video frames were found."
            return result
        active_frames = sum(1 for n in counts if n > 0)
        consistency = round(100 * active_frames / len(counts))
        average_light = sum(brightness) / len(brightness)
        quality = "good" if 65 <= average_light <= 210 and consistency >= 40 else "limited"
        if average_light < 65:
            note = "Low light may reduce detection accuracy. Face counts are approximate."
        elif average_light > 210:
            note = "Bright or washed-out frames may reduce detection accuracy. Counts are approximate."
        elif consistency < 40:
            note = "Few sampled frames had a visible face; occlusion or camera framing may affect counts."
        else:
            note = "Presence is estimated from sampled frames; this is not identity-based attendance."
        result.update({
            "available": True,
            "sampled_frames": len(counts),
            "peak_visible_faces": max(counts),
            "presence_consistency_pct": consistency,
            "mean_brightness": round(average_light, 1),
            "video_duration_seconds": round(frame_count / fps, 1) if fps > 0 and frame_count else None,
            "quality": quality,
            "note": note,
        })
        return result
    except Exception:
        result["note"] = "Video processing failed. Try a short MP4 or use the app without video."
        return result
    finally:
        if capture is not None:
            try:
                capture.release()
            except Exception:
                pass
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _wav_samples(data: bytes) -> tuple[list[float] | None, int | None]:
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            rate = wav.getframerate()
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            nframes = min(wav.getnframes(), rate * MAX_AUDIO_SECONDS)
            raw = wav.readframes(nframes)
        if width not in (1, 2, 4) or rate <= 0:
            return None, None
        scale = float(1 << (8 * width - 1))
        samples: list[float] = []
        step = width * channels
        for offset in range(0, len(raw) - step + 1, step):
            # Average channels and normalize; no audio content is persisted.
            values = []
            for channel in range(channels):
                part = raw[offset + channel * width: offset + (channel + 1) * width]
                if width == 1:
                    integer = part[0] - 128
                    channel_scale = 128.0
                else:
                    integer = int.from_bytes(part, "little", signed=True)
                    channel_scale = scale
                values.append(integer / channel_scale)
            samples.append(sum(values) / len(values))
        return samples, rate
    except Exception:
        return None, None


def _audio_signals(data: bytes | None, path_or_suffix: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "speech_activity_pct": None,
        "quality": "unavailable",
        "note": "Add an audio track to estimate broad activity; speech is not transcribed.",
    }
    if data is None and not path_or_suffix:
        return result
    samples: list[float] | None = None
    rate: int | None = None
    if data is not None:
        samples, rate = _wav_samples(data)
        if samples is None:
            try:
                import librosa  # Optional dependency; only loaded for supplied audio.
                import numpy as np
                array, rate = librosa.load(io.BytesIO(data), sr=16000, mono=True, duration=MAX_AUDIO_SECONDS)
                samples = np.asarray(array, dtype=float).tolist()
            except Exception:
                result["note"] = "Audio analysis needs a WAV file or the optional librosa decoder."
                return result
    else:
        try:
            import librosa
            import numpy as np
            array, rate = librosa.load(str(path_or_suffix), sr=16000, mono=True, duration=MAX_AUDIO_SECONDS)
            samples = np.asarray(array, dtype=float).tolist()
        except Exception:
            result["note"] = "Audio analysis needs a WAV file or the optional librosa decoder."
            return result
    if not samples or not rate:
        result["note"] = "No readable audio samples were found."
        return result
    # Compute coarse window RMS. This measures sound activity, not who spoke or what was said.
    window = max(1, int(rate * 0.5))
    rms_values: list[float] = []
    for start in range(0, len(samples), window):
        chunk = samples[start:start + window]
        if chunk:
            rms_values.append(math.sqrt(sum(v * v for v in chunk) / len(chunk)))
    floor = max(0.008, (sorted(rms_values)[len(rms_values) // 2] * 0.45) if rms_values else 0.008)
    active = sum(1 for rms in rms_values if rms >= floor)
    activity = round(100 * active / max(1, len(rms_values)))
    quality = "good" if max(rms_values, default=0) > 0.03 else "limited"
    result.update({
        "available": True,
        "speech_activity_pct": activity,
        "quality": quality,
        "duration_seconds": round(len(samples) / rate, 1),
        "note": "Broad audio-energy activity only; this does not identify speakers or transcribe speech.",
    })
    return result


def _suggestions(video: dict[str, Any], audio: dict[str, Any], engagement: int | None) -> list[str]:
    tips: list[str] = []
    if video.get("quality") == "limited":
        tips.append("Check camera framing and room lighting; some people may be outside the view or occluded.")
    if audio.get("available") and audio.get("speech_activity_pct", 0) < 12:
        tips.append("If this was a discussion, invite a short verbal check-in; low sound activity can also mean quiet independent work.")
    if video.get("available") and video.get("presence_consistency_pct", 0) < 50:
        tips.append("Review the session recording or attendance sheet manually; sampled presence can miss students who move or leave the frame.")
    if engagement is not None and engagement < 55:
        tips.append("Try a brief question, poll, or worked example, then compare the next few minutes of group-level signals.")
    if not tips:
        tips.append("Use a quick comprehension check and compare it with the next session; these estimates are prompts for instructor review.")
    return tips[:4]


def _gemini_summary(metrics: dict[str, Any]) -> str | None:
    """Ask Gemini for wording based only on de-identified aggregate metrics."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    # Only allow known scalar aggregate fields. No user text, class label, faces, or media.
    safe_metrics = {
        key: metrics.get(key)
        for key in ("engagement_score", "attendance_count_estimate", "presence_consistency_pct", "audio_activity_pct", "signal_quality")
        if isinstance(metrics.get(key), (int, float, str, type(None)))
    }
    prompt = (
        "Write one short, cautious instructor-facing suggestion based only on these coarse, "
        "de-identified classroom signal estimates. Do not infer emotions, individual behavior, "
        "learning ability, or causes. Say estimates are uncertain. Metrics: "
        + json.dumps(safe_metrics, separators=(",", ":"))
    )
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read(256_000).decode("utf-8"))
        parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        summary = " ".join(str(part.get("text", "")).strip() for part in parts if part.get("text"))
        # Keep model output plain, short, and safe to display as ordinary text.
        summary = re.sub(r"(?i)https?://\S+", "", summary)
        summary = re.sub(r"<[^>]*>", " ", summary)
        summary = re.sub(r"[\x00-\x1f\x7f<>\[\]{}*_`#]", " ", summary)
        summary = re.sub(r"\s+", " ", summary).strip()
        return summary[:400] or None
    except Exception:
        # Never surface provider payloads, request URLs, or credentials to the UI.
        return None


def analyze_session(
    video_file: Any = None,
    audio_file: Any = None,
    session_label: str = "",
    use_gemini: bool = False,
    *,
    video_path: str | os.PathLike[str] | None = None,
    audio_path: str | os.PathLike[str] | None = None,
    frames: Any = None,
    audio_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Analyze optional video/audio and return group-level estimates for a UI.

    `frames` is accepted as an alternate UI argument containing a single image
    or a list/tuple of in-memory images. Image frames are processed locally and
    never returned. `session_label` is shown locally only, and is never sent to
    Gemini. Gemini summaries require both `use_gemini=True` and a configured
    GEMINI_API_KEY, and receive aggregate numbers only.
    """
    if video_path is not None:
        video_file = video_path
    if audio_path is not None:
        audio_file = audio_path
    if audio_bytes is not None and audio_file is None:
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "audio.wav"  # type: ignore[attr-defined]

    video_data, video_suffix, video_error = _read_upload(video_file)
    audio_data, audio_suffix, audio_error = _read_upload(audio_file)
    video = _video_signals(video_data, video_suffix)
    audio = _audio_signals(audio_data, audio_suffix)

    # Optional in-memory still frames can be provided by a camera capture component.
    # Counts only; no images or face crops leave this function.
    frame_error = None
    if frames is not None and not video.get("available"):
        try:
            import cv2
            import numpy as np
            from PIL import Image
            cascade_path = getattr(getattr(cv2, "data", None), "haarcascades", "")
            detector = cv2.CascadeClassifier(os.path.join(cascade_path, "haarcascade_frontalface_default.xml"))
            frame_list = frames if isinstance(frames, (list, tuple)) else [frames]
            counts: list[int] = []
            lights: list[float] = []
            for item in frame_list[:MAX_VIDEO_FRAMES]:
                if isinstance(item, Image.Image):
                    rgb = np.asarray(item.convert("RGB"))
                    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
                else:
                    arr = np.asarray(item)
                    if arr.ndim == 3:
                        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
                    else:
                        gray = arr
                if gray.size == 0:
                    continue
                lights.append(float(gray.mean()))
                reduced = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
                faces = detector.detectMultiScale(reduced, scaleFactor=1.15, minNeighbors=5, minSize=(20, 20))
                counts.append(int(len(faces)))
            if counts:
                consistency = round(100 * sum(c > 0 for c in counts) / len(counts))
                brightness = sum(lights) / len(lights)
                video = {
                    "available": True,
                    "sampled_frames": len(counts),
                    "peak_visible_faces": max(counts),
                    "presence_consistency_pct": consistency,
                    "mean_brightness": round(brightness, 1),
                    "quality": "good" if 65 <= brightness <= 210 and consistency >= 40 else "limited",
                    "note": "In-memory frame estimates only; no identity matching or media retention.",
                }
        except Exception:
            frame_error = "In-memory frame analysis is unavailable; install OpenCV and Pillow."

    engagement_parts: list[float] = []
    if video.get("available") and video.get("presence_consistency_pct") is not None:
        engagement_parts.append(float(video["presence_consistency_pct"]))
    if audio.get("available") and audio.get("speech_activity_pct") is not None:
        # Audio activity is a weak proxy only; it is not treated as a student-level signal.
        engagement_parts.append(float(audio["speech_activity_pct"]))
    engagement = round(sum(engagement_parts) / len(engagement_parts)) if engagement_parts else None
    if len(engagement_parts) == 1:
        confidence = "low"
    elif len(engagement_parts) == 2:
        confidence = "low"  # Two noisy proxies do not constitute a validated engagement model.
    else:
        confidence = "unavailable"

    attendance = video.get("peak_visible_faces") if video.get("available") else None
    quality_values = [v.get("quality") for v in (video, audio) if v.get("available")]
    signal_quality = "limited" if "limited" in quality_values else ("available" if quality_values else "unavailable")
    result: dict[str, Any] = {
        "session_label": str(session_label or "")[:120],
        "attendance_count_estimate": attendance,
        "attendance_estimate_label": "Peak visible face count (approximate)" if attendance is not None else "Not available",
        "engagement_score": engagement,
        "engagement_label": "Heuristic signal score" if engagement is not None else "Not available",
        "engagement_confidence": confidence,
        "video_signals": video,
        "audio_signals": audio,
        "presence_consistency_pct": video.get("presence_consistency_pct"),
        "audio_activity_pct": audio.get("speech_activity_pct"),
        "signal_quality": signal_quality,
        "suggestions": _suggestions(video, audio, engagement),
        "ai_mode": "local_rules",
        "ai_summary": None,
        "privacy_note": "Processed locally; raw media is not retained. Estimates are group-level and should not be used to judge an individual student.",
        "errors": [e for e in (video_error, audio_error, frame_error) if e],
    }
    if use_gemini:
        if os.getenv("GEMINI_API_KEY", "").strip():
            summary = _gemini_summary(result)
            if summary:
                result["ai_summary"] = summary
                result["ai_mode"] = "local_rules_plus_gemini_aggregate_only"
            else:
                result["errors"].append("Gemini summary was unavailable; local suggestions remain active.")
        else:
            result["errors"].append("Gemini was requested but GEMINI_API_KEY is not configured.")
    return result


