"""Ebenen statt Höhenprofil, Einsinktiefe, feste Gesamthöhe, weiche Greifmulde, Kästen."""
import cadquery as cq
from shapely.geometry import Point
import numpy as np
import pytest

from app.geometry.cutters import grip_cutter
from app.geometry.layout import compute_layout
from app.geometry.samples import synthetic_pliers
from app.schemas import Compartment, InsertSpec, Placement
from app.vision.profile import bottom_from_levels, fit_levels


def _pliers_bottom():
    """Backen 3 mm, Griffschutz 0, Griffe 6 mm mit Rampen, Rauschen, Anstieg am Ende (Hand)."""
    s = np.arange(0, 165.5, 0.5)
    z = np.interp(s, [0, 80, 86, 100, 108, 150, 165], [3, 3, 0, 0, 6, 6, 11])
    z += np.random.default_rng(1).normal(0, 0.15, s.size)
    return s, z


def test_three_levels_no_penetration_no_end_rise():
    s, z = _pliers_bottom()
    lv = fit_levels(s, z)
    assert len(lv) == 3
    assert [round(q[2]) for q in lv] == [3, 0, 6]
    assert lv[0][0] == 0 and lv[-1][1] == pytest.approx(165, abs=0.5)
    floor = bottom_from_levels(s, lv)
    assert (floor - z <= 0.6).all()                 # nirgends steckt das Werkzeug im Boden
    # der Anstieg am Ende bildet keine eigene Ebene, die letzte liegt auf den Griffen
    assert lv[-1][0] < 115


def test_level_count_and_reliable_mask():
    s, z = _pliers_bottom()
    assert len(fit_levels(s, z, count=2)) == 2
    assert len(fit_levels(s, z, count=4)) == 4
    ok = s < 140                                     # Ende verdeckt: zählt nicht
    lv = fit_levels(s, z, ok)
    assert lv[-1][1] == pytest.approx(165, abs=0.5)


def _spec(**kw):
    return InsertSpec(placements=[Placement(object_id="p", rot_deg=90)], auto_grip=False, **kw)


def test_sink_fraction_lets_tool_protrude():
    o = synthetic_pliers()
    T = max(o.profile.top)
    for sink in (0.5, 0.75, 1.0):
        lay = compute_layout(_spec(sink=sink), {"p": o})
        deepest = min(p.z0 for p in lay.pieces) + 0.4          # Auflage der tiefsten Ebene
        assert lay.z_surface - deepest == pytest.approx(sink * T, abs=0.05)
        assert lay.sink[0] == pytest.approx(sink, abs=0.01)


def test_fixed_total_height_reduces_sink():
    o = synthetic_pliers()
    lay = compute_layout(_spec(height_mm=30.0), {"p": o})
    assert lay.total_height == pytest.approx(30.0, abs=0.01)
    lay2 = compute_layout(_spec(height_mm=22.0, sink=1.0), {"p": o})
    assert lay2.total_height == pytest.approx(22.0, abs=0.01)
    assert min(p.z0 for p in lay2.pieces) >= 4.75 + 1.5 - 1e-6
    assert any("flacher" in w for w in lay2.warnings)


def test_grid_does_not_grow_with_compartments():
    o = synthetic_pliers()
    lay0 = compute_layout(_spec(), {"p": o})
    x0, y0, x1, y1 = lay0.inner.bounds
    big = Compartment(x=x0 - lay0.shift[0], y=y0 - lay0.shift[1], w=x1 - x0, l=8, depth=None,
                      polygon=None)
    lay1 = compute_layout(_spec(compartments=[big]), {"p": o})
    assert (lay1.grid_x, lay1.grid_y) == (lay0.grid_x, lay0.grid_y)


def test_compartment_max_depth_follows_height():
    o = synthetic_pliers()
    c = Compartment(x=5, y=5, w=20, l=20, depth=None)
    for h in (25.0, 40.0):
        lay = compute_layout(_spec(height_mm=h, compartments=[c]), {"p": o})
        assert lay.comps[0].z0 == pytest.approx(4.75 + 1.5)


def test_soft_grip_profile():
    o = synthetic_pliers()
    from app.schemas import GripRecess
    spec = InsertSpec(grid_x=3, grid_y=5, auto_grip=False, placements=[Placement(object_id="p", rot_deg=90)],
                      grip_recesses=[GripRecess(x=0, y=0, w=16, attach=0, s=60, edge_r=3)])
    lay = compute_layout(spec, {"p": o})
    g = lay.grips[0]
    solid = grip_cutter(g, lay.z_surface + 5)[0]
    assert solid.isValid()
    (ax, ay), (bx, by) = list(g.axis.coords)
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    nx, ny = -(by - ay) / L, (bx - ax) / L
    zt = lay.z_surface
    inside = lambda d, z: solid.isInside(cq.Vector(cx + nx * d, cy + ny * d, z))   # noqa: E731
    assert inside(0, g.z0 + 0.3)                     # Boden in der Mitte
    assert inside(6.0, zt - 0.5)                     # Kantenradius: knapp unter der Oberfläche schon Mulde
    assert not inside(5.5, zt - 4.0)                 # ... aber keine senkrechte Wand bis unten
    assert not inside(8.5, zt - 0.1)                 # außerhalb der Öffnung
    # runde Enden: hinter dem Endpunkt wird die Mulde flacher
    ux, uy = (bx - ax) / L, (by - ay) / L
    assert not solid.isInside(cq.Vector(bx + ux * 6, by + uy * 6, g.z0 + 1))
    assert solid.isInside(cq.Vector(bx + ux * 2, by + uy * 2, zt - 2))


def test_divider_lines_split_free_area():
    from app.schemas import CompLine
    o = synthetic_pliers()
    base = InsertSpec(grid_x=3, grid_y=5, placements=[Placement(object_id="p", rot_deg=90)], comp_cells=True)
    lay0 = compute_layout(base, {"p": o})
    assert len([c for c in lay0.comps if c.cell is not None]) == 1          # ganze freie Fläche
    sx, sy = lay0.shift
    lines = [CompLine(x0=4 - sx, y0=60 - sy, x1=20 - sx, y1=60 - sy),      # waagrecht, links
             CompLine(x0=15 - sx, y0=20 - sy, x1=15 - sx, y1=40 - sy)]     # senkrecht, stoppt an Linie 1
    lay = compute_layout(base.model_copy(update={"comp_lines": lines}), {"p": o})
    (_, a), (_, b) = lay.lines
    pocket = lay.pocket_union()
    assert a.coords[0][0] == pytest.approx(lay.inner.bounds[0], abs=0.1)     # vom Rand ...
    assert pocket.distance(Point(a.coords[-1])) < 4                         # ... bis ans Werkzeug
    assert b.coords[-1][1] == pytest.approx(60 - max(base.comp_wall, 0.8) / 2, abs=0.6)
    cells = [c for c in lay.comps if c.cell is not None]
    assert len(cells) == 2 and not lay.warnings          # Ring um das Werkzeug: zwei Schnitte = zwei Felder
    # Feld entfernen
    rep = cells[0].rep
    lay2 = compute_layout(base.model_copy(update={"comp_lines": lines, "comp_skip": [list(rep)]}), {"p": o})
    assert len([c for c in lay2.comps if c.cell is not None]) == 1
