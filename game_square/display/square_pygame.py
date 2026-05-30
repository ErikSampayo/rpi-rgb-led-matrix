"""
Pygame renderer for a 64x64 pixel grid.

Each logical pixel is drawn as a square scaled up for visibility.
Mouse clicks translate back to grid (x, y) coordinates.
"""

import pygame
from .base import Display, Color, BLACK


class SquarePygameDisplay(Display):
    def __init__(self, pixel_size: int = 10, title: str = "64x64 Matrix"):
        """
        pixel_size : how many screen pixels each matrix pixel occupies
        """
        pygame.init()
        self.pixel_size = pixel_size
        self._buf: list[list[Color]] = [
            [BLACK] * self.WIDTH for _ in range(self.HEIGHT)
        ]
        self.clicked: list[tuple[int, int]] = []
        self.keys_pressed: list[int] = []
        self.keys_held = None   # pygame key state sequence, updated each frame
        self.mouse_pos: tuple[int, int] = (0, 0)   # current grid position of mouse

        w = self.WIDTH  * pixel_size
        h = self.HEIGHT * pixel_size
        self._screen = pygame.display.set_mode((w, h))
        pygame.display.set_caption(title)

    # ------------------------------------------------------------------
    # Display interface
    # ------------------------------------------------------------------

    def set_pixel(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self.WIDTH and 0 <= y < self.HEIGHT:
            self._buf[y][x] = color

    def clear(self) -> None:
        for y in range(self.HEIGHT):
            for x in range(self.WIDTH):
                self._buf[y][x] = BLACK

    def render(self) -> None:
        ps = self.pixel_size
        for y in range(self.HEIGHT):
            for x in range(self.WIDTH):
                c = self._buf[y][x]
                rect = (x * ps, y * ps, ps, ps)
                pygame.draw.rect(self._screen, c, rect)
                if ps > 4:
                    # thin grid lines for readability
                    pygame.draw.rect(self._screen, (20, 20, 20), rect, 1)
        pygame.display.flip()

    def pump_events(self) -> bool:
        self.clicked.clear()
        self.keys_pressed.clear()
        # Snapshot all currently held keys
        self.keys_held = pygame.key.get_pressed()
        # Update mouse pos every frame from current cursor position
        mx, my = pygame.mouse.get_pos()
        self.mouse_pos = (
            max(0, min(self.WIDTH  - 1, mx // self.pixel_size)),
            max(0, min(self.HEIGHT - 1, my // self.pixel_size)),
        )
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    return False
                self.keys_pressed.append(event.key)
            if event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                gx = mx // self.pixel_size
                gy = my // self.pixel_size
                if 0 <= gx < self.WIDTH and 0 <= gy < self.HEIGHT:
                    self.clicked.append((gx, gy))
        return True
