# legacy/ — archived pre-pipeline code (not maintained)

Kept for history, **not part of the maintained project** — excluded from
ruff, the test suite, and CI. Nothing in `src/` or `scripts/` imports any of
it. The living project is the `src/` medallion pipeline + agent layer (see the
top-level `README.md` and `SPEC.md`).

| Path | What it was | Superseded by |
|---|---|---|
| `spotify/` | v0 standalone Spotify scripts (`spotify_analytics.py`, `spotify_config.py`, a notebook). Used a client-secret auth flow. | `src/ingestion/` — PKCE-only, no secret; the guardrails module enforces the 2026 API surface. |
| `00_tools/notebooks/media_converter.py` | A general-purpose "convert media between formats" utility (moviepy + yt-dlp). | `src/ingestion/audio_downloader.py` — purpose-built YouTube→MP3 acquisition, idempotent + rate-limited, keyed on `spotify_track_id`. |

These were the exploratory starting point before the pipeline was designed.
They're archived rather than deleted so the project's evolution stays legible.
