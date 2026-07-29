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
    CAPTURE_MAX    = 100   # ticks to fully capture from neutral
    CAPTURE_RATE   = 0.4   # per tick per net agent (attack)
    GARRISON_RATE  = 0.2   # extra per tick when only friendlies present (no enemy)

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
        # capture: -CAPTURE_MAX..+CAPTURE_MAX
        # negative = player 0 (red), positive = player 1 (blue)
        # 0 = neutral
        self.capture: float = 0.0
        self._casing = _rotate(_BASE_CASING, orientation)
        self._fill   = _rotate(_BASE_FILL,   orientation)
        ndx, ndy     = _rotate([_BASE_NUB],  orientation)[0]
        self._nub    = (ndx, ndy)

    def contest(self, red_agents: int, blue_agents: int) -> bool:
        """
        Push capture value based on contesting agents.  Returns True if the
        battery just flipped (crossed ±CAPTURE_MAX for the first time).

        Garrison bonus: if only one side is present, they get CAPTURE_RATE +
        GARRISON_RATE per agent.  If both sides are present the bonus cancels
        and only the net difference at base CAPTURE_RATE applies.

        Decay: when no agents are contesting, drift back toward neutral.
        """
        prev = self.capture

        if red_agents == 0 and blue_agents == 0:
            return False

        contested = red_agents > 0 and blue_agents > 0
        if contested:
            # Both sides present — base rate only, net difference
            delta = (blue_agents - red_agents) * self.CAPTURE_RATE
        else:
            # Uncontested — garrison bonus applies
            rate = self.CAPTURE_RATE + self.GARRISON_RATE
            delta = (blue_agents - red_agents) * rate

        self.capture = max(-self.CAPTURE_MAX,
                           min( self.CAPTURE_MAX, self.capture + delta))

        just_capped = (abs(self.capture) >= self.CAPTURE_MAX
                       and abs(prev) < self.CAPTURE_MAX)
        if just_capped:
            # Battery is now owned by the capturing side
            self.owner_color = PLAYER_COLORS[0] if self.capture <= -self.CAPTURE_MAX else PLAYER_COLORS[1]
            self.capture = -self.CAPTURE_MAX if self.capture < 0 else self.CAPTURE_MAX
            return True
        return False

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

    @property
    def _capture_color(self) -> Color:
        """Blend between owner colour and attacker colour based on capture progress."""
        frac = abs(self.capture) / self.CAPTURE_MAX   # 0..1
        if frac < 0.01:
            return self._base_color
        # Attacker colour is opposite sign: red pushes negative, blue positive
        attacker = PLAYER_COLORS[1] if self.capture > 0 else PLAYER_COLORS[0]  # blue / red
        base = self._base_color
        return Color(
            int(base.r * (1 - frac) + attacker.r * frac),
            int(base.g * (1 - frac) + attacker.g * frac),
            int(base.b * (1 - frac) + attacker.b * frac),
        )

    def draw(self, display: Display, tick: int) -> None:
        t = tick / 50.0 * 2 * math.pi
        fill_bright = 0.45 + 0.55 * math.sin(t)

        casing_color = _dim(self._base_color, CASING_DIM)

        # Fill pixels show capture progress: captured portion uses attacker colour,
        # remaining portion keeps the owner/neutral pulse.
        frac = abs(self.capture) / self.CAPTURE_MAX
        pulse_color    = _dim(self._base_color,   max(0.2, fill_bright))
        captured_color = _dim(self._capture_color, 0.9)

        for dx, dy in self._casing:
            display.set_pixel(self.x + dx, self.y + dy, casing_color)

        total = len(self._fill)
        for i, (dx, dy) in enumerate(self._fill):
            # Fill pixels drain left-to-right as capture increases
            if total > 1 and i < round(frac * total):
                display.set_pixel(self.x + dx, self.y + dy, captured_color)
            else:
                display.set_pixel(self.x + dx, self.y + dy, pulse_color)


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
    Color( 50, 100, 240),   # player 2 — blue
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

    SPAWN_COST = 5   # energy credits required to spawn one agent

    def __init__(self, x: int, y: int, player: int):
        self.x = x
        self.y = y
        self.color = PLAYER_COLORS[player % len(PLAYER_COLORS)]
        self.energy: int = 0   # accumulated credits from inbound pulses

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

    def can_spawn(self) -> bool:
        return self.energy >= self.SPAWN_COST

    def consume_spawn(self) -> None:
        self.energy = max(0, self.energy - self.SPAWN_COST)

    FLASH_DURATION = 12   # ticks for the spawn flash
    DISSIPATION_DURATION = 14   # ticks for the energy-venting puff

    def trigger_spawn_flash(self) -> None:
        """Start a brief full-bright flash to signal a spawn event."""
        self._flash_ticks = self.FLASH_DURATION

    def trigger_dissipation(self) -> None:
        """Start a venting puff to signal energy dissipating because the
        armory is full but has no usable output path."""
        self._dissipation_ticks = self.DISSIPATION_DURATION

    def draw(self, display: Display, tick: int) -> None:
        flash = getattr(self, '_flash_ticks', 0)
        if flash > 0:
            self._flash_ticks = flash - 1
            # Flash: all shell + centre full white-bright, fading out
            frac = flash / self.FLASH_DURATION          # 1.0 → 0.0
            brightness = 0.4 + 0.6 * frac
            for dx, dy in self._SHELL:
                display.set_pixel(self.x + dx, self.y + dy, _dim(self.color, brightness))
            display.set_pixel(self.x, self.y, _dim(self.color, brightness))
            return

        diss = getattr(self, '_dissipation_ticks', 0)
        if diss > 0:
            self._dissipation_ticks = diss - 1
            # Venting puff: shell pixels glow dim white-grey, radiating
            # outward from centre and fading over the duration.
            frac = diss / self.DISSIPATION_DURATION     # 1.0 → 0.0
            vent = Color(120, 120, 130)
            # Centre brightens then fades
            c_bright = 0.5 * frac
            display.set_pixel(self.x, self.y, _dim(vent, c_bright))
            # Shell: outer pixels brighter early, inner later (radiating out)
            for dx, dy in self._SHELL:
                dist = abs(dx) + abs(dy)            # 1 or 2
                # outer pixels (dist 2) lead the wave, inner (dist 1) lag
                wave = max(0.0, frac - (0.0 if dist == 2 else 0.25))
                display.set_pixel(self.x + dx, self.y + dy,
                                  _dim(vent, 0.45 * wave))
            # Brief sparks 1px beyond the tips during the first half
            if frac > 0.5:
                spark_b = 0.35 * (frac - 0.5) * 2.0
                for tdx, tdy in self._TIPS:
                    display.set_pixel(self.x + tdx, self.y + tdy,
                                      _dim(vent, spark_b))
            return

        # Shell pixels: light up one pip per credit, cap at SPAWN_COST.
        # When full (≥ SPAWN_COST), pulse the centre to signal "ready".
        filled = min(self.energy, self.SPAWN_COST)
        shell_pixels = list(self._SHELL)           # 12 pixels
        pips_total   = len(shell_pixels)           # spread credits across shell
        pips_lit     = round(filled / self.SPAWN_COST * pips_total)
        ready        = self.energy >= self.SPAWN_COST

        for idx, (dx, dy) in enumerate(shell_pixels):
            if idx < pips_lit:
                brightness = 0.6 if not ready else (
                    0.55 + 0.45 * (0.5 + 0.5 * math.sin(tick * 0.18))
                )
            else:
                brightness = 0.08
            display.set_pixel(self.x + dx, self.y + dy, _dim(self.color, brightness))

        centre_bright = (
            0.55 + 0.45 * (0.5 + 0.5 * math.sin(tick * 0.18))
            if ready else 0.25 + 0.15 * (0.5 + 0.5 * math.sin(tick * 0.07))
        )
        display.set_pixel(self.x, self.y, _dim(self.color, centre_bright))
