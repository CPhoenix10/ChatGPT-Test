from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx


class FS42Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = await self.client.get(f"{self.base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def station_names(self) -> list[str]:
        data = await self._get("/summary/stations")
        names = data.get("network_names") or data.get("stations") or []
        if isinstance(names, dict):
            names = list(names.keys())
        return [str(x) for x in names]

    async def station_config(self, network_name: str) -> dict[str, Any]:
        return await self._get(f"/stations/{quote(network_name, safe='')}")

    async def schedule(self, network_name: str, start: datetime, end: datetime) -> dict[str, Any]:
        return await self._get(
            f"/schedules/{quote(network_name, safe='')}",
            params={
                "start": start.replace(microsecond=0).isoformat(),
                "end": end.replace(microsecond=0).isoformat(),
            },
        )

    async def schedule_around_now(self, network_name: str, now: datetime, hours: int) -> dict[str, Any]:
        return await self.schedule(network_name, now - timedelta(minutes=10), now + timedelta(hours=hours))
