"""Hand-/Fingerentfernung im Seitenfoto.

Idee: In der Draufsicht liegt das Werkzeug ohne Hand auf dem Blatt. Daraus wird ein
Farbmodell (Lab-Histogramm) des Werkzeugs gelernt. Im Seitenfoto bleiben nur Maskenpixel,
deren Farbe im Werkzeugmodell deutlich häufiger vorkommt als im Seitenfoto insgesamt
(Bayes-Verhältnis). Keine feste Hautfarben-Regel: rote/gelbe Griffe bleiben erhalten,
solange sie in der Draufsicht vorkommen.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter

from .a4 import PX_PER_MM

BINS = 16
RATIO_MIN = 0.3


@dataclass
class HandResult:
    mask: np.ndarray        # bereinigte Werkzeugmaske (uint8 0/255)
    hand: np.ndarray        # entfernte Pixel (uint8 0/255)
    removed_frac: float     # Anteil entfernter Maskenfläche
    applied: bool


def _lab(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(cv2.GaussianBlur(img, (0, 0), 2.0), cv2.COLOR_BGR2Lab)


def _hist(lab: np.ndarray, m: np.ndarray) -> np.ndarray:
    h = cv2.calcHist([lab], [0, 1, 2], (m > 0).astype(np.uint8) * 255, [BINS] * 3, [0, 256] * 3)
    h = gaussian_filter(h, 0.7)
    return h / max(h.sum(), 1e-9)


def _disk(mm: float) -> np.ndarray:
    r = max(1, int(round(mm * PX_PER_MM)))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def _prune_thin(m: np.ndarray) -> np.ndarray:
    """Dünne Anhängsel (Schattensäume an Fingern) entfernen: Öffnung mit einem Radius relativ
    zur typischen Werkzeugdicke, danach Rekonstruktion der Ränder nahe dem Kern."""
    dt = cv2.distanceTransform(m, cv2.DIST_L2, 5)
    ridge = dt[(dt > 0) & (dt >= cv2.dilate(dt, np.ones((5, 5), np.uint8)) - 1e-3)]
    if ridge.size < 20:
        return m
    half = float(np.median(ridge))                     # halbe typische Dicke (px)
    r = int(max(2, 0.55 * half))
    core = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(core, connectivity=8)
    if n <= 1:
        return m
    core = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    g = r + int(PX_PER_MM)
    near = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1)))
    return (m & near).astype(np.uint8)


def remove_hand(side_rect: np.ndarray, side_mask: np.ndarray, top_rect: np.ndarray,
                top_mask: np.ndarray) -> HandResult:
    ms = side_mask > 0
    if ms.sum() < 100 or (top_mask > 0).sum() < 100:
        return HandResult(side_mask, np.zeros_like(side_mask), 0.0, False)
    core_top = cv2.erode(top_mask, _disk(1.0)) > 0          # Werkzeugpixel ohne Randsaum
    lab_s = _lab(side_rect)
    ht = _hist(_lab(top_rect), core_top)
    hs = _hist(lab_s, ms)
    idx = (lab_s // (256 // BINS)).astype(np.intp)
    pt = ht[idx[..., 0], idx[..., 1], idx[..., 2]]
    ps = hs[idx[..., 0], idx[..., 1], idx[..., 2]]
    tool = (ms & (pt / (ps + 1e-12) > RATIO_MIN)).astype(np.uint8)

    # Ränder der Hand (dunkle Schattensäume) entfernen, größte Komponente behalten, Löcher schließen
    tool = cv2.morphologyEx(tool, cv2.MORPH_OPEN, _disk(1.2))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(tool, connectivity=8)
    if n <= 1:
        return HandResult(side_mask, np.zeros_like(side_mask), 0.0, False)
    keep = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    tool = (lab == keep).astype(np.uint8)
    tool = cv2.morphologyEx(tool, cv2.MORPH_CLOSE, _disk(1.5))
    tool &= ms.astype(np.uint8)
    tool = _prune_thin(tool)

    removed = ms & (tool == 0)
    frac = float(removed.sum()) / float(ms.sum())
    if frac < 0.03:                                          # nichts Nennenswertes entfernt
        return HandResult(side_mask, np.zeros_like(side_mask), 0.0, False)
    return HandResult(tool * 255, removed.astype(np.uint8) * 255, frac, True)
