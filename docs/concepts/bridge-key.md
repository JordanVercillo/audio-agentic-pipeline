# The bridge key

*One identifier, everywhere. The rule the whole project rests on.*

← back to [How it works](../HOW_IT_WORKS.md)

---

## What it is

Every song this project touches is identified by its **Spotify track ID** — a
22-character string like `4cOdK2wGLETKBW3PvgPWqT`. In code it is always the
column `spotify_track_id`.

It's called the *bridge key* because it bridges systems that share nothing else:

| System | How the song appears |
|---|---|
| Spotify's API | `spotify_track_id` |
| The audio file on disk | `4cOdK2wGLETKBW3PvgPWqT.mp3` |
| The measurements table | row keyed on `spotify_track_id` |
| Every warehouse table | joins on `spotify_track_id` |
| The provenance record | which YouTube video, keyed on `spotify_track_id` |

Spotify, YouTube and a `.mp3` file have no concept of each other. The bridge key
is the only thing that says "this file is that song's audio".

## The jargon

- A **key** is the column that identifies a row.
- A **primary key** uniquely identifies one row in a table — no duplicates, no
  nulls.
- A **foreign key** is that same value appearing in another table, pointing back.
- A **join** is combining two tables by matching on the key.

If the key is reliable, joins are trivially correct. If it isn't, every number
computed from a join is suspect and you usually can't tell which ones.

## The rule

> **Never introduce a second ID system.**

Not a "internal track number", not a hash of the filename, not a
`(artist, title)` pair. One key.

## Why — the failure it prevents

Suppose you added an internal `track_num` alongside the Spotify ID. Now
something has to keep the two in sync. It will drift — a re-import renumbers,
a partial load skips a row, two code paths generate them differently. Then:

- the features table says track 41 is 128 BPM
- the metadata table says track 41 is a different song
- every chart is confidently wrong, and **nothing raises an error**

That's the worst class of data bug: silent, plausible, and invisible until
someone happens to notice one song's numbers look odd.

## The complication: two IDs, one recording

The rule is "one ID per song". Reality is messier — Spotify frequently has the
**same recording** under multiple IDs: the single, the album cut, the remaster,
the regional release. Same audio, different `spotify_track_id`.

This is *not* solved by inventing a second key. It's solved by picking one ID
as **canonical** and flagging the rest as its duplicates:

- Both IDs keep their own row — nothing is deleted, the bridge key is untouched
- One is marked `duplicate_of` the other
- Aggregates count the canonical one only, so **one recording never votes twice**
- The duplicate's own page still works if you navigate to it

Where this bites: without it, a song's "most similar track" is literally itself
under another ID. So flagged duplicates are removed from the *candidate* pool
for similarity while remaining valid as the *query*.

→ Detail: [`../DEDUP_QA_SPEC.md`](../DEDUP_QA_SPEC.md)

## A real bug this caused

Cluster assignments were stored in a table keyed on `spotify_track_id` alone.
That looked right — one song, one cluster. But the table also held a `model_id`,
because assignments belong to a *particular* trained model.

With the key on the song alone, training a new model **overwrote the old
model's assignments**. One retrain took the serving model from 700 assigned
songs to 4, silently, because each new row replaced rather than joined.

The fix was a **composite key** — `(spotify_track_id, model_id)` together. The
grain of that table isn't "one row per song", it's "one row per song *per
model*", and the key has to say so.

**The lesson:** the bridge key identifies a *song*. It does not automatically
identify a *row*. Always ask what one row means, then make the key match.

→ Next: [Layers and grain](layers-and-grain.md)
