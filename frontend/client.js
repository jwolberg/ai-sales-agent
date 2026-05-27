// Minimal WebRTC client for the voice demo: mic -> /voice/offer -> play agent audio.
const callBtn = document.getElementById("call");
const hangupBtn = document.getElementById("hangup");
const statusEl = document.getElementById("status");
const remoteAudio = document.getElementById("remote");

let pc = null;
let localStream = null;

function setStatus(msg) {
  statusEl.textContent = msg;
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

async function startCall() {
  callBtn.disabled = true;
  setStatus("Checking voice configuration…");
  try {
    const status = await (await fetch("/voice/status")).json();
    if (!status.ready) {
      setStatus(`Voice not configured. Missing: ${status.missing_keys.join(", ")}`);
      callBtn.disabled = false;
      return;
    }

    pc = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    });
    pc.ontrack = (event) => {
      remoteAudio.srcObject = event.streams[0];
    };
    pc.onconnectionstatechange = () => {
      if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
        setStatus(`Connection ${pc.connectionState}.`);
      }
    };

    setStatus("Requesting microphone…");
    localStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));

    const offer = await pc.createOffer({ offerToReceiveAudio: true });
    await pc.setLocalDescription(offer);
    await waitForIceGathering(pc);

    setStatus("Connecting…");
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

    hangupBtn.disabled = false;
    setStatus("Connected — start talking. The agent will greet you.");
  } catch (e) {
    setStatus(`Error: ${e.message}`);
    stopCall();
  }
}

function stopCall() {
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
