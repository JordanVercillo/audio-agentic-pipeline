# How it works

**Start here.** This page explains the whole system in plain language. You do
not need to know this codebase, and you do not need much data-engineering
background — jargon is defined the first time it appears.

Deeper pages are linked as you go. Read this one top to bottom and you will
understand what the project does and roughly how; follow a link only when you
want the detail behind a particular piece.

---

## 1. The one-sentence version

Spotify deleted the API that told apps what a song *sounds* like, so this
project **downloads the audio and measures it itself**, stores those
measurements in a warehouse, and serves them as a website and to AI agents.

---

## 2. The problem it solves

Until early 2026 Spotify offered an endpoint called `/audio-features`. Ask it
about a song and it returned tempo, energy, danceability and so on. Hundreds of
music-analytics projects were built on it.

In February 2026 Spotify removed it for third-party apps. Every project that
**consumed** those numbers stopped working.

This project's answer is to become the **producer** of those numbers instead of
a consumer of them. It gets the audio, runs signal-processing maths over the
waveform, and produces its own measurements. Nobody can switch those off.

---

## 3. The five stages

Everything is a variation on this line:

```
    Spotify          YouTube          your CPU         warehouse        website
   (metadata)   →    (audio)     →    (measure)    →   (store)     →   (serve)
```

| Stage | What happens | Why it's separate |
|---|---|---|
| **1. Metadata** | Ask Spotify what you listen to: song names, artists, albums, IDs | It's the only thing Spotify still gives us |
| **2. Audio** | Find each song on YouTube, download it, convert to MP3 | Spotify won't give us audio; we need the actual sound |
| **3. Measure** | Run [DSP](concepts/features.md) over the waveform → 83 numbers per song | This is the part that replaces the deleted API |
| **4. Store** | Write those numbers into a layered warehouse | So they can be queried, audited and rebuilt |
| **5. Serve** | A website, plus an interface AI agents can query | The numbers are only useful if something reads them |

A **pipeline** is just these stages wired together so they run in order,
repeatedly, without a human retyping anything.

---

## 4. The single most important idea: one ID

Every song has a Spotify ID, e.g. `4cOdK2wGLETKBW3PvgPWqT`. That string is used
as the **only** identifier, everywhere:

- the metadata row is keyed on it
- the audio file on disk is literally named `4cOdK2wGLETKBW3PvgPWqT.mp3`
- the 83 measurements are stored against it
- every table in the warehouse joins on it

It is called the **bridge key** because it is the bridge between systems that
otherwise know nothing about each other.

The rule is absolute: **no second ID system, ever.** If you have two ways of
identifying the same song, sooner or later two parts of the system disagree
about which song they're talking about, and every number downstream is quietly
wrong.

→ [**The bridge key**](concepts/bridge-key.md) — why one ID, and what goes
wrong with two.

---

## 5. What a "measurement" actually is

Stage 3 turns a waveform into numbers. Some are intuitive (tempo in BPM,
loudness). Most are not — they describe the *shape* of the sound's frequency
content, which is how you tell a bright, crisp mix from a warm, muddy one.

There are **83** of them per song. A page on the site shows every single one
with a plain-English description, so nothing is a black box.

An important distinction that trips people up:

- **Measured** — genuinely in physical units (tempo in BPM, loudness in dBFS)
- **Derived** — a rank against the rest of the corpus, 0 to 1 (`energy`,
  `danceability`)

A derived number is *relative*. If new songs arrive, a song's `energy` can
change without a single note of its audio changing. Confusing the two produced
a real bug: an artist's "sound drift over time" was computed on a derived
column, so other artists' songs arriving moved *this* artist's history.

→ [**Features**](concepts/features.md) — the 83 columns, measured vs derived,
and the frozen contract.

---

## 6. Where the data lives (and why in layers)

Data does not go straight from the audio to the website. It moves through
layers, each doing one job:

```
  raw arrival  →  cleaned  →  modelled  →  ready-to-serve
   (staging)     (cleansed)   (modeled)       (marts)
```

- **Staging** — exactly what arrived, untouched. Kept so you can always ask
  "what did we actually receive?"
- **Cleansed** — validated, deduplicated, one row per song.
- **Modeled** — organised for analysis: a central table of facts surrounded by
  descriptive tables (a **star schema**).
- **Marts** — small, pre-computed tables shaped for one job each, so the website
  never does heavy work while someone is waiting.

Why bother? Because when a number looks wrong, you can walk **backwards** layer
by layer and find exactly where it went wrong. That's called **lineage**, and
without layers you don't have it.

→ [**Layers and grain**](concepts/layers-and-grain.md) — what each layer holds,
what "one row means one ___" means, and why marts are rebuilt whole.

---

## 7. What happens when someone logs in

The most common question. Short version:

1. **Instantly** — Spotify is asked for your top songs. Names, artists and
   album art appear right away.
2. **Instantly** — any of your songs already measured (because someone else's
   library included them) are shown with full analysis.
3. **Queued** — songs nobody has measured yet go into a work queue.
4. **~15 seconds each** — a background worker downloads and measures them.
   50 new songs takes roughly 12 minutes.
5. **After that batch** — the pre-computed tables are rebuilt so everyone's
   percentiles reflect the larger corpus.

The site tells you how many of your songs are analyzed rather than quietly
averaging over the ones that happen to be ready. **An honest partial answer
beats a confident wrong one** — that principle shows up everywhere here.

→ [**The login walkthrough**](concepts/login-walkthrough.md) — the same story
with the actual function names and timings.

---

## 8. The machine learning, honestly

There are three unsupervised models. **Unsupervised** means nobody labelled the
right answer; the algorithm finds structure on its own.

1. **Clustering** — group songs that sound alike, and name each group by what
   distinguishes it ("Punchy · Smooth").
2. **Projection** — squash 77 dimensions down to 2 so the collection can be
   drawn as a map.
3. **Similarity** — given a song, find the nearest others.

Two things are worth knowing up front, because they are unusual and deliberate:

**Training and serving are separate.** A new model is trained automatically
whenever the corpus grows, but it is **not** published automatically. Publishing
changes which group a visitor's "home sound" belongs to and what the colours on
the map mean — a human-visible change — so a person approves it. The exception
is a retrain that provably changes nothing perceptible, which promotes itself.

**Both are now measured.** The clustering was tested against shuffled data and
the groups are real, just weak. The similarity model was scored against
playlist co-occurrence — and the interesting part is where it wins: on songs
whose playlist-mates are **obscure**, it beats "just recommend famous tracks"
by 7×; on well-known ones it loses. Since a discovery feature exists precisely
for the obscure case, that split matters more than the average, which hid it.

→ [**Clustering and similarity**](concepts/clustering-and-similarity.md) — how
each works, the train/serve split, and the open questions.

---

## 9. How we know the numbers are right

Three independent checks run over different things:

| Check | What it examines |
|---|---|
| the test suite | the code — does each function do what it claims? |
| the warehouse audit | the data — 26 structural rules over the tables |
| the QA sweep | the live corpus — is every displayed number traceable to real audio? |

Plus rules with teeth: a song whose audio source can't be verified is excluded
from **every** average, not merely hidden. And as of 2026-07-31 the numbers in
the public documents are **generated from the live system**, so a build fails
if a document drifts out of date.

→ [**Trust and data quality**](concepts/trust-and-data-quality.md) — the
checks, the duplicate problem, and why some songs are withheld.

---

## 10. Where to go next

| You want to… | Read |
|---|---|
| run it yourself | [`SELF_HOSTING.md`](SELF_HOSTING.md) |
| demo it to someone | [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) |
| know what's next | [`PHASE2_ROADMAP.md`](PHASE2_ROADMAP.md) |
| see the build story | [`CASE_STUDY.md`](CASE_STUDY.md) |
| understand the architecture in depth | [`../CLAUDE_INSTRUCTIONS.md`](../CLAUDE_INSTRUCTIONS.md) |
| see what's planned and why | [`VISION_SPECS.md`](VISION_SPECS.md) |
| let an AI agent query the warehouse | [`AGENT_ACCESS.md`](AGENT_ACCESS.md) |
| know what was deleted and why | [`DELETIONS.md`](DELETIONS.md) |
| see the quality standards | [`QUALITY_BAR.md`](QUALITY_BAR.md) |

---

*The counts on this page are generated by `scripts/docs_facts.py` and a test
fails if they drift from the live system. If you add a concept page, link it
from the table above or from the section it explains — `test_docs_structure.py`
fails on an unlinked page.*
