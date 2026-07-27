"""
WebDisplay — headless Display backend for browser-based play.

Replaces SquarePygameDisplay when running the game server.  The game
loop (demo()) runs unchanged; this class provides the same interface
but communicates with the Tornado server via thread-safe queues
instead of a pygame window.
"""

import queue
import struct

from game_square.display.base import Display, Color, BLACK


class HeldKeysView:
    """
    Mimics the pygame ScancodeWrapper returned by pygame.key.get_pressed().
    Supports ``held[keycode]`` -> bool so the game loop's existing
    ``if held[pygame.K_w]:`` checks work without modification.
    """

    __slots__ = ("_held",)

    def __init__(self, held: set[int]):
        self._held = held

    def __getitem__(self, key: int) -> bool:
        return key in self._held


class WebDisplay(Display):
    """
    Display backend that serialises the framebuffer to RGBA bytes for
    WebSocket broadcast and receives keyboard input from a queue.

    The game thread calls ``render()`` (pushes frame) and
    ``pump_events()`` (drains input) at ~25 fps.  The server thread
    pushes input events into ``input_queue`` and drains ``frame_queue``
    for broadcasting.
    Frame protocol (binary WebSocket messages):
      0x00 + RGBA[16384]  — full frame (first frame, after reset, or when
                            delta would be larger than full frame)
      0x01 + count[2] + count × (x, y, r, g, b) — delta frame
      0x02                 — no change since last frame
    """

    def __init__(self):
        self._buf: list[list[Color]] = [
            [BLACK] * self.WIDTH for _ in range(self.HEIGHT)
        ]
        self.clicked: list[tuple[int, int]] = []
        self.keys_pressed: list[int] = []
        self.keys_held = HeldKeysView(set())
        self.mouse_pos: tuple[int, int] = (0, 0)

        self.frame_queue: queue.Queue = queue.Queue(maxsize=4)
        self.input_queue: queue.Queue = queue.Queue()
        self.sound_queue: queue.Queue = queue.Queue()

        self._held_keys: set[int] = set()
        self._frame_count = 0
        self._should_reset = False
        self._prev_buf: list[list[Color]] | None = None
        self._full_frame_pending = True

    # ------------------------------------------------------------------
    # Display interface
    # ------------------------------------------------------------------

    def set_pixel(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self.WIDTH and 0 <= y < self.HEIGHT:
            self._buf[y][x] = color

    def clear(self) -> None:
        self._buf = [[BLACK] * self.WIDTH for _ in range(self.HEIGHT)]

    def render(self) -> None:
        if self._full_frame_pending or self._prev_buf is None:
            msg = self._build_full_frame()
        else:
            msg = self._build_delta()

        try:
            self.frame_queue.put_nowait(msg)
        except queue.Full:
            pass

        self._prev_buf = [list(row) for row in self._buf]
        self._full_frame_pending = False

    def _build_full_frame(self) -> bytes:
        buf = bytearray(1 + self.WIDTH * self.HEIGHT * 4)
        buf[0] = 0x00
        i = 1
        for y in range(self.HEIGHT):
            for x in range(self.WIDTH):
                c = self._buf[y][x]
                buf[i]     = c.r
                buf[i + 1] = c.g
                buf[i + 2] = c.b
                buf[i + 3] = 255
                i += 4
        return bytes(buf)

    def _build_delta(self) -> bytes:
        changed: list[tuple[int, int, Color]] = []
        for y in range(self.HEIGHT):
            cur_row = self._buf[y]
            prev_row = self._prev_buf[y]
            for x in range(self.WIDTH):
                if cur_row[x] != prev_row[x]:
                    changed.append((x, y, cur_row[x]))

        if not changed:
            return b'\x02'

        delta_size = 3 + len(changed) * 5
        full_size = 1 + self.WIDTH * self.HEIGHT * 4
        if delta_size >= full_size:
            return self._build_full_frame()

        buf = bytearray(delta_size)
        buf[0] = 0x01
        buf[1] = (len(changed) >> 8) & 0xFF
        buf[2] = len(changed) & 0xFF
        i = 3
        for x, y, c in changed:
            buf[i]     = x
            buf[i + 1] = y
            buf[i + 2] = c.r
            buf[i + 3] = c.g
            buf[i + 4] = c.b
            i += 5
        return bytes(buf)

    def pump_events(self) -> bool:
        if self._should_reset:
            self._should_reset = False
            self._held_keys.clear()
            self.keys_held = HeldKeysView(set())
            self.clear()
            return False

        self.clicked.clear()
        self.keys_pressed.clear()

        while True:
            try:
                ev = self.input_queue.get_nowait()
            except queue.Empty:
                break
            kind = ev[0]
            if kind == "down":
                code = ev[1]
                if code not in self._held_keys:
                    self.keys_pressed.append(code)
                self._held_keys.add(code)
            elif kind == "up":
                self._held_keys.discard(ev[1])

        self.keys_held = HeldKeysView(self._held_keys)
        return True

    # ------------------------------------------------------------------
    # Server-side helpers (called from the Tornado thread)
    # ------------------------------------------------------------------

    def push_input(self, kind: str, keycode: int) -> None:
        self.input_queue.put((kind, keycode))

    def push_sound(self, name: str) -> None:
        self.sound_queue.put(name)

    def request_reset(self) -> None:
        self._should_reset = True
        self._full_frame_pending = True
