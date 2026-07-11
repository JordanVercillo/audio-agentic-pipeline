# Scaling — from 117 tracks to 1M (SPEC P7)

The pipeline runs on pandas today because the corpus is small (117 tracks).
This is the honest design narrative for the same medallion warehouse at
**10K and 1M tracks** — what changes, what doesn't, and where the real
bottleneck actually is. Zero cloud spend: the Spark path is proven for
correctness locally/in-CI; the cloud design is reasoned, not billed.

> **Vision decision (2026-07-11, owner): REAL data only — no synthetic rows to
> demo scale, ever.** Every row the product reasons about (warehouse, features,
> analytics, and any performance *benchmark*) must be real — Jordan's own
> Spotify + locally-extracted DSP, or real users' libraries. A fabricated
> 1M-row benchmark would betray the honest-measurement ethos as much as a faked
> feature would, so we will NOT manufacture volume to show off Spark. (This does
> not touch ground-rule #5: unit *tests* keep their `generate_test_signal()`
> synthetic fixtures — synthetic is for proving CODE correctness in tests, and
> must never stand in for DATA the product measures or reports.) **Consequently
> Spark/scale is PARKED:** the P7 parity proof below + this design doc already
> bank the scale-readiness evidence. Revisit only when we genuinely accumulate
> more real data, or need to speed up real extraction — not before. (Honest
> ceiling: real-user data growth is capped by the Spotify dev-mode 5-seat
> allowlist, so the corpus stays small for the foreseeable future — which is
> exactly why parity-on-real-data + a reasoned design is the right level of
> proof here.)

## First, find the real bottleneck

At scale the expensive step is **not** the warehouse transforms — it's
**audio acquisition + DSP**:

| Stage | 1M-track cost | Bound by |
|---|---|---|
| Metadata fetch (Spotify API) | minutes | API rate limits (paginated) |
| **Audio acquisition (YouTube)** | **the dominant cost** | **network + politeness rate-limiting** (5–30 s/track by design) |
| **DSP extraction (librosa, 77-dim)** | hours–days | CPU, embarrassingly parallel per track |
| Warehouse transforms (dedup, cast, join, centroids) | minutes | shuffle on `spotify_track_id` — cheap |

So the scaling story is two very different problems:

1. **Acquisition + DSP** — I/O- and CPU-bound, embarrassingly parallel per
   `spotify_track_id`. Scale with a **work queue + horizontal workers**
   (Cloud Run jobs / Dataproc / a Beam `ParDo`), not a bigger Spark cluster.
   The idempotency guards (file cache + Parquet cache) make this restartable
   and cheap to re-run — that's already in `audio_downloader.py` /
   `collection_extractor.py`.
2. **Warehouse transforms** — the classic distributed-SQL workload. This is
   where the `spark/` jobs live, and where the pandas→Spark parity matters.

## Spark ↔ pandas parity (verified)

The `spark/` jobs mirror the pandas transforms exactly; `spark/parity_check.py`
proves it and runs green in CI on Linux (the `spark-parity` job):

- **`feature_transform.py`** (Staging→Cleansed): window-function dedup
  (`row_number()` over `partitionBy(spotify_track_id).orderBy(_landed_at desc)`),
  type casts, null fills → **same dedup row-counts** as `build_cleansed_*`.
- **`temporal_aggregate.py`** (Cleansed→centroids): `groupBy(time_range).agg(mean)`
  → **centroid values identical within 1e-3** to `compute_temporal_centroids`.

The taste-drift *score* is a driver-side O(1) step on the 3 centroids — the
canonical metric is the RMS σ-shift in `src/analysis/drift.py` (ADR-003
amended, D-9); the distributed value is the centroid aggregation.

> **Windows local dev:** Spark's Hadoop layer needs `winutils.exe` + `hadoop.dll`
> (`HADOOP_HOME`) for local file IO — otherwise `NativeIO$Windows.access0`
> throws. The jobs are unchanged; it's a local shim. On Linux/macOS/cluster
> (and CI) Spark runs natively, which is why parity is verified there.

## Data layout at 10K–1M

**Object store + external tables, not a monolithic warehouse:**

```
gs://vercillo-taste/warehouse/
  staging/  features_raw/snapshot_date=YYYY-MM-DD/part-*.parquet   ← append-only, immutable
            tracks_raw/  snapshot_date=YYYY-MM-DD/part-*.parquet
  cleansed/ features/    part-*.parquet                            ← rebuilt incrementally
  modeled/  fact_listening_features/ time_range=.../part-*.parquet
```

- **Staging** stays append-only immutable snapshots — partition by
  `snapshot_date` so a run only reads/writes its own partition (predicate
  pushdown; no full-history scan).
- **Cleansed** dedups across snapshots. At 1M tracks the dedup shuffle keys
  on `spotify_track_id` — the natural partition/bucket key. Bucket by
  `hash(spotify_track_id)` (e.g. 200 buckets) so dedup and the fact join are
  co-partitioned (shuffle-free join).
- **Modeled** partitions the fact table by `time_range` for the analytical
  reads (only 3 values — fine as a *read* partition; too coarse as a *compute*
  partition, hence the hash-bucket above for the join).
- **BigQuery external tables** over the gold Parquet give SQL access without a
  load step — and let the P5 agent's `query_warehouse` point at BigQuery
  instead of local DuckDB with **zero tool changes** (both are read-only SQL
  over the same star schema).

## Compute: Spark vs Dataflow (Beam)

| | **Spark (Dataproc)** | **Dataflow (Apache Beam)** |
|---|---|---|
| Best for | the batch warehouse transforms (this repo's `spark/` jobs) | the acquisition+DSP fan-out (`ParDo` per track, autoscaling) |
| Model | RDD/DataFrame, shuffle-centric | pipeline of transforms, unified batch/stream |
| Ops | manage a cluster (or serverless Spark) | fully managed, autoscaling workers |
| Why here | the dedup/aggregation IS a shuffle workload | per-track DSP is a stateless fan-out — Beam's autoscaling fits it better than a fixed Spark cluster |

**Recommendation:** Beam/Dataflow for the acquisition+DSP fan-out (the
bottleneck, stateless, autoscale to zero); Spark/Dataproc — or just BigQuery
SQL — for the warehouse transforms (a shuffle-join workload that BigQuery does
natively). Picking the right tool per stage beats forcing everything through
one engine.

## The one cloud slice worth building first (P7 stretch)

Not a full migration — **one thin, high-signal slice**: publish the gold
Parquet to a GCS bucket, define **BigQuery external tables** over it, and
point the P5 MCP `query_warehouse` tool at BigQuery. That demonstrates the
whole thesis end-to-end — *agents querying a cloud warehouse built for them* —
for the cost of a few GB-months of storage and on-demand query bytes.

## What this system is deliberately NOT

- **Not streaming.** It's batch (listening history is pulled, not streamed).
  A real-time variant would be Beam streaming on a playlist-change webhook —
  designed here, not built, because the batch cadence matches the data.
- **Not multi-tenant at rest.** Single-user by default; the P8 pilot is
  session-ephemeral (see `SPEC.md`).
