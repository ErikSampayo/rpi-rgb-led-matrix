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

        self._held_keys: set[int] = set()
        self._frame_count = 0

    # ------------------------------------------------------------------
    # Display interface
    # ------------------------------------------------------------------

    def set_pixel(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self.WIDTH and 0 <= y < self.HEIGHT:
            self._buf[y][x] = color

    def clear(self) -> None:
        self._buf = [[BLACK] * self.WIDTH for _ in range(self.HEIGHT)]

    def render(self) -> None:
        buf = bytearray(self.WIDTH * self.HEIGHT * 4)
        i = 0
        for y in range(self.HEIGHT):
            for x in range(self.WIDTH):
                c = self._buf[y][x]
                buf[i]     = c.r
                buf[i + 1] = c.g
                buf[i + 2] = c.b
                buf[i + 3] = 255
                i += 4
        try:
            self.frame_queue.put_nowait(bytes(buf))
        except queue.Full:
            pass

    def pump_events(self) -> bool:
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
