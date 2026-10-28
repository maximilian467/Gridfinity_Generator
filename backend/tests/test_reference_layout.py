import math
"""Zielbild nach docs/samples/Spitzzange_Gridfinity_3x5_V2_mit_Kaesten.stl:
Zange senkrecht, mittig, Langloch-Greifmulde quer am Gelenk mit rundem Boden, Kästen in den
freien Flächen, deren Wand der Werkzeugkontur folgt."""
import cadquery as cq
import pytest
from shapely.geometry import Polygon

from app.geometry.insert_cad import build_insert
from app.geometry.layout import compute_layout, pocket_outline
from app.geometry.samples import synthetic_pliers
from app.schemas import InsertSpec, Placement


@pytest.fixture(scope="module")
def ref():
    o = synthetic_pliers()
    spec = InsertSpec(grid_x=3, grid_y=5, placements=[Placement(object_id="pliers", x=0, y=0, rot_deg=90)],
                      auto_compartments=True, comp_follow=True)
    return spec, o, build_insert(spec, {"pliers": o})


def test_centered(ref):
    _, _, r = ref
    lay = r.layout
    x0, y0, x1, y1 = lay.pocket_union().union(lay.grips[0].poly).bounds
    ix0, iy0, ix1, iy1 = lay.inner.bounds
    assert (x0 - ix0) == pytest.approx(ix1 - x1, abs=0.5)
    assert (y0 - iy0) == pytest.approx(iy1 - y1, abs=0.5)


def test_auto_grip_rounded_and_below_tool(ref):
    _, _, r = ref
    g = next(g for g in r.layout.grips if g.auto)
    assert g.rounded
    deepest_pocket = min(p.z0 for p in r.layout.pieces if p.poly.intersects(g.poly))
    assert g.z0 < deepest_pocket - 5                     # Finger kommt unter das Werkzeug
    solid = r.body.val()
    (ax, ay), (bx, by) = list(g.axis.coords)
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    ux, uy = (bx - ax), (by - ay)
    n = (ux ** 2 + uy ** 2) ** 0.5
    nx, ny = -uy / n, ux / n
    # Mitte des Bodens: Luft knapp über dem tiefsten Punkt
    assert not solid.isInside(cq.Vector(cx, cy, g.z0 + 0.4))
    # quer zur Mitte am Rand der Mulde, gleiche Höhe: Material (U-Profil statt flacher Boden)
    assert solid.isInside(cq.Vector(cx + nx * g.radius * 0.9, cy + ny * g.radius * 0.9, g.z0 + 0.4))


def test_compartments_follow_contour(ref):
    spec, _, r = ref
    comps = [c for c in r.layout.comps if c.auto]
    assert len(comps) >= 2
    pockets = r.layout.pocket_union()
    grips = r.layout.grips[0].poly
    for c in comps:
        assert r.layout.inner.contains(c.poly)
        assert c.poly.distance(pockets) >= spec.comp_wall - 0.05
        assert c.poly.distance(grips) >= spec.comp_wall - 0.05
        b = c.poly.bounds
        assert b[2] - b[0] >= spec.comp_min_size and b[3] - b[1] >= spec.comp_min_size
    # mindestens ein Kasten ist kein Rechteck (Wand folgt der Tasche)
    assert any(c.poly.area < 0.97 * Polygon.from_bounds(*c.poly.bounds).area for c in comps)
    assert not [w for w in r.warnings if "überlappen" in w or "Wand zwischen" in w or "Innenbereich" in w]


def test_reference_body_valid(ref):
    _, _, r = ref
    assert r.checks.valid and r.checks.solid_count == 1 and r.checks.watertight
    assert r.volume_sum_ok
    assert [p.name for p in r.parts] == ["Körper", "Greifmulden", "Taschen", "Fächer"]


def test_smoothing_never_shrinks():
    notch = [[0, 0], [100, 0], [100, 20], [52, 20], [51, 18.5], [50, 20], [0, 20]]   # 1,5 mm Kerbe
    raw = Polygon(notch)
    o0 = pocket_outline(notch, 1.0, 0.0, 0.0)
    o1 = pocket_outline(notch, 1.0, 0.0, 1.5)
    assert o1.buffer(0.06).contains(raw.buffer(1.0, join_style=1))
    assert o1.area >= o0.area
    # Kerbe geschlossen: oben an der Kerbe liegt die Kontur wieder auf voller Höhe
    from shapely.geometry import LineString as _LS
    cut = _LS([(51, 0), (51, 40)]).intersection(o1)
    assert cut.bounds[3] >= 20.7
    # glatt: kein Knick über 30° zwischen zwei Segmenten
    import numpy as np
    c = np.asarray(o1.exterior.coords)[:-1]
    d = np.diff(np.vstack([c, c[:1]]), axis=0)
    ang = np.degrees(np.abs(np.angle(np.exp(1j * (np.arctan2(d[:, 1], d[:, 0]) - np.roll(np.arctan2(d[:, 1], d[:, 0]), 1))))))
    assert ang.max() < 30


def test_center_off_keeps_positions():
    o = synthetic_pliers()
    spec = InsertSpec(grid_x=5, grid_y=3, auto_center=False, auto_grip=False,
                      placements=[Placement(object_id="pliers", x=10, y=40)])
    lay = compute_layout(spec, {"pliers": o})
    assert lay.shift == (0.0, 0.0)
    assert lay.pocket_union().bounds[0] == pytest.approx(10 - spec.clearance_xy - spec.clearance_end, abs=0.3)


def test_attached_grip_slides_along_axis_and_stays_centered():
    from app.schemas import GripRecess
    o = synthetic_pliers()
    res = []
    for s_ in (40.0, 120.0):
        spec = InsertSpec(grid_x=3, grid_y=5, auto_grip=False, placements=[Placement(object_id="p", rot_deg=90)],
                          grip_recesses=[GripRecess(x=0, y=0, w=16, attach=0, s=s_)])
        lay = compute_layout(spec, {"p": o})
        gb, pb = lay.grips[0].poly.bounds, lay.pocket_union().bounds
        res.append(((gb[1] + gb[3]) / 2, (gb[0] + gb[2]) / 2, (pb[0] + pb[2]) / 2))
    assert res[1][0] - res[0][0] == pytest.approx(80, abs=0.5)        # entlang der Achse verschoben
    for _, gx, px in res:
        assert gx == pytest.approx(px, abs=0.5)                        # quer mittig


def test_bottom_points_and_polyline():
    import numpy as np
    from app.vision.profile import bottom_from_points, bottom_points
    s = np.arange(0, 160.5, 0.5)
    z = np.where(s < 60, 3.0, np.where(s < 75, 0.0, 2.0)) + np.random.default_rng(0).normal(0, 0.1, s.size)
    pts = bottom_points(s, z)
    assert 5 <= len(pts) <= 12
    b = bottom_from_points(s, pts)
    assert abs(b[int(67 / 0.5)] - 0) < 0.3 and abs(b[int(30 / 0.5)] - 3) < 0.4
    # Gerade zwischen zwei Punkten: keine Delle
    b2 = bottom_from_points(s, [[0, 2], [80, 0], [160, 2]])
    assert b2[int(40 / 0.5)] == pytest.approx(1.0, abs=0.01)


def test_attached_grip_can_be_angled():
    from app.schemas import GripRecess
    o = synthetic_pliers()
    out = {}
    for ang in (0.0, 30.0):
        spec = InsertSpec(grid_x=3, grid_y=5, auto_grip=False, auto_center=False,
                          placements=[Placement(object_id="p", x=60, y=10, rot_deg=90)],
                          grip_recesses=[GripRecess(x=0, y=0, w=16, attach=0, s=80, angle_deg=ang)])
        lay = compute_layout(spec, {"p": o})
        (ax, ay), (bx, by) = list(lay.grips[0].axis.coords)
        out[ang] = (math.degrees(math.atan2(by - ay, bx - ax)), math.hypot(bx - ax, by - ay))
    # Werkzeug um 90° gedreht: quer zur Achse = x-Richtung; 30° schräg dreht die Mulde mit
    assert abs(((out[30.0][0] - out[0.0][0]) + 180) % 360 - 180) == pytest.approx(30, abs=0.5)
    assert out[30.0][1] > out[0.0][1]                 # schräge Sehne ist länger


def test_angled_grip_across_two_legs():
    # schräge Sehne schneidet zwei getrennte Schenkel (MultiLineString) -> kein Absturz, ganze Breite
    from shapely.geometry import box
    from app.geometry.layout import grip_across_angled
    legs = box(0, -20, 100, -10).union(box(0, 10, 100, 20))
    cx, cy, L = grip_across_angled(legs, 50, 0, 22.0, 10, 0)
    assert L == pytest.approx(40 / math.cos(math.radians(22)), abs=0.01)
    assert (cx, cy) == (pytest.approx(50, abs=0.01), pytest.approx(0, abs=0.01))
