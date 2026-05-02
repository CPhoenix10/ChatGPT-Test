from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class TranscodeConfig(BaseModel):
    video_codec: str = "libx264"
    preset: str = "veryfast"
    crf: int = 23
    audio_codec: str = "aac"
    audio_bitrate: str = "128k"


class AppConfig(BaseModel):
    fs42_base_url: str = "http://127.0.0.1:4242"
    public_base_url: str = "http://127.0.0.1:8088"
    hls_root: Path = Path("./hls")
    media_root: Path = Path(".")
    ffmpeg_bin: str = "ffmpeg"
    stream_all_channels: bool = True
    channels: list[str] = Field(default_factory=list)
    segment_seconds: int = 4
    playlist_size: int = 8
    poll_seconds: int = 2
    lookahead_hours: int = 8
    transcode: TranscodeConfig = Field(default_factory=TranscodeConfig)


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    cfg_path = Path(path)
    data: dict[str, Any] = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text()) or {}
    return AppConfig.model_validate(data)
