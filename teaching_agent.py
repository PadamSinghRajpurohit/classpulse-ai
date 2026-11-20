"""Bounded, offline teaching-suggestion agent for aggregate classroom signals.

The agent has a small read-only tool set and a fixed action catalogue. It never
receives media, class names, roster records, or student-level observations.
Its output is advisory and should be reviewed by the instructor.
"""
from __future__ import annotations

from typing import Any, Callable


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _inspect_signal_quality(signals: dict[str, Any]) -> dict[str, Any]:
    video = signals.get("video_signals") or {}
    audio = signals.get("audio_signals") or {}
    flags: list[str] = []
    if video.get("available") and video.get("quality") == "limited":
        flags.append("video_quality_limited")
    if audio.get("available") and audio.get("quality") == "limited":
        flags.append("audio_quality_limited")
    if audio.get("available") and audio.get("likely_speech_activity_pct") is None:
        flags.append("speech_not_detected_by_vad")
    return {"flags": flags, "video_available": bool(video.get("available")), "audio_available": bool(audio.get("available"))}


def _select_teaching_prompts(signals: dict[str, Any], quality: dict[str, Any]) -> list[dict[str, str]]:
    """Select up to three non-punitive group-level prompts from fixed rules."""
    video = signals.get("video_signals") or {}
    audio = signals.get("audio_signals") or {}
    prompts: list[dict[str, str]] = []

    if "video_quality_limited" in quality["flags"]:
        prompts.append({"title": "Improve camera coverage", "detail": "Check framing and lighting, then review the group estimate manually."})
    if "audio_quality_limited" in quality["flags"]:
        prompts.append({"title": "Check audio quality", "detail": "Move the microphone closer or reduce background noise before comparing audio activity."})

    sustained = _number(video.get("sustained_presence_pct"))
    presence = _number(video.get("presence_consistency_pct"))
    if video.get("available") and ((sustained is not None and sustained < 50) or (presence is not None and presence < 50)):
        prompts.append({"title": "Verify attendance manually", "detail": "The camera only estimates visible faces over time; confirm the roster yourself."})

    speech = _number(audio.get("likely_speech_activity_pct"))
    if audio.get("available") and speech is not None and speech < 15:
        prompts.append({"title": "Offer a low-pressure check-in", "detail": "If it fits the activity, invite a brief question or response; quiet work can be productive too."})

    motion = _number(video.get("group_motion_activity_pct"))
    if video.get("available") and motion is not None and motion < 10:
        prompts.append({"title": "Vary the activity", "detail": "Consider a short discussion, stretch, or worked example. Low frame change can also come from a steady camera or lesson."})

    score = _number(signals.get("engagement_score"))
    confidence = str(signals.get("engagement_confidence") or "unavailable")
    if score is not None and score < 55 and confidence == "low":
        prompts.append({"title": "Check understanding", "detail": "Try a brief poll or comprehension question and compare the next group-level session signals."})

    if not prompts:
        prompts.append({"title": "Use an instructor check", "detail": "Pair these uncertain group signals with a quick comprehension check and your classroom context."})
    return prompts[:3]


def _safety_review(prompts: list[dict[str, str]]) -> list[dict[str, str]]:
    """Apply a conservative output gate to the fixed, non-identifying catalogue."""
    prohibited = ("emotion", "ability score", "discipline", "at risk", "individual student")
    approved = []
    for prompt in prompts:
        text = f"{prompt.get('title', '')} {prompt.get('detail', '')}".casefold()
        if not any(term in text for term in prohibited):
            approved.append({"title": prompt["title"], "detail": prompt["detail"]})
    return approved[:3]


_TOOLS: dict[str, Callable[..., Any]] = {
    "inspect_signal_quality": _inspect_signal_quality,
    "select_teaching_prompts": _select_teaching_prompts,
    "safety_review": _safety_review,
}


def run_teaching_agent(signals: dict[str, Any]) -> dict[str, Any]:
    """Run a short, transparent tool workflow on aggregate signals only."""
    quality = _TOOLS["inspect_signal_quality"](signals)
    prompts = _TOOLS["select_teaching_prompts"](signals, quality)
    approved = _TOOLS["safety_review"](prompts)
    return {
        "mode": "offline_bounded_rule_agent",
        "tools_used": ["inspect_signal_quality", "select_teaching_prompts", "safety_review"],
        "signal_quality_flags": quality["flags"],
        "suggestions": approved,
        "review_note": "Group-level prompts only. Low activity is not evidence of an individual learner's engagement, intent, or ability.",
    }
