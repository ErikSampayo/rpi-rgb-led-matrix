(function () {
  "use strict";

  const canvas = document.getElementById("game");
  const ctx = canvas.getContext("2d");
  const roleBadge = document.getElementById("role-badge");

  const GAME_KEYS = new Set([
    "KeyW", "KeyS", "KeyA", "KeyD", "KeyE", "KeyF",
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "KeyN", "KeyM",
  ]);

  let ws = null;
  let role = "spectator";
  let imageData = ctx.createImageData(64, 64);
  let awaitingFullFrame = false;

  // ------------------------------------------------------------------
  // Web Audio API synthesizer
  // ------------------------------------------------------------------

  let audioCtx = null;

  function initAudio() {
    if (audioCtx) return;
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }

  function tone(opts) {
    if (!audioCtx) return;
    const t = audioCtx.currentTime;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = opts.type || "square";
    osc.frequency.setValueAtTime(opts.freq, t);
    if (opts.freqEnd) {
      osc.frequency.exponentialRampToValueAtTime(
        Math.max(1, opts.freqEnd), t + opts.dur
      );
    }
    const vol = opts.vol || 0.15;
    gain.gain.setValueAtTime(vol, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + opts.dur);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start(t);
    osc.stop(t + opts.dur);
  }

  const SOUNDS = {
    spawn:    () => tone({ type: "square",   freq: 200,  freqEnd: 700,  dur: 0.12, vol: 0.12 }),
    connect:  () => tone({ type: "square",   freq: 500,  freqEnd: 900,  dur: 0.06, vol: 0.10 }),
    derezz:   () => tone({ type: "sawtooth", freq: 800,  freqEnd: 80,   dur: 0.30, vol: 0.15 }),
    capture:  () => {
      tone({ type: "square", freq: 400, dur: 0.10, vol: 0.14 });
      setTimeout(() => tone({ type: "square", freq: 600, dur: 0.15, vol: 0.14 }), 90);
    },
    toggle:   () => tone({ type: "sine",     freq: 300,  dur: 0.03, vol: 0.08 }),
    reset:    () => tone({ type: "sawtooth", freq: 600,  freqEnd: 50,   dur: 0.40, vol: 0.12 }),
    bounce:   () => tone({ type: "triangle", freq: 180,  freqEnd: 120,  dur: 0.08, vol: 0.10 }),
  };

  // ------------------------------------------------------------------
  // Continuous wire-drawing sound (saw wave, per-player base pitch)
  // ------------------------------------------------------------------

  const WIRE_BASE_FREQ = [110, 165];   // P1 = A2, P2 = E3
  const WIRE_STEP_HZ   = 3;            // pitch rise per pixel
  const WIRE_MAX_HZ    = 440;
  let wireOsc = [null, null];
  let wireGain = [null, null];
  let wireSteps = [0, 0];

  function wireStart(player) {
    if (!audioCtx) return;
    wireStop(player);
    wireSteps[player] = 0;
    const t = audioCtx.currentTime;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(WIRE_BASE_FREQ[player], t);
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.04, t + 0.05);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start(t);
    wireOsc[player] = osc;
    wireGain[player] = gain;
  }

  function wireStep(player) {
    const osc = wireOsc[player];
    if (!osc || !audioCtx) return;
    wireSteps[player]++;
    const freq = Math.min(WIRE_MAX_HZ, WIRE_BASE_FREQ[player] + wireSteps[player] * WIRE_STEP_HZ);
    osc.frequency.linearRampToValueAtTime(freq, audioCtx.currentTime + 0.04);
  }

  function wireStop(player) {
    const osc = wireOsc[player];
    const gain = wireGain[player];
    if (!osc || !audioCtx) return;
    const t = audioCtx.currentTime;
    gain.gain.cancelScheduledValues(t);
    gain.gain.setValueAtTime(gain.gain.value, t);
    gain.gain.linearRampToValueAtTime(0, t + 0.08);
    osc.stop(t + 0.10);
    wireOsc[player] = null;
    wireGain[player] = null;
  }

  function playSound(name) {
    if (!audioCtx) initAudio();
    if (audioCtx.state === "suspended") audioCtx.resume();

    if (name.startsWith("wire_start_")) {
      wireStart(parseInt(name.slice(-1)));
      return;
    }
    if (name.startsWith("wire_step_")) {
      wireStep(parseInt(name.slice(-1)));
      return;
    }
    if (name.startsWith("wire_end_")) {
      wireStop(parseInt(name.slice(-1)));
      return;
    }

    const fn = SOUNDS[name];
    if (fn) fn();
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws`;
    ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      roleBadge.textContent = "Connected — waiting for role...";
    };

    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        const msg = JSON.parse(event.data);
        if (msg.type === "role") {
          role = msg.role;
          if (role === "player1") {
            roleBadge.textContent = "You are Player 1 (Red)";
            roleBadge.className = "player1";
          } else if (role === "player2") {
            roleBadge.textContent = "You are Player 2 (Blue)";
            roleBadge.className = "player2";
          } else {
            roleBadge.textContent = "Spectating";
            roleBadge.className = "spectator";
          }
        } else if (msg.type === "reset") {
          ctx.clearRect(0, 0, 64, 64);
          imageData = ctx.createImageData(64, 64);
          awaitingFullFrame = true;
          wireStop(0);
          wireStop(1);
          playSound("reset");
        } else if (msg.type === "sound") {
          playSound(msg.name);
        }
      } else {
        const frame = new Uint8Array(event.data);
        if (frame.length < 1) return;
        const flag = frame[0];

        if (flag === 0x00) {
          if (frame.length !== 1 + 64 * 64 * 4) return;
          imageData.data.set(frame.subarray(1));
          ctx.putImageData(imageData, 0, 0);
          awaitingFullFrame = false;
        } else if (flag === 0x01 && !awaitingFullFrame) {
          const count = (frame[1] << 8) | frame[2];
          let offset = 3;
          for (let i = 0; i < count; i++) {
            const x = frame[offset];
            const y = frame[offset + 1];
            const idx = (y * 64 + x) * 4;
            imageData.data[idx]     = frame[offset + 2];
            imageData.data[idx + 1] = frame[offset + 3];
            imageData.data[idx + 2] = frame[offset + 4];
            imageData.data[idx + 3] = 255;
            offset += 5;
          }
          ctx.putImageData(imageData, 0, 0);
        }
      }
    };

    ws.onclose = () => {
      roleBadge.textContent = "Disconnected — reconnecting...";
      roleBadge.className = "";
      setTimeout(connect, 2000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  function sendKey(type, code) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type, code }));
  }

  document.addEventListener("keydown", (e) => {
    if (!audioCtx) initAudio();
    if (GAME_KEYS.has(e.code)) {
      e.preventDefault();
      if (!e.repeat) {
        sendKey("keydown", e.code);
      }
    }
  });

  document.addEventListener("keyup", (e) => {
    if (GAME_KEYS.has(e.code)) {
      e.preventDefault();
      sendKey("keyup", e.code);
    }
  });

  document.getElementById("reset-btn").addEventListener("click", () => {
    if (!audioCtx) initAudio();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "reset" }));
    }
  });

  connect();
})();
