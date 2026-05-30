#!/usr/bin/env bash
# Regenerate the VAD replay-harness fixtures (VAD-T5, extended VAD-T6).
#
# Synthesized speech (macOS `say`, offline — no API keys) with *deliberate* pauses and
# disfluencies, so the offline evaluator (app.simulator.vad_replay) has canonical, committed,
# realistically-long inputs. Apple's `[[slnc N]]` markup inserts N ms of silence; "um"/"uh" are
# spoken as voiced fillers (they keep VAD in speech, the way a real caller's hesitation does).
# The content is domain-relevant (Nerdy tutoring sales) so the clips read like real callers.
#
# Output: 16 kHz mono PCM s16 WAV (what Silero/the harness want). Re-run from the repo root:
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

# 1) Multi-sentence turn with a ~0.7s mid-thought pause — the canonical "jumps in too soon" case.
gen midsentence_pause \
  "I'm calling about my son. [[slnc 600]] He's a junior, [[slnc 700]] and, um, he's been really \
struggling with the math section on the S A T, so we wanted some help."

# 2) Caller trailing off into a hesitation ("so…") — they haven't finished their thought.
gen trailing_filler \
  "We've already tried a couple of tutors, [[slnc 500]] and honestly it just hasn't really \
clicked for her, [[slnc 650]] so"

# 3) Two genuinely separate turns with a long gap — control: stays multiple turns even when relaxed.
gen two_utterances \
  "Yes, that sounds good to us. [[slnc 1600]] So when can we actually get started, and how many \
sessions a week would you recommend?"

# 4) Heavy disfluency (um/uh, restarts) — fillers are voiced, so VAD should ride through them
#    rather than treat each gap as turn-end.
gen disfluent_ums \
  "So, um, [[slnc 450]] I guess what I'm really wondering is, [[slnc 500]] uh, do you do, like, \
one on one sessions, [[slnc 450]] or is it, um, more of a group thing?"

# 5) Domain question comparing chemistry vs biology — long, clause-heavy, with thinking pauses.
gen chem_vs_bio \
  "She needs help in science, [[slnc 500]] but I'm honestly not sure if it's chemistry or biology. \
[[slnc 800]] It's the class with the periodic table, [[slnc 500]] um, and balancing equations. \
[[slnc 700]] Would that be chemistry, or biology?"

# 6) Payment turn with a spoken card/phone number — digits + a mid-number pause are an edge case
#    for endpointing (callers pause between digit groups).
gen payment \
  "Okay, [[slnc 500]] and how does paying actually work? [[slnc 700]] Can I just put it on a card? \
[[slnc 600]] Um, you can text the link to me at five five five, [[slnc 350]] one two three four."

# 7) Edge case: very short single-word turns separated by long gaps — stresses start/stop detection.
gen edge_short_turns \
  "Yes. [[slnc 1400]] Okay. [[slnc 1400]] Sounds good to me."
