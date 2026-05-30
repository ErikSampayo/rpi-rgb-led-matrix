"""
64x64 concept demo.

Run on Windows (dev):
    python -m game_square.main

Run on Pi (prod):
    python -m game_square.main --hardware
"""

import argparse
import math
import time
import sys
import os
import random

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from game_square.display.base import Color, BLACK, WHITE
from game_square.nodes import EnergyNode, PlayerBase, Armory
from game_square.links import PowerLine, _l_path
from game_square.agents import Agent, check_collisions


def _dim(color: Color, factor: float) -> Color:
    return Color(int(color.r * factor), int(color.g * factor), int(color.b * factor))

# Player 2 is yellow (index 2 in PLAYER_COLORS)
PLAYER_INDICES = [0, 2]   # red, yellow

# Key bindings: (up, down, left, right)
import pygame
PLAYER_KEYS = [
    (pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d),           # red
    (pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT), # yellow
]

WIRE_STEP_TICKS = 3   # ticks between each pixel step while key held


class WireBuilder:
    """
    Manages one player's growing wire.

    States:
      idle       — waiting; pressing a key picks a random CPU pin and starts
      building   — wire is growing pixel by pixel from the CPU pin
      done       — wire committed or cancelled; goes back to idle next tick
    """

    def __init__(self, base: PlayerBase, keys: tuple):
        self.base   = base
        self.keys   = keys          # (up, down, left, right) pygame key codes
        self.path: list[tuple[int,int]] = []
        self.active = False         # True while growing
        self._cooldown = 0          # ticks until next step allowed

    def _node_pixels(self, connectables) -> set[tuple[int,int]]:
        """All pixels occupied by any node (used for collision)."""
        occupied = set()
        for obj in connectables:
            if isinstance(obj, EnergyNode):
                # bounding box approximation — just mark centre ±3
                for dy in range(-3, 4):
                    for dx in range(-3, 4):
                        occupied.add((obj.x + dx, obj.y + dy))
            elif isinstance(obj, PlayerBase):
                for dx, dy in obj._FRAME + obj._PINS:
                    occupied.add((obj.x + dx, obj.y + dy))
                occupied.add((obj.x, obj.y))
            elif isinstance(obj, Armory):
                for dx, dy in obj._SHELL:
                    occupied.add((obj.x + dx, obj.y + dy))
                occupied.add((obj.x, obj.y))
        return occupied

    def start(self, connectables) -> None:
        """Pick a random free CPU pin and begin building."""
        pins = self.base.connection_points
        self.path = [random.choice(pins)]
        self.active = True
        self._cooldown = 0

    def step(self, direction: tuple[int,int], links: list, connectables) -> str:
        """
        Attempt to grow one pixel in `direction`.
        Returns: 'ok', 'hit_wire', 'hit_node', 'out_of_bounds', 'connected'
        """
        if not self.active or not self.path:
            return 'idle'

        hx, hy = self.path[-1]
        nx, ny = hx + direction[0], hy + direction[1]

        # Out of bounds
        if not (0 <= nx < 64 and 0 <= ny < 64):
            return 'out_of_bounds'

        # Check if we've reached a connection point on another node
        for obj in connectables:
            if obj is self.base:
                continue
            if hasattr(obj, 'connection_points'):
                cps = obj.connection_points
            elif hasattr(obj, 'connection_point'):
                cps = [obj.connection_point]
            else:
                continue
            if (nx, ny) in cps:
                self.path.append((nx, ny))
                return 'connected'

        # Check collision with existing link pixels
        link_pixels: dict[tuple[int,int], PowerLine] = {}
        for lk in links:
            for px, py in lk.path:
                link_pixels[(px, py)] = lk
        if (nx, ny) in link_pixels:
            return 'hit_wire'

        # Check collision with node body pixels (not connection points)
        node_pix = self._node_pixels(connectables)
        if (nx, ny) in node_pix:
            return 'hit_node'

        self.path.append((nx, ny))
        return 'ok'

    def commit(self, connectables, links: list, tick: int) -> PowerLine | None:
        """
        Finalise the path into a PowerLine and return it.
        The last pixel of self.path must be a connection point on some node.
        """
        if len(self.path) < 2:
            return None
        # Find destination node
        end = self.path[-1]
        dest_obj = None
        for obj in connectables:
            if obj is self.base:
                continue
            if hasattr(obj, 'connection_points'):
                cps = obj.connection_points
            elif hasattr(obj, 'connection_point'):
                cps = [obj.connection_point]
            else:
                continue
            if end in cps:
                dest_obj = obj
                break
        if dest_obj is None:
            return None

        lk = PowerLine.__new__(PowerLine)
        lk.source       = self.base
        lk.destination  = dest_obj
        lk.path         = list(self.path)
        lk.active       = True
        lk.powered      = False
        lk._length      = len(lk.path)
        lk._phase_start = None
        lk.gated                = True   # CPU is always the source
        lk._queued              = []
        lk._arrivals_checked_at = -1

        # If the wire reached a battery, flip so EnergyNode is at source
        # and pulses travel battery → CPU (free-running, not gated).
        if isinstance(dest_obj, EnergyNode):
            lk.source, lk.destination = lk.destination, lk.source
            lk.path = list(reversed(lk.path))
            lk.gated = False

        return lk

    def draw(self, display, color: Color) -> None:
        if not self.active or not self.path:
            return
        for i, (px, py) in enumerate(self.path):
            brightness = 0.5 + 0.5 * (i / max(1, len(self.path) - 1))
            display.set_pixel(px, py, _dim(color, brightness))
        # Blink the head
        hx, hy = self.path[-1]
        display.set_pixel(hx, hy, color)


PALETTE = [
    Color(180, 30, 30),
    Color(180, 100, 0),
    Color(140, 160, 0),
    Color(0, 150, 60),
    Color(0, 120, 160),
    Color(40, 40, 160),
    Color(120, 0, 160),
]

NODE_COUNT    = 5
NODE_MARGIN   = 8   # keep nodes away from edges
NODE_MIN_DIST = 14  # minimum distance between any two nodes


def _random_node_positions(count: int, margin: int, min_dist: int) -> list[tuple[int, int]]:
    import random
    ORIENTATIONS = ('up', 'down', 'left', 'right')
    positions = []
    attempts  = 0
    while len(positions) < count and attempts < 10_000:
        x = random.randint(margin, 63 - margin)
        y = random.randint(margin, 63 - margin)
        if all(abs(x - px) + abs(y - py) >= min_dist for px, py, _ in positions):
            positions.append((x, y, random.choice(ORIENTATIONS)))
        attempts += 1
    return positions


def get_display(hardware: bool):
    if hardware:
        from game_square.display.led_matrix import SquareLEDDisplay
        return SquareLEDDisplay()
    else:
        from game_square.display.square_pygame import SquarePygameDisplay
        return SquarePygameDisplay(pixel_size=10)


# ---------------------------------------------------------------------------
# Simple ripple demo
# ---------------------------------------------------------------------------

class Ripple:
    def __init__(self, x: int, y: int, color: Color):
        self.x = x
        self.y = y
        self.color = color
        self.age = 0.0          # in ticks
        self.max_age = 40.0     # fade out after this many ticks
        self.speed = 0.6        # pixels per tick

    @property
    def alive(self) -> bool:
        return self.age < self.max_age

    def radius(self) -> float:
        return self.age * self.speed

    def brightness(self) -> float:
        return max(0.0, 1.0 - self.age / self.max_age)

    def tick(self):
        self.age += 1


def draw_ripple(display, ripple: Ripple) -> None:
    r = ripple.radius()
    b = ripple.brightness()
    c = Color(
        int(ripple.color.r * b),
        int(ripple.color.g * b),
        int(ripple.color.b * b),
    )
    thickness = 1.5
    # Draw a ring at radius r
    for angle_deg in range(0, 360, 2):
        angle = math.radians(angle_deg)
        for dr in [-thickness, 0, thickness]:
            pr = r + dr
            px = int(round(ripple.x + pr * math.cos(angle)))
            py = int(round(ripple.y + pr * math.sin(angle)))
            display.set_pixel(px, py, c)


def _place_one_player(display, player: int, nodes: list, already_placed: list, tick_ref: list) -> tuple:
    """
    Two-step placement for a single player: CPU base then Armory.
    already_placed: list of (base, armory) tuples for players already placed (drawn as bg).
    tick_ref: [tick] mutable so tick persists across calls.
    Returns (PlayerBase, Armory) or (None, None) on quit.
    """
    ghost_base   = PlayerBase(0, 0, player)
    ghost_armory = Armory(0, 0, player)
    placed_base  = None

    def draw_bg(t):
        display.clear()
        for node in nodes:
            node.draw(display, t)
        for b, a in already_placed:
            b.draw(display, t)
            a.draw(display, t)

    # Phase 1: place CPU base
    while placed_base is None:
        if not display.pump_events():
            return None, None
        mx, my = getattr(display, "mouse_pos", (32, 32))
        ghost_base.x, ghost_base.y = mx, my
        draw_bg(tick_ref[0])
        ghost_base.draw(display, tick_ref[0])
        display.render()
        tick_ref[0] += 1
        time.sleep(0.04)
        for (cx, cy) in getattr(display, "clicked", []):
            placed_base = PlayerBase(cx, cy, player)

    # Phase 2: place Armory
    placed_armory = None
    while placed_armory is None:
        if not display.pump_events():
            return None, None
        mx, my = getattr(display, "mouse_pos", (32, 32))
        ghost_armory.x, ghost_armory.y = mx, my
        draw_bg(tick_ref[0])
        placed_base.draw(display, tick_ref[0])
        ghost_armory.draw(display, tick_ref[0])
        display.render()
        tick_ref[0] += 1
        time.sleep(0.04)
        for (cx, cy) in getattr(display, "clicked", []):
            placed_armory = Armory(cx, cy, player)

    return placed_base, placed_armory


def placement_phase(display, nodes: list) -> tuple:
    """
    Sequential placement for both players.
    Returns ((base0, armory0), (base1, armory1)) or (None, None) on quit.
    """
    tick_ref = [0]

    base0, armory0 = _place_one_player(display, PLAYER_INDICES[0], nodes, [], tick_ref)
    if base0 is None:
        return None, None

    base1, armory1 = _place_one_player(display, PLAYER_INDICES[1], nodes, [(base0, armory0)], tick_ref)
    if base1 is None:
        return None, None

    return (base0, armory0), (base1, armory1)


def _update_power(links: list, tick: int = 0) -> None:
    """
    Propagate power through the link graph.
    EnergyNodes are always powered regardless of which end of a link they're on.
    Power flows in both directions from an EnergyNode.
    Calls link.power_on(tick) the first time a link becomes powered.
    """
    from game_square.nodes import EnergyNode as _EN
    # EnergyNodes are unconditionally powered; seed both ends of any link touching one
    powered_objs: set = set()
    for link in links:
        if isinstance(link.source, _EN):
            powered_objs.add(link.source)
            powered_objs.add(link.destination)
        if isinstance(link.destination, _EN):
            powered_objs.add(link.destination)
            powered_objs.add(link.source)
    # Propagate downstream: if a link's source is powered, destination becomes powered
    changed = True
    while changed:
        changed = False
        for link in links:
            if link.source in powered_objs and link.destination not in powered_objs:
                powered_objs.add(link.destination)
                changed = True
            # Also propagate backwards through battery-adjacent links
            if link.destination in powered_objs and link.source not in powered_objs:
                if isinstance(link.destination, _EN) or isinstance(link.source, _EN):
                    powered_objs.add(link.source)
                    changed = True
    for link in links:
        newly_powered = (not link.powered) and (
            link.source in powered_objs or link.destination in powered_objs
        )
        link.powered = (link.source in powered_objs)
        if newly_powered:
            link.power_on(tick)


PIN_SNAP = 5   # max Manhattan distance to snap to a pin


def _all_pins(connectables: list) -> list[tuple[tuple[int,int], object]]:
    """Return [(pin_xy, owner), ...] for every connection point on every connectable."""
    result = []
    for obj in connectables:
        if hasattr(obj, 'connection_points'):
            for pin in obj.connection_points:
                result.append((pin, obj))
        elif hasattr(obj, 'connection_point'):
            result.append((obj.connection_point, obj))
    return result


def _nearest_pin(px: int, py: int, all_pins: list, exclude_owner=None):
    """Return (pin_xy, owner) of the closest pin, or None if nothing within PIN_SNAP."""
    best, best_dist = None, PIN_SNAP + 1
    for pin, owner in all_pins:
        if owner is exclude_owner:
            continue
        d = abs(pin[0] - px) + abs(pin[1] - py)
        if d < best_dist:
            best_dist, best = d, (pin, owner)
    return best


def _draw_ghost_line(display, x0: int, y0: int, x1: int, y1: int, color: Color) -> None:
    """Draw a dim L-shaped preview line."""
    for px, py in _l_path(x0, y0, x1, y1):
        display.set_pixel(px, py, color)


def demo(display) -> None:
    W, H = display.WIDTH, display.HEIGHT
    tick = 0

    nodes = [EnergyNode(x, y, orientation) for x, y, orientation in _random_node_positions(NODE_COUNT, NODE_MARGIN, NODE_MIN_DIST)]

    # Placement phase — both players place their base and armory
    result = placement_phase(display, nodes)
    if result[0] is None:
        return
    (base0, armory0), (base1, armory1) = result

    bases   = [base0, base1]
    armories = [armory0, armory1]

    links: list[PowerLine] = []
    agents: list[Agent] = []

    # One WireBuilder per player, keyed to their base
    wire_builders = [
        WireBuilder(base0, PLAYER_KEYS[0]),
        WireBuilder(base1, PLAYER_KEYS[1]),
    ]

    while True:
        if not display.pump_events():
            break

        connectables = nodes + bases + armories
        keys = getattr(display, 'keys_pressed', [])

        # --- Keyboard wire building ---
        for wb in wire_builders:
            up, down, left, right = wb.keys
            direction = None
            if up    in keys: direction = ( 0, -1)
            elif down  in keys: direction = ( 0,  1)
            elif left  in keys: direction = (-1,  0)
            elif right in keys: direction = ( 1,  0)

            if direction is not None:
                if not wb.active:
                    wb.start(connectables)
                elif wb._cooldown <= 0:
                    result = wb.step(direction, links, connectables)
                    if result == 'connected':
                        new_link = wb.commit(connectables, links, tick)
                        if new_link:
                            links.append(new_link)
                            _update_power(links, tick)
                        wb.active = False
                        wb.path = []
                    elif result == 'hit_wire':
                        # Sever the wire that was hit
                        hit_px = (wb.path[-1][0] + direction[0],
                                  wb.path[-1][1] + direction[1])
                        links = [lk for lk in links
                                 if hit_px not in lk.path]
                        _update_power(links, tick)
                        wb.active = False
                        wb.path = []
                    elif result in ('hit_node', 'out_of_bounds'):
                        wb.active = False
                        wb.path = []
                    else:   # 'ok'
                        wb._cooldown = WIRE_STEP_TICKS
            if wb._cooldown > 0:
                wb._cooldown -= 1

        # --- CPU energy buffering ---
        # Inbound battery→CPU links: count newly arrived pulses and credit the base.
        for lk in links:
            if isinstance(lk.destination, PlayerBase) and lk.powered:
                lk.destination.energy += lk.check_arrivals(tick)
        # Outbound CPU→* gated links: spend one energy credit per link per tick.
        for base in bases:
            for lk in links:
                if lk.source is base and lk.gated and lk.powered and base.energy > 0:
                    lk.queue_pulse(tick)
                    base.energy -= 1

        # --- Update armories and spawn agents ---
        for arm in armories:
            fed = any(lk.powered and (lk.destination is arm or lk.source is arm) for lk in links)
            if fed:
                arm.update()
            if arm.ready:
                # Find any powered link touching this armory and use it as the
                # travel path — oriented so agents depart FROM the armory.
                spawn_path = None
                for lk in links:
                    if not lk.powered:
                        continue
                    if lk.source is arm:
                        spawn_path = list(lk.path)
                        break
                    if lk.destination is arm:
                        spawn_path = list(reversed(lk.path))
                        break
                if spawn_path and len(spawn_path) > 1:
                    owner = bases[armories.index(arm)]
                    agents.append(Agent(path=spawn_path, color=owner.color))

        for agent in agents:
            agent.update()
        check_collisions(agents)
        agents = [a for a in agents if a.alive]

        # --- Draw ---
        display.clear()

        for link in links:
            link.draw(display, tick)

        for wb in wire_builders:
            if wb.active:
                wb.draw(display, wb.base.color)

        for node in nodes:
            node.draw(display, tick)
        for arm in armories:
            arm.draw(display, tick)
        for base in bases:
            base.draw(display, tick)

        for agent in agents:
            agent.draw(display)

        display.render()
        tick += 1
        time.sleep(0.04)


def main():
    parser = argparse.ArgumentParser(description="64x64 concept demo")
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
