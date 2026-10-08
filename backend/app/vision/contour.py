"""Maske -> Kontur in Papier-mm, PCA-Ausrichtung (Plan D)."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from shapely.geometry import Polygon
from shapely.validation import make_valid

from .a4 import rect_px_to_mm


def mask_to_polygon(mask: np.ndarray, fill_holes: bool = True, simplify_mm: float = 0.1) -> Polygon:
    """Größte Außenkontur der Maske als Polygon in Papier-mm (x rechts, y unten)."""
    mode = cv2.RETR_EXTERNAL if fill_holes else cv2.RETR_CCOMP
    cnts, hier = cv2.findContours((mask > 0).astype(np.uint8), mode, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        raise ValueError("Maske leer")
    i = int(np.argmax([cv2.contourArea(c) for c in cnts]))
    outer = rect_px_to_mm(cnts[i].reshape(-1, 2).astype(float) + 0.5)
    holes = []
    if not fill_holes and hier is not None:
        for j, c in enumerate(cnts):
            if hier[0][j][3] == i and len(c) >= 4:
                holes.append(rect_px_to_mm(c.reshape(-1, 2).astype(float) + 0.5))
    poly = make_valid(Polygon(outer, holes))
    if poly.geom_type != "Polygon":
        poly = max((g for g in getattr(poly, "geoms", []) if g.geom_type == "Polygon"), key=lambda g: g.area)
    return poly.simplify(simplify_mm)


@dataclass
class Frame:
    """Papier-mm (y unten) -> objekt-lokal (x = Länge ab linkem Ende, y quer nach oben)."""
    cx: float
    cy: float
    theta: float          # Winkel der Längsachse in Papierkoordinaten
    x0: float = 0.0
    y0: float = 0.0

    def to_local(self, pts) -> np.ndarray:
        p = np.asarray(pts, float) - [self.cx, self.cy]
        c, s = np.cos(-self.theta), np.sin(-self.theta)
        x = p[:, 0] * c - p[:, 1] * s
        y = p[:, 0] * s + p[:, 1] * c
        return np.column_stack([x - self.x0, -y - self.y0])    # y_cad = -y_img

    def to_paper(self, pts) -> np.ndarray:
        q = np.asarray(pts, float)
        x = q[:, 0] + self.x0
        y = -(q[:, 1] + self.y0)
        c, s = np.cos(self.theta), np.sin(self.theta)
        return np.column_stack([x * c - y * s + self.cx, x * s + y * c + self.cy])


def pca_frame(poly: Polygon) -> Frame:
    pts = np.asarray(poly.exterior.coords)[:-1]
    # Flächenschwerpunkt als Zentrum, Hauptachse aus Kovarianz der Fläche (dicht gesampelt)
    cen = np.array(poly.centroid.coords[0])
    xmin, ymin, xmax, ymax = poly.bounds
    gx, gy = np.meshgrid(np.arange(xmin, xmax, 0.5), np.arange(ymin, ymax, 0.5))
    from shapely import contains_xy
    inside = contains_xy(poly, gx.ravel(), gy.ravel())
    sample = np.column_stack([gx.ravel()[inside], gy.ravel()[inside]]) - cen
    w, v = np.linalg.eigh(np.cov(sample.T))
    ax = v[:, int(np.argmax(w))]
    if ax[0] < -1e-9 or (abs(ax[0]) <= 1e-9 and ax[1] < 0):
        ax = -ax
    fr = Frame(cen[0], cen[1], float(np.arctan2(ax[1], ax[0])))
    loc = fr.to_local(pts)
    fr.x0 = float(loc[:, 0].min())
    fr.y0 = float((loc[:, 1].min() + loc[:, 1].max()) / 2)
    return fr


def polygon_local(poly: Polygon, frame: Frame) -> Polygon:
    pts = frame.to_local(np.asarray(poly.exterior.coords)[:-1])
    return make_valid(Polygon(pts)).buffer(0)
