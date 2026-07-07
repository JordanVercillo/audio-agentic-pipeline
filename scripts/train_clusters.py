"""
train_clusters.py — train the song + artist cluster models over the feature cache
(APP_SPEC Epic C).

    uv run python scripts/train_clusters.py [--coords umap|pca]

Deterministic (fixed seeds, silhouette-chosen k). Re-run after the cache grows —
each run persists a new versioned model; the webapp always reads the latest.
"""

import argparse
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.store.cache import FeatureCache  # noqa: E402
from src.store.clusters import train_artist_clusters, train_song_clusters  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train cluster models over the cache.")
    parser.add_argument("--coords", choices=("pca", "umap"), default="pca",
                        help="2-D map method (default pca; umap for larger corpora)")
    args = parser.parse_args()

    cache = FeatureCache()
    songs = train_song_clusters(cache, coords=args.coords)
    if songs:
        print(f"songs:   k={songs['k']} silhouette={songs['silhouette']} "
              f"over {songs['n_tracks']} tracks")
        for cid, label in songs["labels"].items():
            print(f"         [{cid}] {label}")
    else:
        print("songs:   skipped (not enough cached tracks)")

    artists = train_artist_clusters(cache)
    if artists:
        print(f"artists: k={artists['k']} silhouette={artists['silhouette']} "
              f"over {artists['n_artists']} artists")
        for cid, label in artists["labels"].items():
            print(f"         [{cid}] {label}")
    else:
        print("artists: skipped (not enough artists)")
