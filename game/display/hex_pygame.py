"""
Pygame hex renderer for development on desktop.

Draws a flat-top hexagonal grid in a pygame window. Each hex tile
is rendered as a filled polygon with a border. Mouse clicks are
translated back to (q, r) and stored in `clicked` for the game loop
to consume.
"""

import math
import pygame
from .base import Display, Color, BLACK
from game.hex_grid import Hex, hex_range


class HexPygameDisplay(Display):
    def __init__(
        self,
        radius: int = 5,
        tile_size: int = 32,
        title: str = "Hex Board",
        bg_color: tuple = (20, 20, 20),
        border_color: tuple = (60, 60, 60),
    ):
        """
        radius    : board radius in tiles (radius 3 → 37 tiles)
        tile_size : pixel radius of each hex
        """
        pygame.init()

        self.radius = radius
        self.tile_size = tile_size
        self.bg_color = bg_color
        self.border_color = border_color

        # All valid tile coords on the board
        self.tiles: dict[Hex, Color] = {h: BLACK for h in hex_range(radius)}

        # Events the game loop can poll
        self.clicked: list[Hex] = []       # tiles clicked this frame
        self.keys_pressed: list[int] = []  # pygame key constants pressed this frame

        # Work out window size from the board extents
        all_centers = [self._hex_to_pixel(h) for h in self.tiles]
        min_x = min(p[0] for p in all_centers) - tile_size
        max_x = max(p[0] for p in all_centers) + tile_size
        min_y = min(p[1] for p in all_centers) - tile_size
        max_y = max(p[1] for p in all_centers) + tile_size
        margin = tile_size
        self._offset_x = -min_x + margin
        self._offset_y = -min_y + margin
        width  = int(max_x - min_x + 2 * margin)
        height = int(max_y - min_y + 2 * margin)

        self._screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(title)
        self._font = pygame.font.SysFont("monospace", max(8, tile_size // 4))

    # ------------------------------------------------------------------
    # Display interface
    # ------------------------------------------------------------------

    def set_tile(self, q: int, r: int, color: Color) -> None:
        h = Hex(q, r)
        if h in self.tiles:
            self.tiles[h] = color

    def clear(self) -> None:
        for h in self.tiles:
            self.tiles[h] = BLACK

    def render(self) -> None:
        self._screen.fill(self.bg_color)
        for h, color in self.tiles.items():
            self._draw_hex(h, color)
        pygame.display.flip()

    def pump_events(self) -> bool:
        self.clicked.clear()
        self.keys_pressed.clear()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return False
            if event.type == pygame.MOUSEBUTTONDOWN:
                h = self._pixel_to_hex(event.pos)
                if h in self.tiles:
                    self.clicked.append(h)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    return False
                self.keys_pressed.append(event.key)
        return True

    # ------------------------------------------------------------------
    # Flat-top hex geometry helpers
    # ------------------------------------------------------------------

    def _hex_to_pixel(self, h: Hex) -> tuple[float, float]:
        """Axial → pixel center (flat-top)."""
        x = self.tile_size * 3 / 2 * h.q
        y = self.tile_size * math.sqrt(3) * (h.r + h.q / 2)
        return x, y

    def _corners(self, cx: float, cy: float) -> list[tuple[float, float]]:
        """6 corner points for a flat-top hex centered at (cx, cy)."""
        return [
            (
                cx + self.tile_size * math.cos(math.radians(60 * i)),
                cy + self.tile_size * math.sin(math.radians(60 * i)),
            )
            for i in range(6)
        ]

    def _draw_hex(self, h: Hex, color: Color) -> None:
        raw_x, raw_y = self._hex_to_pixel(h)
        cx = raw_x + self._offset_x
        cy = raw_y + self._offset_y
        pts = self._corners(cx, cy)
        pygame.draw.polygon(self._screen, color, pts)
        pygame.draw.polygon(self._screen, self.border_color, pts, 1)
        # Optional: draw coords for debugging
        # label = self._font.render(f"{h.q},{h.r}", True, (180, 180, 180))
        # self._screen.blit(label, (cx - label.get_width()//2, cy - label.get_height()//2))

    def _pixel_to_hex(self, pos: tuple[int, int]) -> Hex:
        """Screen pixel → nearest hex using axial rounding."""
        px = pos[0] - self._offset_x
        py = pos[1] - self._offset_y
        q = (2 / 3 * px) / self.tile_size
        r = (-1 / 3 * px + math.sqrt(3) / 3 * py) / self.tile_size
        return _axial_round(q, r)


def _axial_round(q: float, r: float) -> Hex:
    """Round fractional axial coords to nearest hex."""
    s = -q - r
    rq, rr, rs = round(q), round(r), round(s)
    dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs - s)
    if dq > dr and dq > ds:
        rq = -rr - rs
    elif dr > ds:
        rr = -rq - rs
    return Hex(int(rq), int(rr))
