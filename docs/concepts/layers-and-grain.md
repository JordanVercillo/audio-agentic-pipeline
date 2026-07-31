# Layers and grain

*Why data moves through stages, and the question you must answer about every
table.*

← back to [How it works](../HOW_IT_WORKS.md)

---

## Grain: the question to ask first

**Grain** is the answer to "what does one row mean?"

- `track_perceptual` → one row per **song**
- `artist_rollup` → one row per **artist**
- `cluster_profile` → one row per **cluster**
- `corpus_facts` → one row for the **entire corpus**
- `track_clusters` → one row per **song per model**

That last one looks like a technicality and isn't. Getting it wrong is what
caused the assignment-loss bug described in [the bridge key](bridge-key.md).

**Ask the grain question before writing any table.** Nearly every confusing data
bug is two people assuming different grains for the same table — one thinks
"one row per song", the other "one row per song per play", and the average comes
out wrong.

## The layers

Data arrives messy and leaves tidy. Doing that in one step means that when a
number is wrong you have nowhere to look. So it happens in stages, each with one
job:

### Staging — "what actually arrived"

Raw, untouched, exactly as received. Written as timestamped snapshots
(`features_raw_20260731_201928.parquet`) and never edited.

Why keep it? Because when a number looks wrong, the first question is always
"did we receive bad data, or break good data?" Without staging you cannot tell.

### Cleansed — "validated and deduplicated"

Types corrected, obvious garbage dropped, duplicates resolved, one row per song.
This is the first layer you'd actually trust.

### Modeled — "organised for analysis"

A **star schema**: one central table of measurements (a **fact** table)
surrounded by descriptive tables (**dimensions**).

- fact → `fact_listening_features` — the numbers
- dimensions → `dim_tracks`, `dim_artists`, `dim_time_range` — the labels

The shape exists because facts are many and dimensions are few. You store the
song's name once in `dim_tracks` rather than repeating it on every measurement
row. "Star" because a diagram of it looks like one.

### Marts — "ready to serve"

Small pre-computed tables, each shaped for one job: `track_card` for the song
page, `artist_rollup` for the artist page, `feature_stats` for percentiles.

The website reads these and does almost no work per request. Computing an
artist's averages while a visitor waits would be slow *and* would give different
answers to different people depending on timing.

## Materialization: how a table gets built

**Materialization** = whether a table is computed fresh each time it's read, or
computed once and stored.

| Strategy | Meaning | Used here for |
|---|---|---|
| **View** | recomputed on every read | nothing — too slow at request time |
| **Full-refresh table** | rebuilt from scratch each run | **all marts** |
| **Incremental** | only new rows appended | staging snapshots |

Marts are deliberately **full-refresh**. It sounds wasteful — why rebuild 1,946
rows to add 3? Two reasons:

1. **Percentiles are relative.** A song's "louder than 80% of your library"
   depends on the whole library. Add songs and *every* percentile shifts.
   Appending three rows would leave 1,946 stale ones.
2. **Full-refresh is idempotent.** Run it twice, same answer. Incremental logic
   has to reason about what's already there, and that's where the bugs live.

The whole rebuild takes ~3 seconds, so correctness is cheap here.

## Idempotency

**Idempotent** = running it twice gives the same result as running it once.

This is treated as a feature, not an accident:

- downloads skip audio already on disk
- extraction skips songs already measured
- mart rebuilds overwrite atomically
- the queue won't double-enqueue a song already queued

Why it matters: things fail halfway. A network drop, a killed process, a reboot.
If a rerun is safe, recovery is just "run it again". If it isn't, recovery
means a human working out precisely how far it got — at 2am, under pressure,
guessing.

## Lineage

**Lineage** is the ability to trace a number backwards to its source.

Here it's unusually literal: any number on the site traces to the song, to the
measurement run, to the exact YouTube video the audio came from, with a
confidence score for whether that video really was that song.

That's why "which video?" is stored at all. Without it, "this song is 128 BPM"
is an assertion. With it, it's a claim you can check.

## Why "Parquet only"

Every table here is **Parquet**, never CSV. Parquet is columnar — it stores each
column together rather than each row together.

- **Types survive.** CSV has no types; every read guesses. A column of song IDs
  starting with digits eventually gets read as a number and mangled.
- **Reading one column is cheap.** Percentiles need `tempo_bpm` from 1,946 rows,
  not all 83 columns.
- **It compresses far better**, because similar values sit adjacent.

→ Next: [Features](features.md)
