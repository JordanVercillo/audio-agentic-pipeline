# Features

*What gets measured from the audio, and the difference between a measurement
and a rank.*

← back to [How it works](../HOW_IT_WORKS.md)

---

## What a "feature" is

In data science, a **feature** is one input column describing a thing. Here a
thing is a song, and a feature is one number describing its sound.

The audio is a waveform — hundreds of thousands of amplitude samples per second.
That's far too much to compare or store per song, and almost none of it is
meaningful individually. **Feature extraction** is the step that reduces a
waveform to a small set of numbers that capture something a person would
recognise.

There are **83** per song. A few examples:

| Feature | Plain English |
|---|---|
| `tempo_bpm` | speed, in beats per minute |
| `rms_mean` | average loudness |
| `spectral_centroid_mean` | where the "centre of gravity" of the frequencies sits — high means bright/crisp, low means warm/dark |
| `zcr_mean` | how often the waveform crosses zero — a proxy for noisiness |
| `harmonic_ratio` | how much of the sound is tonal (notes) vs percussive (hits) |
| `mfcc_mean_0..12` | a compact description of the overall timbre — the "colour" of the sound |

MFCCs are the least intuitive and the most useful. Roughly: they describe the
*shape* of the frequency spectrum in a way that tracks how human hearing works.
You cannot read one and picture a sound, but two songs with similar MFCCs
generally do sound alike.

## The critical distinction: measured vs derived

This catches everyone, and it caused a real bug here.

**Measured** features are in physical units and depend only on that song's
audio:
- `tempo_bpm` = 128 BPM
- `loudness_db` = −10.8 dBFS

**Derived** features are a **rank against every other song in the corpus**,
scaled 0–1:
- `energy` = 0.94 means "louder/punchier than 94% of the library"
- `danceability`, `acousticness` — same idea

A derived value is *relative*. Add new songs and a song's `energy` changes
**without a single sample of its audio changing.**

### The bug this caused

An artist page showed "how their sound moved across their catalogue" — computed
on `energy`. Since `energy` is a corpus-relative rank, *other artists'* songs
arriving would move *this* artist's historical drift. The page claimed to state
a fact about the artist and stated a fact about the corpus.

Fixed by switching to `loudness_db`, a genuine measurement in dBFS.

**Rule of thumb:** if a claim is about one song or one artist, it must use a
measured feature. Derived features are only honest in comparisons ("this song
vs your library"), which is exactly what they're for.

## The frozen 77

Of the 83 columns, a specific **77** form the vector used for clustering and
similarity. That set is **frozen**: its contents and order cannot change.

Why so strict? Because a stored model holds centroids — coordinates in that
77-dimensional space. Change which columns are in the vector, or their order,
and every stored coordinate silently refers to different axes. Nothing errors;
the model just starts giving wrong answers.

Changing it is possible but expensive: it requires re-measuring every song in
the corpus and retraining every model. So it is treated as a **contract** —
something other code is entitled to rely on — and a change needs an explicit
owner decision, not a pull request.

## Standardization (z-scoring)

Raw features live on wildly different scales: `tempo_bpm` around 120,
`rms_mean` around 0.2. If you measured distance between songs directly, tempo
would dominate everything simply because its numbers are bigger.

**Z-scoring** fixes this: for each column, subtract the mean and divide by the
standard deviation. Every column ends up centred on 0 with a spread of about 1,
so each contributes comparably.

The mean and standard deviation used are **stored inside the model**. That's
deliberate — it means the numbers used when *serving* are guaranteed to be the
ones fitted during *training*. If serving re-derived them from current data, the
model would drift away from its own training as the corpus grew. That mismatch
has a name — **train/serve skew** — and it's prevented here structurally rather
than by remembering to be careful.

## Transparency

Every one of the 83 features is shown on the site at `/song/{id}/features`, with
its description, its unit, its value and its percentile against the corpus.

That description is read from a data table, not written into the page template.
So retuning a measurement cannot leave the page describing the old behaviour —
the explanation and the number come from the same source.

→ Next: [Clustering and similarity](clustering-and-similarity.md)
