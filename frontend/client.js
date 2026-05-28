// Minimal WebRTC client for the voice demo: mic -> /voice/offer -> play agent audio.
const callBtn = document.getElementById("call");
const hangupBtn = document.getElementById("hangup");
const statusEl = document.getElementById("status");
const remoteAudio = document.getElementById("remote");

let pc = null;
let localStream = null;
let answered = false;
let answerCtx = null; // Web Audio context used to detect when the agent actually starts speaking

// Phone-call intro sound effects (Phase 9): dial+digits one-shot, then ring looped until the
// agent answers. Silent placeholder stubs ship in frontend/audio/ — see frontend/audio/README.md.
const dialSound = new Audio("audio/dial.mp3");
const ringSound = new Audio("audio/ring.mp3");
ringSound.loop = true;

function setStatus(msg) {
  statusEl.textContent = msg;
}

// Begin the dialing illusion: play dial+digits, then loop ringing until the call is answered.
function startDialingSound() {
  // When the dial+digits clip ends, ring until answered (unless the agent already picked up).
  dialSound.onended = () => {
    if (!answered) {
      setStatus("Ringing…");
      ringSound.currentTime = 0;
      ringSound.play().catch(() => {});
    }
  };
  setStatus("Dialing…");
  dialSound.currentTime = 0;
  // play() can reject (e.g. autoplay policy); the call still proceeds without the effect.
  dialSound.play().catch(() => {});
}

// Stop and reset both effects (on answer, hang up, or error).
function stopDialingSound() {
  dialSound.onended = null;
  for (const sound of [dialSound, ringSound]) {
    sound.pause();
    sound.currentTime = 0;
  }
}

// Single offer/answer (no trickle): wait for ICE gathering to finish before sending.
function waitForIceGathering(connection) {
  return new Promise((resolve) => {
    if (connection.iceGatheringState === "complete") return resolve();
    const check = () => {
      if (connection.iceGatheringState === "complete") {
        connection.removeEventListener("icegatheringstatechange", check);
        resolve();
      }
    };
    connection.addEventListener("icegatheringstatechange", check);
    setTimeout(resolve, 3000); // fallback so we never hang
  });
}

// The agent "picks up": stop the ringing and let its greeting play through #remote.
function onAnswered() {
  if (answered) return;
  answered = true;
  closeAnswerDetection();
  stopDialingSound();
  setStatus("Connected — the agent is speaking.");
}

// Keep ringing until the agent's audio *actually starts*. The WebRTC connection becomes
// "connected" (and ontrack fires) well before the agent speaks, so those are too early to treat
// as a pickup — we'd cut the ring and drop into silence. Instead, tap the inbound stream and
// answer on the first real audio energy (the greeting). A deadline guarantees we don't ring
// forever if no audio ever arrives.
// Create the audio context while the click's user-activation is still fresh; a context created
// later (after the awaits in startCall) can be blocked/suspended by the browser autoplay policy.
function ensureAnswerCtx() {
  try {
    if (!answerCtx) answerCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (answerCtx.state === "suspended") answerCtx.resume().catch(() => {});
  } catch (e) {
    answerCtx = null;
  }
}

function detectAnswerFromStream(stream) {
  if (answered) return;
  try {
    ensureAnswerCtx();
    if (!answerCtx) throw new Error("no AudioContext");
    const source = answerCtx.createMediaStreamSource(stream);
    const analyser = answerCtx.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    const data = new Uint8Array(analyser.frequencyBinCount);
    const deadline = Date.now() + 30000; // hard cap: pick up within 30s regardless
    const poll = () => {
      if (answered) return;
      analyser.getByteFrequencyData(data);
      let energy = 0;
      for (const v of data) energy += v;
      if (energy > 400 || Date.now() > deadline) {
        onAnswered();
        return;
      }
      requestAnimationFrame(poll);
    };
    poll();
  } catch (e) {
    // No Web Audio (or stream not analysable) — fall back to answering immediately.
    console.warn("[answer-detect] falling back:", e);
    onAnswered();
  }
}

function closeAnswerDetection() {
  if (answerCtx) {
    answerCtx.close().catch(() => {});
    answerCtx = null;
  }
}

async function startCall() {
  callBtn.disabled = true;
  answered = false;
  ensureAnswerCtx(); // prime the audio context now, under the fresh click gesture
  setStatus("Checking voice configuration…");
  try {
    const status = await (await fetch("/voice/status")).json();
    if (!status.ready) {
      setStatus(`Voice not configured. Missing: ${status.missing_keys.join(", ")}`);
      closeAnswerDetection();
      callBtn.disabled = false;
      return;
    }

    // Voice is configured — begin the phone-call illusion while we connect in parallel.
    startDialingSound();

    pc = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    });
    pc.ontrack = (event) => {
      remoteAudio.srcObject = event.streams[0];
      // Don't answer yet — ring until the agent's audio actually starts (see detectAnswer…).
      detectAnswerFromStream(event.streams[0]);
    };
    pc.onconnectionstatechange = () => {
      console.log("[webrtc] connectionState:", pc.connectionState);
      if (["failed", "disconnected", "closed"].includes(pc.connectionState) && !answered) {
        stopDialingSound();
        setStatus(`Connection ${pc.connectionState}.`);
      }
    };
    pc.oniceconnectionstatechange = () =>
      console.log("[webrtc] iceConnectionState:", pc.iceConnectionState);

    // Mic is requested in parallel with the dialing sound; the browser shows its own permission
    // prompt, so we keep the on-screen status on the "Dialing…/Ringing…" phone narrative.
    localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));
    // Diagnostic: confirm the mic track is captured, live, and not muted.
    localStream.getAudioTracks().forEach((t) =>
      console.log("[mic] track:", {
        label: t.label,
        enabled: t.enabled,
        muted: t.muted,
        readyState: t.readyState,
      }),
    );

    const offer = await pc.createOffer({ offerToReceiveAudio: true });
    await pc.setLocalDescription(offer);
    await waitForIceGathering(pc);

    const resp = await fetch("/voice/offer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sdp: pc.localDescription.sdp,
        type: pc.localDescription.type,
      }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      setStatus(`Error: ${err.detail || resp.status}`);
      stopCall();
      return;
    }
    const answer = await resp.json();
    await pc.setRemoteDescription({ type: answer.type, sdp: answer.sdp });

    // The call is in progress; keep ringing until the connection actually answers (onAnswered).
    hangupBtn.disabled = false;
  } catch (e) {
    setStatus(`Error: ${e.message}`);
    stopCall();
  }
}

function stopCall() {
  closeAnswerDetection();
  stopDialingSound();
  answered = false;
  if (pc) {
    pc.close();
    pc = null;
  }
  if (localStream) {
    localStream.getTracks().forEach((track) => track.stop());
    localStream = null;
  }
  callBtn.disabled = false;
  hangupBtn.disabled = true;
  setStatus("Call ended.");
}

callBtn.addEventListener("click", startCall);
hangupBtn.addEventListener("click", stopCall);
