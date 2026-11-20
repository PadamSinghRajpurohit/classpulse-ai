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
import struct
import tempfile
import urllib.error
import urllib.request
import wave
import zipfile
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlsplit

MAX_MEDIA_BYTES = 100 * 1024 * 1024
MAX_VIDEO_FRAMES = 48
MAX_AUDIO_SECONDS = 300
MIN_SUSTAINED_PRESENCE_SECONDS = 15.0
MAX_SUSTAINED_SAMPLE_GAP_SECONDS = 10.0
MOTION_DIFF_THRESHOLD = 2.0
MAX_FACE_LANDMARKER_FACES = 24
FACE_ORIENTATION_CENTER_BAND_DEGREES = 20.0
MAX_FACE_LANDMARKER_MODEL_BYTES = 32 * 1024 * 1024
MAX_FACE_LANDMARKER_ARCHIVE_ENTRIES = 128
MAX_FACE_LANDMARKER_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
FACE_LANDMARKER_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)


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


def _valid_face_landmarker_archive(bundle: zipfile.ZipFile) -> bool:
    """Bound archive metadata before CRC-reading entries to reject ZIP bombs."""
    try:
        entries = bundle.infolist()
        if not entries or len(entries) > MAX_FACE_LANDMARKER_ARCHIVE_ENTRIES:
            return False
        total_uncompressed = 0
        for entry in entries:
            if entry.file_size < 0 or entry.compress_size < 0:
                return False
            if entry.file_size > MAX_FACE_LANDMARKER_UNCOMPRESSED_BYTES:
                return False
            total_uncompressed += entry.file_size
            if total_uncompressed > MAX_FACE_LANDMARKER_UNCOMPRESSED_BYTES:
                return False
        return bundle.testzip() is None
    except (OSError, RuntimeError, zipfile.BadZipFile):
        return False


def _valid_face_landmarker_task(path: Path) -> bool:
    try:
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_FACE_LANDMARKER_MODEL_BYTES:
            return False
        with zipfile.ZipFile(path) as bundle:
            return _valid_face_landmarker_archive(bundle)
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return False


def _face_landmarker_model_path() -> tuple[Path | None, str | None]:
    """Get the pinned official model, cached outside the project after validation."""
    model_path = Path.home() / ".cache" / "classpulse" / "models" / "face_landmarker_float16_v1.task"
    try:
        if _valid_face_landmarker_task(model_path):
            return model_path, None
        model_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None, "The local model cache is unavailable; head orientation will be skipped."

    temporary_path: str | None = None
    try:
        request = urllib.request.Request(FACE_LANDMARKER_MODEL_URL, headers={"User-Agent": "ClassPulse/1.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            final_url = urlsplit(response.geturl())
            content_type = response.headers.get_content_type().casefold()
            if response.status != 200 or final_url.scheme != "https" or final_url.hostname != "storage.googleapis.com":
                return None, "The official MediaPipe model source could not be verified; head orientation will be skipped."
            if content_type not in {"application/octet-stream", "application/zip", "application/x-zip-compressed"}:
                return None, "The downloaded model had an unexpected content type; head orientation will be skipped."
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if not 0 < int(content_length) <= MAX_FACE_LANDMARKER_MODEL_BYTES:
                        return None, "The official model exceeded the local size limit; head orientation will be skipped."
                except ValueError:
                    return None, "The official model size could not be verified; head orientation will be skipped."
            model_bytes = response.read(MAX_FACE_LANDMARKER_MODEL_BYTES + 1)
        if not 0 < len(model_bytes) <= MAX_FACE_LANDMARKER_MODEL_BYTES:
            return None, "The official model exceeded the local size limit; head orientation will be skipped."
        # MediaPipe task bundles are ZIP containers. Reject HTML/error pages and
        # corrupt archives before the runtime attempts to load model data.
        if not zipfile.is_zipfile(io.BytesIO(model_bytes)):
            return None, "The official model bundle failed its format check; head orientation will be skipped."
        with zipfile.ZipFile(io.BytesIO(model_bytes)) as bundle:
            if not _valid_face_landmarker_archive(bundle):
                return None, "The official model bundle failed its integrity check; head orientation will be skipped."
        with tempfile.NamedTemporaryFile(prefix="classpulse-face-landmarker-", suffix=".part", dir=model_path.parent, delete=False) as temp:
            temporary_path = temp.name
            temp.write(model_bytes)
        os.replace(temporary_path, model_path)
        temporary_path = None
        if not _valid_face_landmarker_task(model_path):
            model_path.unlink(missing_ok=True)
            return None, "The cached model bundle failed validation; head orientation will be skipped."
        return model_path, None
    except Exception:
        return None, "The optional MediaPipe model is unavailable offline or could not be validated; Haar estimates remain available."
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def _create_face_landmarker() -> tuple[Any | None, str | None]:
    """Create an optional local landmarker; do not block Haar analysis on failure."""
    try:
        import mediapipe as mp
    except Exception:
        return None, "MediaPipe is not installed; head orientation is unavailable."
    model_path, model_note = _face_landmarker_model_path()
    if model_path is None:
        return None, model_note or "The optional MediaPipe model is unavailable; head orientation is unavailable."
    try:
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_faces=MAX_FACE_LANDMARKER_FACES,
            output_facial_transformation_matrixes=True,
        )
        return mp.tasks.vision.FaceLandmarker.create_from_options(options), None
    except Exception:
        return None, "MediaPipe could not load the optional local model; Haar estimates remain available."


def _orientation_angles(matrices: Any) -> list[tuple[float, float]]:
    """Convert local face transforms to camera-relative yaw/pitch proxies."""
    try:
        import numpy as np
    except Exception:
        return []
    angles: list[tuple[float, float]] = []
    for matrix in matrices or []:
        try:
            transform = np.asarray(matrix, dtype=float)
            if transform.shape != (4, 4) or not np.isfinite(transform).all():
                continue
            rotation = transform[:3, :3]
            left, _, right = np.linalg.svd(rotation)
            rotation = left @ right
            if np.linalg.det(rotation) < 0:
                left[:, -1] *= -1
                rotation = left @ right
            yaw = math.degrees(math.asin(max(-1.0, min(1.0, -float(rotation[2, 0])))))
            pitch = math.degrees(math.atan2(float(rotation[2, 1]), float(rotation[2, 2])))
            angles.append((yaw, pitch))
        except Exception:
            continue
    return angles


def _bbox_iou(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[0] + first[2], second[0] + second[2])
    y2 = min(first[1] + first[3], second[1] + second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = first[2] * first[3] + second[2] * second[3] - intersection
    return intersection / union if union > 0 else 0.0


def _summarize_anonymous_face_tracks(
    box_samples: list[list[tuple[float, float, float, float]]],
    sample_times: list[float | None],
    sample_interval: float | None,
    duration: float | None,
) -> dict[str, Any]:
    """Temporarily link adjacent boxes by IoU and return aggregate durations only."""
    available = (
        sample_interval is not None and duration is not None and duration > 0
        and sample_interval <= MAX_SUSTAINED_SAMPLE_GAP_SECONDS
    )
    empty = {
        "anonymous_face_tracker_available": available,
        "sustained_visible_face_track_count": None if not available else 0,
        "longest_visible_face_track_seconds": None if not available else 0.0,
        "tracked_face_presence_pct": None if not available else 0.0,
        "face_tracking_iou_threshold": 0.25,
        "face_tracking_note": (
            "Ephemeral adjacent-frame bounding-box matching only; no face crops, embeddings, names, or track IDs are returned."
            if available else "Sustained face tracking is unavailable because video sample spacing or duration is not reliable."
        ),
    }
    if not available:
        return empty

    tracks: list[dict[str, Any]] = []
    for sample_index, boxes in enumerate(box_samples):
        candidates: list[tuple[float, int, int]] = []
        for track_index, track in enumerate(tracks):
            if track["last_sample_index"] != sample_index - 1:
                continue
            for box_index, box in enumerate(boxes):
                overlap = _bbox_iou(track["bbox"], box)
                if overlap >= 0.25:
                    candidates.append((overlap, track_index, box_index))
        candidates.sort(reverse=True)
        matched_tracks: set[int] = set()
        matched_boxes: set[int] = set()
        for _, track_index, box_index in candidates:
            if track_index in matched_tracks or box_index in matched_boxes:
                continue
            track = tracks[track_index]
            track["bbox"] = boxes[box_index]
            track["last_sample_index"] = sample_index
            track["last_time"] = sample_times[sample_index]
            track["hits"] += 1
            matched_tracks.add(track_index)
            matched_boxes.add(box_index)
        for box_index, box in enumerate(boxes):
            if box_index in matched_boxes:
                continue
            tracks.append({
                "bbox": box,
                "first_sample_index": sample_index,
                "last_sample_index": sample_index,
                "first_time": sample_times[sample_index],
                "last_time": sample_times[sample_index],
                "hits": 1,
            })

    sustained_intervals: list[tuple[float, float]] = []
    durations: list[float] = []
    for track in tracks:
        first_time = track["first_time"]
        last_time = track["last_time"]
        if first_time is None or last_time is None or track["hits"] < 2:
            continue
        track_duration = max(0.0, float(last_time) - float(first_time) + sample_interval)
        if track_duration >= MIN_SUSTAINED_PRESENCE_SECONDS:
            durations.append(track_duration)
            sustained_intervals.append((max(0.0, float(first_time)), min(duration, float(last_time) + sample_interval)))

    union_seconds = 0.0
    if sustained_intervals:
        sustained_intervals.sort()
        left, right = sustained_intervals[0]
        for next_left, next_right in sustained_intervals[1:]:
            if next_left <= right:
                right = max(right, next_right)
            else:
                union_seconds += max(0.0, right - left)
                left, right = next_left, next_right
        union_seconds += max(0.0, right - left)
    empty.update({
        "sustained_visible_face_track_count": len(durations),
        "longest_visible_face_track_seconds": round(max(durations), 1) if durations else 0.0,
        "tracked_face_presence_pct": round(100 * min(duration, union_seconds) / duration),
    })
    return empty


def _summarize_video_samples(
    counts: list[int],
    brightness: list[float],
    motion_diffs: list[float],
    sample_times: list[float | None],
    duration: float | None,
    sample_interval: float | None,
    orientation_samples: list[dict[str, float | int]] | None = None,
    orientation_note: str | None = None,
) -> dict[str, Any]:
    """Reduce sampled detections to non-identifying group-level time signals."""
    active = [count > 0 for count in counts]
    consistency = round(100 * sum(active) / max(1, len(active)))
    average_light = sum(brightness) / max(1, len(brightness))
    mean_delta = sum(motion_diffs) / len(motion_diffs) if motion_diffs else None
    motion_activity = (
        round(100 * sum(value >= MOTION_DIFF_THRESHOLD for value in motion_diffs) / len(motion_diffs))
        if motion_diffs else None
    )

    # Presence is sustained only when detections continue across adjacent samples.
    # No attempt is made to associate a face in one sample with a face in another.
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_active in enumerate(active):
        contiguous = True
        if index and sample_times[index] is not None and sample_times[index - 1] is not None and sample_interval:
            gap = float(sample_times[index]) - float(sample_times[index - 1])
            contiguous = (
                sample_interval <= MAX_SUSTAINED_SAMPLE_GAP_SECONDS
                and 0 <= gap <= sample_interval * 1.5
            )
        if is_active and (start is None or contiguous):
            if start is None:
                start = index
        else:
            if start is not None:
                runs.append((start, index - 1))
            start = index if is_active else None
    if start is not None:
        runs.append((start, len(active) - 1))

    def run_seconds(first: int, last: int) -> float | None:
        if sample_interval is None or sample_interval > MAX_SUSTAINED_SAMPLE_GAP_SECONDS:
            return None
        first_time = sample_times[first]
        last_time = sample_times[last]
        if first_time is not None and last_time is not None:
            return max(0.0, float(last_time) - float(first_time) + sample_interval)
        return (last - first + 1) * sample_interval

    run_durations = [run_seconds(first, last) for first, last in runs]
    known_runs = [value for value in run_durations if value is not None]
    longest_run = max(known_runs) if known_runs else None
    sustained_seconds = sum(
        value for value in known_runs if value >= MIN_SUSTAINED_PRESENCE_SECONDS
    )
    sustained_pct = (
        round(100 * min(sustained_seconds, duration) / duration)
        if duration and duration > 0 else None
    )

    windows: list[dict[str, Any]] = []
    orientation_samples = orientation_samples or []
    total_orientation_faces = sum(int(sample.get("face_count", 0)) for sample in orientation_samples)
    yaw_sum = sum(float(sample.get("abs_yaw_sum", 0.0)) for sample in orientation_samples)
    pitch_sum = sum(float(sample.get("abs_pitch_sum", 0.0)) for sample in orientation_samples)
    centered_faces = sum(int(sample.get("centered_count", 0)) for sample in orientation_samples)
    for index, count in enumerate(counts):
        time_value = sample_times[index] if index < len(sample_times) else None
        if duration and duration > 0 and time_value is not None:
            relative = round(100 * min(max(float(time_value), 0.0), duration) / duration, 1)
        elif len(counts) > 1:
            relative = round(100 * index / (len(counts) - 1), 1)
        else:
            relative = 0.0
        delta = motion_diffs[index - 1] if index > 0 and index - 1 < len(motion_diffs) else None
        orientation = orientation_samples[index] if index < len(orientation_samples) else {}
        orientation_face_count = int(orientation.get("face_count", 0))
        windows.append({
            "relative_progress_pct": relative,
            "time_seconds": round(float(time_value), 2) if time_value is not None else None,
            "visible_face_count_estimate": int(count),
            "visible_presence": bool(count > 0),
            "frame_motion_level_pct": round(min(100.0, delta * 100.0 / 32.0), 1) if delta is not None else None,
            "head_orientation_sampled_faces": orientation_face_count,
            "head_orientation_mean_abs_yaw_degrees": (
                round(float(orientation.get("abs_yaw_sum", 0.0)) / orientation_face_count, 1)
                if orientation_face_count else None
            ),
            "head_orientation_mean_abs_pitch_degrees": (
                round(float(orientation.get("abs_pitch_sum", 0.0)) / orientation_face_count, 1)
                if orientation_face_count else None
            ),
            "head_orientation_camera_relative_centered_pct": (
                round(100 * int(orientation.get("centered_count", 0)) / orientation_face_count)
                if orientation_face_count else None
            ),
        })

    quality = "good" if 65 <= average_light <= 210 and consistency >= 40 else "limited"
    if average_light < 65:
        note = "Low light may reduce detection accuracy. Counts and temporal presence are approximate."
    elif average_light > 210:
        note = "Bright or washed-out frames may reduce detection accuracy. Counts and temporal presence are approximate."
    elif consistency < 40:
        note = "Few sampled frames had a visible face; occlusion or camera framing may affect estimates."
    else:
        note = "Group presence is estimated from sampled frames; no identity matching is performed."
    return {
        "available": True,
        "sampled_frames": len(counts),
        "peak_visible_faces": max(counts),
        "presence_consistency_pct": consistency,
        "sustained_presence_pct": sustained_pct,
        "longest_group_presence_run_seconds": round(longest_run, 1) if longest_run is not None else None,
        "sustained_presence_threshold_seconds": MIN_SUSTAINED_PRESENCE_SECONDS,
        "sustained_presence_max_sample_gap_seconds": MAX_SUSTAINED_SAMPLE_GAP_SECONDS,
        "sustained_presence_available": sample_interval is not None and sample_interval <= MAX_SUSTAINED_SAMPLE_GAP_SECONDS,
        "group_motion_activity_pct": motion_activity,
        "low_motion_proxy_pct": 100 - motion_activity if motion_activity is not None else None,
        "mean_frame_delta_gray": round(mean_delta, 2) if mean_delta is not None else None,
        "motion_threshold_mean_gray_delta": MOTION_DIFF_THRESHOLD,
        "mean_brightness": round(average_light, 1),
        "video_duration_seconds": round(duration, 1) if duration is not None else None,
        "temporal_windows": windows,
        "head_orientation_proxy_pct": round(100 * centered_faces / total_orientation_faces) if total_orientation_faces else None,
        "head_orientation_centered_pct": round(100 * centered_faces / total_orientation_faces) if total_orientation_faces else None,
        "head_orientation_sampled_face_observations": total_orientation_faces,
        "head_orientation_mean_abs_yaw_degrees": round(yaw_sum / total_orientation_faces, 1) if total_orientation_faces else None,
        "head_orientation_mean_abs_pitch_degrees": round(pitch_sum / total_orientation_faces, 1) if total_orientation_faces else None,
        "head_orientation_center_band_degrees": FACE_ORIENTATION_CENTER_BAND_DEGREES,
        "head_orientation_available": total_orientation_faces > 0,
        "head_orientation_confidence": "very_low" if total_orientation_faces else "unavailable",
        "head_orientation_note": (
            "Camera-relative head-angle proxy from optional MediaPipe landmarks. It is not gaze, attention, or engagement; no landmarks or face features are retained."
            if total_orientation_faces else (orientation_note or "MediaPipe head orientation is unavailable; Haar face-presence and motion estimates remain active.")
        ),
        "quality": quality,
        "note": note + " Low frame motion may reflect a static camera or scene and is not evidence of learner inactivity.",
    }


def _video_signals(
    data: bytes | None,
    path_or_suffix: str | None,
    include_head_orientation: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "sampled_frames": 0,
        "peak_visible_faces": None,
        "presence_consistency_pct": None,
        "sustained_presence_pct": None,
        "longest_group_presence_run_seconds": None,
        "sustained_presence_threshold_seconds": MIN_SUSTAINED_PRESENCE_SECONDS,
        "sustained_presence_max_sample_gap_seconds": MAX_SUSTAINED_SAMPLE_GAP_SECONDS,
        "sustained_presence_available": False,
        "group_motion_activity_pct": None,
        "low_motion_proxy_pct": None,
        "mean_frame_delta_gray": None,
        "motion_threshold_mean_gray_delta": MOTION_DIFF_THRESHOLD,
        "head_orientation_proxy_pct": None,
        "head_orientation_centered_pct": None,
        "head_orientation_sampled_face_observations": 0,
        "head_orientation_mean_abs_yaw_degrees": None,
        "head_orientation_mean_abs_pitch_degrees": None,
        "head_orientation_center_band_degrees": FACE_ORIENTATION_CENTER_BAND_DEGREES,
        "head_orientation_available": False,
        "head_orientation_confidence": "unavailable",
        "head_orientation_note": (
            "Head orientation is disabled. Enable the optional local MediaPipe feature to calculate camera-relative angle estimates."
            if not include_head_orientation
            else "MediaPipe head orientation is unavailable; Haar face-presence and motion estimates remain active."
        ),
        "anonymous_face_tracker_available": False,
        "sustained_visible_face_track_count": None,
        "longest_visible_face_track_seconds": None,
        "tracked_face_presence_pct": None,
        "face_tracking_iou_threshold": 0.25,
        "face_tracking_note": "Sustained face tracking is unavailable because video sample spacing or duration is not reliable.",
        "temporal_windows": [],
        "mean_brightness": None,
        "video_duration_seconds": None,
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
    landmarker = None
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

        landmarker_note = None
        if include_head_orientation:
            landmarker, landmarker_note = _create_face_landmarker()
        else:
            landmarker_note = "Head orientation is disabled. Enable the optional local MediaPipe feature to calculate camera-relative angle estimates."

        counts: list[int] = []
        brightness: list[float] = []
        motion_diffs: list[float] = []
        sample_times: list[float | None] = []
        box_samples: list[list[tuple[float, float, float, float]]] = []
        orientation_samples: list[dict[str, float | int]] = []
        previous_gray = None
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
                if previous_gray is not None and previous_gray.shape == reduced.shape:
                    # Frame-level change is a coarse scene-motion proxy; it can also
                    # respond to camera shake, lighting changes, or display content.
                    delta = cv2.absdiff(previous_gray, reduced)
                    motion_diffs.append(float(cv2.mean(delta)[0]))
                previous_gray = reduced
                faces = detector.detectMultiScale(reduced, scaleFactor=1.15, minNeighbors=5, minSize=(20, 20))
                counts.append(int(len(faces)))
                sample_time = frame_index / fps if fps > 0 else None
                sample_times.append(sample_time)
                box_samples.append([tuple(float(value) for value in box) for box in faces])

                orientation_sample: dict[str, float | int] = {
                    "face_count": 0, "abs_yaw_sum": 0.0, "abs_pitch_sum": 0.0, "centered_count": 0,
                }
                if landmarker is not None:
                    try:
                        import mediapipe as mp
                        max_dimension = max(frame.shape[0], frame.shape[1])
                        landmark_frame = frame
                        if max_dimension > 960:
                            ratio = 960 / max_dimension
                            landmark_frame = cv2.resize(frame, (int(frame.shape[1] * ratio), int(frame.shape[0] * ratio)))
                        rgb = cv2.cvtColor(landmark_frame, cv2.COLOR_BGR2RGB)
                        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                        landmark_result = landmarker.detect(mp_image)
                        angles = _orientation_angles(getattr(landmark_result, "facial_transformation_matrixes", []))
                        orientation_sample = {
                            "face_count": len(angles),
                            "abs_yaw_sum": sum(abs(yaw) for yaw, _ in angles),
                            "abs_pitch_sum": sum(abs(pitch) for _, pitch in angles),
                            "centered_count": sum(
                                1 for yaw, pitch in angles
                                if abs(yaw) <= FACE_ORIENTATION_CENTER_BAND_DEGREES
                                and abs(pitch) <= FACE_ORIENTATION_CENTER_BAND_DEGREES
                            ),
                        }
                    except Exception:
                        landmarker_note = "Optional MediaPipe orientation analysis failed; Haar estimates remain available."
                        try:
                            landmarker.close()
                        except Exception:
                            pass
                        landmarker = None
                orientation_samples.append(orientation_sample)
            frame_index += 1
        if not counts:
            result["note"] = "No readable video frames were found."
            return result
        duration = frame_count / fps if fps > 0 and frame_count else None
        sample_interval = stride / fps if fps > 0 else None
        result.update(_summarize_video_samples(
            counts, brightness, motion_diffs, sample_times, duration, sample_interval,
            orientation_samples=orientation_samples,
            orientation_note=landmarker_note,
        ))
        result.update(_summarize_anonymous_face_tracks(box_samples, sample_times, sample_interval, duration))
        if landmarker is not None:
            try:
                landmarker.close()
            except Exception:
                pass
        result["note"] += " " + result["face_tracking_note"] + " " + result["head_orientation_note"]
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
        if landmarker is not None:
            try:
                landmarker.close()
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


def _webrtc_vad_windows(samples: list[float], sample_rate: int, duration: float) -> tuple[list[float] | None, str | None]:
    """Return likely-speech ratios in relative clip bins when local WebRTC VAD exists."""
    try:
        import webrtcvad  # Optional: no VAD dependency is required for broad energy metrics.
    except Exception:
        return None, "WebRTC VAD is not installed; only broad sound-energy activity is reported."

    target_rate = 16000
    vad_samples = samples
    if sample_rate != target_rate:
        try:
            import librosa
            import numpy as np
            vad_samples = np.asarray(
                librosa.resample(np.asarray(samples, dtype=float), orig_sr=sample_rate, target_sr=target_rate),
                dtype=float,
            ).tolist()
            sample_rate = target_rate
        except Exception:
            return None, "Local VAD needs 16 kHz audio; optional resampling was unavailable."

    vad = webrtcvad.Vad(2)
    frame_samples = sample_rate // 50  # 20 ms, supported by WebRTC VAD.
    bin_count = max(1, min(MAX_VIDEO_FRAMES, math.ceil(duration / 0.5)))
    total = [0] * bin_count
    spoken = [0] * bin_count
    frame_count = len(vad_samples) // frame_samples
    for frame_index in range(frame_count):
        offset = frame_index * frame_samples
        frame = vad_samples[offset:offset + frame_samples]
        pcm = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767)) for value in frame)
        is_speech = bool(vad.is_speech(pcm, sample_rate))
        midpoint = (offset + frame_samples / 2) / sample_rate
        bin_index = min(bin_count - 1, int(midpoint / max(duration, 0.001) * bin_count))
        total[bin_index] += 1
        spoken[bin_index] += int(is_speech)
    if not frame_count:
        return None, "Local VAD could not form any complete audio frames."
    windows = [round(100 * speech / frames) if frames else 0.0 for speech, frames in zip(spoken, total)]
    return windows, None


def _audio_signals(data: bytes | None, path_or_suffix: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "speech_activity_pct": None,
        "sound_activity_pct": None,
        "likely_speech_activity_pct": None,
        "speech_activity_method": "unavailable",
        "temporal_windows": [],
        "quality": "unavailable",
        "note": "Add an audio track to estimate broad sound activity. Speech detection is optional and local.",
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

    duration = len(samples) / rate
    vad_windows, vad_note = _webrtc_vad_windows(samples, rate, duration)
    likely_speech = (
        round(sum(vad_windows) / len(vad_windows))
        if vad_windows else None
    )
    # Compress sound energy into at most 48 relative-progress bins so result size
    # stays bounded for the maximum five-minute input.
    bin_count = max(1, min(MAX_VIDEO_FRAMES, math.ceil(duration / 0.5)))
    bin_values: list[list[float]] = [[] for _ in range(bin_count)]
    bin_active: list[list[bool]] = [[] for _ in range(bin_count)]
    for index, rms in enumerate(rms_values):
        midpoint = (index * 0.5 + min(0.25, max(0.0, duration - index * 0.5) / 2))
        bin_index = min(bin_count - 1, int(midpoint / max(duration, 0.001) * bin_count))
        bin_values[bin_index].append(rms)
        bin_active[bin_index].append(rms >= floor)
    temporal_windows = []
    for index in range(bin_count):
        start_seconds = duration * index / bin_count
        end_seconds = duration * (index + 1) / bin_count
        local_rms = bin_values[index]
        local_active = bin_active[index]
        temporal_windows.append({
            "relative_start_pct": round(100 * index / bin_count, 1),
            "relative_end_pct": round(100 * (index + 1) / bin_count, 1),
            "start_seconds": round(start_seconds, 2),
            "end_seconds": round(end_seconds, 2),
            "sound_energy_rms": round(sum(local_rms) / len(local_rms), 4) if local_rms else None,
            "sound_activity_pct": round(100 * sum(local_active) / len(local_active)) if local_active else None,
            "likely_speech_activity_pct": vad_windows[index] if vad_windows and index < len(vad_windows) else None,
        })
    result.update({
        "available": True,
        # Legacy alias retained for existing UI/API clients; use the explicit
        # likely_speech_activity_pct field for VAD-only speech estimates.
        "speech_activity_pct": activity,
        "sound_activity_pct": activity,
        "likely_speech_activity_pct": likely_speech,
        "speech_activity_method": "webrtcvad" if likely_speech is not None else "energy_only",
        "temporal_windows": temporal_windows,
        "quality": quality,
        "duration_seconds": round(duration, 1),
        "note": (
            "Likely speech activity comes from optional local WebRTC VAD; it does not identify speakers or transcribe speech."
            if likely_speech is not None
            else "Only broad sound-energy activity is available; this is not speech or interaction detection. " + (vad_note or "")
        ),
    })
    return result


def _mean_numeric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if isinstance(row.get(key), (int, float))]
    return round(sum(values) / len(values), 1) if values else None


def _align_temporal_windows(video: dict[str, Any], audio: dict[str, Any]) -> list[dict[str, Any]]:
    """Align modality summaries by relative clip progress, not clock time."""
    video_bins: dict[int, list[dict[str, Any]]] = {}
    audio_bins: dict[int, list[dict[str, Any]]] = {}
    for row in video.get("temporal_windows", []):
        progress = row.get("relative_progress_pct")
        if isinstance(progress, (int, float)):
            index = min(MAX_VIDEO_FRAMES - 1, max(0, round(float(progress) / 100 * (MAX_VIDEO_FRAMES - 1))))
            video_bins.setdefault(index, []).append(row)
    for row in audio.get("temporal_windows", []):
        start = row.get("relative_start_pct")
        end = row.get("relative_end_pct")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            progress = (float(start) + float(end)) / 2
            index = min(MAX_VIDEO_FRAMES - 1, max(0, int(progress / 100 * MAX_VIDEO_FRAMES)))
            audio_bins.setdefault(index, []).append(row)

    output: list[dict[str, Any]] = []
    for index in range(MAX_VIDEO_FRAMES):
        visual = video_bins.get(index, [])
        sound = audio_bins.get(index, [])
        if not visual and not sound:
            continue
        visible = [bool(row.get("visible_presence")) for row in visual]
        face_counts = [row.get("visible_face_count_estimate") for row in visual if isinstance(row.get("visible_face_count_estimate"), (int, float))]
        motion = [row.get("frame_motion_level_pct") for row in visual if isinstance(row.get("frame_motion_level_pct"), (int, float))]
        energy = [row.get("sound_activity_pct") for row in sound if isinstance(row.get("sound_activity_pct"), (int, float))]
        speech = [row.get("likely_speech_activity_pct") for row in sound if isinstance(row.get("likely_speech_activity_pct"), (int, float))]
        output.append({
            "relative_start_pct": round(100 * index / MAX_VIDEO_FRAMES, 1),
            "relative_end_pct": round(100 * (index + 1) / MAX_VIDEO_FRAMES, 1),
            "visible_presence_pct": round(100 * sum(visible) / len(visible)) if visible else None,
            "visible_face_count_estimate": round(sum(face_counts) / len(face_counts), 1) if face_counts else None,
            "frame_motion_level_pct": round(sum(motion) / len(motion), 1) if motion else None,
            "sound_activity_pct": round(sum(energy) / len(energy), 1) if energy else None,
            "likely_speech_activity_pct": round(sum(speech) / len(speech), 1) if speech else None,
            "head_orientation_mean_abs_yaw_degrees": _mean_numeric(visual, "head_orientation_mean_abs_yaw_degrees"),
            "head_orientation_mean_abs_pitch_degrees": _mean_numeric(visual, "head_orientation_mean_abs_pitch_degrees"),
            "head_orientation_camera_relative_centered_pct": _mean_numeric(visual, "head_orientation_camera_relative_centered_pct"),
            "available_modalities": (["video"] if visual else []) + (["audio"] if sound else []),
        })
    return output


def _fused_activity_score(video: dict[str, Any], audio: dict[str, Any]) -> tuple[int | None, list[str], str]:
    """Make a low-confidence group activity heuristic with quality-aware weights."""
    components: list[tuple[str, float, float]] = []
    video_reliability = 1.0 if video.get("quality") == "good" else 0.5
    audio_reliability = 1.0 if audio.get("quality") == "good" else 0.5
    if video.get("available"):
        presence = video.get("presence_consistency_pct")
        movement = video.get("group_motion_activity_pct")
        if isinstance(presence, (int, float)):
            components.append(("group_presence_consistency", float(presence), 0.35 * video_reliability))
        if isinstance(movement, (int, float)):
            components.append(("coarse_group_frame_motion", float(movement), 0.25 * video_reliability))
    if audio.get("available"):
        speech = audio.get("likely_speech_activity_pct")
        if isinstance(speech, (int, float)):
            components.append(("likely_speech_vad", float(speech), 0.40 * audio_reliability))
        else:
            sound = audio.get("sound_activity_pct")
            if isinstance(sound, (int, float)):
                # Sound energy is deliberately down-weighted; it is not a speech detector.
                components.append(("broad_sound_energy_only", float(sound), 0.10 * audio_reliability))
    if not components:
        return None, [], "unavailable"
    denominator = sum(weight for _, _, weight in components)
    score = round(sum(value * weight for _, value, weight in components) / max(denominator, 0.001))
    modalities = {"video" if name.startswith(("group_", "coarse_group")) else "audio" for name, _, _ in components}
    low_quality = any(
        (name.startswith(("group_", "coarse_group")) and video.get("quality") != "good")
        or (name.startswith(("likely_speech", "broad_sound")) and audio.get("quality") != "good")
        for name, _, _ in components
    )
    confidence = "very_low" if low_quality or len(modalities) < 2 or "broad_sound_energy_only" in [name for name, _, _ in components] else "low"
    return score, [name for name, _, _ in components], confidence


def _suggestions(video: dict[str, Any], audio: dict[str, Any], engagement: int | None, confidence: str) -> list[str]:
    tips: list[str] = []
    if video.get("quality") == "limited":
        tips.append("Check camera framing and room lighting; some people may be outside the view or occluded.")
    if video.get("available") and video.get("low_motion_proxy_pct") is not None and video.get("low_motion_proxy_pct", 0) >= 85:
        tips.append("The scene changed very little; this can reflect a fixed camera or steady lesson, not learner inactivity.")
    if audio.get("available") and audio.get("likely_speech_activity_pct") is not None and audio.get("likely_speech_activity_pct", 0) < 12:
        tips.append("If this was a discussion, invite a short verbal check-in; low sound activity can also mean quiet independent work.")
    elif audio.get("available") and audio.get("likely_speech_activity_pct") is None and audio.get("sound_activity_pct", 0) < 12:
        tips.append("Sound energy was low; check microphone placement. Energy-only audio cannot establish whether anyone was speaking.")
    if video.get("available") and video.get("presence_consistency_pct", 0) < 50:
        tips.append("Review the session recording or attendance sheet manually; sampled presence can miss students who move or leave the frame.")
    if engagement is not None and engagement < 55 and confidence == "low":
        tips.append("Try a brief question, poll, or worked example, then compare the next few minutes of group-level signals.")
    elif engagement is not None and confidence == "very_low":
        tips.append("Treat the activity score as very uncertain; verify the camera and microphone signals before drawing conclusions.")
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
        for key in (
            "engagement_score", "attendance_count_estimate", "presence_consistency_pct",
            "sustained_presence_pct", "group_motion_activity_pct", "audio_activity_pct",
            "likely_speech_activity_pct", "signal_quality", "engagement_confidence",
        )
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
    include_head_orientation: bool = False,
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
    video = _video_signals(video_data, video_suffix, include_head_orientation=include_head_orientation)
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
            motion_diffs: list[float] = []
            previous_gray = None
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
                if previous_gray is not None and previous_gray.shape == reduced.shape:
                    motion_diffs.append(float(cv2.mean(cv2.absdiff(previous_gray, reduced))[0]))
                previous_gray = reduced
                faces = detector.detectMultiScale(reduced, scaleFactor=1.15, minNeighbors=5, minSize=(20, 20))
                counts.append(int(len(faces)))
            if counts:
                video = _summarize_video_samples(counts, lights, motion_diffs, [None] * len(counts), None, None)
                video["note"] = "In-memory frame estimates only; no identity matching or media retention. " + video["note"]
        except Exception:
            frame_error = "In-memory frame analysis is unavailable; install OpenCV and Pillow."

    engagement, score_components, confidence = _fused_activity_score(video, audio)

    attendance = video.get("peak_visible_faces") if video.get("available") else None
    quality_values = [v.get("quality") for v in (video, audio) if v.get("available")]
    signal_quality = "limited" if "limited" in quality_values else ("available" if quality_values else "unavailable")
    quality_flags: list[str] = []
    if video.get("available"):
        quality_flags.append("video_faces_are_group_presence_estimates_not_identity_attendance")
        quality_flags.append("frame_motion_is_a_scene_change_proxy_not_an_inactivity_detector")
        if video.get("head_orientation_available"):
            quality_flags.append("head_orientation_is_camera_relative_and_not_gaze_or_attention")
        elif include_head_orientation:
            quality_flags.append("head_orientation_unavailable_without_landmark_model")
        else:
            quality_flags.append("head_orientation_disabled_by_default")
        if video.get("anonymous_face_tracker_available"):
            quality_flags.append("anonymous_face_tracks_are_ephemeral_iou_matches_with_low_confidence")
    if audio.get("available") and audio.get("likely_speech_activity_pct") is None:
        quality_flags.append("audio_is_sound_energy_only_without_local_vad")
    if video.get("available") and audio.get("available"):
        quality_flags.append("modalities_aligned_by_relative_clip_progress_not_clock_offsets")
    if confidence in {"very_low", "low"}:
        quality_flags.append("activity_score_is_unvalidated_and_advisory")
    alignment_windows = _align_temporal_windows(video, audio)
    audio_activity = audio.get("sound_activity_pct")
    result: dict[str, Any] = {
        "session_label": str(session_label or "")[:120],
        "attendance_count_estimate": attendance,
        "attendance_estimate_label": "Peak visible face count (approximate)" if attendance is not None else "Not available",
        "engagement_score": engagement,
        "engagement_label": "Low-confidence group activity heuristic" if engagement is not None else "Not available",
        "engagement_confidence": confidence,
        "fused_score_components": score_components,
        "fused_score_method": "Quality-weighted group proxies; broad sound energy is heavily down-weighted and no calibrated engagement model is used.",
        "video_signals": video,
        "audio_signals": audio,
        "presence_consistency_pct": video.get("presence_consistency_pct"),
        "audio_activity_pct": audio_activity,
        "likely_speech_activity_pct": audio.get("likely_speech_activity_pct"),
        "group_motion_activity_pct": video.get("group_motion_activity_pct"),
        "sustained_presence_pct": video.get("sustained_presence_pct"),
        "sustained_visible_face_track_count": video.get("sustained_visible_face_track_count"),
        "longest_visible_face_track_seconds": video.get("longest_visible_face_track_seconds"),
        "tracked_face_presence_pct": video.get("tracked_face_presence_pct"),
        "anonymous_face_tracker_available": video.get("anonymous_face_tracker_available", False),
        "head_orientation_proxy_pct": video.get("head_orientation_proxy_pct"),
        "head_orientation_available": video.get("head_orientation_available", False),
        "time_alignment": {
            "method": "relative_clip_progress",
            "synchronized": False,
            "limitation": "Source start offsets and capture timestamps are unavailable; matching relative progress does not prove real-time synchronization.",
        },
        "multimodal_time_windows": alignment_windows,
        "signal_quality_flags": quality_flags,
        "signal_quality": signal_quality,
        "suggestions": _suggestions(video, audio, engagement, confidence),
        "ai_mode": "local_rules",
        "ai_summary": None,
        "privacy_note": "Processed locally; raw media is not retained. Estimates are group-level and should not be used to judge an individual student.",
        "errors": [e for e in (video_error, audio_error, frame_error) if e],
    }
    # The local teaching agent sees aggregate metrics only. Keep the legacy
    # display list of strings while exposing its transparent tool trace.
    try:
        from teaching_agent import run_teaching_agent
        suggestion_agent = run_teaching_agent(result)
        agent_suggestions = suggestion_agent.get("suggestions", [])
        display_suggestions = [
            f"{item.get('title', 'Teaching suggestion')}: {item.get('detail', '')}".strip()
            for item in agent_suggestions if isinstance(item, dict)
        ]
        if display_suggestions:
            result["suggestions"] = display_suggestions
        else:
            result["suggestions"] = _suggestions(video, audio, engagement, confidence)
        result["suggestion_agent"] = suggestion_agent
    except Exception:
        result["suggestions"] = _suggestions(video, audio, engagement, confidence)
        result["suggestion_agent"] = {
            "mode": "local_rules_fallback",
            "tools_used": [],
            "signal_quality_flags": [],
            "suggestions": [],
            "review_note": "The bounded teaching agent was unavailable; fallback prompts are instructor-facing and advisory.",
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


