"""Segmentierung auf dem entzerrten Bild (Plan C).

Primär klassisch (Otsu auf Lab-L innerhalb des Blattes, Klicks wählen/entfernen Regionen).
Optional SAM 2.1 (ultralytics) falls Gewichte unter data/models/ liegen.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..config import ROOT
from .a4 import A4_H, A4_W, MARGIN_MM, PX_PER_MM, RECT_H, RECT_W
from .refine import refine_mask

SAM_WEIGHTS = ROOT / "data" / "models" / "sam2.1_b.pt"
NEG_RADIUS_MM = 5.0


def paper_rect_px(inset_mm: float = 1.0) -> tuple[int, int, int, int]:
    x0 = int((MARGIN_MM + inset_mm) * PX_PER_MM)
    y0 = int((MARGIN_MM + inset_mm) * PX_PER_MM)
    x1 = int((MARGIN_MM + A4_W - inset_mm) * PX_PER_MM)
    y1 = int((MARGIN_MM + A4_H - inset_mm) * PX_PER_MM)
    return x0, y0, x1, y1


def _lightness(rect_bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(cv2.GaussianBlur(rect_bgr, (0, 0), 2.0), cv2.COLOR_BGR2Lab)[:, :, 0]


def classical_mask(rect_bgr: np.ndarray, pos=(), neg=()) -> np.ndarray:
    """pos/neg: Punkte in entzerrten Pixeln (x, y). Rückgabe uint8 0/255."""
    L = _lightness(rect_bgr)
    x0, y0, x1, y1 = paper_rect_px()
    roi = L[y0:y1, x0:x1]
    thr, _ = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    obj = np.zeros(L.shape, np.uint8)
    obj[y0:y1, x0:x1] = (roi < thr).astype(np.uint8) * 255
    obj = cv2.morphologyEx(obj, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    for (x, y) in neg:
        cv2.circle(obj, (int(x), int(y)), int(NEG_RADIUS_MM * PX_PER_MM), 0, -1)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(obj, connectivity=8)
    if n <= 1:
        return np.zeros(L.shape, np.uint8)
    keep = set()
    for (x, y) in pos:
        xi, yi = int(x), int(y)
        if 0 <= yi < lab.shape[0] and 0 <= xi < lab.shape[1] and lab[yi, xi] > 0:
            keep.add(int(lab[yi, xi]))
    if not keep:
        keep = {1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))}
    return np.isin(lab, list(keep)).astype(np.uint8) * 255


def sam_available() -> bool:
    return SAM_WEIGHTS.exists()


_sam_model = None


def _get_sam():
    global _sam_model
    if _sam_model is None:
        from ultralytics import SAM

        _sam_model = SAM(str(SAM_WEIGHTS))
    return _sam_model


def sam_mask(rect_bgr: np.ndarray, pos, neg, box=None) -> np.ndarray:
    model = _get_sam()
    pts = [list(map(float, p)) for p in list(pos) + list(neg)]
    lbl = [1] * len(pos) + [0] * len(neg)
    kw = {"points": pts, "labels": lbl} if pts else {}
    if box is not None:
        kw["bboxes"] = list(map(float, box))
    res = model(rect_bgr, **kw, verbose=False)[0]
    m = res.masks.data[0].cpu().numpy()
    m = cv2.resize(m.astype(np.uint8), (RECT_W, RECT_H), interpolation=cv2.INTER_NEAREST)
    return m * 255


def segment(rect_bgr: np.ndarray, pos=(), neg=(), use_sam: bool = True) -> np.ndarray:
    base = classical_mask(rect_bgr, pos, neg)
    if use_sam and sam_available() and (pos or neg):
        try:
            seed = sam_mask(rect_bgr, pos, neg)
            return refine_mask(rect_bgr, seed)
        except Exception:
            pass
    return refine_mask(rect_bgr, base)
