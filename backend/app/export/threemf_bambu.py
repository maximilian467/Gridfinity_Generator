"""3MF-Writer für Bambu Studio / OrcaSlicer: ein Objekt, mehrere Parts mit Filament-Slot.

Struktur nach Bambu-Konvention (Parts = Komponenten eines Eltern-Objekts,
Namen/Extruder in Metadata/model_settings.config). Fallback: Standard-3MF mit
mehreren Objekten (`write_plain_3mf`). Noch nicht gegen echtes Bambu Studio getestet.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import quoteattr

import numpy as np

from .glb import part_mesh

CT = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="text/xml"/>
</Types>"""
RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"""
IDENT = "1 0 0 0 1 0 0 0 1 0 0 0"
NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def _mesh_xml(m) -> str:
    v = "".join(f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in m.vertices)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in m.faces)
    return f"<mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh>"


def _meshes(parts):
    ms = [part_mesh(p.shape) for p in parts]
    allv = np.vstack([m.vertices for m in ms])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    shift = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    for m in ms:
        m.vertices = m.vertices - shift
    return ms


def write_bambu_3mf(parts, path: Path, name: str = "Einlage", bed=(128.0, 128.0)) -> Path:
    ms = _meshes(parts)
    n = len(parts)
    objs = "".join(f'<object id="{i + 1}" type="model">{_mesh_xml(m)}</object>' for i, m in enumerate(ms))
    comps = "".join(f'<component objectid="{i + 1}" transform="{IDENT}"/>' for i in range(n))
    pid = n + 1
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{NS}">'
        '<metadata name="Application">BambuStudio-02.00.00.00</metadata>'
        '<metadata name="BambuStudio:3mfVersion">1</metadata>'
        f"<resources>{objs}"
        f'<object id="{pid}" type="model"><components>{comps}</components></object></resources>'
        f'<build><item objectid="{pid}" transform="1 0 0 0 1 0 0 0 1 {bed[0]} {bed[1]} 0" printable="1"/></build>'
        "</model>"
    )
    parts_xml = ""
    for i, (p, m) in enumerate(zip(parts, ms)):
        parts_xml += (
            f'<part id="{i + 1}" subtype="normal_part">'
            f'<metadata key="name" value={quoteattr(p.name)}/>'
            '<metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>'
            f'<metadata key="extruder" value="{p.slot}"/>'
            f'<mesh_stat face_count="{len(m.faces)}" edges_fixed="0" degenerate_facets="0" '
            'facets_reversed="0" backwards_edges="0"/></part>'
        )
    cfg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<config>'
        f'<object id="{pid}"><metadata key="name" value={quoteattr(name)}/>'
        f'<metadata key="extruder" value="{parts[0].slot}"/>{parts_xml}</object>'
        '<plate><metadata key="plater_id" value="1"/><metadata key="plater_name" value=""/>'
        '<metadata key="locked" value="false"/>'
        f'<model_instance><metadata key="object_id" value="{pid}"/>'
        '<metadata key="instance_id" value="0"/><metadata key="identify_id" value="1"/></model_instance>'
        "</plate></config>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/model_settings.config", cfg)
    return path


def write_plain_3mf(parts, path: Path, name: str = "Einlage") -> Path:
    """Standard-3MF: je Teil ein Objekt, gleiche Koordinaten (Teile liegen deckungsgleich)."""
    ms = _meshes(parts)
    objs = "".join(
        f'<object id="{i + 1}" name={quoteattr(p.name)} type="model">{_mesh_xml(m)}</object>'
        for i, (p, m) in enumerate(zip(parts, ms))
    )
    items = "".join(f'<item objectid="{i + 1}" transform="1 0 0 0 1 0 0 0 1 128 128 0"/>'
                    for i in range(len(parts)))
    model = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xmlns="{NS}">'
             f"<resources>{objs}</resources><build>{items}</build></model>")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", model)
    return path


def write_objects_3mf(objs: list[tuple[str, object, tuple[float, float]]], path: Path) -> Path:
    """Standard-3MF mit getrennten Objekten (z. B. Baseplate-Kacheln): (Name, Workplane, Lage x/y).
    Jedes Objekt behält seine Koordinaten (Unterkante z = 0) und steht an seiner Lage; das Ganze wird
    auf die Druckplatte mittig gesetzt (Slicer ordnen ohnehin neu an, wenn es nicht passt)."""
    ms = [part_mesh(shape) for _, shape, _ in objs]
    lo = np.min([m.vertices.min(axis=0) + (x, y, 0) for m, (_, _, (x, y)) in zip(ms, objs)], axis=0)
    hi = np.max([m.vertices.max(axis=0) + (x, y, 0) for m, (_, _, (x, y)) in zip(ms, objs)], axis=0)
    cx, cy = 128 - (lo[0] + hi[0]) / 2, 128 - (lo[1] + hi[1]) / 2
    res = "".join(f'<object id="{i + 1}" name={quoteattr(n)} type="model">{_mesh_xml(m)}</object>'
                  for i, ((n, _, _), m) in enumerate(zip(objs, ms)))
    items = "".join(f'<item objectid="{i + 1}" transform="1 0 0 0 1 0 0 0 1 {x + cx:.4f} {y + cy:.4f} {-m.vertices[:, 2].min():.4f}"/>'
                    for i, ((_, _, (x, y)), m) in enumerate(zip(objs, ms)))
    model = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xmlns="{NS}">'
             f"<resources>{res}</resources><build>{items}</build></model>")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", model)
    return path
