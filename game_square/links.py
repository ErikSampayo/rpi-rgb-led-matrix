"""
Links — connections between bases and batteries (or any two grid points).

A Link owns a path (list of (x,y) pixels) and draws it each frame.
Subclasses can override draw() for different visual styles.

PowerLine: the core link type. Draws a dim static wire with bright
energy pulses traveling from source → destination.
"""

import math
from game_square.display.base import Display, Color

# Links accept any node with connection_point / closest_connection_point
Connectable = object


def _dim(color: Color, factor: float) -> Color:
    return Color(
        int(color.r * factor),
        int(color.g * factor),
        int(color.b * factor),
    )


def _l_path(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Orthogonal L-shaped path: horizontal first, then vertical."""
    pixels = []
    # Horizontal segment
    step = 1 if x1 >= x0 else -1
    for x in range(x0, x1 + step, step):
        pixels.append((x, y0))
    # Vertical segment (skip the corner pixel already added)
    step = 1 if y1 >= y0 else -1
    for y in range(y0 + step, y1 + step, step):
        pixels.append((x1, y))
    return pixels


class Link:
    """
    Base class for all connections on the grid.

    source/destination can be any node with:
      - connection_point -> tuple[int, int]
      - closest_connection_point(target) -> tuple[int, int]

    Subclass and override draw() to create different visual styles.
    """

    def __init__(self, source: Connectable, destination: Connectable):
        self.source      = source
        self.destination = destination
        sx, sy = source.connection_point
        # Pick whichever pin on the destination is closest to the source (Manhattan)
        dx, dy = destination.closest_connection_point((sx, sy))
        self.path        = _l_path(sx, sy, dx, dy)
        self.active  = True   # False = sever/hide the link entirely
        self.powered = True   # False = show wire only, no energy pulses

    def draw(self, display: Display, tick: int) -> None:
        raise NotImplementedError


class PowerLine(Link):
    """
    Draws a dim wire between source and destination.
    Bright pulses travel from battery → base, each representing
    one unit of energy in transit.

    Visual:
      - Wire:   dim faction color at ~15% brightness
      - Pulse:  bright faction color, gaussian falloff, ~3px wide
      - Pulses are tick-based: each starts at position 0 and travels forward.
        When the link first becomes powered, phase_start is set to the current
        tick, so the first pulse visibly launches from the source end.
    """

    PULSE_SPEED   = 0.4    # pixels per tick
    PULSE_SPACING = 20     # ticks between successive pulses (free-running links)
    PULSE_WIDTH   = 2.0    # gaussian sigma in pixels
    WIRE_DIM      = 0.12   # wire brightness
    PULSE_BRIGHT  = 0.95   # pulse peak brightness

    def __init__(self, source: Connectable, destination: Connectable):
        super().__init__(source, destination)
        self._length      = len(self.path)
        self._phase_start: int | None = None  # set when link first powered

        # Gated mode: pulses only launch when queue_pulse() is called
        self.gated        = False
        self._queued: list[int] = []   # list of launch ticks for queued pulses
        self._arrivals_checked_at: int = -1  # last tick we reported arrivals

    def power_on(self, tick: int) -> None:
        """Call when this link transitions from unpowered → powered."""
        self._phase_start = tick

    def queue_pulse(self, tick: int) -> None:
        """
        (Gated links only) Schedule one pulse to launch immediately.
        Call this when the upstream node has energy to spend.
        """
        self._queued.append(tick)

    def check_arrivals(self, tick: int) -> int:
        """
        Return the number of pulses that completed their journey
        since the last call. Resets the counter each call.
        """
        if self._phase_start is None or self._length < 2:
            return 0
        prev = self._arrivals_checked_at
        self._arrivals_checked_at = tick

        count = 0
        if self.gated:
            # Count queued pulses whose position has passed _length
            for launch_tick in self._queued:
                pos = (tick - launch_tick) * self.PULSE_SPEED
                prev_pos = max(0, (prev - launch_tick) * self.PULSE_SPEED) if prev >= 0 else 0
                if prev_pos < self._length <= pos:
                    count += 1
        else:
            elapsed = tick - self._phase_start
            prev_elapsed = max(0, prev - self._phase_start) if prev >= 0 else 0
            i = 0
            while True:
                launch = i * self.PULSE_SPACING
                if launch > elapsed:
                    break
                pos      = (elapsed      - launch) * self.PULSE_SPEED
                prev_pos = (prev_elapsed - launch) * self.PULSE_SPEED if prev_elapsed > launch else 0
                if prev_pos < self._length <= pos:
                    count += 1
                i += 1
        return count

    @property
    def _color(self) -> Color:
        # Prefer destination faction color; fall back to source; then neutral cyan
        for obj in (self.destination, self.source):
            c = getattr(obj, 'color', None) or getattr(obj, 'owner_color', None)
            if c:
                return c
        from game_square.nodes import NEUTRAL_ENERGY
        return NEUTRAL_ENERGY

    def draw(self, display: Display, tick: int) -> None:
        if not self.active or self._length < 2:
            return

        wire_color = _dim(self._color, self.WIRE_DIM)
        for px, py in self.path:
            display.set_pixel(px, py, wire_color)

        if not self.powered or self._phase_start is None:
            return  # unpowered: wire only, no pulses

        # Tick-based pulses: each pulse starts at position 0 when spawned.
        # Pulse i launches at tick = phase_start + i * PULSE_SPACING.
        # Its current position = (tick - launch_tick) * PULSE_SPEED.
        # Pulses that haven't launched yet or have passed the end are skipped.
        def _draw_pulses(launch_ticks):
            for launch_tick in launch_ticks:
                pulse_pos = (tick - launch_tick) * self.PULSE_SPEED
                if pulse_pos < 0:
                    continue
                if pulse_pos > self._length + self.PULSE_WIDTH * 3:
                    continue
                lo = max(0,            int(pulse_pos - self.PULSE_WIDTH * 3))
                hi = min(self._length, int(pulse_pos + self.PULSE_WIDTH * 3) + 1)
                for i in range(lo, hi):
                    dist = abs(i - pulse_pos)
                    factor = self.PULSE_BRIGHT * math.exp(-(dist ** 2) / (2 * self.PULSE_WIDTH ** 2))
                    if factor > 0.04:
                        px, py = self.path[i]
                        display.set_pixel(px, py, _dim(self._color, factor))

        if self.gated:
            _draw_pulses(self._queued)
        else:
            elapsed = tick - self._phase_start
            launch_ticks = []
            i = 0
            while True:
                launch_offset = i * self.PULSE_SPACING
                if launch_offset > elapsed:
                    break
                launch_ticks.append(self._phase_start + launch_offset)
                i += 1
            _draw_pulses(launch_ticks)
