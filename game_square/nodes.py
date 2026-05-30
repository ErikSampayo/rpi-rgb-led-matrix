"""
Resource nodes for the Tron RTS concept demo.

Each node exposes a draw(display, tick) method so the game loop
only needs to call node.draw(display, tick) once per frame.
"""

import math
from game_square.display.base import Display, Color, BLACK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dim(color: Color, factor: float) -> Color:
    return Color(
        int(color.r * factor),
        int(color.g * factor),
        int(color.b * factor),
    )


# ---------------------------------------------------------------------------
# Energy Node — drawn as a pixel-art battery
#
# Supports 4 orientations: 'up', 'down', 'left', 'right'
# The nub always points in the named direction; connection_point
# returns the nub tip so links always attach correctly.
#
# Base shape (nub up):
#    .X.   <- nub    (y-3)
#   XXX    <- top cap(y-2)
#   X X    <- fill   (y-1)
#   X X    <- fill   (y+0)
#   XXX    <- bot cap(y+1)
# ---------------------------------------------------------------------------

NEUTRAL_ENERGY = Color(0, 220, 180)
CASING_DIM     = 0.25


def _rotate(offsets: list[tuple[int,int]], orientation: str) -> list[tuple[int,int]]:
    """Rotate (dx,dy) offsets for the given orientation (base = nub-up)."""
    if orientation == 'up':
        return offsets
    elif orientation == 'down':
        return [(-dx, -dy) for dx, dy in offsets]
    elif orientation == 'left':
        return [(dy, -dx) for dx, dy in offsets]
    elif orientation == 'right':
        return [(-dy, dx) for dx, dy in offsets]
    return offsets


_BASE_CASING = [
    (0, -3),
    (-1, -2), (0, -2), (1, -2),
    (-1, -1), (1, -1),
    (-1,  0), (1,  0),
    (-1,  1), (0,  1), (1,  1),
]
_BASE_FILL = [(0, -1), (0, 0)]
_BASE_NUB  = (0, -3)   # tip offset when nub faces up


class EnergyNode:
    def __init__(self, x: int, y: int, orientation: str = 'up'):
        """
        orientation: 'up' | 'down' | 'left' | 'right'
        Controls which direction the nub (and connection_point) faces.
        """
        assert orientation in ('up', 'down', 'left', 'right')
        self.x = x
        self.y = y
        self.orientation  = orientation
        self.owner_color: Color | None = None
        self._casing = _rotate(_BASE_CASING, orientation)
        self._fill   = _rotate(_BASE_FILL,   orientation)
        ndx, ndy     = _rotate([_BASE_NUB],  orientation)[0]
        self._nub    = (ndx, ndy)

    @property
    def connection_point(self) -> tuple[int, int]:
        """One pixel beyond the battery nub tip — link starts outside the sprite."""
        ndx, ndy = self._nub
        # Extend one more step in the same outward direction
        sign_x = 1 if ndx > 0 else (-1 if ndx < 0 else 0)
        sign_y = 1 if ndy > 0 else (-1 if ndy < 0 else 0)
        return (self.x + ndx + sign_x, self.y + ndy + sign_y)

    @property
    def _base_color(self) -> Color:
        return self.owner_color if self.owner_color else NEUTRAL_ENERGY

    def draw(self, display: Display, tick: int) -> None:
        t = tick / 50.0 * 2 * math.pi
        fill_bright = 0.45 + 0.55 * math.sin(t)

        fill_color   = _dim(self._base_color, max(0.2, fill_bright))
        casing_color = _dim(self._base_color, CASING_DIM)

        for dx, dy in self._casing:
            display.set_pixel(self.x + dx, self.y + dy, casing_color)

        for dx, dy in self._fill:
            display.set_pixel(self.x + dx, self.y + dy, fill_color)


# ---------------------------------------------------------------------------
# Player Base — drawn as a pixel-art CPU chip
#
# Shape (centered at x, y), total footprint ~7x7px:
#
#    .X.X.        <- top pins    (y-3)
#   XXXXX         <- top edge    (y-2)
#   X   X         <- body        (y-1)
# X X + X X       <- center row  (y+0)  (side pins at x±3)
#   X   X         <- body        (y+1)
#   XXXXX         <- bottom edge (y+2)
#    .X.X.        <- bottom pins (y+3)
#
# Center pixel pulses brightly in faction color.
# Body/pins are dim faction color.
# ---------------------------------------------------------------------------

PLAYER_COLORS = [
    Color(220,  50,  50),   # player 1 — red
    Color( 50, 180, 220),   # player 2 — cyan
    Color(200, 180,   0),   # player 3 — yellow
    Color(160,  50, 220),   # player 4 — purple
]


class PlayerBase:
    _FRAME = (
        # top edge
        (-2, -2), (-1, -2), (0, -2), (1, -2), (2, -2),
        # bottom edge
        (-2,  2), (-1,  2), (0,  2), (1,  2), (2,  2),
        # left/right sides
        (-2, -1), (2, -1),
        (-2,  0), (2,  0),
        (-2,  1), (2,  1),
    )
    # Pin stubs extend to ±3; connection points are one pixel further at ±4
    _PINS = (
        # top pins
        (-1, -3), (1, -3),
        # bottom pins
        (-1,  3), (1,  3),
        # left pins
        (-3, -1), (-3,  1),
        # right pins
        ( 3, -1), ( 3,  1),
    )
    # Connection points: one pixel outward from each pin tip
    _PIN_CONNECTIONS = (
        (-1, -4), (1, -4),
        (-1,  4), (1,  4),
        (-4, -1), (-4,  1),
        ( 4, -1), ( 4,  1),
    )
    _CENTER = (0, 0)

    def __init__(self, x: int, y: int, player: int):
        """player: 0-indexed player number"""
        self.x = x
        self.y = y
        self.color = PLAYER_COLORS[player % len(PLAYER_COLORS)]
        self.energy: int = 0   # energy credits received from inbound battery links

    @property
    def connection_points(self) -> list[tuple[int, int]]:
        """All 8 connection points, one pixel beyond each pin tip."""
        return [(self.x + dx, self.y + dy) for dx, dy in self._PIN_CONNECTIONS]

    def closest_connection_point(self, target: tuple[int, int]) -> tuple[int, int]:
        """Return the connection point nearest to target using Manhattan distance."""
        tx, ty = target
        return min(self.connection_points, key=lambda p: abs(p[0] - tx) + abs(p[1] - ty))

    @property
    def connection_point(self) -> tuple[int, int]:
        """Default connection point (top-left). Use closest_connection_point() for links."""
        return (self.x + self._PIN_CONNECTIONS[0][0], self.y + self._PIN_CONNECTIONS[0][1])

    def draw(self, display: Display, tick: int) -> None:
        # Center pulses quickly like a processor clock
        t = tick / 20.0 * 2 * math.pi
        core_bright = 0.5 + 0.5 * math.sin(t)

        frame_color  = _dim(self.color, 0.3)
        pin_color    = _dim(self.color, 0.2)
        center_color = _dim(self.color, max(0.4, core_bright))

        for dx, dy in self._FRAME:
            display.set_pixel(self.x + dx, self.y + dy, frame_color)
        for dx, dy in self._PINS:
            display.set_pixel(self.x + dx, self.y + dy, pin_color)
        display.set_pixel(self.x + self._CENTER[0], self.y + self._CENTER[1], center_color)

        # Energy visualised by lighting up frame pixels.
        # The 16 frame pixels fill clockwise from top-left as energy rises.
        # Full bar = 10 credits.
        ENERGY_CAP = 10
        FRAME_CLOCKWISE = (
            (-2,-2),(-1,-2),(0,-2),(1,-2),(2,-2),   # top L→R
            (2,-1),(2,0),(2,1),                      # right T→B
            (2,2),(1,2),(0,2),(-1,2),(-2,2),         # bottom R→L
            (-2,1),(-2,0),(-2,-1),                   # left B→T
        )
        lit = round(min(self.energy, ENERGY_CAP) / ENERGY_CAP * len(FRAME_CLOCKWISE))
        for i, (dx, dy) in enumerate(FRAME_CLOCKWISE):
            if i < lit:
                display.set_pixel(self.x + dx, self.y + dy, _dim(self.color, 0.85))
            else:
                display.set_pixel(self.x + dx, self.y + dy, frame_color)


# ---------------------------------------------------------------------------
# Armory (Siren node) — produces agents when charged
#
# Shape (centered at x, y), diamond ~5x5px:
#
#      X        y-2
#     XXX       y-1
#    XX+XX      y+0   (center pulses with charge level)
#     XXX       y+1
#      X        y+2
#
# Connection points at the 4 diamond tips.
# Charges each tick; sets .ready = True for one tick when an agent should spawn.
# ---------------------------------------------------------------------------


class Armory:
    _SHELL = (
        (0, -2),
        (-1, -1), (0, -1), (1, -1),
        (-2,  0), (-1,  0), (1,  0), (2,  0),
        (-1,  1), (0,  1), (1,  1),
        (0,  2),
    )
    # Connection tips one pixel beyond each diamond point
    _TIPS = ((0, -3), (0, 3), (-3, 0), (3, 0))

    CHARGE_TICKS = 80   # ticks to produce one agent

    def __init__(self, x: int, y: int, player: int):
        self.x = x
        self.y = y
        self.color = PLAYER_COLORS[player % len(PLAYER_COLORS)]
        self._charge: int = 0
        self._ready: bool = False

    @property
    def connection_points(self) -> list[tuple[int, int]]:
        return [(self.x + dx, self.y + dy) for dx, dy in self._TIPS]

    def closest_connection_point(self, target: tuple[int, int]) -> tuple[int, int]:
        tx, ty = target
        return min(self.connection_points, key=lambda p: abs(p[0] - tx) + abs(p[1] - ty))

    def output_connection_point(self, input_point: tuple[int, int], target: tuple[int, int]) -> tuple[int, int]:
        """Return the tip closest to target, excluding the tip used as input."""
        tx, ty = target
        return min(
            (p for p in self.connection_points if p != input_point),
            key=lambda p: abs(p[0] - tx) + abs(p[1] - ty),
        )

    @property
    def connection_point(self) -> tuple[int, int]:
        return (self.x, self.y - 3)

    @property
    def ready(self) -> bool:
        """True for exactly one tick when an agent should be spawned."""
        return self._ready

    def update(self) -> None:
        """Call once per game tick to advance charge."""
        self._ready = False
        self._charge += 1
        if self._charge >= self.CHARGE_TICKS:
            self._charge = 0
            self._ready = True

    def draw(self, display: Display, tick: int) -> None:
        charge_frac = self._charge / self.CHARGE_TICKS
        shell_bright  = 0.15 + 0.25 * charge_frac
        pulse_speed   = 0.04 + 0.18 * charge_frac
        t             = tick * pulse_speed * 2 * math.pi
        center_bright = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t))

        shell_color  = _dim(self.color, shell_bright)
        center_color = _dim(self.color, center_bright)

        for dx, dy in self._SHELL:
            display.set_pixel(self.x + dx, self.y + dy, shell_color)
        display.set_pixel(self.x, self.y, center_color)
