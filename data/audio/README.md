# Audio assets

Looping ambient audio ("comfort noise") mixed **under** the agent's voice so the call never
falls to dead digital silence. Mixed on the **output** path only (what the caller hears), so it
never reaches Deepgram STT or Silero VAD — no transcription/turn-taking contamination.

## Current asset

- **`ambient.wav`** — the active bed: **mono, 24 kHz, PCM s16, ~3.3 s**. Converted from
  `ambient.mp3` (the source MP3s are kept for re-conversion).
- `ambient.mp3`, `ambient1.mp3` — source clips (two different ambiences). To switch beds, convert
  the other one to `ambient.wav` (see command below).

## Hard requirements (don't skip — the mixer is picky)

Pipecat's `SoundfileMixer` **does not resample and does not downmix**. If the file doesn't match,
it logs a warning and **silently plays nothing**. So the WAV must be:

- **WAV/PCM** (libsndfile — not MP3).
- **Mono.**
- **Sample rate == the transport's output rate.** We pin that to **24000 Hz** in P4.5-T6
  (`audio_out_sample_rate`); the asset is 24 kHz to match. If the output rate changes, re-convert.
- **Seamless loop** — no click at the seam (a short loop repeats often, so a pop is very audible).
- **Subtle** — mixed at low volume (~0.10–0.20, configurable); barely-there room tone.

## Re-convert from MP3 (ffmpeg)

```bash
ffmpeg -y -i data/audio/ambient.mp3 -ac 1 -ar 24000 -sample_fmt s16 data/audio/ambient.wav
```

## Wiring (P4.5-T6)

`SoundfileMixer(sound_files={"ambient": "data/audio/ambient.wav"}, default_sound="ambient",
volume=…, loop=True)` attached via `TransportParams(audio_out_mixer=…)`, gated behind an
`ambient_noise` config flag (off by default, like `voice_debug`). Volume is runtime-adjustable.

> **Dependency:** `SoundfileMixer` imports `soundfile`, which is **not yet installed** in the
> venv. P4.5-T6 must add `soundfile` (and its libsndfile) to the `voice` extra.

## Caveats to revisit in P4.5-T6

- **Short loop (~3.3 s)** may sound repetitive over a long call — prefer a longer bed, or add a
  crossfade at the loop boundary.
- Confirm the transport output rate really is 24 kHz once the engine is wired; re-convert if not.

## VAD replay fixtures (`vad_fixtures/`, VAD-T5)

Canonical inputs for the offline turn-taking evaluator (`app.simulator.vad_replay`). Unlike the
ambient bed, these are **inbound-speech** clips — synthesized with macOS `say` (offline, no API
keys) with *deliberate* pauses and disfluencies, so the evaluator has stable, committed,
realistically-long callers to sweep. Content is domain-relevant (Nerdy tutoring sales). 16 kHz
mono PCM s16 (what Silero/the harness want).

Turn counts below are from the real Silero VAD at `stop_secs` 0.2 → 1.0 (`--sweep`). The pattern
to notice: the aggressive 0.2 default shreds a single thought into many turns (the agent jumps in);
a larger `stop_secs` merges them — *without* swallowing genuinely separate turns.

| fixture | what it is | turns 0.2 → 1.0 |
|---|---|---|
| **`midsentence_pause.wav`** | multi-sentence turn with a ~0.7 s mid-thought pause + an "um" | 6 → 3 → 3 → 2 → **1** |
| **`trailing_filler.wav`** | caller trailing off into a hesitation ("…so") | 3 → 3 → 2 → **1** → 1 |
| **`two_utterances.wav`** | two genuine turns, ~1.6 s gap — *control* | 4 → **2** → 2 → 2 → 2 |
| **`disfluent_ums.wav`** | heavy um/uh + restarts — fillers should be ridden through | 10 → 4 → **1** → 1 → 1 |
| **`chem_vs_bio.wav`** | long "is it chemistry or biology?" question, clause pauses | 7 → 5 → 3 → 3 → 2 |
| **`payment.wav`** | "how does paying work?" + a spoken card/phone number | 6 → 5 → 3 → 3 → 2 |
| **`edge_short_turns.wav`** | three one-word turns, ~1.4 s gaps — edge case | **3 at every value** |

`edge_short_turns` is the counterweight to the others: its gaps exceed every tested `stop_secs`, so
the count never collapses — proof the dial merges *hesitation* pauses, not *deliberate* turn breaks.

Regenerate with `bash data/audio/vad_fixtures/generate.sh`. The real-VAD path is asserted against
several of these in `backend/tests/test_vad_replay.py` (skips if they're absent).

## Honesty note (§18)

Ambiance for naturalness only; the agent still must never claim to be human. Comfort noise ≠
pretending to be a person.
