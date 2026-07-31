# Director review — Vision F S1–S6 (sessions 68–71)

**Run 2026-07-31.** Scope `e0cef8d..6d256ae`. Method: two independent
adversarial red-teams (data-platform, webapp) over code the author had already
self-reviewed and shipped, plus a measurement pass and a standards pass.

## Verdict

The arc delivered real capability — cluster coverage 36.7% → 100%, ISRC 0% →
100%, `/artists` 15 → 902, 83 features exposed, two surfaces bounded instead of
linear. **And it shipped three blockers, one of which was corrupting live
serving data for 24 hours while every gate read green.**

That combination is the finding. Not "we were sloppy" — the session ran tests,
audits, smoke and browser checks at every slice. The gates were real; they were
pointed at the wrong things.

## What broke

| # | Defect | Found by | Pre-existing? | Live impact |
|---|---|---|---|---|
| **B1** | `promote_model` remapped id-KEYED structures and left `centroids`, which is id-INDEXED. Live model 13: **1,894 of 1,894 stored assignments disagreed with its own nearest-centroid rule.** | red-team | **No — shipped this session** | 24 h of wrong cluster ids for any track the training run missed; wrong legend colour + blurb on those |
| **B2** | Retrain loop unbounded: `freshness()` measures the SERVED model, a non-stable retrain isn't promoted, so it retrains **every poll forever** (~3 min CPU + ~1,900 rows per cycle) | red-team | No | Latent — needed a rename-producing refit to trigger |
| **B3** | 826 of 891 artist links on the new **public** page were dead, under a caption asserting they worked | red-team | No | Every anonymous visitor to `/artists`, ~24 h |
| B4 | `track_clusters` keyed on the bridge key alone — every retrain silently hollowed out its predecessor (700 → 4 rows) | building on top | **Yes — years old** | Fixed in S2 |
| B5 | `match_identity` un-scaled L2-normalised centroids → noise (−0.73 where truth is −0.97) | building on top | No (same session) | Would have refused every automatable promotion |
| B6 | "Muse" rendered as two cards — the guard against a silent *merge* produced a visible *split* | **using the live product** | No | Cosmetic, caught pre-commit |
| B7 | `/analytics` caption over-counted the map by 4 (in-memory assignments have no coordinates) | using the live product | No | Caught pre-commit |
| B8 | `rms_mean` was "Loudness" on one page and "Energy" on another, colliding with a *different* derived `energy` | consolidation (S4a) | **Yes** | Live for months |
| B9 | ISRC absent from the serving cache entirely (0 of 2,357) while the plan said 5.6% | measuring before building | **Yes** | Would have made Phase 5 unmeasurable |

## Discovery channels — the number that predicts escapes

| channel | count | what it says |
|---|---|---|
| **D-red** (red-team) | **3 blockers** | The only channel that caught the serving-data corruption |
| D-build (building on top) | 3 | Pre-existing defects surface when a new feature reaches them |
| D-use (using the product) | 2 | Both caught pre-commit; cheap and effective |
| D-self (author's own new tests) | 1 | **Low. This is the finding.** |
| D-matrix (standing gates) | 3 | route matrix ×2, `GOLD_SCHEMA_SHRINK` ×1 — all worked as designed |
| D-post (after shipping) | 0 known | but B1/B3 were live for 24 h before a red-team looked |

**Self-catch ratio ≈ 33%.** Two-thirds of defects were found by something other
than the author's own tests. For a solo project shipping to production daily
that is the number to move.

## Why the gates missed B1 specifically

The shipped test was named `test_promotion_remap_preserves_cluster_identity`
and asserted `promoted.labels["0"] == old_label_of_0`. "Identity" has two
halves — the words a visitor reads *and* the geometry that assigns tracks. The
test checked the half its author had been thinking about. Both audits, 905
tests and a browser check agreed with it, because none of them ever asked the
model whether it agreed with itself.

> A test named for an invariant is not the same as a test of that invariant.

## What improved efficiency (measured, not asserted)

| change | before | after | measured how |
|---|---|---|---|
| `/analytics` + `/artist` projections | 280 ms / 6.5 MB | 54 ms / 0.6 MB | live corpus, warm best-of-3 |
| Post-drain chain | 5.31 s (2.73 ms/track) | 3.81 s (1.96 ms/track) | live, and debounced so it no longer runs per poll |
| Chain headroom | breaks ~11k tracks | ~15.3k + debounce | derived from the per-track cost |
| `/recommend` page | 166 KB, 1,895 options | 18 KB, 103 options | live fetch |
| `/explore` scatter | 153 KB | 72 KB, bounded | live fetch |
| Cluster coverage | 36.7% | 100% | audit |
| ISRC coverage | 0% | 100% (2,356/2,357) | backfill, 47 calls |
| artist_meta | 73 rows, 38 genres | 900 rows, 468 genres | backfill, 17 calls |
| `similar()` (earlier arc) | 176 ms | 7.7 ms | perf pass |

## Code-to-test ratio per slice

`S1a 51/112 · S2a 263/235 · S2b 244/105 · S3a 90/46 · S3b 170/31 · S4a 115/81 ·
S4b 412/190 · S5a 208/126 · S5b 121/69 · S5c 65/32 · S6 43/42`

The two lowest-ratio slices (S3b 0.18, S2b 0.43) are where B1 and B9 lived.
Not proof, but worth watching.

## Actions taken during this review

- ✅ B1 fixed + **live model 13 repaired** (backup first; 0% → 100% agreement)
- ✅ B2 fixed (retrain skipped when a candidate exists) + `model_id` indexed
- ✅ B3 fixed both ways — linkability derived from what resolves, *and*
  `backfill_artist_meta.py` made the data real (891/902 live-verified)
- ✅ `promote_model` refuses to re-apply a map (rollback corruption)
- ✅ `docs/QUALITY_BAR.md` (Q1–Q12) + `src/store/test_audit_tripwires.py`
- ✅ Coverage tooling added; runs in CI because Windows can't (numpy/tracer clash)

## Carried findings — all 12 closed, same day

Every row below was fixed, with the measurement or the test that proves it.

| from | item | closed by |
|---|---|---|
| platform | `_backfill_promoted_at` ran per `FeatureCache()` | one-shot marker in `schema_migrations`; the shipped test hid this by simulating a "legacy" DB *after* the migration had run, so it was split into the two cases it conflated |
| platform | `_migrate_track_cluster_key` SQLite-only | dialect guard + drops a stranded `_pkfix` first (stale rows would have won under `INSERT OR IGNORE`) |
| platform | proposed `CLUSTER_ASSIGNMENT_DESYNC` | shipped and **proven to fire both ways** (clean 1.0 / id-space scramble 0.0); live corpus reads 95.8%, FALSE. 26 flags now |
| platform | 3 tests that don't test their name | all three rewritten; each now fails for the reason it is named |
| platform | `build_raw_feature_marts` re-reads the corpus | one read for the whole chain: **2 scans → 1, 0.20 s of 3.24 s**, linear in corpus size |
| webapp | `_percentile` quartile interpolation | deciles stored; **mean error 4.69 → 0.72, max 22 → 9.2, pull-toward-ordinary −4.25 → −0.18** |
| webapp | `artist_drift` on a corpus rank | now `loudness_db` (tier "measured", dBFS) |
| webapp | `artist_drift` reports `last − first` | least-squares slope per year over every point; up-then-down is named an `arc` |
| webapp | `/artist/{id}` fuses what the index splits | name-matching only where a name cannot contradict an id; the caption says how many it took |
| webapp | pager drops `genre`/`f`; `total_cards` empty; genre caption miscounts | all three fixed and live-verified (`/artists?genre=uk+garage&per=50&f=brightness` keeps both params across pages) |
| webapp | tautological assertions | `assert … or True` and a ±5 escape hatch on an exact equality replaced with real claims — both pass, so the code was right and the tests weren't looking |
| both | no 375/768/1280 pass | done on `/artists`, `/song/{id}/features` (83 rows) and `/artist/{id}`: **zero page overflow at all three**; wide tables scroll inside `.lib-wrap`, the body never does |

### One new defect, found the same way the review's worst ones were

Moving `artist_drift` off `energy` pointed it at a column `artist_albums`
does not compute, and **the entire drift block silently stopped rendering**.
929 tests stayed green — every one of them passed its own column explicitly.
Found by loading the page (D-use). Fixed by pointing at `loudness_db`, which
the album builder does produce, plus the assertion that would have caught it:
the default column must be in `_ALBUM_FEATURES`. Rendering it then printed the
raw column name, because the P4.7.0 registry had never been told about
`loudness_db` — the exact failure that registry exists to prevent, arriving
from a surface it hadn't heard of. Registered, and gated by a test.

> Two of the three defects in this fix-up round came from *using the page*.
> That is the same finding the review opened with, arriving again, one level up.

## The lesson worth keeping

Every gate this project owns worked exactly as designed and none of them was
pointed at the invariant that broke. The cheapest thing that found real defects
was **someone other than the author looking** — three blockers, none of which
any amount of self-review had surfaced in a full day of work.
