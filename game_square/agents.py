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
