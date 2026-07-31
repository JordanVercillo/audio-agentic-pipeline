# Trust and data quality

*How the project knows its numbers are real, and what it does when they aren't.*

← back to [How it works](../HOW_IT_WORKS.md)

---

## The core problem

The audio doesn't come from Spotify — it comes from YouTube, found by searching
for the song's name and artist. That search can be **wrong**: a live version, a
cover, a remix, a DJ set, a completely different song with a similar title.

If the wrong audio is measured, the numbers are real measurements *of the wrong
thing* — which is worse than missing data, because nothing looks broken.

Most of what follows exists to handle that.

## Provenance: every number traces to its source

For each song the project records which YouTube video the audio came from: URL,
video ID, title, channel, duration, the search query used, and a **match
confidence** score.

So any number on the site can be traced, in one click, to the exact recording it
was measured from. Without this, "this song is 128 BPM" is an assertion. With
it, it's checkable.

## Withholding: excluded from *every* average

If a song's source can't be verified, it is not merely hidden from view — it is
removed from **every** calculation: the percentiles, the clusters, the corpus
averages, the answers the AI agent gives.

This distinction matters more than it sounds. Hiding a row from a page while
still counting it in the averages is the most common way a dashboard tells a
confident lie. Here one shared filter governs display *and* aggregation, so they
cannot diverge.

The site states how many songs are withheld rather than quietly averaging over
the rest.

## The gate before download

Before spending ~15 seconds downloading and measuring, a candidate video is
checked: does the title actually correspond to the song? Is the duration close
to Spotify's? Is it obviously a DJ mix or a full album upload?

Rejecting early is cheaper than measuring the wrong audio and detecting it
later — and *far* cheaper than not detecting it.

## Duplicates

Spotify routinely lists the same recording under several IDs — single, album
cut, remaster, regional release.

Handled by flagging, never deleting: one ID is **canonical**, the others point
at it. Aggregates count the canonical one only, so one recording never votes
twice, but each ID keeps a working page.

→ Detail: [`../DEDUP_QA_SPEC.md`](../DEDUP_QA_SPEC.md)

## The three checks

Independent, and pointed at different things — a system can pass any one and
still be wrong:

| Check | Examines | Asks |
|---|---|---|
| **Test suite** | the code | does each function do what it claims? |
| **Warehouse audit** | the data structure | 26 rules over the tables |
| **QA sweep** | the live corpus | is every displayed number traceable to real audio? |

The tests use **synthetic audio** generated in code. They never need the
internet, credentials, or downloaded music — so anyone can clone the repo and
run them.

### A flag nobody has seen fire is a comment

Every one of the 26 audit rules must be **proven** to fire: a test builds
deliberately broken data and confirms the flag goes true, *and* confirms it
stays false on clean data. A rule stuck on is as useless as one stuck off — it
just fails loudly instead of silently.

## Lessons written into the checks

Each of these came from a real failure:

**A test named for a rule isn't a test of that rule.** A test called
"promotion preserves cluster identity" checked that the *labels* survived. It
did not check that the *geometry* did. Identity had two halves; the test checked
the one its author was thinking about, and a serious bug lived under a green
tick for a day.

**Derive, don't restate.** Any number shown to a person should be computed from
the same source as the thing it describes. Retyping it creates a copy that rots.
The public documents carried ten wrong numbers this way — a test count of 579
when there were 930 — none of them wrong when written. They now come from a
generator, and a build fails if a document drifts.

**A fix that's a command, not a trigger, regresses on schedule.** "Remember to
update the numbers" is not a fix. "The build fails if the numbers are stale" is.

**Measure before claiming.** Every "this is faster/better" needs the command
that produced both the before and the after.

## What is deliberately *not* claimed

Being explicit about limits is part of the same discipline:

- The models have **no evaluation** yet (see
  [clustering and similarity](clustering-and-similarity.md))
- **Release dates are Spotify's**, so a remaster reads as its reissue year, not
  when the music was recorded. Stated in the UI rather than silently corrected.
- **Genre data is sparse** — Spotify's own limitation. The pages say so instead
  of implying full coverage.
- Some measurements are **estimates** (tempo and key are inferred from audio,
  not read from a score) and are labelled as such.

→ Back to [How it works](../HOW_IT_WORKS.md)
