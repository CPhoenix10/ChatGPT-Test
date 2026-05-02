from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AppConfig
from .resolver import NowPlaying


@dataclass
class WorkerState:
    station: str
    running: bool = False
    current_path: str | None = None
    current_offset: float | None = None
    error: str | None = None
    last_now: dict[str, Any] | None = None


@dataclass
class FFMpegWorker:
    station: str
    config: AppConfig
    process: subprocess.Popen | None = None
    state: WorkerState = field(init=False)

    def __post_init__(self) -> None:
        self.state = WorkerState(station=self.station)
        self.channel_dir.mkdir(parents=True, exist_ok=True)

    @property
    def safe_station(self) -> str:
        return self.station.replace("/", "_").replace(" ", "%20")

    @property
    def channel_dir(self) -> Path:
        return self.config.hls_root / self.station

    @property
    def playlist_path(self) -> Path:
        return self.channel_dir / "index.m3u8"

    def desired_matches(self, now_playing: NowPlaying, tolerance: float = 10.0) -> bool:
        if not self.process or self.process.poll() is not None:
            return False
        if self.state.current_path != now_playing.path:
            return False
        if self.state.current_offset is None:
            return False
        # ffmpeg runs forward in real-time, so do not restart for normal offset drift.
        return True

    def stop(self) -> None:
        if not self.process:
            return
        if self.process.poll() is None:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except Exception:
                    pass
        self.process = None
        self.state.running = False

    def start(self, now_playing: NowPlaying) -> None:
        self.stop()
        self.channel_dir.mkdir(parents=True, exist_ok=True)
        for old in self.channel_dir.glob("*.ts"):
            old.unlink(missing_ok=True)
        self.playlist_path.unlink(missing_ok=True)

        c = self.config
        t = c.transcode
        input_path = now_playing.path
        cmd = [
            c.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-re",
            "-ss",
            f"{max(0.0, now_playing.offset_seconds):.3f}",
            "-i",
            input_path,
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c:v",
            t.video_codec,
            "-preset",
            t.preset,
            "-crf",
            str(t.crf),
            "-c:a",
            t.audio_codec,
            "-b:a",
            t.audio_bitrate,
            "-f",
            "hls",
            "-hls_time",
            str(c.segment_seconds),
            "-hls_list_size",
            str(c.playlist_size),
            "-hls_flags",
            "delete_segments+program_date_time+independent_segments",
            "-hls_segment_filename",
            str(self.channel_dir / "seg_%06d.ts"),
            str(self.playlist_path),
        ]
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
                text=True,
            )
            self.state.running = True
            self.state.current_path = now_playing.path
            self.state.current_offset = now_playing.offset_seconds
            self.state.error = None
            self.state.last_now = {
                "station": now_playing.station,
                "block_title": now_playing.block_title,
                "item_title": now_playing.item_title,
                "path": now_playing.path,
                "offset_seconds": now_playing.offset_seconds,
                "item_duration_seconds": now_playing.item_duration_seconds,
                "block_start": now_playing.block_start.isoformat(),
                "block_end": now_playing.block_end.isoformat(),
            }
        except Exception as exc:
            self.state.error = str(exc)
            self.state.running = False
            self.process = None

    async def check_stderr(self) -> None:
        if not self.process or not self.process.stderr:
            return
        if self.process.poll() is not None:
            try:
                err = self.process.stderr.read()[-2000:]
            except Exception:
                err = "ffmpeg exited"
            self.state.error = err or "ffmpeg exited"
            self.state.running = False
