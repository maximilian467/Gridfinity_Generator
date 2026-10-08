"""Kantenverfeinerung im Randband (Plan C.5)."""
from __future__ import annotations

import cv2
import numpy as np

from .a4 import PX_PER_MM

BAND_MM = 1.5


def refine_mask(rect_bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if mask.max() == 0:
        return mask
    L = cv2.cvtColor(cv2.GaussianBlur(rect_bgr, (0, 0), 1.2), cv2.COLOR_BGR2Lab)[:, :, 0].astype(np.float32)
    r = int(BAND_MM * PX_PER_MM)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    m = (mask > 0).astype(np.uint8)
    outer = cv2.dilate(m, k)
    inner = cv2.erode(m, k)
    band = (outer > 0) & (inner == 0)
    ring = (cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (4 * r + 1, 4 * r + 1))) > 0) & (outer == 0)
    if ring.sum() < 100 or inner.sum() < 100:
        return mask
    paper = float(np.median(L[ring]))
    obj = float(np.median(L[inner > 0]))
    thr = (paper + obj) / 2
    new = inner.copy()
    cls = (L < thr) if obj < paper else (L > thr)
    new[band & cls] = 1
    c = np.ones((3, 3), np.uint8)
    new = cv2.morphologyEx(new, cv2.MORPH_OPEN, c)
    new = cv2.morphologyEx(new, cv2.MORPH_CLOSE, c)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(new, connectivity=8)
    if n <= 1:
        return mask
    core = lab[inner > 0]
    core = core[core > 0]
    if core.size == 0:
        return mask
    keep = np.bincount(core).argmax()
    return (lab == keep).astype(np.uint8) * 255
