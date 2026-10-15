"""Worker-Funktionen für den Prozesspool (müssen top-level und picklebar sein)."""
from __future__ import annotations

from pathlib import Path

from .schemas import BaseplateSpec, InsertSpec, ObjectSpec
from .storage import url_for

PLA_G_PER_MM3 = 1.24e-3


def build_insert_job(out_dir: str, insert_json: str, objects_json: dict[str, str]) -> dict:
    import cadquery as cq

    from .export.fit_test import make_fit_test
    from .export.glb import export_glb
    from .export.parts_zip import write_parts_zip
    from .export.step import export_step
    from .export.stl import export_stl
    from .export.threemf_bambu import write_bambu_3mf, write_plain_3mf
    from .geometry.insert_cad import build_insert

    out = Path(out_dir)
    from .storage import slots_from_colors
    spec = slots_from_colors(InsertSpec.model_validate_json(insert_json))
    slot_hex = {getattr(spec.colors, k): getattr(spec.color_hex, k) for k in ("body", "pocket", "grip", "compartment")}
    objects = {k: ObjectSpec.model_validate_json(v) for k, v in objects_json.items()}
    res = build_insert(spec, objects)
    name = "einlage"
    files = {
        "3mf": write_bambu_3mf(res.parts, out / f"{name}.3mf", spec.name),
        "3mf_plain": write_plain_3mf(res.parts, out / f"{name}_einfach.3mf", spec.name),
        "stl": export_stl(res.body, out / f"{name}.stl"),
        "parts_zip": write_parts_zip(res.parts, out / f"{name}_teile.zip"),
        "glb": export_glb(res.parts, out / f"{name}.glb", slot_hex),
    }
    asm = cq.Assembly(name=spec.name)
    palette = [(0.8, 0.8, 0.82), (0.9, 0.47, 0.12), (0.24, 0.5, 0.86), (0.35, 0.67, 0.35), (0.75, 0.27, 0.27)]
    for p in res.parts:
        if p.slot in slot_hex:
            h = slot_hex[p.slot].lstrip("#")
            c = tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        else:
            c = palette[(p.slot - 1) % len(palette)]
        asm.add(p.shape, name=p.name, color=cq.Color(*c))
    files["step"] = export_step(asm, out / f"{name}.step")
    if res.layout.pieces:
        files["fit_test"] = export_stl(make_fit_test(res.layout), out / "passform_test.stl")
    c = res.checks
    checks = {
        "valid": c.valid, "solid_count": c.solid_count, "watertight": c.watertight,
        "volume_mm3": c.volume_mm3, "weight_g": round(c.volume_mm3 * PLA_G_PER_MM3, 1),
        "volume_sum_ok": res.volume_sum_ok, "parts": {p.name: round(p.shape.val().Volume(), 1) for p in res.parts},
        "bbox": list(c.bbox), "grid_x": res.layout.grid_x, "grid_y": res.layout.grid_y,
        "height_u": res.layout.height_u,
    }
    return {"outputs": {k: url_for(v) for k, v in files.items()}, "checks": checks, "warnings": res.warnings}


def build_baseplate_job(out_dir: str, spec_json: str) -> dict:
    from .geometry.baseplate import build_baseplate_files

    out = Path(out_dir)
    spec = BaseplateSpec.model_validate_json(spec_json)
    files, info = build_baseplate_files(spec, out)
    return {"outputs": {k: url_for(v) for k, v in files.items()}, "checks": info, "warnings": info.get("warnings", [])}
