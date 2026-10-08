import xml.etree.ElementTree as ET
import zipfile

import cadquery as cq
import pytest
import trimesh

from app.export.fit_test import make_fit_test
from app.export.glb import export_glb
from app.export.parts_zip import write_parts_zip
from app.export.step import export_step
from app.export.threemf_bambu import write_bambu_3mf, write_plain_3mf
from app.geometry.checks import check_shape
from app.geometry.insert_cad import build_insert
from app.geometry.samples import synthetic_pliers
from app.schemas import GripRecess, InsertSpec, Placement


@pytest.fixture(scope="module")
def res():
    o = synthetic_pliers()
    spec = InsertSpec(grid_x=5, grid_y=2, placements=[Placement(object_id="pliers", x=12, y=42)],
                      grip_recesses=[GripRecess(x=60, y=42, w=14, l=40, rot_deg=90)])
    return build_insert(spec, {"pliers": o})


def test_bambu_3mf_structure(res, tmp_path):
    p = write_bambu_3mf(res.parts, tmp_path / "e.3mf")
    z = zipfile.ZipFile(p)
    assert {"3D/3dmodel.model", "Metadata/model_settings.config", "[Content_Types].xml"} <= set(z.namelist())
    cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
    names = [pt.find("metadata[@key='name']").get("value") for pt in cfg.iter("part")]
    assert names == [pt.name for pt in res.parts]
    ex = [int(pt.find("metadata[@key='extruder']").get("value")) for pt in cfg.iter("part")]
    assert ex == [pt.slot for pt in res.parts]
    model = ET.fromstring(z.read("3D/3dmodel.model"))
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    assert len(model.findall(".//m:component", ns)) == len(res.parts)
    assert len(model.findall(".//m:build/m:item", ns)) == 1


def test_3mf_loads_and_geometry_matches(res, tmp_path):
    for fn, writer in (("b.3mf", write_bambu_3mf), ("p.3mf", write_plain_3mf)):
        p = writer(res.parts, tmp_path / fn)
        sc = trimesh.load(p)
        vol = sum(g.volume for g in sc.geometry.values())
        assert vol == pytest.approx(res.checks.volume_mm3, rel=5e-3)


def test_glb_stl_step_fit(res, tmp_path):
    g = export_glb(res.parts, tmp_path / "e.glb")
    assert len(trimesh.load(g).geometry) == len(res.parts)
    z = write_parts_zip(res.parts, tmp_path / "p.zip")
    assert len(zipfile.ZipFile(z).namelist()) == len(res.parts)
    asm = cq.Assembly()
    for p in res.parts:
        asm.add(p.shape, name=p.name)
    assert export_step(asm, tmp_path / "e.step").stat().st_size > 1000
    ft = make_fit_test(res.layout)
    c = check_shape(ft)
    assert c.ok and c.bbox[2] == pytest.approx(3.0, abs=0.01)
    assert c.bbox[0] == pytest.approx(5 * 42 - 0.5, abs=0.3)
