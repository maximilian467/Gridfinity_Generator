"""Farbteile: Haut um Greifmulden > Taschen > Fächer, dann Schrift je Farbe; Rest = Körper (Plan H)."""
from __future__ import annotations

import cadquery as cq

from ..schemas import InsertSpec, color_palette
from .cutters import fuse_all, prism
from .layout import Layout

TOP_EXTRA = 5.0


def _grown(lay: Layout, spec: InsertSpec) -> dict[str, list[cq.Shape]]:
    sk = spec.color_skin
    top = lay.z_surface + TOP_EXTRA if sk.show_top_ring else lay.z_surface - 0.6
    out: dict[str, list[cq.Shape]] = {"grip": [], "pocket": [], "compartment": []}
    for p in lay.pieces:
        out["pocket"] += prism(p.poly.buffer(sk.wall, join_style=1), p.z0 - sk.floor, top)
    for g in lay.grips:
        out["grip"] += prism(g.poly.buffer(sk.wall, join_style=1), g.z0 - sk.floor, top)
    for c in lay.comps:
        out["compartment"] += prism(c.poly.buffer(sk.wall, join_style=1), c.z0 - sk.floor, top)
    return out


def _text_regions(lay: Layout, spec: InsertSpec) -> dict[str, list[cq.Shape]]:
    """Farbbereich der Schrift je Farbe: erhaben = die Buchstaben selbst, bündig = die oberste
    Schicht in Buchstabenform, vertieft = der Boden der Vertiefung (Farbhaut)."""
    from .insert_cad import RAISED_SEAT

    out: dict[str, list[cq.Shape]] = {}
    for t in lay.all_texts:
        st = t.spec.style
        if st == "raised":
            z0, z1 = t.z0 - RAISED_SEAT, t.z1 + 1.0
        elif st == "flush":
            z0, z1 = t.z0, t.z1 + 1.0
        else:
            # vertieft: Boden und Wände der Vertiefung bis in die obersten Schichten (Schrift bleibt von oben farbig)
            reg = t.poly.buffer(spec.color_skin.wall, join_style=1)
            out.setdefault(t.spec.color.lower(), []).extend(prism(reg, t.z0 - spec.color_skin.floor, t.z1 + 1.0))
            continue
        out.setdefault(t.spec.color.lower(), []).extend(prism(t.poly, z0, z1))
    return out


def split_color_parts(body: cq.Workplane, lay: Layout, spec: InsertSpec):
    from .insert_cad import Part

    grown = _grown(lay, spec)
    slots = spec.colors
    names = {"grip": "Greifmulden", "pocket": "Taschen", "compartment": "Fächer"}
    given: cq.Workplane | None = None
    parts: list[Part] = []
    # Schrift zuerst: Fachbeschriftungen liegen im Fach (sonst nähme die Fächerhaut sie mit)
    for color, shapes in _text_regions(lay, spec).items():
        gr = fuse_all(shapes)
        part = body.intersect(gr)
        if given is not None:
            part = part.cut(given)
        if not part.solids().vals() or part.val().Volume() < 1e-3:
            continue
        n = sum(1 for p in parts if p.group == "text")
        parts.append(Part("Schrift" if n == 0 else f"Schrift {n + 1}", part, color_palette(spec).index(color) + 1, "text"))
        given = part if given is None else given.union(part)
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
    parts[1:] = sorted(parts[1:], key=lambda p: p.group == "text")      # Reihenfolge wie bisher: Schrift zuletzt
    return parts
