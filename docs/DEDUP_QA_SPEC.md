# Epic O4 + QA-2 — aggressive duplicate consolidation & full-surface validation

**Owner ask (2026-07-24):** *"All features should be tested and all duplicate
tracks consolidated. This should be done aggressively. If a track is in a
separate album or single they should be treated as one. The only difference
should be if there is different audio for a different version — a remix or live
version, acoustic, etc."*

Written after measuring the live corpus, not from the docs. Every number below
was produced by a read-only probe against `data/feature_cache.db` on
2026-07-24 with the app running.

---

## 1. Measured baseline

| metric | value |
|---|---|
| known tracks (`track_meta`) | 847 |
| analyzed (`track_features`, all with a loudness curve) | 780 |
| canonical in the marts / `track_card` | 730 |
| flagged twins (`duplicate_of`) | 35 |
| warehouse audit | **19 flags, all false** |
| `qa_audit.py` | **0 failed · 7 passed · 2 notes** |
| suite | green · ruff clean |

Metadata fill (the dedup inputs): `duration_ms` 784/847 · `album_name` 557/847 ·
`popularity` 847/847 · `primary_artist_id` 784/847. All healthy — a first probe
that read 0% was an artifact of `all_meta()` being a deliberate 2-field
projection, not a data gap.

### The acoustic tiebreak actually separates

The production tiebreak is a 13-column **z-scored** cosine (`_SIMILARITY_COLS`),
not raw 77-dim. Measured:

| population | z-cosine |
|---|---|
| the 10 analyzed flagged twins | 0.9826 – 1.0000 |
| 7 real version pairs (remix / acoustic / mix) | −0.24 – **+0.68** |
| random unrelated pairs | p50 −0.01 · p99 +0.84 · **0.275%** ≥ 0.95 |

So `DEFAULT_COSINE_MIN = 0.95` is a genuinely discriminating gate. Keep it.

---

## 2. The finding: today's rule is right by accident, and inverted

`normalize_title()` **strips** version qualifiers — `- BUNT. Remix`,
`- Acoustic`, `- KETTAMA MIX` all vanish — so a remix and its original land in
the *same* bucket. What keeps them apart today is incidental:

| pair | what actually blocked the merge |
|---|---|
| Opalite / Opalite – BUNT. Remix | a credited remixer changed the artist string |
| Air Maxes / Air Maxes – KETTAMA MIX | **only** a 32.8 s duration gap (same artist string) |
| Everchanging / Everchanging – Acoustic | **only** a 34.9 s duration gap |
| JOY (If You Want) / JOY (By My Side) — *different songs* | artist string + duration; both titles normalize to `joy` |

Meanwhile the **exact full-artist-string equality** requirement blocks exactly
the merges the owner wants: a single credited `A, B` never matches the album's
`A`.

**Aggressive consolidation is therefore not "loosen the rule" — it is invert
it.** Make the version tag the discriminator; make release and credit
differences irrelevant.

### What a duration-led pass finds that title bucketing structurally cannot

42 exact-`duration_ms` collision groups; 25 share a leading artist (17 are
cross-artist coincidences, so artist must stay required). Of the 25, 22 are
already flagged — and the 3 that are not are the interesting ones:

1. **`Here's Lookin At You, Kid` / `Here's Looking At You, Kid`** (The Gaslight
   Anthem, both 216040 ms) — a spelling variant. A title-keyed bucket can never
   catch this.
2. **`Air Maxes - KETTAMA MIX` / `Airmaxes - KETTAMA Mix`** (both 213977 ms) — a
   spacing variant of the *same* version tag.
3. **`Won't Stand Down` ×2** (Muse, both 209061 ms, same title, same artist) —
   metadata says one recording, but the two acquisitions score **z-cosine
   0.667**. The gate correctly refused to merge; what it revealed is that **at
   least one of the two audio pickups is wrong**. That is a provenance defect,
   not a dedup decision.

Finding #3 is a new class of check and the honest form of the parked O3d miner.

---

## 3. Epic O4 — the build

Doctrine unchanged (O3): consolidation is a **read-time view**. The bridge key
is never merged, no features are deleted, twins keep their own stored analysis.

### O4a — version-aware title parsing *(pure, `dedup.py`)*
`parse_title(name) -> (base, version_tag)` — **extract** the qualifier instead
of discarding it. Merge requires `base` equal **AND `version_tag` equal** (both
empty, or the same tag).

- **VERSION tags — different audio, never merge:** remix/rmx · live · acoustic ·
  unplugged · instrumental · karaoke · demo · session · cover · edit / radio
  edit · VIP · dub · extended · club mix · sped up · slowed · reprise ·
  re-recorded / "Taylor's Version".
- **RELEASE qualifiers — same recording, ignore:** remaster(ed) · deluxe ·
  anniversary · expanded · bonus track · single/album version · original ·
  explicit/clean · mono/stereo · reissue · "from the motion picture".
- **Correctness fix:** parentheses are stripped **only when their content is a
  known qualifier**. Today `_PAREN_RE` nukes every parenthetical, which is why
  two different songs both normalize to `joy`.

Assumptions stated for the owner (flag if wrong): a **remaster is the same
performance → merge**; a **re-recording ("Taylor's Version") is different audio
→ split**; a **radio edit is different audio → split**.

### O4b — release-blind, credit-blind keying
Artist key = `primary_artist_id` when both sides have it, else the normalized
**leading** artist. `album_name` never gates a merge — it is the thing being
collapsed. Safe *because* O4a now splits versions by design.

### O4c — duration-led candidate generation *(the new engine)*
Exact `duration_ms` equality + same artist key ⇒ a candidate **even when the
titles differ**, subject to equal version tags and a title-similarity floor.
Catches the spelling and spacing variants above.

### O4d — the acoustic-disagreement flag *(new)*
Metadata says one recording, z-cosine says otherwise ⇒ **do not merge, do not
ignore**: surface it into the existing needs-source / repair flow.
`Won't Stand Down` is case #1.

### O4e — wiring
Refresh flags → `duplicate_flags.parquet` → `corpus_facts` honesty fields →
`/library` chip copy. `TWIN_LEAKAGE` and `PROVENANCE_ORPHAN` stay green; add a
`DEDUP_DISAGREEMENT` note to the warehouse audit.

---

## 4. Epic QA-2 — the validation run

Five layers; the first two exist today, the rest are the build.

1. **Regression** — `pytest src/` green + `ruff` clean. *(exists)*
2. **Data invariants** — `qa_audit.py` (9 checks) + warehouse audit (19 flags).
   *(exists)*
3. **Route matrix** *(new)* — all **30 routes × 4 personas** (anon · guest ·
   viewer · owner), asserting the intended status **and** one content invariant
   each. Today's route tests are per-feature and scattered, so gate coverage is
   not provable — this is the class that produced bug A7 (owner repair tools
   hidden by the D-57 gate).
4. **Dedup golden set** *(new)* — the owner's rule encoded as tests over real
   pairs from this corpus: the 7 version pairs **must split**, the 25
   exact-duration same-artist groups **must merge**, the JOY pair **must
   split**.
5. **Live smoke** *(new)* — the standing browser-validation practice, scripted:
   anon landing / library / song / queue / privacy / healthz through the public
   edge, plus the guest path.

### Definition of done
Both audits clean · suite green · every route in the matrix · the dedup golden
set passing · live smoke green · the corpus numbers restated honestly on
`/library` and in `corpus_facts`.

---

## 5. Outcome (shipped 2026-07-24)

**O4 is live.** Corpus 730 → **728** canonical, exactly as measured in advance:

| change | pair |
|---|---|
| + merged | `Here's Lookin At You, Kid` → `Here's Looking At You, Kid` (spelling) |
| + merged | `Air Maxes - KETTAMA MIX` → `Airmaxes - KETTAMA Mix` (spacing) |
| − split | `Bliss` un-flagged from `Bliss - XX Anniversary RemiXX` (a remix is different audio) |
| O4d | `Won't Stand Down` ×2 — one acquisition is the wrong audio, now surfaced |

Owner call on the open question: **continuous DJ "- Mixed" edits SPLIT** — they
are different audio, which is the rule as written.

The red-team's ship-blocker proved itself on real data: `Bliss` came back
`queued` rather than stranded at terminal `done`. A false-merge class the corpus
does not contain (`Club 0`/`Club 1` at 0.83 difflib) was caught by the synthetic
warehouse fixture and closed with a digit-sequence guard.

**QA-2 is live.** 771 tests green · ruff clean · warehouse audit **20 flags, all
false** · `qa_audit` 0 failed · live smoke **14/14 through the public edge**.
Two bugs found and fixed (`/guest` session hijack, `/openapi.json` exposure), and
the matrix's first act was catching a machine-dependency in itself — see journal
#54 and #55.

Verified on the live site, both halves of the rule:
`"looking at you"` → **one** row, "2 releases of this recording", matched via the
other spelling; `"everchanging"` → **two** rows, whose measured BPMs (144 vs 123)
confirm the acoustic take really is different audio.
