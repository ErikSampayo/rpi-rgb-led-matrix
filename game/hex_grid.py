"""
Hex grid utilities using axial coordinates (q, r) with flat-top orientation.

Cube coords: q + r + s = 0  (s is derived as -q - r)
A regular hex board of radius R contains all tiles where
  max(|q|, |r|, |q+r|) <= R
"""

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class Hex:
    q: int
    r: int

    @property
    def s(self) -> int:
        return -self.q - self.r

    def neighbors(self) -> list["Hex"]:
        return [self + d for d in HEX_DIRECTIONS]

    def distance(self, other: "Hex") -> int:
        return max(abs(self.q - other.q), abs(self.r - other.r), abs(self.s - other.s))

    def __add__(self, other: "Hex") -> "Hex":
        return Hex(self.q + other.q, self.r + other.r)

    def __sub__(self, other: "Hex") -> "Hex":
        return Hex(self.q - other.q, self.r - other.r)

    def __repr__(self) -> str:
        return f"Hex({self.q}, {self.r})"


# Flat-top hex: 6 axial directions
HEX_DIRECTIONS = [
    Hex(1, 0), Hex(1, -1), Hex(0, -1),
    Hex(-1, 0), Hex(-1, 1), Hex(0, 1),
]


def hex_range(radius: int) -> Iterator[Hex]:
    """All hexes within `radius` steps of the origin."""
    for q in range(-radius, radius + 1):
        for r in range(max(-radius, -q - radius), min(radius, -q + radius) + 1):
            yield Hex(q, r)


def ring(center: Hex, radius: int) -> list[Hex]:
    """All hexes exactly `radius` steps from center."""
    if radius == 0:
        return [center]
    results = []
    h = center + Hex(HEX_DIRECTIONS[4].q * radius, HEX_DIRECTIONS[4].r * radius)
    for direction in HEX_DIRECTIONS:
        for _ in range(radius):
            results.append(h)
            h = h + direction
    return results
