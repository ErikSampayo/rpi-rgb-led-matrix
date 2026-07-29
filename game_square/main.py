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
from game_square.agents import Agent, check_collisions, DirectedAgent


def _dim(color: Color, factor: float) -> Color:
    return Color(int(color.r * factor), int(color.g * factor), int(color.b * factor))

# Player 2 is blue (index 1 in PLAYER_COLORS)
PLAYER_INDICES = [0, 1]   # red, blue

# Key bindings: (up, down, left, right, agent_mode, link_mode)
from game_square.keys import (
    K_w, K_s, K_a, K_d, K_e, K_f,
    K_UP, K_DOWN, K_LEFT, K_RIGHT, K_n, K_m,
)
PLAYER_KEYS = [
    (K_w, K_s, K_a, K_d, K_e, K_f),
    (K_UP, K_DOWN, K_LEFT, K_RIGHT, K_n, K_m),
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
        """All pixels occupied by any node body (used for collision, excludes connection points)."""
        occupied = set()
        for obj in connectables:
            if isinstance(obj, EnergyNode):
                for dx, dy in obj._casing:
                    occupied.add((obj.x + dx, obj.y + dy))
                for dx, dy in obj._fill:
                    occupied.add((obj.x + dx, obj.y + dy))
                ndx, ndy = obj._nub
                occupied.add((obj.x + ndx, obj.y + ndy))
            elif isinstance(obj, PlayerBase):
                for dx, dy in obj._FRAME + obj._PINS:
                    occupied.add((obj.x + dx, obj.y + dy))
                occupied.add((obj.x, obj.y))
            elif isinstance(obj, Armory):
                for dx, dy in obj._SHELL:
                    occupied.add((obj.x + dx, obj.y + dy))
                occupied.add((obj.x, obj.y))
        return occupied

    def start(self, direction: tuple[int,int], links: list, pin_idx: int = 0) -> bool:
        """
        Pick the CPU pin on the side matching `direction` that isn't already
        the start of a committed link.  pin_idx selects which of the two
        pins to prefer when both are free (alternates via caller).
        Returns False (do nothing) if both pins on that side are already wired.
        """
        # Map direction → pair of _PIN_CONNECTIONS indices
        # _PIN_CONNECTIONS order: north(0,1), south(2,3), west(4,5), east(6,7)
        DIR_PINS = {
            ( 0, -1): (0, 1),   # up    → north pins
            ( 0,  1): (2, 3),   # down  → south pins
            (-1,  0): (4, 5),   # left  → west pins
            ( 1,  0): (6, 7),   # right → east pins
        }
        pair = DIR_PINS.get(direction)
        if pair is None:
            return False

        all_pins = self.base.connection_points   # list of 8 absolute (x,y)
        used_starts = {lk.path[0] for lk in links if lk.source is self.base}
        available = [i for i in pair if all_pins[i] not in used_starts]
        if not available:
            return False

        if len(available) == 2:
            chosen = all_pins[available[pin_idx % 2]]
        else:
            chosen = all_pins[available[0]]
        self.path = [chosen]
        self.active = True
        self._cooldown = 0
        return True

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

        # Check self-intersection (wire cannot cross itself)
        if (nx, ny) in self.path:
            return 'hit_wire'

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
                # Batteries can only have one wire connected at a time
                if isinstance(obj, EnergyNode):
                    has_link = any(
                        lk.source is obj or lk.destination is obj
                        for lk in links
                    )
                    if has_link:
                        return 'hit_node'
                # Cannot wire to an opposing player's armory
                if isinstance(obj, Armory) and obj.color != self.base.color:
                    return 'hit_node'
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
            # Claim ownership and set capture to full so same-colour agents
            # don't accidentally push it past the threshold and sever the link.
            dest_obj.owner_color = self.base.color
            from game_square.nodes import PLAYER_COLORS
            dest_obj.capture = (-EnergyNode.CAPTURE_MAX
                                if self.base.color == PLAYER_COLORS[0]
                                else EnergyNode.CAPTURE_MAX)

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


def _random_node_positions(count: int, margin: int, min_dist: int,
                            avoid: list[tuple[int,int]] | None = None) -> list[tuple[int, int]]:
    ORIENTATIONS = ('up', 'down', 'left', 'right')
    avoid = avoid or []
    positions = []
    attempts  = 0
    while len(positions) < count and attempts < 10_000:
        x = random.randint(margin, 63 - margin)
        y = random.randint(margin, 63 - margin)
        existing = [(px, py, _) for px, py, _ in positions] + [(ax, ay, None) for ax, ay in avoid]
        if all(abs(x - px) + abs(y - py) >= min_dist for px, py, _ in existing):
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


def auto_placement(nodes: list) -> tuple:
    """
    Place bases and armories automatically — no mouse needed.
    Red CPU: top-left corner region.
    Blue CPU: bottom-right corner region.
    Armories: random, kept away from batteries and the other base.
    """
    base0 = PlayerBase(10, 10, PLAYER_INDICES[0])
    base1 = PlayerBase(53, 53, PLAYER_INDICES[1])

    occupied = [(obj.x, obj.y) for obj in nodes] + [(base0.x, base0.y), (base1.x, base1.y)]

    def random_armory(player_idx):
        for _ in range(10_000):
            x = random.randint(NODE_MARGIN, 63 - NODE_MARGIN)
            y = random.randint(NODE_MARGIN, 63 - NODE_MARGIN)
            if all(abs(x - ox) + abs(y - oy) >= NODE_MIN_DIST for ox, oy in occupied):
                occupied.append((x, y))
                return Armory(x, y, player_idx)
        # Fallback if no space found
        return Armory(32, 32, player_idx)

    armory0 = random_armory(PLAYER_INDICES[0])
    armory1 = random_armory(PLAYER_INDICES[1])

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

    # Refresh battery ownership: owned by whoever has a powered link to it;
    # reset to None if no powered link touches the battery.
    for link in links:
        if isinstance(link.source, _EN):
            if link.powered:
                dest_color = getattr(link.destination, 'color', None) \
                             or getattr(link.destination, 'owner_color', None)
                if dest_color:
                    link.source.owner_color = dest_color
                    # Keep capture pinned to the owner's side so same-colour
                    # garrisoning agents can't accidentally trigger a flip.
                    from game_square.nodes import PLAYER_COLORS
                    if dest_color == PLAYER_COLORS[0]:
                        link.source.capture = -link.source.CAPTURE_MAX
                    else:
                        link.source.capture =  link.source.CAPTURE_MAX
            else:
                # Only clear if no other powered link claims this battery
                claimed = any(
                    lk.powered and (lk.source is link.source or lk.destination is link.source)
                    for lk in links if lk is not link
                )
                if not claimed:
                    link.source.owner_color = None


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

    BASE_POSITIONS = [(10, 10), (53, 53)]
    nodes = [EnergyNode(x, y, orientation) for x, y, orientation in
             _random_node_positions(NODE_COUNT, NODE_MARGIN, NODE_MIN_DIST, avoid=BASE_POSITIONS)]

    (base0, armory0), (base1, armory1) = auto_placement(nodes)

    bases   = [base0, base1]
    armories = [armory0, armory1]

    links: list[PowerLine] = []
    directed: list[DirectedAgent] = []   # player-controlled agents
    agents:   list[Agent]         = []   # auto-spawned path agents

    # Attack path templates set by the player's directed agent
    # Maps armory -> {direction: path} so each of the 4 outputs has its own path
    armory_attack_paths: dict = {armory0: {}, armory1: {}}
    # Rotation index per armory: which output to spawn from next (0..3)
    armory_rotation: dict = {armory0: 0, armory1: 0}

    # One WireBuilder per player, keyed to their base
    wire_builders = [
        WireBuilder(base0, PLAYER_KEYS[0]),
        WireBuilder(base1, PLAYER_KEYS[1]),
    ]

    # Per-player mode: 'link' or 'agent'
    player_mode = ['link', 'link']
    # One active DirectedAgent per player (or None)
    player_agent: list[DirectedAgent | None] = [None, None]
    # Chosen launch direction while in preview (before agent spawns)
    player_preview_dir: list[tuple[int,int]] = [(0, -1), (0, -1)]
    # Wire preview direction (always set, like player_preview_dir; first
    # press aims/primes, second press of same direction starts the wire)
    wire_preview_dir: list[tuple[int,int]] = [(0, -1), (0, -1)]
    # Wire primed: True after the first directional keypress (waiting for
    # the second press of the same direction to start the wire).
    wire_primed = [False, False]
    # Pin rotation per player: {direction: 0|1} — alternates which of the
    # two CPU pins on a side gets used next.
    wire_pin_idx: list[dict[tuple[int,int], int]] = [{}, {}]
    # Armed: True when the player has pressed E and is waiting for a scout
    # to spawn or steering one.  False (waiting) after the scout finishes —
    # the armory's rotational auto-spawn handles output until E is pressed.
    player_armed = [False, False]

    # Tip offset for each direction
    DIR_TIP: dict[tuple[int,int], tuple[int,int]] = {
        ( 0, -1): ( 0, -3),
        ( 0,  1): ( 0,  3),
        (-1,  0): (-3,  0),
        ( 1,  0): ( 3,  0),
    }

    # Clockwise rotation order for armory auto-spawn
    SPAWN_DIRS = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    # Reverse of DIR_TIP: tip offset → direction
    TIP_TO_DIR = {tip: d for d, tip in DIR_TIP.items()}
    # CPU pin indices for each direction (matches _PIN_CONNECTIONS order)
    DIR_PIN_INDICES = {
        ( 0, -1): (0, 1),   # up    → north pins
        ( 0,  1): (2, 3),   # down  → south pins
        (-1,  0): (4, 5),   # left  → west pins
        ( 1,  0): (6, 7),   # right → east pins
    }

    while True:
        if not display.pump_events():
            break

        connectables = nodes + bases + armories
        keys_pressed = getattr(display, 'keys_pressed', [])
        held = getattr(display, 'keys_held', None)

        # --- Mode toggle ---
        for i, arm in enumerate(armories):
            _, _, _, _, k_agent, k_link = PLAYER_KEYS[i]
            if k_agent in keys_pressed:
                # Enter agent mode and arm for a new scout.  Releasing
                # the current scout puts it on auto-pilot.
                player_mode[i] = 'agent'
                player_armed[i] = True
                if wire_builders[i].active:
                    wire_builders[i].active = False
                    wire_builders[i].path = []
                wire_primed[i] = False
                player_agent[i] = None
                display.push_sound("toggle")
            if k_link in keys_pressed:
                player_mode[i] = 'link'
                wire_primed[i] = False
                display.push_sound("toggle")
                if player_agent[i] and player_agent[i].alive:
                    player_agent[i].derezz()
                player_agent[i] = None

        # --- Build pixel sets for DirectedAgent collision ---
        link_px_set: set[tuple[int,int]] = set()
        for lk in links:
            for px, py in lk.path:
                link_px_set.add((px, py))
        # Also include developing (uncommitted) wire-builder paths
        for wb in wire_builders:
            for px, py in wb.path:
                link_px_set.add((px, py))
        node_px_set: set[tuple[int,int]] = set()
        for obj in connectables:
            if isinstance(obj, EnergyNode):
                continue   # agents can enter batteries
            if isinstance(obj, PlayerBase):
                for dx, dy in obj._FRAME + obj._PINS:
                    node_px_set.add((obj.x + dx, obj.y + dy))
                node_px_set.add((obj.x, obj.y))
            elif isinstance(obj, Armory):
                for dx, dy in obj._SHELL:
                    node_px_set.add((obj.x + dx, obj.y + dy))
                node_px_set.add((obj.x, obj.y))
        # Map every battery pixel → EnergyNode for contest detection
        battery_pixel_map: dict[tuple[int,int], EnergyNode] = {}
        for node in nodes:
            for dx, dy in node._casing:
                battery_pixel_map[(node.x + dx, node.y + dy)] = node
            for dx, dy in node._fill:
                battery_pixel_map[(node.x + dx, node.y + dy)] = node
            ndx, ndy = node._nub
            battery_pixel_map[(node.x + ndx, node.y + ndy)] = node
            battery_pixel_map[node.connection_point] = node

        # --- Keyboard wire building (link mode) ---
        # Two-stage: first press of a direction shows a preview pip on
        # the CPU pins; second press of the same direction starts the wire.
        for i, wb in enumerate(wire_builders):
            if player_mode[i] != 'link':
                continue
            up, down, left, right, _, _ = wb.keys

            if not wb.active:
                # Two-stage selection using fresh keypresses only
                press_dir = None
                if   up in keys_pressed:    press_dir = ( 0, -1)
                elif down in keys_pressed:  press_dir = ( 0,  1)
                elif left in keys_pressed:  press_dir = (-1,  0)
                elif right in keys_pressed: press_dir = ( 1,  0)

                if press_dir is not None:
                    if wire_primed[i] and wire_preview_dir[i] == press_dir:
                        # Second press — start the wire
                        pidx = wire_pin_idx[i].get(press_dir, 0)
                        if wb.start(press_dir, links, pidx):
                            wire_pin_idx[i][press_dir] = (pidx + 1) % 2
                            display.push_sound(f"wire_start_{i}")
                        wire_primed[i] = False
                    else:
                        # First press or different direction — set preview
                        wire_preview_dir[i] = press_dir
                        wire_primed[i] = True
            else:
                # Wire active: grow with held keys
                direction = None
                if held is not None:
                    if   held[up]:    direction = ( 0, -1)
                    elif held[down]:  direction = ( 0,  1)
                    elif held[left]:  direction = (-1,  0)
                    elif held[right]: direction = ( 1,  0)

                if direction is not None and wb._cooldown <= 0:
                    result = wb.step(direction, links, connectables)
                    if result == 'connected':
                        new_link = wb.commit(connectables, links, tick)
                        if new_link:
                            links.append(new_link)
                            _update_power(links, tick)
                            display.push_sound("connect")
                        display.push_sound(f"wire_end_{i}")
                        wb.active = False
                        wb.path = []
                    elif result == 'hit_wire':
                        display.push_sound(f"wire_end_{i}")
                        wb.active = False
                        wb.path = []
                    elif result in ('hit_node', 'out_of_bounds'):
                        display.push_sound(f"wire_end_{i}")
                        wb.active = False
                        wb.path = []
                    else:   # 'ok'
                        display.push_sound(f"wire_step_{i}")
                        wb._cooldown = WIRE_STEP_TICKS

            if wb._cooldown > 0:
                wb._cooldown -= 1

        # --- Determine which armory tips are occupied by wires ---
        armory_wired_dirs: dict = {}
        for arm in armories:
            wired = set()
            for lk in links:
                if lk.destination is not arm and lk.source is not arm:
                    continue
                for cp in arm.connection_points:
                    if cp in lk.path:
                        offset = (cp[0] - arm.x, cp[1] - arm.y)
                        d = TIP_TO_DIR.get(offset)
                        if d:
                            wired.add(d)
                        break
            armory_wired_dirs[arm] = wired

        # --- Credit armory energy from inbound pulses ---
        # Done early so the player's scout gets first dibs on energy
        # before the auto-spawn rotation consumes it.
        for lk in links:
            if isinstance(lk.destination, Armory) and lk.powered:
                lk.destination.energy += lk.check_arrivals(tick)

        # --- Agent steering and auto-launch ---
        # Three states per player (while in agent mode):
        #   waiting     — scout just finished; no new controllable scout
        #                 until E is pressed.  The armory's rotational
        #                 auto-spawn continues using saved paths.
        #   armed       — E pressed, no scout; held keys aim preview,
        #                 auto-launches a controllable scout when charged.
        #   controlling — armed, scout alive; held keys steer it.
        for i, arm in enumerate(armories):
            if player_mode[i] != 'agent':
                continue
            up, down, left, right, _, _ = PLAYER_KEYS[i]

            held_dir = None
            if held is not None:
                if   held[up]:    held_dir = ( 0, -1)
                elif held[down]:  held_dir = ( 0,  1)
                elif held[left]:  held_dir = (-1,  0)
                elif held[right]: held_dir = ( 1,  0)

            pa = player_agent[i]
            if pa is not None and pa.alive:
                # --- Controlling: steer the scout ---
                if held_dir is not None:
                    pa.steer(held_dir)
            elif player_armed[i]:
                # --- Armed: aim preview, auto-launch when charged ---
                wired = armory_wired_dirs[arm]
                if held_dir is not None and held_dir not in wired:
                    player_preview_dir[i] = held_dir

                want_dir = player_preview_dir[i]
                if want_dir in wired or want_dir == (0, 0):
                    want_dir = next((d for d in SPAWN_DIRS if d not in wired), None)

                if want_dir is not None and arm.can_spawn() and want_dir not in wired:
                    arm.consume_spawn()
                    arm.trigger_spawn_flash()
                    display.push_sound("spawn")
                    chosen_tip = DIR_TIP[want_dir]
                    sx, sy = arm.x + chosen_tip[0], arm.y + chosen_tip[1]
                    pa = DirectedAgent(sx, sy, bases[i].color)
                    pa.steer(want_dir)
                    pa.source_armory = arm
                    pa.launch_dir = want_dir
                    pa._cooldown = DirectedAgent.STEP_TICKS
                    player_agent[i] = pa
                    directed.append(pa)
            else:
                # --- Waiting: aim preview only, no launch ---
                wired = armory_wired_dirs[arm]
                if held_dir is not None and held_dir not in wired:
                    player_preview_dir[i] = held_dir

        # --- CPU energy buffering ---
        # Inbound battery→CPU links: count newly arrived pulses and credit the base.
        for lk in links:
            if isinstance(lk.destination, PlayerBase) and lk.powered:
                lk.destination.energy += lk.check_arrivals(tick)
        # Outbound CPU→* gated links: spend one energy credit per link,
        # but only once per PULSE_SPACING ticks so the rate matches inbound.
        for base in bases:
            for lk in links:
                if lk.source is base and lk.gated and lk.powered and base.energy > 0:
                    last = getattr(lk, '_last_queued_tick', -PowerLine.PULSE_SPACING)
                    if tick - last >= PowerLine.PULSE_SPACING:
                        lk.queue_pulse(tick)
                        lk._last_queued_tick = tick
                        base.energy -= 1

        # --- Battery capture ---
        # Wired (owned) batteries: only enemy agents can push capture;
        # same-colour agents and passive decay are suppressed so a defensive
        # agent never accidentally trips the flip threshold.
        # Unwired batteries: full contest + decay logic applies.
        for node in nodes:
            is_wired = any(
                lk.powered and (lk.source is node or lk.destination is node)
                for lk in links
            )
            # Count both player-controlled and auto-spawned agents at this battery.
            def _contesting_node(a) -> bool:
                return a.alive and getattr(a, 'contesting', False) \
                       and getattr(a, '_contest_battery', None) is node
            red_count    = sum(
                1 for da in directed
                if da.alive and da.contesting and da._contest_battery is node
                and da.color == bases[0].color
            ) + sum(1 for a in agents if _contesting_node(a) and a.color == bases[0].color)
            blue_count = sum(
                1 for da in directed
                if da.alive and da.contesting and da._contest_battery is node
                and da.color == bases[1].color
            ) + sum(1 for a in agents if _contesting_node(a) and a.color == bases[1].color)
            if is_wired:
                # Only contest if enemy agents are present; same-colour
                # defenders count normally so 1v1 is a true stalemate.
                owner_is_red = (node.owner_color == bases[0].color)
                enemy_count = blue_count if owner_is_red else red_count
                if enemy_count == 0:
                    continue
                flipped = node.contest(red_count, blue_count)
            else:
                flipped = node.contest(red_count, blue_count)
            if flipped:
                links = [lk for lk in links
                         if lk.source is not node and lk.destination is not node]
                _update_power(links, tick)
                display.push_sound("capture")

        # Update directed (player-controlled) agents
        for da in directed:
            was_contesting = da.contesting
            da.update(link_px_set, node_px_set, battery_pixel_map,
                      list(agents) + list(directed))
            # Continuously update the path while the scout is alive so
            # auto-spawned agents can follow it in real-time, before the
            # path is complete.  The path persists after the scout dies
            # or reaches a battery.
            if da.alive and da.source_armory is not None and len(da.full_path) > 1:
                paths = armory_attack_paths[da.source_armory]
                if da.launch_dir in paths:
                    paths[da.launch_dir].clear()
                    paths[da.launch_dir].extend(da.full_path)
                else:
                    paths[da.launch_dir] = list(da.full_path)
            if da.contesting and not was_contesting:
                for i in range(len(player_agent)):
                    if player_agent[i] is da:
                        player_agent[i] = None
                        player_armed[i] = False

        # Collisions between directed agents
        check_collisions(directed)
        directed = [da for da in directed if da.alive]

        # --- Auto-spawn ---
        # Auto-spawn a path agent when armory has enough credits.
        # Rotates through the 4 outputs, spawning from the next one that
        # has a recorded path.
        for arm in armories:
            if not arm.can_spawn():
                continue
            paths = armory_attack_paths.get(arm, {})
            if not paths:
                continue
            rot = armory_rotation[arm]
            wired = armory_wired_dirs[arm]
            for offset in range(4):
                idx = (rot + offset) % 4
                d = SPAWN_DIRS[idx]
                if d in wired:
                    continue
                path = paths.get(d)
                if path:
                    arm.consume_spawn()
                    arm.trigger_spawn_flash()
                    display.push_sound("spawn")
                    agents.append(Agent(path=path, color=arm.color))
                    armory_rotation[arm] = (idx + 1) % 4
                    break

        all_contesting = list(agents) + list(directed)
        for agent in agents:
            agent.update(link_px_set, battery_pixel_map, all_contesting)

        # Check for bounces and play sound
        for a in agents + directed:
            if getattr(a, 'bounced', False):
                display.push_sound("bounce")
                a.bounced = False

        alive_before = sum(1 for a in agents + directed if a.alive)
        check_collisions(agents + directed)
        alive_after = sum(1 for a in agents + directed if a.alive)
        if alive_after < alive_before:
            display.push_sound("derezz")
        agents = [a for a in agents if a.alive]
        # Sync player_agent refs
        for i in range(len(player_agent)):
            if player_agent[i] is not None and not player_agent[i].alive:
                player_agent[i] = None
                player_armed[i] = False

        # --- Draw ---
        display.clear()

        for link in links:
            link.draw(display, tick)

        for wb in wire_builders:
            if wb.active:
                wb.draw(display, wb.base.color)

        # Draw wire bip on a CPU pin (always visible in link mode when no
        # wire is actively growing).  Mirrors agent mode: wire_preview_dir
        # is always set (defaults to up); wire_primed distinguishes the
        # slow dim unprimed blink from the fast bright primed blink.
        # Falls back to another direction if the current one's pins are
        # all used.
        for i, wb in enumerate(wire_builders):
            if player_mode[i] != 'link' or wb.active:
                continue
            base = bases[i]
            all_pins = base.connection_points
            used = {lk.path[0] for lk in links if lk.source is base}
            primed = wire_primed[i]
            # Pick the direction to show the bip on
            d = wire_preview_dir[i]
            available = [idx for idx in DIR_PIN_INDICES[d]
                         if all_pins[idx] not in used]
            if not available:
                # Current direction's pins are full — fall back to the
                # first direction with a free pin
                d = next((dd for dd in SPAWN_DIRS
                          if any(all_pins[idx] not in used
                                 for idx in DIR_PIN_INDICES[dd])), None)
                if d is None:
                    continue
                available = [idx for idx in DIR_PIN_INDICES[d]
                             if all_pins[idx] not in used]
            pidx = wire_pin_idx[i].get(d, 0)
            chosen_idx = (available[pidx % len(available)]
                          if len(available) > 1 else available[0])
            pin = all_pins[chosen_idx]
            if primed:
                blink = (tick // 3) % 2 == 0
                bright = 1.0 if blink else 0.3
                c = Color(
                    min(255, int(base.color.r * bright + 60)),
                    min(255, int(base.color.g * bright + 60)),
                    min(255, int(base.color.b * bright + 60)),
                )
            else:
                blink = (tick // 8) % 2 == 0
                bright = 0.5 if blink else 0.1
                c = Color(int(base.color.r * bright),
                          int(base.color.g * bright),
                          int(base.color.b * bright))
            display.set_pixel(*pin, c)

        for node in nodes:
            node.draw(display, tick)
        for arm in armories:
            arm.draw(display, tick)
        # Draw agent bip on an armory tip (always visible in agent mode
        # when no scout is alive).  Unprimed (waiting) = slow dim blink.
        # Primed (armed, user aiming) = fast bright blink with white tint.
        for i, arm in enumerate(armories):
            if player_mode[i] != 'agent':
                continue
            pa = player_agent[i]
            if pa is not None and pa.alive:
                continue
            tip = DIR_TIP[player_preview_dir[i]]
            px, py = arm.x + tip[0], arm.y + tip[1]
            c = bases[i].color
            if player_armed[i]:
                # Primed (armed): fast blink + white tint
                blink = (tick // 3) % 2 == 0
                bright = 1.0 if blink else 0.4
                c = Color(
                    min(255, int(c.r * bright + 60)),
                    min(255, int(c.g * bright + 60)),
                    min(255, int(c.b * bright + 60)),
                )
            else:
                # Unprimed (waiting): slow blink, dim
                blink = (tick // 8) % 2 == 0
                bright = 0.5 if blink else 0.1
                c = Color(int(c.r * bright), int(c.g * bright), int(c.b * bright))
            display.set_pixel(px, py, c)
        for base in bases:
            base.draw(display, tick)

        for da in directed:
            da.draw(display)
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
