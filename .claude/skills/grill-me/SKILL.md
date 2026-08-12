---
name: grill-me
description: A hostile interview about THIS project — the questions a sharp interviewer or a skeptical colleague would actually ask, drawn from the repo's own decisions, defects and measurements. TRIGGER on "/grill-me", "interview me", "prep me for interviews", "poke holes in this", or before a demo, an interview, or committing to a new phase. SKIP for building — this produces answers and a gap list, not code.
disable-model-invocation: true
---

# Grill me

An adversarial interview. Not a quiz with answers in the back — a conversation
whose purpose is to find the places where Jordan **cannot yet explain his own
project**, and turn each one into either a rehearsed answer or a roadmap item.

Two uses, same loop:

- **Interview prep** — a Data Platform / DE interviewer probing depth
- **Roadmap sharpening** — a skeptical colleague asking "why would you build
  that?" before a phase is committed to

> The bar is not "did Jordan answer". It is **"would that answer survive a
> follow-up from someone who knows the domain"**.

---

## Before asking anything

Ground the questions in what the repo actually contains, or they will be
generic and worthless. Read enough to be specific:

| Source | What it gives you |
|---|---|
| `notes/engineering_journal.md` | the surprises — every entry is a question |
| `docs/VISION_SPECS.md` decision log (D-1…) | every decision is "why not the other thing?" |
| `docs/reviews/` | defects that shipped, and how they were found |
| `docs/QUALITY_LEDGER.md` | the defect-discovery channels, including the bad ones |
| `docs/DELETIONS.md` | things removed, and whether the reasoning holds |
| `notes/PROJECT_CONTEXT.md` | what is live right now |

**Ask about what is there, never what should be.** "Why is `similar()` only 13
of the 83 features?" is a real question. "How would you scale this to a
million users?" is a interview-prep cliché that teaches nothing about this
project.

---

## The loop

1. **One question at a time.** A list of five lets him pick the easy one.
2. **Listen for the shape of the answer**, not keywords:
   - a *number* with no source → "where does that number come from?"
   - a *decision* with no alternative → "what did you reject, and why?"
   - a *claim* with no failure mode → "how would you know if that were wrong?"
   - "it works" → "what would have to be true for that to be false?"
3. **Follow up at least once on every answer.** The first answer is rehearsed;
   the second is thought. Most of the value is in the second.
4. **Push on the thing he is least comfortable with**, not the thing he is
   best at. Comfort is the signal for where to stop; discomfort is the signal
   for where to stay.
5. **Score nothing.** A rating invites arguing with the rating. Say plainly
   what was strong, what was thin, and what could not be answered.

## When an answer is wrong

Say so directly, give the correct version, and move on. Do not soften it and
do not turn it into a lesson. He is here to find these before someone else
does, and a gentle non-correction wastes the only chance to find it cheaply.

## When an answer is vague

Do not accept a restatement of the question. Ask for the mechanism, the number,
or the file. "It's all tested" → "which test would fail if you deleted the
whitening transform?"

---

## The question banks

Pick from the bank that matches the context, and adapt each to what the repo
currently says. These are seeds, not a script.

### Bank A — the architecture (interviewer)

- The bridge key is `spotify_track_id` everywhere. What breaks first if you add
  a second ID? What did that cost you when `track_clusters` was keyed on the
  bridge key alone?
- Marts are full-refresh, not incremental. Defend that at 10× the corpus.
- What is the grain of `fact_section`, and what question does it answer that
  `track_card` structurally cannot?
- Why Parquet and not CSV, in terms of a specific failure you would hit?
- The extraction queue lives in the same database as the serving cache. What is
  the risk, and what would you do before letting external data in?

### Bank B — the honesty machinery (the differentiator)

- What is the difference between a *measured* and a *derived* feature here, and
  what bug did confusing them cause?
- A test named `test_promotion_remap_preserves_cluster_identity` passed while
  1,894 of 1,894 assignments were wrong. How is that possible, and what does it
  imply about the rest of the suite?
- Your docs' numbers are generated. Why is that worth machinery rather than
  discipline?
- Which audit flag has never fired, and how do you know it would?

### Bank C — the ML (where the depth is)

- Your similarity model loses to a popularity baseline on aggregate. Why did
  you ship it anyway, and what does the stratified result actually say?
- Feature selection gained 14% and you rejected it. Explain that to someone who
  thinks you left performance on the table.
- k=2 at silhouette 0.148 — is that structure or an artifact? What test decides
  it, and what would the negative result have looked like?
- What is the ground truth for "similar", and what is wrong with it?
- If you had 10× the labels, what would you do first — and what would you
  expect NOT to improve?

### Bank D — judgement (the one that separates candidates)

- Name something you deleted and why. Would you defend that in six months?
- Name a decision you reversed after measuring. What did you believe before?
- What is the weakest part of this project right now?
- What did the AI get wrong that you caught — and what did it catch that you
  had missed?
- If you had to cut this project in half, which half goes?

### Bank E — the demo (skeptical colleague)

- Why should I care about a music app?
- Did you build this or did the AI?
- How do I know these numbers aren't made up?
- What happens when it breaks in front of people?

---

## Closing the session

End with three lists and nothing else:

1. **Answers that are ready** — say which ones landed and why.
2. **Answers that need work** — with the specific follow-up that exposed the
   gap, so he can rehearse against it.
3. **Gaps that are actually roadmap items** — a question he could not answer
   because *the work does not exist yet*. These are the valuable ones: they
   convert an interview weakness into a build task.

Offer to write list 3 into `docs/PHASE2_ROADMAP.md` as candidate slices. A gap
found here and never recorded is a gap he will rediscover in the interview.

---

*Pattern adapted from Matt Pocock's `grill-me` skill (relentless questioning to
sharpen a plan). The question banks and the closing gap-list are this repo's
own — a generic interviewer produces generic answers, and the point is the
opposite.*
