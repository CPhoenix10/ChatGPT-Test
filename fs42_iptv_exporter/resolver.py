from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


PATH_KEYS = (
    "path",
    "file",
    "filepath",
    "file_path",
    "filename",
    "full_path",
    "media_path",
    "video_path",
    "source",
    "url",
)
DURATION_KEYS = ("duration", "duration_seconds", "runtime", "length", "seconds")
TITLE_KEYS = ("title", "name", "show_title", "program", "network_name")


@dataclass(frozen=True)
class NowPlaying:
    station: str
    block_title: str
    item_title: str
    path: str
    offset_seconds: float
    item_duration_seconds: float | None
    block_start: datetime
    block_end: datetime
    raw_item: dict[str, Any]


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    return None


def as_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
        parts = value.split(":")
        if len(parts) == 3:
            try:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + float(s)
            except ValueError:
                return None
    return None


def blocks_from_schedule(schedule: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("schedule_blocks", "blocks", "schedule", "items"):
        value = schedule.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def item_list_from_block(block: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("plan", "content", "items", "playlist", "segments", "media"):
        value = block.get(key)
        if isinstance(value, list):
            return [normalize_item(x) for x in value]
    return [normalize_item(block)]


def normalize_item(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"value": value}


def find_first_path(value: Any) -> str | None:
    if isinstance(value, str):
        lowered = value.lower()
        if lowered.startswith(("http://", "https://", "rtsp://", "rtmp://")):
            return value
        if any(lowered.endswith(ext) for ext in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".mp3", ".m4v", ".ts")):
            return value
        if "/" in value or "\\" in value:
            return value
        return None
    if isinstance(value, dict):
        for key in PATH_KEYS:
            if key in value:
                found = find_first_path(value[key])
                if found:
                    return found
        for nested in value.values():
            found = find_first_path(nested)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = find_first_path(item)
            if found:
                return found
    return None


def find_title(item: dict[str, Any], fallback: str = "") -> str:
    for key in TITLE_KEYS:
        value = item.get(key)
        if value:
            return str(value)
    return fallback


def find_duration(item: dict[str, Any]) -> float | None:
    for key in DURATION_KEYS:
        seconds = as_seconds(item.get(key))
        if seconds is not None:
            return seconds
    return None


def block_duration(block: dict[str, Any]) -> float | None:
    start = parse_dt(block.get("start_time") or block.get("start"))
    end = parse_dt(block.get("end_time") or block.get("end"))
    if start and end:
        return (end - start).total_seconds()
    return find_duration(block)


def resolve_media_path(path: str, media_root: Path) -> str:
    if path.lower().startswith(("http://", "https://", "rtsp://", "rtmp://")):
        return path
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str((media_root / p).resolve())


def resolve_now(schedule: dict[str, Any], station: str, now: datetime, media_root: Path) -> NowPlaying | None:
    for block in blocks_from_schedule(schedule):
        start = parse_dt(block.get("start_time") or block.get("start"))
        end = parse_dt(block.get("end_time") or block.get("end"))
        if not start or not end or not (start <= now < end):
            continue

        elapsed = (now - start).total_seconds()
        block_title = str(block.get("title") or block.get("name") or "")
        items = item_list_from_block(block)

        if not items:
            continue

        # If FS42 returns a plan with per-item durations, walk it. Otherwise fall back to first media in block.
        for item in items:
            duration = find_duration(item)
            path = find_first_path(item)
            if duration is None:
                if path:
                    return NowPlaying(station, block_title, find_title(item, block_title), resolve_media_path(path, media_root), elapsed, None, start, end, item)
                continue
            if elapsed < duration:
                if not path:
                    return None
                return NowPlaying(station, block_title, find_title(item, block_title), resolve_media_path(path, media_root), max(0.0, elapsed), duration, start, end, item)
            elapsed -= duration

        # Schedule plans sometimes omit break filler details; fall back to last playable item.
        for item in reversed(items):
            path = find_first_path(item)
            if path:
                return NowPlaying(station, block_title, find_title(item, block_title), resolve_media_path(path, media_root), 0.0, find_duration(item), start, end, item)
    return None
