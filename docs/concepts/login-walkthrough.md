# What happens when someone logs in

*The same story as [How it works §7](../HOW_IT_WORKS.md), with the real function
names and timings.*

← back to [How it works](../HOW_IT_WORKS.md)

---

## The shape of it

Two paths run at different speeds. The **request path** is synchronous and must
finish in milliseconds. The **worker path** is asynchronous and takes minutes.
Everything below hangs off that split.

## Step 1 — sign in (no password here, ever)

Login uses **PKCE**, a flow where the app never holds a secret. There is no
client secret anywhere in this project — not in the code, not in the
environment, not on the server. Each visitor authorises Spotify directly and the
app receives a token scoped to them.

## Step 2 — fetch (synchronous, ~1 second)

Spotify is asked for your top tracks over three **listening windows** — last 4
weeks, last 6 months, all time — 50 each. So ≤150 rows arrive, heavily
overlapping, since your all-time favourites are usually recent ones too.

## Step 3 — two writes, in a specific order

```python
cache.remember_meta(meta_items)   # upsert metadata
cache.enqueue(all_ids)            # queue anything unmeasured
dupes = cache.duplicate_flags()   # THEN resolve duplicates
```

**`remember_meta`** is an **upsert** — insert if new, update if present, and
*preserve-if-absent*: a field Spotify didn't return this time never overwrites a
good stored value with null. Logging in twice changes nothing the second time.

**`enqueue`** writes into `extraction_jobs`, a **work table**:

| Situation | What happens |
|---|---|
| never seen | queued, `attempts=0` |
| already queued or running | left alone — no double work |
| failed, under the retry cap | re-queued, **keeping** its attempt count |
| failed, at the cap | **dead-lettered** — never retried again |

Preserving the attempt count matters: resetting it would let a permanently
broken song retry forever, hammering the source.

**Order is load-bearing.** Duplicate resolution runs *after* enqueue, because
the intake guard is what flags a brand-new duplicate. Every derived value is
then computed from canonical IDs, so one recording never votes twice.

## Step 4 — render (still synchronous)

Your dashboard draws from what already exists:

| Your song is… | Served by |
|---|---|
| already measured, already clustered | its stored row |
| already measured, newer than the last training run | **scored live** and not saved |
| not yet measured | listed, but excluded from every average |

That middle row is **online inference against an offline-trained model** — and
it deliberately does not persist:

> `# F14: a GET must not WRITE.`

It used to. Merely *rendering* the analytics page wrote cluster assignments —
and before a coverage fix, wrote them from a model fitted on 37% of the corpus.
Now the read path computes for display and discards; only the worker makes an
assignment durable.

Also: **there is no per-user model.** One global model over the shared corpus.
Your login trains nothing.

## Step 5 — the worker (asynchronous, ~15 s per song)

A background worker polls every 30 seconds and drains the queue. Per song,
median **14.7 s**:

```
find on YouTube (1.2s) → download + convert (~2-3s) → measure (8-12s) → save
```

Roughly three-quarters of that is local CPU doing signal processing, not network
time. **50 new songs ≈ 12 minutes.**

## Step 6 — the post-drain chain (~3 seconds)

When the queue empties, one idempotent chain runs:

1. refresh duplicate flags — so everything downstream sees the current canonical set
2. recompute the perceptual plane — **percentiles recalibrate against the grown corpus**
3. rewrite all marts — full refresh, atomic
4. train a candidate cluster model

Step 2 is why marts are rebuilt whole rather than appended: adding songs shifts
*everyone's* percentiles, so patching in a few rows would leave the rest stale.

The chain is **debounced** — it fires when the queue goes idle or enough new
songs accumulate, not on every poll, because it costs time proportional to the
whole corpus.

## Step 7 — publishing is gated

Step 4 trained a model. It is **not** automatically served.

- **Provably identical in effect** (same k, matching centroids, unchanged
  labels) → promotes itself, because nothing perceptible moved.
- **Anything else** → stays a candidate, the audit raises
  `CLUSTER_PROMOTION_PENDING`, and a human approves it.

→ Detail: [Clustering and similarity](clustering-and-similarity.md)

## The lag budget

| What | When it's ready |
|---|---|
| song appears in your library | immediately |
| cluster shown on the map | immediately (computed live, not saved) |
| acoustic measurements | ~30 s queue wait + ~15 s per song |
| durable cluster assignment | after the next post-drain training |
| percentiles recalibrated | after the next post-drain chain |

Throughout, the page reports **how many** of your songs are analyzed rather than
silently averaging over whichever happen to be ready.

→ Back to [How it works](../HOW_IT_WORKS.md)
