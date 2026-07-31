# Deletion log

Code removed from this repo, and how to get it back.

**The rule (owner, 2026-07-31): nothing is archived in-tree.** No `legacy/`
parking, no commented-out blocks, no "keep it for the portfolio". Git already
is the archive — a file that no longer earns its place is deleted, and its
entry here records what it was, why it went, and the exact commit to restore
it from.

Why a log at all: `git log` answers "what changed" but not "why was this
capability dropped, and was it ever load-bearing?". A reader six months from
now finds an empty `src/search/` and has no way to know whether FAISS was
abandoned or never worked. That question is what this file answers.

**To restore anything below:**

```bash
git show <last-commit-containing>:<path> > <path>   # one file, into the tree
git checkout <last-commit-containing> -- <path>     # same, staged
```

---

## 2026-07-31 — the dormant FAISS vector-search stack

**Deleted:** `src/search/faiss_store.py` (355 lines) ·
`src/search/pipeline.py` (224) · `src/search/test_search.py` (229) ·
`src/search/test_search_stack_is_dormant.py` (the guard that enforced their
dormancy — obsolete once they were gone)

| | |
|---|---|
| **Last commit containing them** | `9a42a1a` (2026-07-31) |
| **Last commit that modified them** | `48ae692` (2026-07-04, "P6: ruff lint config + fixes") |
| **Introduced in** | `b199022` |
| **Restore** | `git checkout 9a42a1a -- src/search/faiss_store.py src/search/pipeline.py` |

**What they were.** A FAISS (Meta's vector-similarity library) index over the
77-dim acoustic fingerprints, plus the DAG around it:

- `FAISSStore` — build / persist / load an index, add vectors keyed by the
  bridge key, k-NN search with cosine or L2.
- `pipeline.build_index_from_features` / `build_index_from_embeddings` /
  `find_similar_tracks` / `visualize_collection` — warehouse → index → query →
  UMAP projection → plot.
- `test_search.py` — a synthetic end-to-end smoke script.

**Why deleted.**

1. **Nothing imported them.** Verified by AST scan across `src/`, `scripts/`
   and `spark/` on 2026-07-31: zero importers outside `src/search/` itself.
   They were not disabled or feature-flagged — simply never wired up.
2. **The app answers this question a different way.** Live "similar tracks" is
   plain `math.dist` over a projected plane in `src/store/cache.py`, measured
   at **7.7 ms** on the ~1,900-track corpus. FAISS pays off at millions of
   vectors; at this scale the index build alone costs more than the scan.
3. **They read as tested and were not.** `test_search.py` defined
   `run_smoke_test()` — not a `test_*` name, so pytest never collected it. Both
   modules sat at **0.0% coverage** in the first CI baseline (2026-07-31) while
   a file named `test_search.py` sat beside them.
4. **Keeping them was the same defect as a stale README number** — code
   asserting a capability the product does not have. The owner's call
   (2026-07-31): don't keep code for the portfolio story.

**Removed with them:** the `faiss-cpu>=1.7.0` dependency (no `import faiss`
remained anywhere), the `_LAZY` / `__all__` entries in `src/search/__init__.py`,
and the FAISS-only fields on `VectorStoreConfig`.

**Kept:** `src/search/visualizer.py` and `src/search/config.py` — `compute_umap`
IS live (`src/analysis/clustering.py` uses it for the taste map, and
`scripts/build_taste_map.py` is a documented run command). Tests were added the
same day.

**If vector search is ever wanted again**, restore is one command — but prefer
rebuilding against the current feature store rather than resurrecting a 2026-07
design that predates the perceptual plane, the bridge-key composite keys and
the D-66 transparency contract.
