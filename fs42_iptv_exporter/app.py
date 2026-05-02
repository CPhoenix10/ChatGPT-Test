from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, PlainTextResponse

from .config import AppConfig, load_config
from .ffmpeg_worker import FFMpegWorker
from .fs42_client import FS42Client
from .resolver import resolve_now

CONFIG = load_config()
CLIENT = FS42Client(CONFIG.fs42_base_url)
WORKERS: dict[str, FFMpegWorker] = {}
TASK: asyncio.Task | None = None
LAST_SCHEDULES: dict[str, dict[str, Any]] = {}


def safe_channel_name(name: str) -> str:
    return name.replace("/", "_")


async def selected_stations() -> list[str]:
    names = await CLIENT.station_names()
    if CONFIG.channels:
        allowed = set(CONFIG.channels)
        names = [n for n in names if n in allowed]
    return names


async def streamer_loop() -> None:
    while True:
        try:
            stations = await selected_stations()
            now = datetime.now()
            for station in stations:
                worker = WORKERS.setdefault(station, FFMpegWorker(station, CONFIG))
                try:
                    schedule = await CLIENT.schedule_around_now(station, now, CONFIG.lookahead_hours)
                    LAST_SCHEDULES[station] = schedule
                    np = resolve_now(schedule, station, now, CONFIG.media_root)
                    if np is None:
                        worker.state.error = "No current playable item resolved from FS42 schedule"
                        continue
                    if not worker.desired_matches(np):
                        worker.start(np)
                    await worker.check_stderr()
                except Exception as exc:
                    worker.state.error = str(exc)
            await asyncio.sleep(CONFIG.poll_seconds)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(CONFIG.poll_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    CONFIG.hls_root.mkdir(parents=True, exist_ok=True)
    global TASK
    TASK = asyncio.create_task(streamer_loop())
    try:
        yield
    finally:
        if TASK:
            TASK.cancel()
        for worker in WORKERS.values():
            worker.stop()
        await CLIENT.close()


app = FastAPI(title="FS42 IPTV Exporter", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "fs42_base_url": CONFIG.fs42_base_url, "channels": list(WORKERS)}


@app.get("/channels.m3u", response_class=PlainTextResponse)
async def channels_m3u() -> str:
    stations = await selected_stations()
    lines = ["#EXTM3U"]
    for station in stations:
        config: dict[str, Any] = {}
        try:
            config = await CLIENT.station_config(station)
        except Exception:
            pass
        station_conf = config.get("station_conf", config)
        channel_number = station_conf.get("channel_number", "")
        safe = quote(station, safe="")
        attrs = f'tvg-id="{station}" tvg-name="{station}"'
        if channel_number != "":
            attrs += f' tvg-chno="{channel_number}"'
        lines.append(f"#EXTINF:-1 {attrs},{station}")
        lines.append(f"{CONFIG.public_base_url.rstrip('/')}/hls/{safe}/index.m3u8")
    return "\n".join(lines) + "\n"


@app.get("/now/{station}")
async def now_playing(station: str) -> dict[str, Any]:
    worker = WORKERS.get(station)
    if not worker:
        raise HTTPException(status_code=404, detail="Unknown or not-yet-started station")
    return worker.state.__dict__


@app.get("/status")
async def status() -> dict[str, Any]:
    return {station: worker.state.__dict__ for station, worker in WORKERS.items()}


@app.get("/debug/schedule/{station}")
async def debug_schedule(station: str) -> dict[str, Any]:
    if station in LAST_SCHEDULES:
        return LAST_SCHEDULES[station]
    now = datetime.now()
    return await CLIENT.schedule_around_now(station, now, CONFIG.lookahead_hours)


@app.get("/hls/{station}/index.m3u8")
async def hls_playlist(station: str) -> Response:
    path = CONFIG.hls_root / station / "index.m3u8"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Playlist not ready yet")
    return FileResponse(path, media_type="application/vnd.apple.mpegurl")


@app.get("/hls/{station}/{segment}")
async def hls_segment(station: str, segment: str) -> Response:
    path = CONFIG.hls_root / station / segment
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Segment not found")
    return FileResponse(path, media_type="video/MP2T")
