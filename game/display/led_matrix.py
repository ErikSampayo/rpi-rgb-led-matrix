"""
LED matrix backend for Raspberry Pi.

The key piece you need to fill in is the wiring map: a dict that
translates each axial hex coord (q, r) to a (pixel_x, pixel_y)
address on the LED matrix. This depends entirely on how your tiles
are physically wired.
"""

from .base import Display, Color, BLACK
from game.hex_grid import Hex, hex_range

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
except ImportError:
    from RGBMatrixEmulator import RGBMatrix, RGBMatrixOptions


def build_default_options(rows: int = 64, cols: int = 64) -> RGBMatrixOptions:
    options = RGBMatrixOptions()
    options.rows = rows
    options.cols = cols
    options.brightness = 80
    return options


class LEDMatrixDisplay(Display):
    def __init__(
        self,
        radius: int = 5,
        wiring_map: dict[tuple[int, int], tuple[int, int]] | None = None,
        options: RGBMatrixOptions | None = None,
    ):
        """
        radius      : board radius (must match HexPygameDisplay)
        wiring_map  : {(q, r): (pixel_x, pixel_y)} — fill this in for your board
        options     : RGBMatrixOptions (defaults to 64x64)
        """
        self._matrix = RGBMatrix(options=options or build_default_options())
        self._canvas = self._matrix.CreateFrameCanvas()
        self._radius = radius

        # Build wiring map — replace this with your actual wiring
        self._wiring: dict[Hex, tuple[int, int]] = {}
        if wiring_map:
            for (q, r), (px, py) in wiring_map.items():
                self._wiring[Hex(q, r)] = (px, py)
        else:
            # Placeholder: auto-layout in a grid so something shows up
            # until you supply real wiring coordinates
            _auto_layout(self._wiring, radius)

    # ------------------------------------------------------------------
    # Display interface
    # ------------------------------------------------------------------

    def set_tile(self, q: int, r: int, color: Color) -> None:
        h = Hex(q, r)
        if h in self._wiring:
            px, py = self._wiring[h]
            self._canvas.SetPixel(px, py, color.r, color.g, color.b)

    def clear(self) -> None:
        self._canvas.Clear()

    def render(self) -> None:
        self._canvas = self._matrix.SwapOnVSync(self._canvas)

    def pump_events(self) -> bool:
        # No windowed events on the Pi — handle GPIO here in future
        return True


def _auto_layout(wiring: dict, radius: int) -> None:
    """
    Temporary placeholder layout: packs hex tiles into a grid so the
    LEDMatrixDisplay does *something* before you wire up real coords.
    Replace with actual (pixel_x, pixel_y) values for your board.
    """
    import math
    tiles = list(hex_range(radius))
    cols = math.ceil(math.sqrt(len(tiles)))
    for i, h in enumerate(tiles):
        wiring[h] = (i % cols, i // cols)
