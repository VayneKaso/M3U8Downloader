# M3U8Downloader

A small Python utility for merging downloaded M3U8/TS segment folders into MP4 files with ffmpeg.

## What it does

- Scans configured download folders for M3U8/index-style task directories.
- Validates TS segment numbering before merging.
- Supports local AES-128 encrypted playlists that reference a downloaded key file.
- Skips existing complete MP4 outputs.
- Monitors free disk space and stops before the disk fills up.

## Requirements

- Python 3.14+
- ffmpeg available on `PATH`

## Usage

Edit the paths at the top of `main.py`, then run:

```bash
python main.py
```
