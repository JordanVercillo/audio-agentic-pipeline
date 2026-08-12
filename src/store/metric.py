"""The similarity metric's transform — defined ONCE, used by serving and by eval.

`similar()` and `src/analysis/metric_experiment.py` must apply the identical
transform or the measured improvement belongs to a metric nobody ships. This is
the same "derive, don't restate" rule the scales registry enforces for labels,
applied to arithmetic.

## Why whitening

The 13 similarity columns are not independent: five are MFCC means, which
correlate with the spectral centroid and rolloff columns. Plain Euclidean
distance over correlated features DOUBLE-COUNTS — timbre gets roughly half the
vote purely because more columns happen to describe it, which nobody decided.

Whitening rotates into the principal axes and scales each to unit variance, so
correlated directions stop voting twice. Euclidean distance in the whitened
space is Mahalanobis distance in the original.

Measured on held-out playlists, paired across 20 re-splits (2026-08-12):
recall@10 **0.0475 -> 0.0525**, mean delta +0.005 with 95% CI (0.0027, 0.0072),
winning 16 of 20 splits.

## Why shrinkage, and why a corpus-size floor

A naive whitening divides by the square root of each eigenvalue. On a corpus
whose features are nearly collinear — a small or synthetic corpus especially —
the smallest eigenvalues are ~0, so those directions get amplified by a huge
factor and the metric ends up ranking by numerical noise. Two guards:

  - **Shrinkage.** `cov + lambda*I`, lambda proportional to the average
    variance. Standard regularisation; it bounds the amplification and degrades
    gracefully toward plain z-scoring as the corpus becomes degenerate.
  - **A sample floor.** Estimating a d x d covariance from fewer than
    ~10d samples gives an estimate dominated by sampling noise, so below that
    this returns the z-scored input unchanged. A 20-track test corpus therefore
    keeps the old behaviour, which is the honest answer for 20 tracks.
"""
from __future__ import annotations

from typing import Optional

# Below MIN_SAMPLES_PER_DIM * d rows, a d x d covariance is mostly sampling
# noise and whitening would amplify it. Ten is the usual rule of thumb.
MIN_SAMPLES_PER_DIM = 10

# lambda = SHRINKAGE * mean(diag(cov)). Small enough not to undo the whitening,
# large enough that a near-zero eigenvalue cannot dominate the metric.
SHRINKAGE = 1e-3


def whitening_matrix(Z, *, shrinkage: float = SHRINKAGE,
                     min_samples_per_dim: int = MIN_SAMPLES_PER_DIM) -> Optional[list]:
    """W such that `Z @ W` is decorrelated and unit-variance, or None.

    `Z` must already be z-scored. Returns None when the corpus is too small to
    estimate a covariance — the caller then keeps the z-scored vectors, which is
    exactly the previous behaviour.
    """
    import numpy as np

    Z = np.asarray(Z, dtype=float)
    if Z.ndim != 2:
        return None
    n, d = Z.shape
    if d == 0 or n < max(2, min_samples_per_dim * d):
        return None

    cov = np.cov(Z, rowvar=False)
    cov = np.atleast_2d(cov)
    lam = shrinkage * float(np.mean(np.diag(cov)))
    if not np.isfinite(lam) or lam <= 0:
        lam = shrinkage
    cov = cov + lam * np.eye(d)

    vals, vecs = np.linalg.eigh(cov)
    if not np.isfinite(vals).all() or (vals <= 0).any():
        return None
    W = vecs / np.sqrt(vals)
    if not np.isfinite(W).all():
        return None
    return W.tolist()


def apply_whitening(vec, W) -> tuple:
    """Project one z-scored vector through the whitening matrix."""
    out = []
    for j in range(len(W[0])):
        out.append(sum(vec[i] * W[i][j] for i in range(len(vec))))
    return tuple(out)
