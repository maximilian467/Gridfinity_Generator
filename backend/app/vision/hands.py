"""Hand-/Fingerentfernung im Seitenfoto.

Primär (``find_hand_sam``): Die Hand kommt immer von außen über den Blattrand. Wo das Blatt in einem
Band knapp innerhalb des Randes verdeckt ist, liegen automatisch Klickpunkte für SAM; SAM schneidet
damit die ganze Hand aus, unabhängig von den Farben des Werkzeugs.

Rückfallebene (``remove_hand``, ohne SAM): In der Draufsicht liegt das Werkzeug ohne Hand auf dem Blatt. Daraus wird ein
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


def _paper(rect: np.ndarray) -> np.ndarray:
    """Papierpixel: hell relativ zum Blatt und farblos (leichte Schatten zählen noch als Papier)."""
    from .segment import paper_rect_px
    lab = cv2.cvtColor(cv2.GaussianBlur(rect, (0, 0), 2), cv2.COLOR_BGR2Lab)
    L = lab[..., 0].astype(np.float32)
    chroma = np.hypot(lab[..., 1].astype(np.float32) - 128, lab[..., 2].astype(np.float32) - 128)
    x0, y0, x1, y1 = paper_rect_px(0)
    paper_L = float(np.median(L[y0:y1, x0:x1]))
    return (L > paper_L * 0.62) & (chroma < 18)


def hand_seed_points(rect: np.ndarray, max_points: int = 6) -> list[list[float]]:
    """Punkte sicher in der Hand: Nicht-Papier im Band 3..8 mm innerhalb des Blattrands, von dort
    bis ~25 mm ins Blatt verfolgt; Punkte mit größtem Abstand zum Flächenrand."""
    from .segment import paper_rect_px
    paper = _paper(rect)
    x0, y0, x1, y1 = paper_rect_px(0)
    o, i = int(3 * PX_PER_MM), int(8 * PX_PER_MM)
    band = np.zeros(paper.shape, bool)
    band[y0 + o:y1 - o, x0 + o:x1 - o] = True
    band[y0 + i:y1 - i, x0 + i:x1 - i] = False
    n, lab, st, _ = cv2.connectedComponentsWithStats((band & ~paper).astype(np.uint8))
    if n <= 1:
        return []
    ci = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    if st[ci, cv2.CC_STAT_AREA] < 30 * PX_PER_MM * PX_PER_MM:      # < 30 mm²: Lochung, Krümel
        return []
    nonpaper = (~paper).astype(np.uint8)
    inside = np.zeros(paper.shape, np.uint8)
    inside[y0:y1, x0:x1] = 1
    reach = (lab == ci).astype(np.uint8)
    kern = np.ones((21, 21), np.uint8)
    for _ in range(12):
        reach = cv2.dilate(reach, kern) & nonpaper & inside
    dist = cv2.distanceTransform(reach, cv2.DIST_L2, 5)
    ys, xs = np.nonzero(dist > 4 * PX_PER_MM)
    if len(xs) == 0:
        ys, xs = np.nonzero(lab == ci)
    order = np.argsort(-dist[ys, xs])
    sel = order[:: max(1, len(order) // max_points)][:max_points]
    return [[float(xs[j]), float(ys[j])] for j in sel]


def find_hand_sam(rect: np.ndarray, mask: np.ndarray) -> HandResult | None:
    """Hand per SAM entfernen. None, wenn keine Hand am Rand gefunden wird oder SAM fehlt."""
    from .segment import sam_available, sam_mask
    ms = mask > 0
    if not sam_available() or ms.sum() < 100:
        return None
    pts = hand_seed_points(rect)
    if not pts:
        return None
    hand = sam_mask(rect, pts, []) > 0
    if hand.sum() < 100:
        return None
    hand = cv2.dilate(hand.astype(np.uint8), _disk(1.0)) > 0       # Fingersaum mitnehmen
    tool = (ms & ~hand).astype(np.uint8)
    tool = cv2.morphologyEx(tool, cv2.MORPH_OPEN, _disk(1.0))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(tool, connectivity=8)
    if n <= 1:
        return None
    tool = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    tool = _prune_thin(tool)
    removed = ms & (tool == 0)
    frac = float(removed.sum()) / float(ms.sum())
    if frac > 0.9:            # SAM hat das Werkzeug erwischt -> nicht vertrauen
        return None
    if frac < 0.02:
        return HandResult(mask, np.zeros_like(mask), 0.0, False)
    return HandResult(tool * 255, removed.astype(np.uint8) * 255, frac, True)


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
