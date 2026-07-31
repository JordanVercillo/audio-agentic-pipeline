"""Q6 - `compute_umap`, the one part of src/search that is actually live.

The first CI coverage baseline (2026-07-31) put `src/search/visualizer.py` at
13.6%, and unlike its neighbours in this package it is NOT dormant:
`src/analysis/clustering.py:348` imports `compute_umap` for the taste-map
projection, and `scripts/build_taste_map.py` is a documented run command in
CLAUDE.md. It had no test.

The rest of `src/search/` (faiss_store.py, pipeline.py) has zero importers
outside the package - see `test_search_stack_is_dormant.py`, which keeps that
true rather than assuming it.

Note for anyone reproducing: `umap` resolves only under the project venv. A bare
`python -c "import umap"` can hit a different interpreter on PATH and report it
missing - Anaconda has shadowed this project's toolchain before.
"""
from __future__ import annotations

import numpy as np
import pytest

umap = pytest.importorskip("umap", reason="umap-learn is an optional dep chain")

from .config import VectorStoreConfig  # noqa: E402
from .visualizer import compute_umap  # noqa: E402


@pytest.fixture(scope="module")
def vectors() -> np.ndarray:
    """Two separated blobs - synthetic, ground rule 5."""
    rng = np.random.default_rng(11)
    return np.vstack([
        rng.normal(-2.0, 0.25, (12, 8)),
        rng.normal(2.0, 0.25, (12, 8)),
    ]).astype(np.float32)


@pytest.fixture(scope="module")
def projection(vectors) -> np.ndarray:
    return compute_umap(vectors)


def test_projection_has_one_row_per_track_and_is_plottable(vectors, projection):
    """`clustering.py` assigns `frame["umap_x"] = projection[:, 0]` straight
    onto the frame, so a row-count mismatch or a NaN corrupts the mart rather
    than raising."""
    assert projection.shape[0] == vectors.shape[0], (
        "row count changed during projection - the frame assignment would misalign")
    assert projection.shape[1] == VectorStoreConfig().umap_n_components
    assert projection.dtype == np.float32
    assert np.isfinite(projection).all(), "a non-finite coordinate reached the map"


def test_projection_is_deterministic(vectors, projection):
    """`VectorStoreConfig.umap_random_state` exists so the committed taste-map
    artifact is reproducible. Unseeded UMAP would redraw the map on every
    rebuild and no diff would ever be meaningful."""
    again = compute_umap(vectors)
    np.testing.assert_allclose(projection, again, rtol=1e-5, atol=1e-5)


def test_too_few_samples_raises_rather_than_projecting_noise():
    """UMAP on 3 points is a picture of nothing. The guard must fire, and say
    what to do about it."""
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="at least 4 samples"):
        compute_umap(rng.normal(0, 1, (3, 8)).astype(np.float32))


def test_n_neighbors_is_clamped_to_the_sample_count():
    """The default n_neighbors (15) exceeds a small corpus, which UMAP rejects.
    `compute_umap` clamps it - so a 5-track collection must project, not crash.
    That is the case a NEW user hits on their first run."""
    rng = np.random.default_rng(3)
    small = rng.normal(0, 1, (5, 8)).astype(np.float32)
    assert VectorStoreConfig().umap_n_neighbors > 5, (
        "fixture no longer exercises the clamp")
    out = compute_umap(small)
    assert out.shape[0] == 5 and np.isfinite(out).all()
