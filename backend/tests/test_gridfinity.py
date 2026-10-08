import cadquery as cq
import pytest
import trimesh

from app.export.step import export_step
from app.export.stl import export_stl
from app.geometry.checks import check_shape
from app.geometry.gridfinity import make_baseplate, make_bin


@pytest.fixture(scope="module")
def bin_3x5x6():
    return make_bin(3, 5, 6)


def test_bbox_with_lip(bin_3x5x6):
    bb = bin_3x5x6.val().BoundingBox()
    assert (bb.xmin, bb.ymin, bb.zmin) == pytest.approx((0, 0, 0), abs=1e-3)
    assert bb.xlen == pytest.approx(125.5, abs=0.05)
    assert bb.ylen == pytest.approx(209.5, abs=0.05)
    # cq-gridfinity: Stapelrand 3.8 mm (Plan: 4.4) -> 42 + 3.8
    assert bb.zlen == pytest.approx(45.8, abs=0.05)


def test_surface_at_42(bin_3x5x6):
    # Innenraum über der Körperoberkante ist offen: bei z=43 nur Ring, bei z=41 voll
    def area(z):
        s = cq.Workplane("XY").box(300, 300, 0.01, centered=False).translate((-20, -20, z))
        return bin_3x5x6.intersect(s).val().Volume() / 0.01
    assert area(41.0) > 125 * 209 * 0.95
    assert area(43.0) < 125 * 209 * 0.2
    assert area(42.2) < area(41.0)


def test_no_lip_top_flat():
    b = make_bin(3, 5, 6, stacking_lip=False)
    assert b.val().BoundingBox().zlen == pytest.approx(42.0, abs=0.01)


def test_fifteen_feet(bin_3x5x6):
    s = cq.Workplane("XY").box(300, 300, 0.01, centered=False).translate((-20, -20, 1.0))
    cut = bin_3x5x6.intersect(s)
    assert len(cut.solids().vals()) == 15
    for sol in cut.solids().vals():
        bb = sol.BoundingBox()
        assert 36.0 < bb.xlen < 38.0 and 36.0 < bb.ylen < 38.0
    bottom = bin_3x5x6.intersect(
        cq.Workplane("XY").box(300, 300, 0.01, centered=False).translate((-20, -20, 0.0)))
    assert len(bottom.solids().vals()) == 15


def test_checks_and_export(bin_3x5x6, tmp_path):
    c = check_shape(bin_3x5x6)
    assert c.valid and c.solid_count == 1 and c.watertight and c.ok
    stl = export_stl(bin_3x5x6, tmp_path / "bin.stl")
    m = trimesh.load(stl)
    assert m.is_watertight
    assert m.volume == pytest.approx(c.volume_mm3, rel=2e-3)
    step = export_step(bin_3x5x6, tmp_path / "bin.step")
    assert step.stat().st_size > 1000
    back = cq.importers.importStep(str(step))
    assert back.val().Volume() == pytest.approx(c.volume_mm3, rel=1e-4)


def test_baseplate_3x3():
    p = make_baseplate(3, 3)
    bb = p.val().BoundingBox()
    assert bb.xlen == pytest.approx(126.0, abs=0.05)
    assert bb.ylen == pytest.approx(126.0, abs=0.05)
    # cq-gridfinity: 4.75 mm (Plan: 4.65)
    assert bb.zlen == pytest.approx(4.75, abs=0.05)
    assert check_shape(p).ok
