"""Farbbild der Draufsicht in Werkzeug-Koordinaten (für die 3D-Ansicht der Schublade).

Die Werkzeugkontur (objekt-lokal) wird aus der Maske der Draufsicht neu ausgerichtet (PCA wie beim
Scan, dazu die Spiegelung, die am besten zur gespeicherten Kontur passt) und das entzerrte Foto in
dieses Raster umgerechnet. Ausgabe: PNG mit Alpha (außerhalb der Kontur durchsichtig), 4 px/mm.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from shapely import affinity
from shapely.geometry import Polygon

from .a4 import MARGIN_MM
from .contour import mask_to_polygon, pca_frame, polygon_local

PX_MM = 4.0


def make_texture(rect_view: np.ndarray, view_scale: float, mask: np.ndarray, contour_local, out: Path) -> dict:
    target = Polygon(contour_local).buffer(0)
    poly = mask_to_polygon(mask)
    fr = pca_frame(poly)
    loc = polygon_local(poly, fr)
    L = target.bounds[2]
    best = None
    for fx in (False, True):
        for fy in (False, True):
            q = affinity.scale(loc, -1 if fx else 1, -1 if fy else 1, origin=(0, 0))
            q = affinity.translate(q, -q.bounds[0], -(q.bounds[1] + q.bounds[3]) / 2 + (target.bounds[1] + target.bounds[3]) / 2)
            iou = q.intersection(target).area / max(q.union(target).area, 1e-9)
            if best is None or iou > best[0]:
                best = (iou, fx, fy, q.bounds[2])
    _, fx, fy, Lq = best
    x0, y0, x1, y1 = target.bounds
    W, H = int(np.ceil((x1 - x0) * PX_MM)) + 1, int(np.ceil((y1 - y0) * PX_MM)) + 1
    u, v = np.meshgrid(np.arange(W) / PX_MM + x0, y1 - np.arange(H) / PX_MM)       # Bild-oben = +y
    xs = u * (Lq / max(L, 1e-9))                       # kleine Längendifferenz (Parallaxe) ausgleichen
    ys = v - (target.bounds[1] + target.bounds[3]) / 2
    # zurück in die (gespiegelte) PCA-Lage, dann in Papier-mm
    lx = (Lq - xs) if fx else xs
    ly = -ys if fy else ys
    pts = fr.to_paper(np.column_stack([lx.ravel(), ly.ravel()]))
    mapx = ((pts[:, 0] + MARGIN_MM) * 10 * view_scale).reshape(H, W).astype(np.float32)
    mapy = ((pts[:, 1] + MARGIN_MM) * 10 * view_scale).reshape(H, W).astype(np.float32)
    img = cv2.remap(rect_view, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    alpha = np.zeros((H, W), np.uint8)
    ring = np.asarray(target.exterior.coords)
    cv2.fillPoly(alpha, [np.round(np.column_stack([(ring[:, 0] - x0) * PX_MM, (y1 - ring[:, 1]) * PX_MM])).astype(np.int32)], 255)
    cv2.imwrite(str(out), np.dstack([img, alpha]))
    inside = img[alpha > 0]
    b, g, r = (np.median(inside, axis=0) if len(inside) else (180, 180, 180))
    return {"color": f"#{int(r):02x}{int(g):02x}{int(b):02x}","x0": x0, "x1": x0 + (W - 1) / PX_MM, "y0": y1 - (H - 1) / PX_MM, "y1": y1, "iou": round(best[0], 3)}
