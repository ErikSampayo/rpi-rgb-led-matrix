"""
Hex board game entry point.

Run on Windows (dev):
    python -m game.main

Run on Pi (prod):
    python -m game.main --hardware
"""

import argparse
import time
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from game.hex_grid import Hex, hex_range, ring
from game.display.base import Color, RED, GREEN, BLUE, YELLOW, CYAN, ORANGE, WHITE, BLACK


BOARD_RADIUS = 5


def get_display(hardware: bool):
    if hardware:
        from game.display.led_matrix import LEDMatrixDisplay
        return LEDMatrixDisplay(radius=BOARD_RADIUS)
    else:
        from game.display.hex_pygame import HexPygameDisplay
        return HexPygameDisplay(radius=BOARD_RADIUS, tile_size=40)


def demo(display) -> None:
    """
    Demo: sweep a color ring outward from the center.
    Click any tile to highlight it. Press Escape to quit.
    """
    # Muted, earthy palette
    ring_colors = [
        Color(80, 30, 30),   # dark red
        Color(80, 55, 20),   # dark amber
        Color(50, 80, 20),   # dark green
        Color(20, 60, 80),   # dark teal
        Color(30, 30, 80),   # dark blue
        Color(60, 20, 80),   # dark purple
        Color(70, 70, 70),   # grey
    ]
    step = 0
    selected: Hex | None = None

    while True:
        if not display.pump_events():
            break

        # Handle mouse clicks
        for h in getattr(display, "clicked", []):
            selected = h
            print(f"Clicked: {h}")

        # Draw board
        display.clear()

        # Highlight rings with slowly cycling color
        for r in range(BOARD_RADIUS + 1):
            color = ring_colors[(r + step) % len(ring_colors)]
            for h in ring(Hex(0, 0), r):
                display.set_tile(h.q, h.r, color)

        # Highlight selected tile
        if selected:
            display.set_tile(selected.q, selected.r, Color(200, 200, 200))

        display.render()
        step += 1
        time.sleep(0.5)  # slower cycle


def main():
    parser = argparse.ArgumentParser(description="Hex board game")
    parser.add_argument("--hardware", action="store_true",
                        help="Use real LED matrix (Raspberry Pi)")
    args = parser.parse_args()

    display = get_display(args.hardware)
    try:
        demo(display)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
