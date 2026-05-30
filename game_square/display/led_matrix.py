"""LED matrix backend — wraps rgbmatrix / RGBMatrixEmulator."""

from .base import Display, Color

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
except ImportError:
    from RGBMatrixEmulator import RGBMatrix, RGBMatrixOptions


class SquareLEDDisplay(Display):
    def __init__(self):
        options = RGBMatrixOptions()
        options.rows = self.HEIGHT
        options.cols = self.WIDTH
        options.brightness = 80
        self._matrix = RGBMatrix(options=options)
        self._canvas = self._matrix.CreateFrameCanvas()

    def set_pixel(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self.WIDTH and 0 <= y < self.HEIGHT:
            self._canvas.SetPixel(x, y, color.r, color.g, color.b)

    def clear(self) -> None:
        self._canvas.Clear()

    def render(self) -> None:
        self._canvas = self._matrix.SwapOnVSync(self._canvas)

    def pump_events(self) -> bool:
        return True
