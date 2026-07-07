"""
src.store — the shared feature-cache serving layer (APP_SPEC Epic A, D-11/D-12).

A track-keyed, user-agnostic cache of local-DSP audio features + spectrograms:
every song is analyzed once, ever, and served to every later visitor. Portable
across SQLite (dev/tests) and Postgres+pgvector (prod) via SQLAlchemy — the
bridge key `spotify_track_id` is the only key, always.
"""
