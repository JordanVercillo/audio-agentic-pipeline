# Demo script

*For showing this to colleagues. Print it, or keep it on a second screen.*

The single most likely way this goes wrong is **not** a wrong number — it's a
sleeping laptop, a stale process, or fifty seconds of silence while a language
model warms up in front of eight people. The checklist matters more than any
feature on the site.

---

## T-30 minutes — the checklist

Run these in order. Each one has a specific failure it catches.

```bash
deploy_app.bat
```

Pulls, syncs dependencies if the lock moved, restarts, and verifies. Watch the
`Code` line at the end — it must say **`up to date`**. `STALE` means the running
process is serving older code than the repo; `UNKNOWN` means something started
it outside this script.

```bash
uv run .claude/skills/app-verify/verify_app.py
```

Every flag must be **false**. `WEBAPP_DOWN`, `PUBLIC_DOWN` and `TUNNEL_DOWN` are
the three that end a demo before it starts.

Then, by hand:

| Check | Why |
|---|---|
| Open **https://vercilloanalytics.com** on your **phone, on cell data** | Your laptop reaching `localhost` proves nothing about the tunnel. This is the only test of the path your audience will use. |
| Click **Chat** once and ask anything | The first LLM call loads the model — that's the fifty seconds. Spend it now, not on stage. |
| Confirm **`/eras`** draws two charts | It reads a mart. If the marts were never rebuilt it shows an empty state instead. |
| Disable sleep on the machine | On-demand hosting means the laptop *is* the server. |

**If you have a week's notice:** add one or two colleagues to the Spotify app's
user list (Spotify dashboard → your app → Users). Have them log in *once*, days
early, so the extraction queue drains before the room sees it. Someone watching
**their own** library is the difference between "neat" and "you built that?" —
it is the highest-impact thing on this page and it is almost no work.

---

## The 7-minute path

Numbers move as the corpus grows. Read them off the screen rather than from
this page — the site derives them, this document doesn't.

### 1 · Landing (30s)

> "Spotify deleted the API that told apps what a song *sounds* like. Every
> project built on it broke. So this one downloads the audio and measures it
> itself."

Point at the counter line. **Do not offer to log them in** — say "there's a
five-seat pilot, so we'll use the guest view, which is the real thing read-only."
Framing it up front makes it a design choice instead of a limitation they
discover.

Click **Explore the live demo**.

### 2 · Dashboard (60s)

Their first sight of real output. Let them read it. The one thing to say:

> "This is a real listening history — top tracks over three time windows — and
> every acoustic number on this page was computed here, from audio, not fetched."

### 3 · One song, deep (90s) — **the proof**

Go to a song, then **All features**. Suggested:
`/song/4qW3BbQAwZsrnu8a3ZRdyT/features`

> "Eighty-three measurements per track. Each one has a plain-English description
> and where this song sits against the rest of the corpus. This is the part that
> replaces the deleted API."

Then scroll to the **provenance** link and open it:

> "And every number traces back to the exact recording it was measured from,
> with a confidence score. If the match were wrong, the numbers would be real
> measurements of the wrong song — so it's checkable."

That pairing — *83 numbers* then *here's the audio they came from* — is the
strongest 30 seconds on the site.

### 4 · `/eras` (90s) — **the moment they lean in**

> "Once you're measuring the audio yourself, you can ask things the metadata
> can't answer."

Let the two charts speak, then:

> "Records got about **four decibels louder** from the seventies to the
> twenties, and songs got about **a minute shorter**. Those are both documented
> industry phenomena — the loudness war, and the streaming squeeze. I didn't go
> looking for them. They fell out of a column that was already in the database."

Then read the caveat box out loud. Saying *"this is my library, not a survey of
music"* before anyone asks is what makes the rest of it credible.

### 5 · `/artists` → one artist (60s)

Search, open an artist. Suggested: `/artist/12Chz98pHFMPJEknJQMWvI` (Muse — 12
dated releases, a real arc).

> "Discography, acoustic profile against the corpus, and how their sound moved
> across their own catalogue — a least-squares trend, not a line from the first
> record to the last, so an artist who went loud and came back doesn't read as
> 'got louder'."

### 6 · `/chat` (60s)

Ask something concrete: **"what are my most energetic tracks?"**

> "This is a local model answering over the warehouse — no data leaves the
> machine. It's grounded: it can only answer from what's actually in the tables."

If it's slow or the answer is thin, move on — it is the least reliable stop and
the demo does not depend on it.

### 7 · Close (60s)

The part that lands with colleagues, because it's the part about *how*:

> "Nearly all of this was built with an AI agent, but the interesting bit isn't
> that it wrote code — it's the harness around it. There's a session loop that
> reloads project memory at the start and writes decisions back at the end. The
> docs regenerate their own numbers and the build fails if they drift. There's a
> review process that red-teams my own work — it found three real bugs in one
> day's output that every test had passed."

Offer [`docs/HOW_IT_WORKS.md`](HOW_IT_WORKS.md) — or the `/how-it-works` page —
as the follow-up link.

---

## If something breaks

| Symptom | Say this, do this |
|---|---|
| Site returns 502 | *"The host is on-demand — it's my machine."* Run `deploy_app.bat`. The Cloudflare worker already serves an honest "demo offline" page, so it doesn't look broken. |
| Chat hangs | *"Local model, cold start."* Move to the next stop and come back. Never wait in silence. |
| A number looks wrong | Say so. **Every surface here states what it can't support** — the withheld tracks, the remaster caveat, the estimator honesty. Being the person who points at their own limitation is worth more than the number. |
| Asked "can I log in?" | *"Five-seat pilot — Spotify gates it. I can add you and you'd get your own full analysis."* Then actually do it. |

---

## Questions you'll get

**"How long did this take?"** — Weeks of evenings. The useful answer is the
harness: session memory, an engineering journal of surprises, and a review
process, which is why it kept moving instead of collapsing under its own size.

**"Did AI write all of it?"** — Most of the code. The judgement calls are
logged as numbered decisions in the spec — what to build, what to refuse, what
to delete. `docs/DELETIONS.md` is a good one to show: an entire vector-search
stack removed because nothing imported it.

**"Is it accurate?"** — Some of it is measured and some is estimated, and the
site says which. The models have an offline evaluation with baselines; one
change shipped because it beat a held-out test, and a feature-selection change
was **rejected** because it gained 14% on the data that chose it and lost 11% on
data it had never seen.

**"What would you do next?"** — More curated playlists. The evaluation is
label-limited, not model-limited, and that was measured rather than guessed.
