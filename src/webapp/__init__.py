"""
src.webapp — P8 production-pilot webapp (SPEC P8, D-7).

A public FastAPI site where any visitor authenticates their OWN Spotify via
session-scoped PKCE (no owner secret — D-8), and the app grounds taste
insights on their listening history joined against our local DSP feature
store (the bridge key `spotify_track_id`).

Slice 1: auth + dashboard (top tracks + acoustic overlap insight).
Later slices: RAG /ask, containerize, Cloud Run. See docs/P8_PLAN.md.
"""
