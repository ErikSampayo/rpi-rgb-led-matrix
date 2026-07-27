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
        }
      } else {
        const frame = new Uint8Array(event.data);
        if (frame.length !== 64 * 64 * 4) return;
        const imageData = ctx.createImageData(64, 64);
        imageData.data.set(frame);
        ctx.putImageData(imageData, 0, 0);
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
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "reset" }));
    }
  });

  connect();
})();
