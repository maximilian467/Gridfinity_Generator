"""Stufenzonen aus dem Seitenprofil (Plan F)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import minimum_filter1d


@dataclass
class Zone:
    a: float       # Beginn entlang s (mm, objekt-lokal)
    b: float       # Ende
    floor: float   # Boden relativ zur Ruhelage (mm); Werkzeug-Unterseite darüber


def compute_zones(s, bottom, length: float, margin: float, step_tol: float = 1.0,
                  min_zone_len: float = 8.0, max_zones: int = 8, ds: float = 0.5) -> list[Zone]:
    s = np.asarray(s, float)
    bottom = np.asarray(bottom, float)
    grid = np.arange(-margin, length + margin + ds / 2, ds)
    b = np.interp(grid, s, bottom)          # außerhalb: Randwert halten
    size = 2 * int(round(margin / ds)) + 1
    f = minimum_filter1d(b, size=size, mode="nearest")

    zones: list[Zone] = []
    start, lo, hi = 0, f[0], f[0]
    for i in range(1, len(f)):
        nlo, nhi = min(lo, f[i]), max(hi, f[i])
        if nhi - nlo > step_tol:
            zones.append(Zone(grid[start] - ds / 2, grid[i] - ds / 2, float(lo)))
            start, lo, hi = i, f[i], f[i]
        else:
            lo, hi = nlo, nhi
    zones.append(Zone(grid[start] - ds / 2, grid[-1] + ds / 2, float(lo)))
    zones[0].a = -margin
    zones[-1].b = length + margin

    def merge(i: int, j: int) -> None:  # j = i+1
        zones[i] = Zone(zones[i].a, zones[j].b, min(zones[i].floor, zones[j].floor))
        del zones[j]

    while len(zones) > 1:
        lens = [z.b - z.a for z in zones]
        k = int(np.argmin(lens))
        if lens[k] >= min_zone_len:
            break
        if k == 0:
            merge(0, 1)
        elif k == len(zones) - 1:
            merge(k - 1, k)
        elif zones[k - 1].floor <= zones[k + 1].floor:
            merge(k - 1, k)
        else:
            merge(k, k + 1)
    while len(zones) > max_zones:
        diffs = [abs(zones[i].floor - zones[i + 1].floor) for i in range(len(zones) - 1)]
        merge(int(np.argmin(diffs)), int(np.argmin(diffs)) + 1)
    return zones


def zones_from_levels(levels, length: float, margin: float) -> list[Zone]:
    """Zonen direkt aus den Ebenen [a, b, z]. An jedem Absatz reicht die tiefere Ebene um das
    Spiel (margin) in die höhere hinein, damit das Werkzeugende samt Spiel hineinpasst."""
    zs = [Zone(float(a), float(b), float(z)) for a, b, z in levels]
    for lo, hi in zip(zs[:-1], zs[1:]):
        cut = lo.b
        if lo.floor < hi.floor:
            cut = min(cut + margin, hi.b - 0.5)
        elif lo.floor > hi.floor:
            cut = max(cut - margin, lo.a + 0.5)
        lo.b = hi.a = cut
    zs[0].a = -margin
    zs[-1].b = length + margin
    return zs
