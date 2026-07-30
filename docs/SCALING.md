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

## Running Spark LOCALLY on this Windows box (measured 2026-07-29/30)

The parity job has only ever been proven on Linux CI. Making it run here
surfaced two distinct problems — recorded because the first is a trap that
silently wins, and the second is a hang that looks like slowness.

**1. The Anaconda shadow (journal #62).** Three env vars aimed Spark at a
different installation entirely:

| Var | Inherited value | Why it breaks us |
|---|---|---|
| `SPARK_HOME` | `C:\spark\spark-3.5.6-bin-hadoop3` | Spark 3.5.6 jars vs our pinned pyspark 4.1.2 |
| `PYSPARK_PYTHON` | `anaconda3\python.exe` | Spark WORKERS launch Anaconda's interpreter — pyspark 3.5.6, none of our deps |
| `PYSPARK_DRIVER_PYTHON` | `anaconda3\python.exe` | same, driver side |

`uv run` fixes the driver's imports and nothing else, so this survives it.
The working invocation pins all of them explicitly:

```powershell
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.20.8-hotspot"  # 4.x needs 17+
Remove-Item Env:SPARK_HOME                      # pyspark 4.1.2 bundles its own jars
$env:PYSPARK_PYTHON = ".\.venv\Scripts\python.exe"
$env:PYSPARK_DRIVER_PYTHON = $env:PYSPARK_PYTHON
```

With JDK 17 + that env, **Spark 4.1.2 starts and runs in-memory work fine**
(verified: SparkSession up in 11 s, count + agg + a real shuffle, 20.5 s total).

**2. `hadoop.dll` — why local FILE access fails, and why the failure looks
like a hang.** Any read from the local filesystem reaches Hadoop's Windows
native IO:

```
java.lang.UnsatisfiedLinkError: 'boolean
  org.apache.hadoop.io.nativeio.NativeIO$Windows.access0(java.lang.String, int)'
  at org.apache.hadoop.fs.Globber.glob(...)
```

`C:\hadoop\bin` has `winutils.exe` but no `hadoop.dll`, and `access0` lives in
the DLL. `FileUtil.canRead` catches `IOException` but **not** `UnsatisfiedLinkError`
— an `Error` — so the globber's ForkJoinPool worker dies and the driver waits
on a future that never completes. It presents as a job that runs forever with
no output, not as a crash. *(That is what a 10-minute "slow" parity run
actually was.)* Note the earlier `WARN NativeCodeLoader: Unable to load
native-hadoop library` is benign and unrelated — in-memory work proceeds.

**The decision (owner, 2026-07-29): WSL2, not a third-party DLL.** Apache
publishes no official Windows Hadoop binaries; every `hadoop.dll` source is a
community GitHub repo shipping an unsigned binary that would be loaded into
the JVM — an unacceptable supply-chain addition for a public repo whose
security posture is part of its story. WSL2 gives real Linux Spark (no
winutils path at all) and full performance for the Phase 5 J2 benchmark.

### ✅ RESOLVED 2026-07-30 — parity is now proven LOCALLY

`powershell -ExecutionPolicy Bypass -File scripts\spark_wsl.ps1 spark/parity_check.py`

```
Spark 4.1.2 · master local[*]
[PASS] features dedup row-count   — pandas=30  spark=30
[PASS] tracks dedup row-count     — pandas=90  spark=90
[PASS] temporal centroid parity   — identical within 1e-3
✅ Spark output matches pandas — parity verified.      (10.9 s)
```

**The claim "Spark parity is verified" is finally true off CI.** Getting
there took three fixes, in order: (1) the WSL app package was registered but
never deployed — `C:\Program Files\WSL\wsl.exe` did not exist while
`wsl.exe` resolved to the old `system32` stub, so every call returned
`REGDB_E_CLASSNOTREG`; an elevated `winget install --id Microsoft.WSL --force`
deployed it. (2) The `Microsoft-Windows-Subsystem-Linux` optional feature was
Disabled — enabled via elevated DISM (exit 3010, reboot required). (3) Ubuntu
installed with `--no-launch` and driven `--user root`, which avoids the
interactive username/password prompt entirely.

`scripts/spark_wsl.ps1` is the durable artifact: `-Setup` provisions the
distro (OpenJDK 17 + a venv with **pyspark pinned to the project's 4.1.2** —
a parity check against a different Spark proves nothing), and the default
path runs any repo script under it. Every Spark-relevant variable is SET,
never inherited, which is the journal-#62 fix made mechanical. All bash is
base64-encoded across the shell boundary, so neither PowerShell/bash quoting
nor CRLF line endings can corrupt it — both bit us while building this.

Measured inside WSL: 30 GB RAM visible, repo reachable at
`/mnt/c/Users/jverc/audio-agentic-pipeline`. Note `/mnt/c` I/O is slower than
the WSL-native filesystem; for the Phase 5 J2 benchmark on 29.5M rows, stage
the parquet inside the distro rather than reading across the mount.
