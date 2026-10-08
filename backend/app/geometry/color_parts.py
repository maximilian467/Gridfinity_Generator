"""Farbteile: Haut um Greifmulden > Taschen > Fächer; Rest = Körper (Plan H)."""
from __future__ import annotations

import cadquery as cq

from ..schemas import InsertSpec
from .cutters import fuse_all, prism
from .layout import Layout

TOP_EXTRA = 5.0


def _grown(lay: Layout, spec: InsertSpec) -> dict[str, list[cq.Shape]]:
    sk = spec.color_skin
    top = lay.z_surface + TOP_EXTRA if sk.show_top_ring else lay.z_surface - 0.6
    out: dict[str, list[cq.Shape]] = {"grip": [], "pocket": [], "compartment": []}
    for p in lay.pieces:
        out["pocket"] += prism(p.poly.buffer(sk.wall, join_style=1), p.z0 - sk.floor, top)
    for poly, z0 in lay.grips:
        out["grip"] += prism(poly.buffer(sk.wall, join_style=1), z0 - sk.floor, top)
    for poly, z0, _ in lay.comps:
        out["compartment"] += prism(poly.buffer(sk.wall, join_style=1), z0 - sk.floor, top)
    return out


def split_color_parts(body: cq.Workplane, lay: Layout, spec: InsertSpec):
    from .insert_cad import Part

    grown = _grown(lay, spec)
    slots = spec.colors
    names = {"grip": "Greifmulden", "pocket": "Taschen", "compartment": "Fächer"}
    given: cq.Workplane | None = None
    parts: list[Part] = []
    for g in ("grip", "pocket", "compartment"):
        gr = fuse_all(grown[g])
        if gr is None:
            continue
        part = body.intersect(gr)
        if given is not None:
            part = part.cut(given)
        if not part.solids().vals() or part.val().Volume() < 1e-3:
            continue
        parts.append(Part(names[g], part, getattr(slots, g), g))
        given = part if given is None else given.union(part)
    main = body if given is None else body.cut(given)
    parts.insert(0, Part("Körper", main, slots.body, "body"))
    return parts
