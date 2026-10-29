"""Fachbeschriftung (mittig im Fach) und Vordach mit Beschriftung."""
import pytest
from fastapi.testclient import TestClient

from app.geometry.insert_cad import build_insert
from app.geometry.layout import SHELF_T, compute_layout, grid_compartments
from app.main import app
from app.schemas import CompLabel, Compartment, InsertSpec, color_palette

client = TestClient(app)


def _bin(labels: list[CompLabel | None], gx=2, gy=1, cols=2, rows=1) -> InsertSpec:
    spec = InsertSpec(grid_x=gx, grid_y=gy, height_mm=42, auto_grip=False, auto_center=False)
    lay = compute_layout(spec, {})
    comps = [Compartment(x=0, y=0, w=1, l=1, depth=None, polygon=[list(p) for p in q.exterior.coords])
             for q in grid_compartments(lay, spec, cols, rows)]
    for c, lb in zip(comps, labels):
        c.label = lb
    return spec.model_copy(update={"compartments": comps})


def test_label_centered_on_floor_and_auto_size():
    spec = _bin([CompLabel(text="10"), CompLabel(text="0.75", size=5)])
    lay = compute_layout(spec, {})
    assert len(lay.comp_labels) == 2 and not lay.shelves
    for t, c in zip(lay.comp_labels, lay.comps):
        assert t.z0 == pytest.approx(c.z0) and t.z1 == pytest.approx(c.z0 + 0.6)
        tc, cc = t.poly.envelope.centroid, c.poly.centroid
        assert (tc.x, tc.y) == pytest.approx((cc.x, cc.y), abs=0.3)          # mittig
        assert c.poly.contains(t.poly)
    assert lay.comp_labels[1].poly.bounds[3] - lay.comp_labels[1].poly.bounds[1] == pytest.approx(5, abs=0.3)
    assert lay.comp_labels[0].spec.size > 5                                      # passt sich dem Fach an


def test_shelf_geometry_and_label_flush_with_surface():
    spec = _bin([CompLabel(text="2x1.5", shelf=True), CompLabel(shelf=True, side="left")])
    lay = compute_layout(spec, {})
    back, left = lay.shelves
    zs = lay.z_surface
    assert back.z_top == pytest.approx(zs - 0.6) and left.z_top == pytest.approx(zs)   # ohne Text bündig
    assert back.z_bottom == pytest.approx(back.z_top - SHELF_T - back.depth)            # 45°
    assert back.poly.bounds[3] == pytest.approx(lay.comps[0].poly.bounds[3])           # an der hinteren Wand
    assert len(lay.comp_labels) == 1 and lay.comp_labels[0].z1 == pytest.approx(zs)
    assert back.poly.buffer(1e-6).contains(lay.comp_labels[0].poly)


def test_cad_one_watertight_body_label_color_part():
    spec = _bin([CompLabel(text="6", shelf=True, color="#ffcc00"), CompLabel(text="4")])
    plain = build_insert(_bin([None, None]), {})
    r = build_insert(spec, {})
    assert r.checks.valid and r.checks.watertight and r.checks.solid_count == 1 and r.volume_sum_ok
    assert r.body.val().Volume() > plain.body.val().Volume() + 500          # Vordach ist Material
    text = [p for p in r.parts if p.group == "text"]
    assert len(text) == 2 and color_palette(spec).index("#ffcc00") + 1 in {p.slot for p in text}


def test_bin_api_with_labels_and_shelf():
    r = client.post("/api/inserts/bin", json={"grid_x": 2, "grid_y": 2, "cols": 2, "rows": 2, "shelf": True, "height_mm": 42,
                                              "labels": ["A", "B", "C"]})
    assert r.status_code == 200, r.text
    ins = r.json()
    assert all(c["label"]["shelf"] for c in ins["compartments"])
    back_left = max(ins["compartments"], key=lambda c: (c["y"], -c["x"]))
    assert back_left["label"]["text"] == "A"
    lay = client.post(f"/api/inserts/{ins['id']}/layout", json=ins).json()
    assert len(lay["shelves"]) == 4, lay
    assert len(lay["comp_labels"]) == 3
