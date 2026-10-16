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


SCAN_STEPS = {"a4": "A4-Blatt suchen", "top": "Draufsicht freistellen", "side": "Seitenansicht freistellen",
              "profile": "Profil berechnen"}


def batch_scan_job(out_dir: str, pid: str, object_ids: list[str], user) -> dict:
    """Stapel-Scan im Projekt: je Werkzeug A4-Blatt, Freistellen beider Ansichten (Hand weg), Profil;
    danach Einlagen nach der Projektvorlage für alle fertigen Werkzeuge und Anordnung in der Schublade.
    Ein Fehler betrifft nur sein Werkzeug: es bleibt unfertig und lässt sich im Scan-Assistenten
    nachbearbeiten."""
    from . import jobs, scan, storage
    from .api.projects import GenerateBody, generate

    def name(oid: str) -> str:
        try:
            return storage.load_object(oid, user).name
        except KeyError:
            return ""

    items = [{"id": oid, "name": name(oid), "status": "wait", "step": None, "error": None, "warnings": []}
             for oid in object_ids]
    n = len(items)

    def report(k: float) -> None:
        jobs.report(out_dir, progress=0.02 + 0.93 * k / (n + 0.5), items=items)

    for k, it in enumerate(items):
        it["status"] = "running"
        try:
            spec = storage.load_object(it["id"], user)
            it["step"] = "a4"
            report(k)
            errors, views = [], []
            for view in ("top", "side"):
                bgr, f35, _ = scan.load(spec, view)
                if scan.detect_corners(spec, view, bgr, f35):
                    views.append(view)
                else:                                       # Schritt bleibt im Scan-Assistenten offen
                    spec.photos[view].pop("rectified_url", None)
                    errors.append(f"A4-Blatt in der {scan.VIEW_NAMES[view]} nicht gefunden.")
                storage.save_object(spec)
            for view in views:                              # Draufsicht zuerst: Rückfallebene der Handentfernung
                it["step"] = view
                report(k + (0.2 if view == "top" else 0.5))
                try:
                    info = scan.segment_view(spec, view)
                except scan.ScanError as e:
                    errors.append(f"{scan.VIEW_NAMES[view]}: {e}")
                    continue
                if view == "top" and info.get("touches_paper_edge"):
                    it["warnings"].append("Das Werkzeug reicht in der Draufsicht bis an den Blattrand.")
            if errors:
                raise scan.ScanError(" ".join(errors) + " Im Scan-Assistenten nachbearbeiten.")
            it["step"] = "profile"
            report(k + 0.85)
            scan.compute_profile(spec)
            T = max(spec.profile.top) if spec.profile and spec.profile.top else 0.0
            if spec.width_mm and T > 1.3 * spec.width_mm:
                it["warnings"].append("Dicker als breit: Draufsicht und Seitenansicht vertauscht?")
            it.update(status="done", step=None, length_mm=spec.length_mm, width_mm=spec.width_mm)
        except scan.ScanError as e:
            it.update(status="error", error=str(e))
        except KeyError:
            it.update(status="error", error="Werkzeug nicht gefunden (gelöscht?)")
        except Exception as e:  # noqa: BLE001 - ein Werkzeug darf den Stapel nicht abbrechen
            it.update(status="error", error=f"Automatische Auswertung fehlgeschlagen ({type(e).__name__}: {e}). "
                                            "Im Scan-Assistenten nachbearbeiten.")
        report(k + 1)
    ok = [it["id"] for it in items if it["status"] == "done"]
    res: dict = {"created": [], "skipped": [], "already": []}
    warnings: list[str] = []
    if ok:
        try:
            res = generate(pid, GenerateBody(object_ids=ok, arrange=True), user)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Einlagen konnten nicht erzeugt werden: {getattr(e, 'detail', e)}")
    return {"outputs": {}, "items": items, "warnings": warnings,
            "checks": {"done": len(ok), "failed": n - len(ok), "generate": res}}
