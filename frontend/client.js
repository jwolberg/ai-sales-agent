// Minimal WebRTC client for the voice demo: mic -> /voice/offer -> play agent audio.
const callBtn = document.getElementById("call");
const hangupBtn = document.getElementById("hangup");
const statusEl = document.getElementById("status");
const remoteAudio = document.getElementById("remote");

let pc = null;
let localStream = null;
let answered = false;

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
  stopDialingSound();
  setStatus("Connected — the agent will greet you.");
}

async function startCall() {
  callBtn.disabled = true;
  answered = false;
  setStatus("Checking voice configuration…");
  try {
    const status = await (await fetch("/voice/status")).json();
    if (!status.ready) {
      setStatus(`Voice not configured. Missing: ${status.missing_keys.join(", ")}`);
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
      onAnswered(); // fallback answer signal (inbound audio = agent picked up)
    };
    pc.onconnectionstatechange = () => {
      console.log("[webrtc] connectionState:", pc.connectionState);
      if (pc.connectionState === "connected") {
        onAnswered();
      } else if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
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
