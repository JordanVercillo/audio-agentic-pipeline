---
name: env-verify
description: Diagnose the Python environment and prove the pipeline can run. TRIGGER when Jordan says the environment is broken, imports fail, ffmpeg/auth errors appear, tests fail unexpectedly, or before the first pipeline run on a machine ("verify my setup"). SKIP for data-quality questions (warehouse-audit) and design work (pipeline-partner).
user-invocable: true
allowed-tools: [Bash, Read, Glob, Grep]
---

Systematically check every component needed to run the pipeline, report
PASS / FAIL / SKIP per check with copy-pasteable fixes. Diagnose only — do
not modify project files. Run all checks; mark dependents SKIP (not FAIL)
when a prerequisite failed.

## Checks, in order

1. **Python** — `python --version` (needs 3.11+; repo has run on 3.13/conda).
2. **Core imports** — `python -c "import librosa, soundfile, numpy, pandas,
   pyarrow, spotipy, yt_dlp, faiss, umap, matplotlib"`. On failure:
   `pip install -r requirements.txt` (name the missing module explicitly).
3. **yt-dlp version** — must be ≥ 2026.2.21 (CVE floor pinned in
   requirements.txt): `python -c "import yt_dlp; print(yt_dlp.version.__version__)"`.
4. **ffmpeg on PATH** — `ffmpeg -version | head -1`. Needed by the MP3
   postprocessor. Fix: `winget install Gyan.FFmpeg` (or conda install ffmpeg).
5. **Spotify credentials** — `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`,
   `SPOTIPY_REDIRECT_URI` present in the environment (report NAMES only,
   never values). Fix: set env vars / `.env` (gitignored).
6. **PySpark sanity** (only if today's work needs spark/) —
   `python -c "import pyspark; print(pyspark.__version__)"`; JVM present
   (`java -version`). Otherwise SKIP with a note.
7. **Test suite** — `pytest src/ -v` (synthetic data; no network needed).
   Report per-module pass/fail counts. Any failure: quote the first
   assertion error, don't paraphrase.
8. **Pipeline smoke (metadata-only)** — only with Jordan's go-ahead (it
   hits the Spotify API): `python scripts/run_pipeline.py --skip-download
   --skip-extract`, then hand off to `warehouse-audit` for the data check.

End with a summary table (check | status | action) and one line stating
whether the machine is cleared for a real pipeline run. Record the result
in `notes/PROJECT_CONTEXT.md`'s session log if you're inside a
pipeline-partner session.
