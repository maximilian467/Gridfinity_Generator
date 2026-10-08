import cadquery as cq
import pytest

from app.geometry.checks import check_shape
from app.geometry.insert_cad import build_insert
from app.geometry.layout import compute_layout
from app.geometry.samples import l_shape, synthetic_pliers
from app.geometry.zones import compute_zones
from app.schemas import Compartment, GripRecess, InsertSpec, Placement


# ---- Zonen --------------------------------------------------------------
S = [i * 0.5 for i in range(201)]


def test_zones_constant_profile_single_zone():
    z = compute_zones(S, [0.0] * 201, 100.0, 2.5)
    assert len(z) == 1 and z[0].a == pytest.approx(-2.5) and z[0].b == pytest.approx(102.5)


def test_zones_step_and_min_filter():
    bottom = [0.0 if x < 50 else 5.0 for x in S]
    z = compute_zones(S, bottom, 100.0, 2.5)
    assert len(z) == 2
    assert z[0].floor == pytest.approx(0.0) and z[1].floor == pytest.approx(5.0)
    # Verschiebungstoleranz: die hohe Zone beginnt erst 2.5 mm hinter der Stufe
    assert z[0].b == pytest.approx(52.5, abs=0.6)


def test_zones_short_merged_and_max():
    bottom = [6.0 if 40 <= x < 44 else 0.0 for x in S]
    z = compute_zones(S, bottom, 100.0, 0.0)
    assert all(zz.b - zz.a >= 8 - 1e-6 for zz in z)
    bt = [(12.0 * (int(x // 10) % 2)) for x in S]
    assert len(compute_zones(S, bt, 100.0, 0.0, max_zones=4)) <= 4


def test_pliers_zones():
    o = synthetic_pliers()
    z = compute_zones(o.profile.s, o.profile.bottom, o.length_mm, 2.5)
    assert 3 <= len(z) <= 8


# ---- Layout -------------------------------------------------------------
def test_auto_grid_and_height():
    o = synthetic_pliers()
    spec = InsertSpec(placements=[Placement(object_id="pliers", x=6, y=30)])
    lay = compute_layout(spec, {"pliers": o})
    assert lay.grid_x == 5 and lay.grid_y == 2
    assert not lay.warnings
    assert min(p.z0 for p in lay.pieces) >= 4.75 + 1.5 - 1e-6
    spec2 = InsertSpec(grid_x=lay.grid_x, grid_y=lay.grid_y, height_u=lay.height_u - 1,
                       placements=spec.placements)
    lay2 = compute_layout(spec2, {"pliers": o})
    assert any("höher" in w for w in lay2.warnings)


# ---- CAD ----------------------------------------------------------------
@pytest.fixture(scope="module")
def pliers_result():
    o = synthetic_pliers()
    spec = InsertSpec(grid_x=5, grid_y=2, placements=[Placement(object_id="pliers", x=12, y=42)],
                      grip_recesses=[GripRecess(shape="stadium", x=60, y=42, w=14, l=40, rot_deg=90)],
                      compartments=[Compartment(x=180, y=55, w=20, l=20, depth=12)])
    return spec, o, build_insert(spec, {"pliers": o})


def test_insert_one_body_valid(pliers_result):
    spec, o, r = pliers_result
    assert r.checks.valid and r.checks.solid_count == 1 and r.checks.watertight
    assert r.volume_sum_ok
    assert all(r.part_checks.values())
    assert [p.name for p in r.parts] == ["Körper", "Greifmulden", "Taschen", "Fächer"]
    u = r.parts[0].shape
    for p in r.parts[1:]:
        u = u.union(p.shape)
    assert check_shape(u, mesh_check=False).solid_count == 1


def test_cutters_inside_inner_area(pliers_result):
    _, _, r = pliers_result
    assert not [w for w in r.warnings if "Innenbereich" in w]
    assert r.body.val().BoundingBox().xlen == pytest.approx(5 * 42 - 0.5, abs=0.3)


def test_pocket_floor_matches_layout(pliers_result):
    _, _, r = pliers_result
    solid = r.body.val()
    for p in r.layout.pieces:
        pt = p.poly.representative_point()
        if any(g.contains(pt) for g, _ in r.layout.grips):
            continue
        assert not solid.isInside(cq.Vector(pt.x, pt.y, p.z0 + 0.3))
        assert solid.isInside(cq.Vector(pt.x, pt.y, p.z0 - 0.3))


def test_lform_not_mirrored():
    o = l_shape()
    spec = InsertSpec(grid_x=2, grid_y=2, height_u=3,
                      placements=[Placement(object_id="lform", x=10, y=20, rot_deg=0)])
    r = build_insert(spec, {"lform": o})
    solid = r.body.val()
    z = r.layout.pieces[0].z0 + 1.0
    # Nase des L: x = 40..60, y = 10..20 (objekt-lokal) -> Einlage (+10, +20)
    assert not solid.isInside(cq.Vector(10 + 55, 20 + 15, z))     # Nase -> Tasche (Luft)
    assert solid.isInside(cq.Vector(10 + 5, 20 + 15, z))          # gespiegelt wäre hier Luft
    assert not solid.isInside(cq.Vector(10 + 5, 20 + 5, z))       # Balken
