"""
Tornado server for browser-based game_square play.

Run:
    python -m game_square.server --port 8080

Players browse to http://localhost:8080/ (or your domain).
First two WebSocket connections get Player 1 (red) and Player 2 (blue);
everyone else is a spectator.

For HTTPS/WSS, put nginx or Caddy in front as a reverse proxy.
"""

import argparse
import os
import threading
import time
import json

import tornado.web
import tornado.ioloop
import tornado.websocket

from game_square.keys import (
    K_w, K_s, K_a, K_d, K_e, K_f,
    K_UP, K_DOWN, K_LEFT, K_RIGHT, K_n, K_m,
)
from game_square.web.display import WebDisplay

# ---------------------------------------------------------------------------
# Key mapping: browser KeyboardEvent.code -> pygame key constant
# ---------------------------------------------------------------------------

KEY_MAP = {
    # Player 1 (red) — WASD + E + F
    "KeyW": K_w,
    "KeyS": K_s,
    "KeyA": K_a,
    "KeyD": K_d,
    "KeyE": K_e,
    "KeyF": K_f,
    # Player 2 (blue) — Arrows + N + M
    "ArrowUp":    K_UP,
    "ArrowDown":  K_DOWN,
    "ArrowLeft":  K_LEFT,
    "ArrowRight": K_RIGHT,
    "KeyN": K_n,
    "KeyM": K_m,
}

GAME_KEY_CODES = set(KEY_MAP.keys())

# ---------------------------------------------------------------------------
# Globals shared between game thread and WebSocket handlers
# ---------------------------------------------------------------------------

display: WebDisplay
clients: list["GameSocketHandler"] = []
player_slots: list["GameSocketHandler | None"] = [None, None]

FRAME_INTERVAL_MS = 40   # ~25 fps broadcast

# ---------------------------------------------------------------------------
# Game thread
# ---------------------------------------------------------------------------

def run_game():
    from game_square.main import demo
    while True:
        demo(display)


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------

class GameSocketHandler(tornado.websocket.WebSocketHandler):

    def open(self):
        global clients, player_slots
        clients.append(self)
        self.role = "spectator"

        for i in range(2):
            if player_slots[i] is None:
                player_slots[i] = self
                self.role = f"player{i + 1}"
                break

        self.write_message(json.dumps({"type": "role", "role": self.role}))

        # Force a full frame so the new client sees current game state
        # instead of deltas with no reference frame.
        display._full_frame_pending = True

    def on_message(self, message):
        try:
            msg = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return
        if msg.get("type") == "reset":
            do_reset()
            return
        if self.role == "spectator":
            return
        if msg.get("type") == "keydown":
            code = KEY_MAP.get(msg.get("code"))
            if code is not None:
                display.push_input("down", code)
        elif msg.get("type") == "keyup":
            code = KEY_MAP.get(msg.get("code"))
            if code is not None:
                display.push_input("up", code)

    def on_close(self):
        global clients, player_slots
        if self in clients:
            clients.remove(self)
        for i in range(2):
            if player_slots[i] is self:
                player_slots[i] = None
                break

    def check_origin(self, origin):
        return True


# ---------------------------------------------------------------------------
# Periodic frame broadcaster
# ---------------------------------------------------------------------------

def broadcast_frames():
    while True:
        try:
            frame = display.frame_queue.get_nowait()
        except Exception:
            break
        for client in list(clients):
            try:
                client.write_message(frame, binary=True)
            except Exception:
                pass

    while True:
        try:
            name = display.sound_queue.get_nowait()
        except Exception:
            break
        msg = json.dumps({"type": "sound", "name": name})
        for client in list(clients):
            try:
                client.write_message(msg)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Static file handlers
# ---------------------------------------------------------------------------

STATIC_DIR = os.path.join(os.path.dirname(__file__), "web", "static")


class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.render(os.path.join(STATIC_DIR, "index.html"))


class ResetHandler(tornado.web.RequestHandler):
    def post(self):
        do_reset()
        self.write({"status": "ok"})

    def get(self):
        do_reset()
        self.write({"status": "ok"})


def do_reset():
    display.request_reset()
    for client in list(clients):
        try:
            client.write_message(json.dumps({"type": "reset"}))
        except Exception:
            pass


class NoCacheStaticFileHandler(tornado.web.StaticFileHandler):
    def set_extra_headers(self, path):
        self.set_header("Cache-Control", "no-cache, must-revalidate")


def make_app() -> tornado.web.Application:
    return tornado.web.Application([
        (r"/",             IndexHandler),
        (r"/reset",        ResetHandler),
        (r"/static/(.*)",  NoCacheStaticFileHandler, {"path": STATIC_DIR}),
        (r"/ws",           GameSocketHandler),
    ])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global display

    parser = argparse.ArgumentParser(description="game_square web server")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0",
                        help="Bind address (use 0.0.0.0 for all interfaces)")
    args = parser.parse_args()

    display = WebDisplay()

    app = make_app()
    app.listen(args.port, address=args.host)

    cb = tornado.ioloop.PeriodicCallback(broadcast_frames, FRAME_INTERVAL_MS)
    cb.start()

    game_thread = threading.Thread(target=run_game, daemon=True)
    game_thread.start()

    print(f"game_square server running on http://{args.host}:{args.port}/")
    print("Press Ctrl+C to stop.")
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
