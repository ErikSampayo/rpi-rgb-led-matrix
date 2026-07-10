# game_square — Concept Demo: Architecture & Design Notes

## Overview

`game_square` is a two-player Tron-themed real-time strategy concept demo rendered on a 64×64 pixel grid. It runs on Windows via a pygame-ce emulator or on a Raspberry Pi driving a real HUB75 LED matrix panel.

The long-term vision is a physical hex-tile board game backed by an LED matrix. `game_square` is the proving ground for core mechanics before that investment is made.

---

## Running

```bash
# Windows / dev (scaled pygame window)
python -m game_square.main

# Raspberry Pi (real LED matrix)
python -m game_square.main --hardware
```

**Dependencies (Windows):**
- Python 3.14+
- `pygame-ce` (not `pygame` — `distutils` was removed in 3.14 and breaks the standard wheel)
- `RGBMatrixEmulator` — install with `--no-deps`, then install `pillow`, `numpy`, `tornado`, `bdfparser` manually
- `libsixel-python` is **not** required (only needed for terminal/sixel rendering)

---

## Directory Layout

```
game_square/
├── ARCHITECTURE.md        ← this file
├── __init__.py
├── main.py                ← entry point, game loop, placement phase
├── nodes.py               ← EnergyNode, PlayerBase, Armory
├── links.py               ← Link base class, PowerLine
├── agents.py              ← Agent units, collision detection
└── display/
    ├── __init__.py
    ├── base.py            ← Abstract Display, Color
    ├── square_pygame.py   ← Desktop renderer (10px/cell scaled window)
    └── led_matrix.py      ← Raspberry Pi backend
```

---

## Display Abstraction

`Display` (in `display/base.py`) is an abstract base class. Both backends expose the same interface:

| Method | Purpose |
|---|---|
| `set_pixel(x, y, color)` | Write one pixel |
| `clear()` | Blank the framebuffer |
| `render()` | Flush buffer to screen/matrix |
| `pump_events() -> bool` | Process OS events; returns `False` on quit |
| `fill_rect(x, y, w, h, color)` | Filled rectangle helper |
| `draw_border(color)` | 1px border around full canvas |

`SquarePygameDisplay` additionally exposes:
- `mouse_pos: tuple[int,int]` — current cursor position in grid coordinates (updated every frame in `pump_events`)
- `clicked: list[tuple[int,int]]` — grid-coordinate click positions collected this frame
- `keys_pressed: list` — pygame key events this frame

`Color` is a `NamedTuple(r, g, b)`. Named constants: `BLACK WHITE RED GREEN BLUE YELLOW CYAN ORANGE PURPLE GREY`.

`PLAYER_COLORS = [Color(220,50,50), Color(50,100,240), Color(200,180,0), Color(160,50,220)]`  
Active players use indices `[0, 1]` → **red** and **blue**.

---

## Game Nodes (`nodes.py`)

### EnergyNode (battery)

- **Shape:** 3×5 px body + 1 px nub, 4 orientations (`up / down / left / right`)
- **Connection point:** 1 px beyond the nub tip (outside the sprite)
- **Behavior:** pulses with a sinusoidal fill animation; is the unconditional power source for all downstream links
- **`connection_point`** property → single `(x, y)` tuple
- Orientation is randomised at spawn

### PlayerBase (CPU chip)

- **Shape:** 5×5 px frame + 8 pin stubs extending to ±3 px
- **Connection points:** 8 total, at ±4 px (1 px beyond each pin tip)
  - Top: `(-1,-4), (1,-4)` — Bottom: `(-1,4), (1,4)` — Left: `(-4,-1), (-4,1)` — Right: `(4,-1), (4,1)`
- **Visual:** frame + pins + pulsing centre pixel (fast "processor clock" animation)
- **`energy: int`** — energy credit counter; incremented when battery pulses arrive, decremented when forwarding pulses outward
- **`connection_points`** property → list of 8 tuples
- **`closest_connection_point(target)`** → Manhattan-nearest pin

### Armory (Siren / diamond)

- **Shape:** diamond, 5×5 px bounding box
- **Connection points:** 4 tips at `(0,±3), (±3,0)` — 1 px beyond drawn tips
- **Charge:** `CHARGE_TICKS = 80`; increments each tick when fed; sets `ready = True` for exactly one tick when full, then resets
- **`update()`** — call once per tick; only call when the armory is fed
- **`ready`** property — single-tick signal to spawn an agent
- **Visual:** shell brightens as charge accumulates; centre pixel pulse rate increases with charge

---

## Links (`links.py`)

### Link (base class)

Connects two `Connectable` objects (anything with `connection_point` / `closest_connection_point`).

Owns a `path: list[tuple[int,int]]` built by `_l_path()` — an **orthogonal L-shaped path** (horizontal segment first, then vertical; no diagonals).

Flags: `active` (show/hide), `powered` (wire only vs. wire + pulses).

### PowerLine

Subclass of `Link`. Draws a dim static wire with bright gaussian-falloff energy pulses travelling from source → destination.

**Constants:**

| Name | Value | Meaning |
|---|---|---|
| `PULSE_SPEED` | 0.4 | px/tick |
| `PULSE_SPACING` | 20 | ticks between auto-launched pulses (free-running mode) |
| `PULSE_WIDTH` | 2.0 | gaussian σ in pixels |
| `WIRE_DIM` | 0.12 | wire brightness factor |
| `PULSE_BRIGHT` | 0.95 | pulse peak brightness factor |

**Two pulse modes:**

1. **Free-running** (`gated = False`, default) — pulses auto-launch every `PULSE_SPACING` ticks from the moment `power_on(tick)` is called. Used for battery→CPU links.

2. **Gated** (`gated = True`) — pulses only launch when `queue_pulse(tick)` is explicitly called (one call = one pulse). Used for CPU→armory (and any CPU-outbound) links, so the CPU acts as a relay: it only forwards a pulse when it has accumulated energy credit.

**Key methods:**

- `power_on(tick)` — call when transitioning unpowered → powered; records `_phase_start`
- `queue_pulse(tick)` — schedule one gated pulse launch at `tick`
- `check_arrivals(tick) -> int` — returns number of pulses that crossed the destination endpoint since the last call (handles both modes); used to credit energy to PlayerBase

**Colour:** derived from `destination.color` → `destination.owner_color` → `source.color` → `NEUTRAL_ENERGY` (cyan).

**Normalisation rule:** `EnergyNode` is always placed at `source` so pulses always travel battery → outward. Enforced in `main.py` when the link is built.

---

## Agents (`agents.py`)

Single-pixel units that travel along a path at `SPEED = 0.3` px/tick.

- **`path`** — list of `(x, y)` pixels from spawn point to destination
- **`pos`** — fractional position along path
- **`alive / arrived`** — lifecycle flags
- **`derezz()`** — kill the agent
- **`draw(display)`** — renders head pixel + 4-pixel fading trail
- **`check_collisions(agents)`** — derezzes both agents if two different-faction agents share a pixel

---

## Power & Energy Flow

```
EnergyNode ──(free-running PowerLine)──► PlayerBase ──(gated PowerLine)──► Armory
                                              ▲
                                    energy credits accumulate
                                    from inbound battery pulses
```

### `_update_power(links, tick)`

Flood-fill every frame:
1. Seed `powered_objs` with both endpoints of any link touching an `EnergyNode`
2. Propagate: if `source` is powered, `destination` becomes powered (backwards propagation only for EnergyNode-adjacent links to avoid accidental reverse-flow)
3. For each link that just transitioned unpowered → powered: call `link.power_on(tick)`

### CPU Energy Relay (game loop, each tick)

```python
# 1. Credit arriving pulses to the destination CPU
for lk in links:
    if isinstance(lk.destination, PlayerBase) and lk.powered:
        lk.destination.energy += lk.check_arrivals(tick)

# 2. Spend one credit per outbound gated link per tick
for base in bases:
    for lk in links:
        if lk.source is base and lk.gated and lk.powered and base.energy > 0:
            lk.queue_pulse(tick)
            base.energy -= 1
```

---

## Game Loop (`main.py`)

### Placement Phase

Both players place interactively in sequence:
1. **Red** moves a ghost `PlayerBase` with the cursor → click to place CPU
2. **Red** moves a ghost `Armory` → click to place Armory
3. **Blue** repeats (red's pieces drawn as background context)

### Main Loop (per tick)

1. `pump_events()` — collect mouse clicks & moves
2. **Input:** click a connection pin to start drag; click a second pin to finalise a `PowerLine`
   - Snap radius: `PIN_SNAP = 5` px (Manhattan)
   - Ghost L-shaped preview line rendered during drag
   - EnergyNode normalisation applied on link creation
   - Links sourced from a `PlayerBase` are marked `gated = True`
3. **CPU energy relay** (see above)
4. **Armory update:** call `arm.update()` when fed; on `arm.ready`, find a powered link touching the armory and spawn an `Agent` along it (departing from the armory's end)
5. **Agent update + collision detection**
6. **Draw:** links → ghost line → energy nodes → armories → bases → agents → `render()`
7. `time.sleep(0.04)` → ~25 ticks/second

### Link Building (manual `__new__` bypass)

Because `Link.__init__` calls `closest_connection_point` immediately, links are assembled manually to support pre-computed paths and custom source/destination ordering:

```python
new_link = PowerLine.__new__(PowerLine)
new_link.source       = ...
new_link.destination  = ...
new_link.path         = _l_path(...)
new_link.active       = True
new_link.powered      = False
new_link._length      = len(new_link.path)
new_link._phase_start = None
new_link.gated                = False
new_link._queued              = []
new_link._arrivals_checked_at = -1
```

---

## Known Gaps / Future Work

- **Win condition** — no end-game logic yet; agents travel and derezz on collision but nothing is "captured"
- **Line crossing / blocking** — links can cross freely; no intersection detection or blocking rule
- **CPU energy display** — the energy counter is functional but not visualised (e.g. bar on chip)
- **Multi-link armory** — armory spawns from the first powered link it finds; no priority or selection
- **Enemy base as target** — agents walk the armed link path but the destination is whichever node is at the far end; no explicit "attack the enemy CPU" routing
- **Link severing** — no mechanic to cut a link after placement
- **More than 2 players** — `PLAYER_INDICES` supports up to 4 colours but placement phase is hardcoded to 2
- **Hex board** — separate `game/` directory has a hex-grid framework (flat-top, radius-5, 91 tiles, click-to-capture) for the eventual physical tile board; currently tabled

---

## Related: RGBMatrixEmulator Setup

`bindings/python/samples/samplebase.py` was modified to fall back gracefully:

```python
try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
except ImportError:
    from RGBMatrixEmulator import RGBMatrix, RGBMatrixOptions
```

The `game_square` display layer handles this independently and does not use `samplebase.py`.
