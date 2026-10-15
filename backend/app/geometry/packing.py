"""Einlagen im Schubladenraster anordnen (einfacher, nachvollziehbarer Algorithmus statt KI).

Jede Einlage belegt gx x gy Zellen (gedreht: gy x gx). Größte zuerst; jede Einlage kommt an die
Stelle (und Drehung), an der sie am meisten Kontakt zu Wand und Nachbarn hat, bei Gleichstand möglichst
weit vorne links. So bleibt die freie Fläche zusammenhängend. Was nicht passt, bleibt draußen und
wird gemeldet (lässt sich von Hand wieder hineinziehen).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Item:
    id: str
    gx: int
    gy: int


def _cells(ix: int, iy: int, w: int, h: int):
    return [(i, j) for i in range(ix, ix + w) for j in range(iy, iy + h)]


def fits(free: set[tuple[int, int]], ix: int, iy: int, w: int, h: int) -> bool:
    return all(c in free for c in _cells(ix, iy, w, h))


def _contact(free: set, nx: int, ny: int, ix: int, iy: int, w: int, h: int) -> int:
    """Kanten der Einlage, an denen keine freie Zelle liegt (Wand, abgewählte Zelle, Nachbar)."""
    n = 0
    for i in range(ix, ix + w):
        n += (i, iy - 1) not in free
        n += (i, iy + h) not in free
    for j in range(iy, iy + h):
        n += (ix - 1, j) not in free
        n += (ix + w, j) not in free
    return n


def pack(nx: int, ny: int, free: set[tuple[int, int]], items: list[Item]) -> tuple[dict[str, tuple[int, int, int]], list[str]]:
    """Rückgabe: {id: (ix, iy, rot)} und Liste der Einlagen, die nicht hineinpassen."""
    free = set(free)
    placed: dict[str, tuple[int, int, int]] = {}
    left: list[str] = []
    for it in sorted(items, key=lambda q: (-(q.gx * q.gy), -max(q.gx, q.gy), q.id)):
        best = None
        for rot, (w, h) in ((0, (it.gx, it.gy)), (90, (it.gy, it.gx))):
            if rot == 90 and it.gx == it.gy:
                continue
            for iy in range(ny - h + 1):
                for ix in range(nx - w + 1):
                    if fits(free, ix, iy, w, h):
                        score = (_contact(free, nx, ny, ix, iy, w, h) / (2 * (w + h)), -iy, -ix)
                        if best is None or score > best[0]:
                            best = (score, ix, iy, rot, w, h)
        if best is None:
            left.append(it.id)
            continue
        _, ix, iy, rot, w, h = best
        free -= set(_cells(ix, iy, w, h))
        placed[it.id] = (ix, iy, rot)
    return placed, left
