# fs42-iptv-exporter

A sidecar HLS/IPTV exporter for FieldStation42.

It asks FS42 what each station should be playing *now*, resolves the current media item and offset, then keeps an HLS playlist alive per channel for VLC, Jellyfin, or any IPTV client.

## Why this exists

FS42 is excellent as the scheduler/catalog/bump/commercial brain. A capture card or screen recorder only captures the currently tuned output, though. This sidecar exposes every FS42 station as its own URL without running one full graphical FS42 player per channel.

## Requirements

- FieldStation42 running with the server/API enabled
- Python 3.11+
- ffmpeg in PATH
- FS42 schedules already generated

Start FS42 API:

```bash
python3 station_42.py --server
```

## Install

From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Edit `config.yaml`:

```yaml
fs42_base_url: "http://127.0.0.1:4242"
public_base_url: "http://YOUR-LAN-IP:8088"
media_root: "/home/cphoenix/FieldStation42"
hls_root: "/tmp/fs42-hls"
```

## Run

```bash
uvicorn fs42_iptv_exporter.app:app --host 0.0.0.0 --port 8088
```

Open:

```text
http://YOUR-LAN-IP:8088/channels.m3u
http://YOUR-LAN-IP:8088/hls/Nickelodeon/index.m3u8
http://YOUR-LAN-IP:8088/now/Nickelodeon
```

## Jellyfin

Jellyfin → Live TV → Tuner Devices → Add M3U Tuner:

```text
http://YOUR-LAN-IP:8088/channels.m3u
```

## Notes

This first version is intentionally defensive about FS42 schedule JSON. It looks for media paths in common fields such as `path`, `file_path`, `filename`, `media`, `video`, `content`, and nested dictionaries. If your FS42 schedule shape differs, run `/debug/schedule/<channel>` and adjust `resolver.py`.

