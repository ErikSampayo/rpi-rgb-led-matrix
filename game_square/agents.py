"""
Agents — single-pixel programs that travel along a link path.

An Agent is spawned by an Armory, given a path to follow, and
travels toward the destination at a fixed speed.

If two agents from different factions occupy the same pixel
they both derezz (alive = False). The game loop is responsible
for checking collisions across all active agents.
"""

import math
from game_square.display.base import Display, Color


def _dim(color: Color, factor: float) -> Color:
    return Color(
        int(color.r * factor),
        int(color.g * factor),
        int(color.b * factor),
    )


class Agent:
    """
    A single program unit traveling along a pre-computed path.

    path   : list of (x, y) pixels from Armory to target
    color  : faction color
    speed  : pixels per tick (fractional)
    """

    SPEED        = 0.3    # pixels per tick
    TRAIL_LEN    = 4      # fading trail behind the agent

    def __init__(self, path: list[tuple[int, int]], color: Color):
        self.path    = path
        self.color   = color
        self.pos     = 0.0          # fractional position along path
        self.alive   = True
        self.arrived = False

    @property
    def pixel(self) -> tuple[int, int] | None:
        """Current integer pixel position, or None if path exhausted."""
        idx = int(self.pos)
        if idx < len(self.path):
            return self.path[idx]
        return None

    def update(self) -> None:
        """Advance the agent along its path."""
        if not self.alive:
            return
        self.pos += self.SPEED
        if self.pos >= len(self.path):
            self.alive   = False
            self.arrived = True

    def derezz(self) -> None:
        """Destroy this agent (collision or severed line)."""
        self.alive = False

    def draw(self, display: Display) -> None:
        if not self.alive:
            return
        idx = int(self.pos)
        # Draw the agent head
        if 0 <= idx < len(self.path):
            display.set_pixel(*self.path[idx], self.color)
        # Draw fading trail behind it
        for t in range(1, self.TRAIL_LEN + 1):
            trail_idx = idx - t
            if 0 <= trail_idx < len(self.path):
                factor = (1.0 - t / (self.TRAIL_LEN + 1)) * 0.5
                display.set_pixel(*self.path[trail_idx], _dim(self.color, factor))


def check_collisions(agents: list[Agent]) -> None:
    """
    Derezz any two living agents from different factions that share a pixel.
    Call once per tick after all agents have been updated.
    """
    living = [a for a in agents if a.alive and a.pixel is not None]
    for i in range(len(living)):
        for j in range(i + 1, len(living)):
            a, b = living[i], living[j]
            if a.color != b.color and a.pixel == b.pixel:
                a.derezz()
                b.derezz()


class DirectedAgent:
    """
    A player-controlled agent that moves freely pixel-by-pixel.

    Spawns at (x, y) and moves continuously in the last direction
    the player pressed.  Steered in real-time; dies on hitting a
    wire, node body, or the grid boundary.
    """

    STEP_TICKS = 3    # ticks between each move
    TRAIL_LEN  = 5

    def __init__(self, x: int, y: int, color: Color):
        self.x      = x
        self.y      = y
        self.color  = color
        self.alive  = True
        self._dir: tuple[int, int] = (0, 0)
        self._trail: list[tuple[int, int]] = []
        self._cooldown = 0

    @property
    def pixel(self) -> tuple[int, int] | None:
        return (self.x, self.y) if self.alive else None

    def steer(self, direction: tuple[int, int]) -> None:
        """Update the movement direction."""
        self._dir = direction

    def update(self, link_pixels: set, node_pixels: set) -> None:
        if not self.alive or self._dir == (0, 0):
            return
        self._cooldown -= 1
        if self._cooldown > 0:
            return
        self._cooldown = self.STEP_TICKS

        nx = self.x + self._dir[0]
        ny = self.y + self._dir[1]

        # Out of bounds
        if not (0 <= nx < 64 and 0 <= ny < 64):
            self.alive = False
            return
        # Hit a wire or node body
        if (nx, ny) in link_pixels or (nx, ny) in node_pixels:
            self.alive = False
            return

        self._trail.append((self.x, self.y))
        if len(self._trail) > self.TRAIL_LEN:
            self._trail.pop(0)
        self.x, self.y = nx, ny

    def derezz(self) -> None:
        self.alive = False

    def draw(self, display: Display) -> None:
        if not self.alive:
            return
        display.set_pixel(self.x, self.y, self.color)
        for i, (tx, ty) in enumerate(reversed(self._trail)):
            factor = (1.0 - (i + 1) / (self.TRAIL_LEN + 1)) * 0.55
            display.set_pixel(tx, ty, _dim(self.color, factor))
