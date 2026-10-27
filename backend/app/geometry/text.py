"""Schriftzüge als Fläche (shapely): Umriss aus der Schrift DejaVu Sans, die matplotlib mitbringt
(überall dieselbe Schrift, auch im Container ohne Systemschriften). Dieselbe Fläche dient der
2D-Vorschau und dem CAD (Prisma), so passt die Vorschau genau zum Druck."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from ..schemas import TextLabel

REF = 100.0          # Schriftgröße beim Erzeugen des Umrisses (fein genug für die Kurven)


@lru_cache(maxsize=2)
def _font(bold: bool):
    import matplotlib
    from matplotlib.font_manager import FontProperties

    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return FontProperties(fname=str(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name))


@lru_cache(maxsize=256)
def _outline(text: str, bold: bool) -> BaseGeometry:
    """Umriss mit Versalhöhe 1, Mitte der Zeile (Breite, Versalhöhe) im Ursprung."""
    from matplotlib.textpath import TextPath

    fp = _font(bold)
    cap = TextPath((0, 0), "H", size=REF, prop=fp).get_extents().y1
    g: BaseGeometry | None = None
    for ring in TextPath((0, 0), text, size=REF, prop=fp).to_polygons():
        if len(ring) < 3:
            continue
        q = Polygon(ring).buffer(0)
        # Löcher (o, A, e ...) sind eigene Ringe: gerade/ungerade-Regel wie beim Schriftsatz
        g = q if g is None else g.symmetric_difference(q)
    if g is None or g.is_empty:
        return Polygon()
    x0, _, x1, _ = g.bounds
    g = affinity.translate(g, -(x0 + x1) / 2, -cap / 2)
    return affinity.scale(g, 1 / cap, 1 / cap, origin=(0, 0)).simplify(0.002)


def text_polygon(t: TextLabel) -> BaseGeometry:
    """Schriftzug im Einlagen-Koordinatensystem (Spec-Koordinaten, vor der Zentrierung)."""
    g = _outline(t.text.strip(), t.bold)
    if g.is_empty:
        return g
    g = affinity.scale(g, t.size, t.size, origin=(0, 0))
    g = affinity.rotate(g, t.rot_deg, origin=(0, 0))
    return affinity.translate(g, t.x, t.y)
