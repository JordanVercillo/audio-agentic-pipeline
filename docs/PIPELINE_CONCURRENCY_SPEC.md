# Pipeline concurrency — the F3 invariant spec (P4.6.5 stage ③)

**Designed 2026-07-29 (session 65, Fable-tier lead, from the session-64
dsp-expert design). This spec is the DESIGN for the 3-stage concurrent
extraction pipeline. It is deliberately the LAST slice of Vision F S6, it is
OPTIONAL, and it has an explicit don't-build exit. Stages ① (thread-parallel
DSP for local-audio paths + shared-STFT, measured 2.08× / bit-identical) and
② (instrumentation) are NOT governed by this doc — they are risk-free and
ship first.**

## The decision frame (read before building)

- Throughput and YouTube request rate are welded one-for-one (no sleep
  exists to hide work behind; ~14.8 s/track p50 measured session 64 — a
  number with a shelf life: re-read it from stage-② instrumentation, not
  from this doc). The pipeline is a DIAL, not a free win: at DSP-pool N=3
  the ceiling is ~4.2 s/track — a 3.5× throughput gain at a 3.5×
  request-rate increase, governed by D-64's pre-signed step-down procedure.
- **The don't-build exit:** if, when S6 arrives, (a) the queue is routinely
  drained (no backlog pain), or (b) the failure drills below cannot be made
  to pass cleanly, or (c) D-64's monitor shows the current rate already
  near the 429 threshold — then stage ③ is NOT built, this spec is marked
  "declined, reasoning: …" in VISION_SPECS, and the risk-free 2× stands as
  the ship. Declining is a first-class outcome.
- **Pre-build red-team gate (mandatory):** before implementation, a
  data-platform-expert red-team pass over this spec + the then-current
  code (the journal-#43 precedent found 3 ship-blockers in a Fable-signed
  plan; concurrency earns the same treatment). Its findings amend this doc
  first, code second.

## Architecture (one process, three stages)

```
[acquire thread ×1] claim_next → in-flight twin check → search → gate → download ─┐
                                                    Queue(maxsize=2, "download-ahead")
[dsp pool ×N=2..3]  load_audio → extract_features → make_mel_spectrogram ─────────┐
                                                    Queue(maxsize=4, "persist-in")
[persist thread ×1] cache.upsert → _record_provenance → unlink audio → ledger
[heartbeat thread]  daemon ticker (beats independently of job progress)
```

Rollout: `WORKER_PIPELINE=0` env default reproduces today's serial loop
EXACTLY (and is the CI default); `ACQUIRE_MIN_INTERVAL_S=15` at launch =
rate-neutral day one; step-downs are D-64's owner-visible moves.

## The invariants (each is a named test; all green or no merge)

**I1 — Crash-safety of claims.** A process kill at ANY point leaves every
claimed-but-unpersisted job recoverable: `requeue_stale_running(T)` with
`T ≥ buffer_depth × p95_track_time` re-opens them; no job is lost, none is
double-persisted after resume. *Drill: kill -9 at 6 injection points
(mid-download, in-queue, mid-DSP, mid-upsert, pre-provenance, mid-ledger);
restart; assert queue + features + provenance converge to exactly-once.*

**I2 — Attempts accounting.** A crash with K buffered jobs burns NO
attempt on jobs that never started DSP: graceful shutdown (SIGINT /
`stop_app`) drains the buffer by requeueing un-started jobs with an
attempts decrement; hard crash relies on I1's reclaim, and a preloaded
`MAX_ATTEMPTS-1` job must NOT dead-letter from a crash alone. *Drill: the
killed-worker attempts-burn scenario, asserted on a job one attempt from
dead-letter.*

**I3 — Single-writer store.** Every SQLite write (upsert, provenance, job
state, dead-letter) goes through the persist thread ONLY — asserted
structurally (the DSP pool holds no cache handle), not by convention.
*Drill: a SQL-shape/threading tripwire that fails if any non-persist thread
opens a write session.*

**I4 — Twin race.** Two dedup twins in the same buffer window produce ONE
download + ONE extraction: the twin check runs solely on the serial acquire
thread against (cache ∪ in-flight id set). *Drill: the test_dedup_golden
twin pair enqueued back-to-back; assert one acquisition, second job closes
as twin.*

**I5 — Memory bound.** Peak RSS ≤ budget (~2 GB at N=3; ~0.4–0.7 GB per
concurrent 4-min track measured) enforced by a HARD duration reject in the
DSP path (`MAX_DURATION_SEC` becomes reject-not-warn for pipeline mode) +
an admission check (`Σ queued durations × N` capped). *Drill: a
gate-stubbed DJ-set-length input must be refused at admission, not OOM
three workers.*

**I6 — Failure isolation.** Any per-job exception in any stage routes that
job to `cache.fail(track_id, reason)` via the persist thread with today's
exact wording semantics; the pool and both queues keep serving other jobs.
*Drill: poison one job per stage; assert the other jobs complete and the
poisoned one dead-letters with the right reason.*

**I7 — Heartbeat honesty.** The daemon ticker beats through a 128 s p99 job
(no WORKER_DOWN false alarm) AND stops beating within one interval of true
process death (no false-alive). The single-instance lock semantics
(`another_worker_alive`, `--takeover`) survive unchanged — one process, one
pid. *Drill: both directions asserted with a fake clock.*

**I8 — Rate governance.** The acquire thread's pacer enforces the global
`ACQUIRE_MIN_INTERVAL_S` across search AND download requests (the aggregate
is what YouTube sees); any 429 trips the global circuit-breaker (halt
acquisition, revert one step, ≥1 h cooldown) while DSP/persist drain what's
buffered. *Drill: fake transport returning 429; assert halt + drain +
no further requests.*

**I9 — Disk hygiene.** ≤ (depth + N) transient MP3s exist at any moment;
startup sweeps orphaned `va_audio_*` temp dirs older than 24 h. *Drill:
crash mid-buffer, restart, assert sweep.*

**I10 — Output equivalence.** For the same input set, pipeline mode and
serial mode produce identical persisted rows (features, provenance,
display columns) — order excepted. *Drill: 6-signal synthetic corpus run
both ways, diff the stores.*

## Acceptance (beyond the drills)

- Suite green with `WORKER_PIPELINE=0` (default) and `=1`; the drills run
  in CI on synthetic signals (no network, ground rule 5).
- A real supervised drain at `ACQUIRE_MIN_INTERVAL_S=15` (rate-neutral):
  throughput delta vs the stage-② baseline reported with the DQ counts in
  the post-drain report (D-64: quarantine rates ride along) — measured, not
  assumed.
- Both audits green after; `smoke_public.py` 14/14; app-verify ALL-FALSE.
- Rollback = env var back to 0; no schema changes in this slice.

## Non-goals (recorded so scope can't creep)

Multi-process workers (needs owner-signed D-64 revision + a job-claim
redesign — out of scope for ③); any change to match_gate/acceptance policy;
any DSP numeric change (that's D-67 territory); raising the default rate.
