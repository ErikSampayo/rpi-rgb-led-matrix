"""Abstract display interface for a 64x64 grid."""

from abc import ABC, abstractmethod
from typing import NamedTuple


class Color(NamedTuple):
    r: int
    g: int
    b: int

    @classmethod
    def off(cls) -> "Color":
        return cls(0, 0, 0)


BLACK  = Color(0, 0, 0)
WHITE  = Color(255, 255, 255)
RED    = Color(200, 30, 30)
GREEN  = Color(30, 180, 30)
BLUE   = Color(30, 30, 200)
YELLOW = Color(200, 180, 0)
CYAN   = Color(0, 180, 180)
ORANGE = Color(200, 100, 0)
PURPLE = Color(120, 0, 180)
GREY   = Color(80, 80, 80)


class Display(ABC):
    WIDTH  = 64
    HEIGHT = 64

    @abstractmethod
    def set_pixel(self, x: int, y: int, color: Color) -> None:
        """Set a single pixel."""

    @abstractmethod
    def clear(self) -> None:
        """Turn off all pixels."""

    @abstractmethod
    def render(self) -> None:
        """Push current state to display."""

    @abstractmethod
    def pump_events(self) -> bool:
        """Process events. Returns False when the app should quit."""

    def fill_rect(self, x: int, y: int, w: int, h: int, color: Color) -> None:
        for dy in range(h):
            for dx in range(w):
                self.set_pixel(x + dx, y + dy, color)

    def draw_border(self, color: Color) -> None:
        for x in range(self.WIDTH):
            self.set_pixel(x, 0, color)
            self.set_pixel(x, self.HEIGHT - 1, color)
        for y in range(self.HEIGHT):
            self.set_pixel(0, y, color)
            self.set_pixel(self.WIDTH - 1, y, color)
