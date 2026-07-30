# The corpus-migration playbook (F2, 2026-07-29)

**The reusable discipline for ANY corpus-scale data-mutating batch** — a
Tier-B re-extraction (D-67), a future backfill that rewrites stored values, a
quarantine sweep, a dedup re-key. Distilled from the operations that earned
it: the D-52 re-extraction program (journal #43's red-team, #45's mid-flight
traps, #46's resume-marker lesson), the wrong-song and wrong-take quarantines
(#46, session-60 DQ), and the QA2 gate inversion (#48). Every future
migration follows this template instead of re-deriving it under pressure;
deviations are recorded in the migration's plan doc, not improvised.

A migration is **irreversible in aggregate** even when each row-write looks
reversible — the pre-state is only fully recoverable from the backup taken at
step 1. Treat every one as an owner-signed operation.

## The invariant list (all eight hold, or the migration does not launch)

1. **Owner-signed plan.** One page: scope (which rows, by what selector),
   the mutation, the cost estimate (time + API/download budget), the abort
   criteria, and the rollback story. The owner signs BEFORE the first write.
   (Precedent: the D-52 batch plan, Fable-signed; the model tier that signs
   is set by the routing table — judgment lies in the plan, not the loop.)
2. **Backup first, verified.** `backup_cache.py` (or the plane's equivalent)
   completes and its output file's existence + size are checked by the
   runner itself before row one. A backup that wasn't verified is a wish.
3. **Dry-run first, and the dry-run is the real selector.** The dry run
   executes the exact selection + gate logic against live data and prints
   the full worklist (or its distribution) WITHOUT writing. A human reads
   it. The wrong-take quarantine's precision fix (38→34 after reading all
   38 — journal's "precision fixed BEFORE executing") happened here; budget
   for it. If dry-run and real run can diverge (different search paths,
   different populations), that divergence IS a bug to fix first (journal
   #49: the runner and batch downloader searched different credit strings).
4. **A durable, resumable ledger** — one row per target, written
   tmp+`os.replace`, holding status + evidence per row. The run can die at
   any row and resume without re-doing or double-doing work. **A resume
   marker is a completion claim, not a quality claim** (journal #46): the
   ledger records WHAT was done; whether it was done RIGHT is the
   verification pass's job, never inferred from the marker.
5. **Atomic swap on success only.** The mutation lands via the plane's
   atomic path (per-pid tmp + `os.replace`; `replace_display=True` semantics
   where old display columns must not survive a re-acquisition — the F2
   preserve-on-None trap). A failed row leaves the OLD state intact and the
   ledger says so; partial writes are unrepresentable.
6. **Spot-check cadence, scheduled in the plan.** A human (or a
   verification script with human review) inspects a sample of completed
   rows at ~5%, ~25%, and end-of-run. The D-52 run's two traps (DJ-set,
   wrong-song) were caught at the 5%-equivalent mark because someone
   LOOKED; the cadence is what makes "launched detached" safe. Each
   checkpoint has the authority to pause the run.
7. **Abort criteria are numbers, written in advance.** e.g. ">2% of
   completed rows fail the post-write verification", "any systematic
   wrong-class detected in a spot-check", "resource use exceeds X". An
   abort triggers: stop, keep the ledger, quarantine-don't-delete anything
   suspect (the owner decides deletions — the D-52 flag-never-auto-dead-letter
   rule), write up what happened.
8. **Post-run: verify → reconcile → re-derive → audit.** The verification
   pass re-checks completed rows against the plan's quality gate (not the
   resume marker); provenance/lineage reconciles (provenance-wins where the
   ledger and provenance disagree); every derived plane rebuilds (marts →
   gold → clusters if populations moved → descriptions); BOTH audits run
   and come back clean, including any migration-specific flag (e.g.
   `MIXED_FEATURE_VERSION` red-by-design mid-run must clear or be
   explained). The wrap records before/after corpus numbers.

## The run-shape checklist (mechanics that have already bitten)

- Scratch space is its OWN directory — never a dir holding pre-existing
  assets the cleanup step would destroy (the F3 `data/raw_audio` blocker).
- Concurrent mart rebuilds: per-pid tmp names (the F1 `_write_atomic` fix).
- The live worker keeps running unless the plan says otherwise — state
  explicitly whether the migration and the worker may write the same rows,
  and if so, who wins (usually: pause the worker, or scope-disjoint).
- Rate-limited externals: the migration inherits the same pacer/circuit-
  breaker rules as production (D-64 for YouTube, D-72's 1.1 s for MB);
  a migration is never an excuse to raise a request rate.
- Version stamps: rows written by the migration carry the new
  FEATURE_VERSION / MATCHER_VERSION / migration id so a mixed corpus is
  visible (D-67), and the relevant `*_VERSION_SKEW` audit message names the
  in-progress ledger while the run is live.
- Cost math in the plan uses MEASURED per-row costs (p50 from
  instrumentation), never folklore numbers (journal #61).

## What this playbook does NOT license

Deletions (owner-only, always via quarantine-first), gate-loosening to make
a migration converge (fix the gate or shrink the scope), synthetic filler
rows (REAL-data rule), or "quick manual fixes" outside the ledger (untracked
mutations are how two write paths diverge — journal #35).
