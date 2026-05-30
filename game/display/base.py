"""Abstract display interface. Game logic only talks to this."""

from abc import ABC, abstractmethod
from typing import NamedTuple


class Color(NamedTuple):
    r: int
    g: int
    b: int

    @classmethod
    def off(cls) -> "Color":
        return cls(0, 0, 0)


# A few named colors for convenience
BLACK  = Color(0, 0, 0)
WHITE  = Color(255, 255, 255)
RED    = Color(255, 0, 0)
GREEN  = Color(0, 255, 0)
BLUE   = Color(0, 0, 255)
YELLOW = Color(255, 220, 0)
CYAN   = Color(0, 255, 255)
ORANGE = Color(255, 120, 0)


class Display(ABC):
    """
    Backend-agnostic display interface.

    All coordinates are axial hex (q, r). Backends translate
    these to pixels, LEDs, or whatever the hardware requires.
    """

    @abstractmethod
    def set_tile(self, q: int, r: int, color: Color) -> None:
        """Set the color of a single hex tile."""

    @abstractmethod
    def clear(self) -> None:
        """Turn off all tiles."""

    @abstractmethod
    def render(self) -> None:
        """Push the current state to the display."""

    @abstractmethod
    def pump_events(self) -> bool:
        """
        Process input events. Returns False if the app should quit,
        True otherwise. Call once per game loop tick.
        """

    def set_tiles(self, tiles: dict[tuple[int, int], Color]) -> None:
        """Convenience: set multiple tiles at once."""
        for (q, r), color in tiles.items():
            self.set_tile(q, r, color)
