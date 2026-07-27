"""
Agents — single-pixel programs that travel along a link path.

An Agent is spawned by an Armory, given a path to follow, and
travels toward the destination at a fixed speed.

If two agents from different factions occupy the same pixel
they both derezz (alive = False). The game loop is responsible
for checking collisions across all active agents.
"""

import math
from game_square.display.base import Display, Color


def _dim(color: Color, factor: float) -> Color:
    return Color(
        int(color.r * factor),
        int(color.g * factor),
        int(color.b * factor),
    )


class Agent:
    """
    A single program unit traveling along a pre-computed path.

    path   : list of (x, y) pixels from Armory to target
    color  : faction color
    speed  : pixels per tick (fractional)
    """

    SPEED        = 0.3    # pixels per tick
    TRAIL_LEN    = 4      # fading trail behind the agent
    OSC_TICKS    = 6
    SHOT_COOLDOWN = 18

    def __init__(self, path: list[tuple[int, int]], color: Color):
        self.path    = path
        self.color   = color
        self.pos     = 0.0          # fractional position along path
        self.alive   = True
        self.arrived = False

        # Contesting state (populated when path end is reached)
        self.contesting = False
        self._contest_battery = None
        self._dir: tuple[int, int] = (0, 0)
        self._hover_base: tuple[int, int] = path[-1] if path else (0, 0)
        self._perp: tuple[int, int] = (0, 1)
        self._osc_offset = 0
        self._osc_dir    = 1
        self._osc_cd     = 0
        self._shot_cd    = 0
        self._shots: list[list[int]] = []
        self.x, self.y   = path[0] if path else (0, 0)
        self._trail: list[tuple[int, int]] = []

    @property
    def pixel(self) -> tuple[int, int] | None:
        """Current integer pixel position, or None if path exhausted."""
        if self.contesting:
            return (self.x, self.y) if self.alive else None
        idx = int(self.pos)
        if idx < len(self.path):
            return self.path[idx]
        return None

    MAX_PER_HOVER = 3   # agents allowed to share the same hover base
    MAX_CONTENDING = 6  # total agents contesting a single battery

    def _battery_perimeter(self, battery) -> list[tuple[int, int]]:
        """Return all in-bounds pixels adjacent to the battery sprite but outside it."""
        bat_pixels: set[tuple[int, int]] = set()
        bat_pixels.add((battery.x, battery.y))
        for ddx, ddy in battery._casing:
            bat_pixels.add((battery.x + ddx, battery.y + ddy))
        for ddx, ddy in battery._fill:
            bat_pixels.add((battery.x + ddx, battery.y + ddy))
        bat_pixels.add((battery.x + battery._nub[0], battery.y + battery._nub[1]))
        perimeter: set[tuple[int, int]] = set()
        for bpx, bpy in bat_pixels:
            for ox, oy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                candidate = (bpx + ox, bpy + oy)
                if candidate not in bat_pixels and 0 <= candidate[0] < 64 and 0 <= candidate[1] < 64:
                    perimeter.add(candidate)
        return list(perimeter)

    def _enter_contest(self, battery_pixel_map: dict,
                       contesting_agents: list | None = None) -> bool:
        """Derive hover position and battery from path end; enter contesting mode."""
        if len(self.path) < 2:
            return False
        hx, hy = self.path[-1]
        px2, py2 = self.path[-2]
        dx = hx - px2
        dy = hy - py2
        # Normalise to unit step
        length = max(abs(dx), abs(dy), 1)
        dx //= length
        dy //= length
        self._dir = (dx, dy)
        # Battery is one step ahead
        bx, by = hx + dx, hy + dy
        battery = battery_pixel_map.get((bx, by))
        if battery is None:
            return False
        self._contest_battery = battery
        # Check if battery is already at capacity
        if contesting_agents:
            current = sum(
                1 for other in contesting_agents
                if other is not self
                and getattr(other, 'contesting', False)
                and getattr(other, '_contest_battery', None) is battery
            )
            if current >= self.MAX_CONTENDING:
                return False
        # Choose a hover position on the battery perimeter with fewest occupants.
        natural_hover = (hx, hy)
        if contesting_agents:
            perimeter = self._battery_perimeter(battery)
            if not perimeter:
                perimeter = [natural_hover]
            # Count how many agents already hover from each perimeter pixel.
            occupancy: dict[tuple[int, int], int] = {p: 0 for p in perimeter}
            for other in contesting_agents:
                if other is self:
                    continue
                if getattr(other, 'contesting', False) \
                        and getattr(other, '_contest_battery', None) is battery:
                    hb = getattr(other, '_hover_base', None)
                    if hb in occupancy:
                        occupancy[hb] += 1
            # Prefer the natural hover spot; fall back to least-occupied spot.
            if occupancy.get(natural_hover, 0) < self.MAX_PER_HOVER:
                chosen = natural_hover
            else:
                chosen = min(perimeter, key=lambda p: occupancy.get(p, 0))
        else:
            chosen = natural_hover
        hx, hy = chosen
        # Derive perp from chosen hover offset relative to battery centre.
        chx = hx - battery.x
        chy = hy - battery.y
        # Direction pointing inward toward battery
        if abs(chx) >= abs(chy):
            self._dir  = (1 if chx < 0 else -1, 0)
            self._perp = (0, 1)
        else:
            self._dir  = (0, 1 if chy < 0 else -1)
            self._perp = (1, 0)
        self._hover_base = (hx, hy)
        self.x, self.y   = hx, hy
        self._osc_offset = 0
        self._osc_dir    = 1
        self._osc_cd     = self.OSC_TICKS
        self._shot_cd    = self.SHOT_COOLDOWN // 2
        self._trail.clear()
        self.contesting  = True
        return True

    def update(self, wire_pixels: set | None = None,
               battery_pixel_map: dict | None = None,
               contesting_agents: list | None = None) -> None:
        """Advance the agent along its path, then contest."""
        if not self.alive:
            return

        if self.contesting:
            # --- Oscillate ---
            self._osc_cd -= 1
            if self._osc_cd <= 0:
                self._osc_cd = self.OSC_TICKS
                new_offset = self._osc_offset + self._osc_dir
                if abs(new_offset) > 1:
                    self._osc_dir  = -self._osc_dir
                    new_offset     = self._osc_offset + self._osc_dir
                bx, by = self._hover_base
                px = bx + self._perp[0] * new_offset
                py = by + self._perp[1] * new_offset
                if 0 <= px < 64 and 0 <= py < 64:
                    self._osc_offset = new_offset
                    self.x, self.y   = px, py
            # --- Shoot ---
            self._shot_cd -= 1
            if self._shot_cd <= 0:
                self._shot_cd = self.SHOT_COOLDOWN
                bat = self._contest_battery
                sdx = 0 if self._dir[0] == 0 else (1 if bat.x > self.x else -1)
                sdy = 0 if self._dir[1] == 0 else (1 if bat.y > self.y else -1)
                self._shots.append([self.x, self.y, sdx, sdy])
            # Advance shots
            next_shots = []
            for shot in self._shots:
                sx, sy, sdx, sdy = shot
                sx += sdx
                sy += sdy
                bat = self._contest_battery
                bat_pixels = (
                    {(bat.x + ddx, bat.y + ddy) for ddx, ddy in bat._casing}
                    | {(bat.x + ddx, bat.y + ddy) for ddx, ddy in bat._fill}
                    | {(bat.x + bat._nub[0], bat.y + bat._nub[1])}
                )
                if 0 <= sx < 64 and 0 <= sy < 64:
                    next_shots.append([sx, sy, sdx, sdy])
                    if (sx, sy) not in bat_pixels and (sx, sy) != (bat.x, bat.y):
                        next_shots.pop()
            self._shots = next_shots
            return

        # --- Travelling along path ---
        self.pos += self.SPEED
        # Die if the current head pixel overlaps a wire
        if wire_pixels:
            px = self.pixel
            if px is not None and px in wire_pixels:
                self.alive = False
                return
        if self.pos >= len(self.path):
            # Reached path end — try to enter contesting state
            if battery_pixel_map is not None and self._enter_contest(battery_pixel_map, contesting_agents):
                self.arrived = True
            else:
                self.alive   = False
                self.arrived = True
        else:
            # Update trail from path position
            idx = int(self.pos)
            if 0 <= idx < len(self.path):
                self.x, self.y = self.path[idx]

    def derezz(self) -> None:
        """Destroy this agent (collision or severed line)."""
        self.alive = False

    def draw(self, display: Display) -> None:
        if not self.alive:
            return
        if self.contesting:
            display.set_pixel(self.x, self.y, self.color)
            # Draw shots
            for shot in self._shots:
                display.set_pixel(shot[0], shot[1], _dim(self.color, 0.9))
            return
        idx = int(self.pos)
        # Draw the agent head
        if 0 <= idx < len(self.path):
            display.set_pixel(*self.path[idx], self.color)
        # Draw fading trail behind it
        for t in range(1, self.TRAIL_LEN + 1):
            trail_idx = idx - t
            if 0 <= trail_idx < len(self.path):
                factor = (1.0 - t / (self.TRAIL_LEN + 1)) * 0.5
                display.set_pixel(*self.path[trail_idx], _dim(self.color, factor))


def check_collisions(agents: list[Agent]) -> None:
    """
    Derezz any two living agents from different factions that share a pixel.
    Call once per tick after all agents have been updated.
    """
    living = [a for a in agents if a.alive and a.pixel is not None]
    for i in range(len(living)):
        for j in range(i + 1, len(living)):
            a, b = living[i], living[j]
            if a.color != b.color and a.pixel == b.pixel:
                a.derezz()
                b.derezz()


class DirectedAgent:
    """
    A player-controlled agent that moves freely pixel-by-pixel.

    States:
      moving     — travelling in _dir; dies on wire/node/boundary
      contesting — reached a battery; hovers outside it and fires shots in
    """

    STEP_TICKS    = 3    # ticks between movement steps (moving state)
    TRAIL_LEN     = 5
    OSC_TICKS     = 6    # ticks between oscillation steps (contesting state)
    SHOT_COOLDOWN = 18   # ticks between shots
    SHOT_SPEED    = 1    # pixels per tick (integer)
    MAX_CONTENDING = 6  # total agents contesting a single battery

    def __init__(self, x: int, y: int, color: Color):
        self.x      = x
        self.y      = y
        self.color  = color
        self.alive  = True
        self._dir: tuple[int, int] = (0, 0)
        self._trail: list[tuple[int, int]] = []
        self._cooldown = 0
        self.full_path: list[tuple[int, int]] = [(x, y)]  # every pixel visited
        self.source_armory = None   # set by game loop to track which armory spawned this
        self.launch_dir: tuple[int, int] = (0, 0)  # direction this agent was launched from

        # Contesting state
        self.contesting = False
        self._contest_battery = None   # EnergyNode being contested
        self._hover_base: tuple[int,int] = (x, y)
        self._perp: tuple[int,int] = (0, 1)
        self._osc_offset  = 0    # current offset along perp axis (-1, 0, 1)
        self._osc_dir     = 1    # +1 or -1
        self._osc_cd      = 0
        self._shot_cd     = 0
        # Each shot: [sx, sy, step_dx, step_dy]
        self._shots: list[list[int]] = []

    @property
    def pixel(self) -> tuple[int, int] | None:
        return (self.x, self.y) if self.alive else None

    def steer(self, direction: tuple[int, int]) -> None:
        if not self.contesting:
            self._dir = direction

    def _enter_contest(self, battery, contesting_agents=None) -> bool:
        """Switch to contesting mode, hovering just outside `battery`.
        Returns False if the battery is at capacity (agent dies instead)."""
        if contesting_agents:
            current = sum(
                1 for other in contesting_agents
                if other is not self
                and getattr(other, 'contesting', False)
                and getattr(other, '_contest_battery', None) is battery
            )
            if current >= self.MAX_CONTENDING:
                return False
        self.contesting      = True
        self._contest_battery = battery
        self._hover_base     = (self.x, self.y)
        self._trail.clear()
        # Perpendicular to approach direction
        dx, dy = self._dir
        self._perp = (abs(dy), abs(dx))   # (0,1)↔(1,0) swap
        self._osc_offset = 0
        self._osc_dir    = 1
        self._osc_cd     = self.OSC_TICKS
        self._shot_cd    = self.SHOT_COOLDOWN // 2   # first shot comes quickly

    def update(self, link_pixels: set, node_pixels: set,
               battery_pixel_map: dict | None = None,
               contesting_agents: list | None = None) -> None:
        if not self.alive:
            return

        if battery_pixel_map is None:
            battery_pixel_map = {}

        if not self.contesting:
            # --- Moving state ---
            if self._dir == (0, 0):
                return
            self._cooldown -= 1
            if self._cooldown > 0:
                return
            self._cooldown = self.STEP_TICKS

            nx = self.x + self._dir[0]
            ny = self.y + self._dir[1]

            if not (0 <= nx < 64 and 0 <= ny < 64):
                self.alive = False
                return
            if (nx, ny) in link_pixels or (nx, ny) in node_pixels:
                self.alive = False
                return
            if (nx, ny) in battery_pixel_map:
                # Reached a battery — stay here and start contesting
                if not self._enter_contest(battery_pixel_map[(nx, ny)], contesting_agents):
                    self.alive = False
                return

            self._trail.append((self.x, self.y))
            if len(self._trail) > self.TRAIL_LEN:
                self._trail.pop(0)
            self.x, self.y = nx, ny
            self.full_path.append((self.x, self.y))

        else:
            # --- Contesting state: oscillate and shoot ---
            # Oscillate along perp axis
            self._osc_cd -= 1
            if self._osc_cd <= 0:
                self._osc_cd = self.OSC_TICKS
                new_offset = self._osc_offset + self._osc_dir
                if abs(new_offset) > 1:
                    self._osc_dir   = -self._osc_dir
                    new_offset      = self._osc_offset + self._osc_dir
                bx, by = self._hover_base
                px = bx + self._perp[0] * new_offset
                py = by + self._perp[1] * new_offset
                if 0 <= px < 64 and 0 <= py < 64:
                    self._osc_offset = new_offset
                    self.x, self.y = px, py

            # Fire a shot toward the battery center
            self._shot_cd -= 1
            if self._shot_cd <= 0:
                self._shot_cd = self.SHOT_COOLDOWN
                bat = self._contest_battery
                sdx = 0 if self._dir[0] == 0 else (1 if bat.x > self.x else -1)
                sdy = 0 if self._dir[1] == 0 else (1 if bat.y > self.y else -1)
                self._shots.append([self.x, self.y, sdx, sdy])

            # Advance shots
            next_shots = []
            for shot in self._shots:
                sx, sy, sdx, sdy = shot
                sx += sdx
                sy += sdy
                # Keep shot alive while it's still inside the battery area
                bat = self._contest_battery
                bat_pixels = (
                    {(bat.x + ddx, bat.y + ddy) for ddx, ddy in bat._casing}
                    | {(bat.x + ddx, bat.y + ddy) for ddx, ddy in bat._fill}
                    | {(bat.x + bat._nub[0], bat.y + bat._nub[1])}
                )
                if 0 <= sx < 64 and 0 <= sy < 64:
                    next_shots.append([sx, sy, sdx, sdy])
                    if (sx, sy) not in bat_pixels and (sx, sy) != (bat.x, bat.y):
                        next_shots.pop()   # left the battery region — discard
            self._shots = next_shots

    def derezz(self) -> None:
        self.alive = False

    def draw(self, display: Display) -> None:
        if not self.alive:
            return
        display.set_pixel(self.x, self.y, self.color)
        for i, (tx, ty) in enumerate(reversed(self._trail)):
            factor = (1.0 - (i + 1) / (self.TRAIL_LEN + 1)) * 0.55
            display.set_pixel(tx, ty, _dim(self.color, factor))
        # Draw shots as bright pixels
        for shot in self._shots:
            sx, sy = shot[0], shot[1]
            display.set_pixel(sx, sy, _dim(self.color, 0.9))

