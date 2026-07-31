# Clustering and similarity

*The three models, why one of them is published by hand, and what isn't proven
yet.*

← back to [How it works](../HOW_IT_WORKS.md)

---

## Unsupervised: nobody labelled the answer

All three models here are **unsupervised** — there is no correct answer to learn
from. Nobody has labelled which songs belong together, so the algorithm finds
structure in the numbers on its own.

That's different from **supervised** learning (predicting a label you already
have examples of) and it has one uncomfortable consequence: **there is no
accuracy score**, because there is nothing to be accurate against.

## 1. Clustering — grouping songs that sound alike

**KMeans** is the algorithm. Given a target number of groups *k*:

1. Drop *k* points into the 77-dimensional space
2. Assign each song to its nearest point
3. Move each point to the average of the songs assigned to it
4. Repeat until nothing moves

Each final point is a **centroid** — the "average sound" of that group.

### Choosing k

*k* isn't known in advance, so several are tried (2 through 6) and scored by
**silhouette**: for each song, how much closer is it to its own group than to
the next nearest group? Ranges −1 to +1.

- above ~0.5 → clear structure
- 0.25–0.5 → weak but real
- below ~0.25 → **no substantial structure**

### What ours currently says

| | |
|---|---|
| k chosen | 2 |
| silhouette | 0.148 |
| split | 937 / 957 |

A near-perfect 50/50 split at 0.148 is what it looks like when the algorithm
**found no real grouping and cut the cloud in half**. Every model back to #7 also
landed on k=2 — the smallest option offered — which is the signature of picking
the least-bad answer in a space without natural clusters.

That might be honest: one person's music library is a narrow slice of all
possible sound, so it may genuinely be *one* taste rather than several. But the
site presents it as "your two sounds", and the geometry doesn't currently support
that strongly.

**The cheap test** — not yet done: re-run the clustering on deliberately
shuffled data. If real data scores no better than nonsense, the groups are an
artifact of the algorithm rather than a fact about the music.

### Naming the groups

A cluster is named by whichever features most distinguish it from the corpus
average — producing labels like "Punchy · Smooth". Genre tags would be nicer,
but Spotify's genre data is too sparse to use, so the names describe what was
actually measured.

## 2. Train always, publish deliberately

This is the unusual part, and it's on purpose.

A new model is trained **automatically** every time the corpus grows meaningfully.
Training is safe: it writes a candidate and changes nothing anyone sees.

Publishing that candidate — **promotion** — is a separate, gated step, because
it changes things a visitor perceives:
- which group their "home sound" belongs to
- what the colours on the map mean
- the wording of their taste description

So a human approves it. The one exception: if a retrain is provably
*identity-stable* — same k, centroids matching the old ones, unchanged labels —
nothing perceptible has moved, so it promotes itself.

Think of it as gating a full-refresh of a dimension that dashboards key on. The
rebuild is cheap; the *meaning change* is what needs a human.

### The identity map

Retraining assigns arbitrary numbers to groups. The group that was `0` may come
back as `1`, with identical membership.

If that were published raw, cluster `0` would silently change meaning: the map's
colours swap, and "your home sound is cluster 0" now refers to different music.
So promotion carries an **identity map** that renumbers the new model to match
the old one, keeping `0` meaning the same *sound* across retrains.

### The bug that hid here

Promotion remapped everything keyed *by* cluster id — labels, descriptions,
stored assignments — but missed `centroids`, which is a **list indexed by
position** rather than a dictionary.

Result: a published model whose stored assignments said one thing and whose own
centroids said another. Measured on the live model: **1,894 of 1,894 stored
assignments disagreed with the model's own nearest-centroid rule.** Every test
passed, both audits were green, because nothing had ever asked the model whether
it agreed with itself.

There is now a check that asks exactly that, on every audit run.

## 3. Projection — the 2-D map

**UMAP** squashes 77 dimensions to 2 so the collection can be drawn. It tries to
keep songs that were close in 77-D close on the flat map.

Read the map's *neighbourhoods*, not its axes. The axes mean nothing
individually — there is no "loudness direction". Distance is approximate too;
squashing 77 dimensions into 2 always loses information.

The projection is **seeded** so the same corpus always draws the same map.
Without that, every rebuild would redraw it and no visual comparison would mean
anything.

## 4. Similarity — nearest neighbours

Given a song, find the closest others. Deliberately simple:

- **13 of the features**, not all 83 — hand-chosen: tempo, loudness, spectral
  shape, harmonicity, punch, and five MFCCs
- **z-scored** so no column dominates by scale
- **exact** distance to every candidate — no index, no approximation
- **7.7 ms** across ~1,900 songs

An approximate-nearest-neighbour index (FAISS) was built for this and
[deleted](../DELETIONS.md) — it trades exactness for speed on a search that
wasn't slow. At tens of thousands of songs that changes.

Duplicates are excluded from the candidate pool, or a song's nearest neighbour
would be itself under a different ID.

## What isn't proven

Stated plainly, because it's the honest state:

1. **No evaluation exists** for similarity or clustering. No recall@k, no
   held-out test. "Are these actually similar?" is currently unanswered.
2. **k=2 may be an artifact.** The null-model test above hasn't been run.
3. **The 13 similarity features were chosen by judgement**, not by any selection
   procedure — and several are correlated, so timbre is over-weighted relative
   to tempo purely by how many columns describe it.

There *is* a possible source of weak labels: songs a human put in the same
playlist. About 17,700 such pairs exist across 25 curated playlists. That's
enough to build a real evaluation — with the caveat that playlist co-occurrence
measures *taste adjacency*, not acoustic similarity, so it would be evidence
rather than proof.

→ Next: [Trust and data quality](trust-and-data-quality.md)
