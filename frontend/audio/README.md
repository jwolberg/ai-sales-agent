# Demo phone-call audio

Browser-played sound effects for the `/demo` "phone call" intro (Phase 9). Unlike
`data/audio/` (server-side comfort-noise mixed into the call), these are **served statically**
to the browser from `frontend/` — they're sound effects the *caller's page* plays, not part of
the agent's audio stream. They never touch STT/VAD.

## Assets

| File | Contents | How `client.js` plays it |
| --- | --- | --- |
| `dial.mp3` | Dial tone → DTMF digits being dialed | played **once** on Call click |
| `ring.mp3` | One clean ring cycle (ring + trailing gap) | `loop = true`, rings until the agent answers |

The files committed here are **silent placeholder stubs** (generated with ffmpeg) so the
playback wiring works before real audio exists. Drop in real MP3s with the same names to make
the demo audible — no code change needed.

## Behavior

On Call click (once `/voice/status` reports ready), the page plays `dial.mp3`; when it ends it
starts looping `ring.mp3` while the WebRTC connection is established in parallel. The moment the
connection reaches `connected`, the ring stops and the agent's greeting plays — like a real call
being answered. Hang up, connection failure, or a denied mic prompt all stop the audio.

## Recommendations for the real assets

- **Keep them short.** `dial.mp3` a few seconds; `ring.mp3` one ring + gap (~2–4 s) so the loop
  feels like real ringing.
- **Loop-safe `ring.mp3`** — start and end on silence (the trailing gap) so repeats don't click.
- Standard US tones if you want realism: dial tone 350+440 Hz; ringback 440+480 Hz, 2 s on /
  4 s off.

## Regenerate the silent placeholders (ffmpeg)

```bash
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=mono -t 3 -q:a 9 frontend/audio/dial.mp3
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=mono -t 2 -q:a 9 frontend/audio/ring.mp3
```

## Honesty note (§18)

Phone-call sound effects are demo polish for realism only. The agent must still never claim to
be human; the dialing illusion does not change that.
