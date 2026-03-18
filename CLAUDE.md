# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Factory (Паузорез)** — Video automation pipeline for Russian-language interviews. Removes pauses, filler words, stutters, and noise from video files without re-encoding.

The technical specification is in `task.md` (Russian). Design docs are in `docs/plans/`.

## Running the Main Script

```bash
# Install dependencies
pip install faster-whisper tqdm

# Dry run (preview only, no processing)
python _scripts/cut_pauses.py projects/test/01_raw/video1343572807.mp4 --dry-run

# Full processing
python _scripts/cut_pauses.py <input_file_or_dir> [--output PATH] [--model large-v3] [--pause 0.5] [--save-transcript]
```

Requires `ffmpeg` and `ffprobe` on PATH. CUDA is auto-detected with CPU fallback.

## Architecture

Single-script pipeline in `_scripts/cut_pauses.py` with three phases:

1. **Transcription** — `faster-whisper` extracts word-level timestamps (Russian)
2. **Filtering** — Removes filler words, stutters, noise tokens, and pauses above threshold
3. **Cut & Concat** — `ffmpeg` concat demuxer extracts and joins speech segments (no re-encode)

## Conventions

- **Project folders**: `YYYY-MM-description` under `projects/`, each with `01_raw/` (input) and `02_cuts/` (output)
- **Output naming**: `{filename}_clean.mp4`
- **User-facing messages and comments**: Russian language
- **Paths**: Use `pathlib.Path` objects
- **Video formats**: `.mp4`, `.mov`, `.mkv`, `.avi`
- **Git branches**: `main` is the primary branch; development happens on `master` or feature branches
