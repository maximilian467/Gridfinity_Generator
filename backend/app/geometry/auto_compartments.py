"""Auto-Fächer (Plan Phase 6): größte freie achsparallele Rechtecke im Innenbereich."""
from __future__ import annotations

import numpy as np
from shapely import contains_xy
from shapely.geometry import box
from shapely.ops import unary_union

from ..schemas import Compartment, InsertSpec
from .gridfinity import FOOT_H
from .layout import Layout


def _max_rect(free: np.ndarray) -> tuple[int, int, int, int] | None:
    """Größtes Rechteck aus True-Zellen: (r0, c0, hgt, wid)."""
    best, best_area = None, 0
    h = np.zeros(free.shape[1], int)
    for r in range(free.shape[0]):
        h = np.where(free[r], h + 1, 0)
        stack: list[tuple[int, int]] = []     # (start, height)
        for c in range(len(h) + 1):
            cur = h[c] if c < len(h) else 0
            start = c
            while stack and stack[-1][1] >= cur:
                s, hh = stack.pop()
                area = hh * (c - s)
                if area > best_area:
                    best_area, best = area, (r - hh + 1, s, hh, c - s)
                start = s
            stack.append((start, cur))
    return best


def propose_compartments(lay: Layout, spec: InsertSpec, max_n: int = 6, min_size: float = 20.0,
                         depth: float = 15.0) -> list[Compartment]:
    inner = lay.inner
    x0, y0, x1, y1 = inner.bounds
    occupied = [p.poly for p in lay.pieces] + [g for g, _ in lay.grips] + [c for c, _, _ in lay.comps]
    blocked = unary_union(occupied).buffer(spec.min_wall) if occupied else None
    xs = np.arange(x0 + 0.5, x1, 1.0)
    ys = np.arange(y0 + 0.5, y1, 1.0)
    gx, gy = np.meshgrid(xs, ys)
    free = np.ones(gx.shape, bool)
    if blocked is not None:
        free &= ~contains_xy(blocked, gx.ravel(), gy.ravel()).reshape(gx.shape)
    max_depth = lay.z_surface - (FOOT_H + spec.floor_min)
    d = max(2.0, min(depth, max_depth))
    out: list[Compartment] = []
    for _ in range(max_n):
        r = _max_rect(free)
        if r is None:
            break
        r0, c0, hh, ww = r
        if hh < min_size or ww < min_size:
            break
        cx, cy = x0 + c0, y0 + r0
        out.append(Compartment(x=float(cx), y=float(cy), w=float(ww), l=float(hh), radius=3.0, depth=round(d, 1)))
        taken = box(cx, cy, cx + ww, cy + hh).buffer(spec.min_wall)
        free &= ~contains_xy(taken, gx.ravel(), gy.ravel()).reshape(gx.shape)
    return out
