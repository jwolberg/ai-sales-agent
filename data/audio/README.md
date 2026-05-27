# Audio assets

Looping ambient audio ("comfort noise") mixed **under** the agent's voice so the call never
falls to dead digital silence. Mixed on the **output** path only (what the caller hears), so it
never reaches Deepgram STT or Silero VAD — no transcription/turn-taking contamination.

## Drop your file here

- **Default path:** `data/audio/ambient.wav` (the config flag points here).
- **Format: WAV** — Pipecat's `SoundfileMixer` reads via libsndfile (WAV/FLAC/OGG). **MP3 is not
  supported.** If you only have an MP3, drop it as `data/audio/ambient.mp3` and it'll be converted
  to WAV during P4.5-T6.
- **Mono**, ideally **16 kHz** (matches the pipeline; otherwise it's resampled once).
- **Seamless loop** — no click or gap at the loop seam, or it sounds robotic.
- **Subtle** — it's mixed at low volume (~0.10–0.20, configurable); it should be barely-there
  room tone, not a distraction.
- **Licensing** — must be royalty-free or otherwise licensed for this use.

## How it's wired (P4.5-T6)

`SoundfileMixer(sound_files={"ambient": <path>}, volume=…, loop=True)` is attached to the
transport via `TransportParams(audio_out_mixer=…)`, gated behind an `ambient_noise` config flag
(off by default, like `voice_debug`). Volume is runtime-adjustable.

## Honesty note (§18)

Ambiance for naturalness is fine and standard, but it must not be used to deceive — the agent
still must never claim to be human if asked. Comfort noise ≠ pretending to be a person.
