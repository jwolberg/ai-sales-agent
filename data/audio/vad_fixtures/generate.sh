#!/usr/bin/env bash
# Regenerate the VAD replay-harness fixtures (VAD-T5).
#
# These are synthesized speech (macOS `say`, offline — no API keys) with *deliberate* pauses, so
# the offline evaluator (app.simulator.vad_replay) has a canonical, committed input. Apple's
# `[[slnc N]]` markup inserts N ms of silence mid-utterance — that pause is exactly what trips
# "the agent jumps in too soon" at a low stop_secs.
#
# Output: 16 kHz mono PCM s16 WAV (what the harness + Silero want). Re-run from the repo root:
#   bash data/audio/vad_fixtures/generate.sh
set -euo pipefail

cd "$(dirname "$0")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

gen() { # name "spoken text with [[slnc ms]] pauses"
  local name="$1" text="$2"
  say -o "$tmp/$name.aiff" "$text"
  ffmpeg -y -loglevel error -i "$tmp/$name.aiff" -ac 1 -ar 16000 -sample_fmt s16 "$name.wav"
  echo "wrote $name.wav"
}

# 1) One utterance with a ~0.7s mid-sentence pause — the canonical "jumps in too soon" case.
#    Should read as ONE turn at a relaxed stop_secs, but SPLIT into two at the aggressive 0.2 default.
gen midsentence_pause "I'm calling about [[slnc 700]] my son's S A T prep."

# 2) Utterance with a trailing hesitation ("so...") — the caller hasn't finished their thought.
gen trailing_filler "I think we need help with chemistry [[slnc 600]] so"

# 3) Two genuinely separate utterances with a long gap — control: stays TWO turns even at high stop_secs.
gen two_utterances "Yes, that works for us. [[slnc 1500]] When can we start?"
