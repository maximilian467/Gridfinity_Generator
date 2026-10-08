"""A4-Erkennung, Homographie, Entzerrung (Plan A).

Papier-Koordinaten: Ursprung links oben, x rechts (297 mm), y unten (210 mm).
Entzerrtes Bild: 10 px/mm plus 40 mm Rand -> 3770 x 2900 px.
"""
from __future__ import annotations

import cv2
import numpy as np

A4_W, A4_H = 297.0, 210.0
PX_PER_MM = 10.0
MARGIN_MM = 40.0
RECT_W = int(round((A4_W + 2 * MARGIN_MM) * PX_PER_MM))   # 3770
RECT_H = int(round((A4_H + 2 * MARGIN_MM) * PX_PER_MM))   # 2900

PAPER_CORNERS_MM = np.array([[0, 0], [A4_W, 0], [A4_W, A4_H], [0, A4_H]], np.float32)


def rect_px_to_mm(pts) -> np.ndarray:
    return np.asarray(pts, float) / PX_PER_MM - MARGIN_MM


def mm_to_rect_px(pts) -> np.ndarray:
    return (np.asarray(pts, float) + MARGIN_MM) * PX_PER_MM


def order_corners(pts: np.ndarray) -> np.ndarray:
    """TL, TR, BR, BL (im Uhrzeigersinn auf dem Bildschirm), längere Seite = x."""
    pts = np.asarray(pts, np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]              # aufsteigend = im Uhrzeigersinn (y nach unten)
    start = int(np.argmin(pts.sum(axis=1)))
    pts = np.roll(pts, -start, axis=0)
    if np.linalg.norm(pts[1] - pts[0]) < np.linalg.norm(pts[3] - pts[0]):
        pts = np.roll(pts, -1, axis=0)       # lange Seite nach x
    return pts


def _paper_mask(small: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_BGR2Lab)
    L = lab[:, :, 0]
    chroma = np.hypot(lab[:, :, 1].astype(np.float32) - 128, lab[:, :, 2].astype(np.float32) - 128)
    thr, _ = cv2.threshold(L, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return ((L > thr) & (chroma < 25)).astype(np.uint8) * 255


def _ransac_lines(pts: np.ndarray, n_lines: int = 8, tol: float = 1.5, rng=None) -> list[np.ndarray]:
    """Dominante Geraden (a, b, c mit a²+b²=1) aus Konturpunkten."""
    rng = rng or np.random.default_rng(0)
    lines = []
    rest = pts.copy()
    for _ in range(n_lines):
        if len(rest) < 30:
            break
        i = rng.integers(0, len(rest), (400, 2))
        p, q = rest[i[:, 0]], rest[i[:, 1]]
        d = q - p
        nrm = np.hypot(d[:, 0], d[:, 1])
        ok = nrm > 10
        if not ok.any():
            break
        p, d, nrm = p[ok], d[ok], nrm[ok]
        nvec = np.column_stack([-d[:, 1], d[:, 0]]) / nrm[:, None]
        c = -(nvec * p).sum(axis=1)
        dist = np.abs(rest @ nvec.T + c)                      # (N, K)
        cnt = (dist < tol).sum(axis=0)
        k = int(np.argmax(cnt))
        if cnt[k] < 40:
            break
        inl = rest[dist[:, k] < tol]
        vx, vy, x0, y0 = cv2.fitLine(inl.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        a_, b_ = -vy, vx
        lines.append(np.array([a_, b_, -(a_ * x0 + b_ * y0)]))
        rest = rest[np.abs(rest @ np.array([a_, b_]) + lines[-1][2]) > 4 * tol]
    return lines


def _intersect(l1: np.ndarray, l2: np.ndarray) -> np.ndarray | None:
    A = np.array([l1[:2], l2[:2]])
    if abs(np.linalg.det(A)) < 1e-6:
        return None
    return np.linalg.solve(A, -np.array([l1[2], l2[2]]))


def _quad_iou(quad: np.ndarray, filled: np.ndarray) -> float:
    q = np.zeros_like(filled)
    cv2.fillConvexPoly(q, np.round(quad).astype(np.int32), 255)
    inter = np.count_nonzero(q & filled)
    union = np.count_nonzero(q | filled)
    return inter / union if union else 0.0


def find_a4_corners(bgr: np.ndarray, work_max: int = 1200) -> np.ndarray | None:
    """Findet die vier Ecken des Blattes (Originalpixel, subpixel-verfeinert).

    Robust gegen angrenzende helle Gegenstände und verdeckte Ecken: dominante Geraden der
    Papierkontur (RANSAC); unter allen Vierecken aus zwei Geradenpaaren gewinnt das mit der
    besten Übereinstimmung (IoU) mit der Papierfläche."""
    h, w = bgr.shape[:2]
    k = min(1.0, work_max / max(h, w))
    small = cv2.resize(bgr, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else bgr
    mask = _paper_mask(small)
    # dünne Brücken zu Nachbarobjekten kappen
    ks = max(5, int(0.02 * min(small.shape[:2])) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (ks, ks)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return None
    big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[big, cv2.CC_STAT_AREA] < 0.05 * small.shape[0] * small.shape[1]:
        return None
    comp = (lab == big).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cnt = max(cnts, key=cv2.contourArea)
    filled = np.zeros_like(comp)
    cv2.drawContours(filled, [cnt], -1, 255, -1)

    candidates: list[np.ndarray] = []
    # Kandidat 1: konvexe Hülle -> 4 Punkte (alter Weg)
    hull = cv2.convexHull(cnt)
    per = cv2.arcLength(hull, True)
    for eps in np.linspace(0.005, 0.08, 40):
        ap = cv2.approxPolyDP(hull, eps * per, True)
        if len(ap) == 4:
            candidates.append(ap.reshape(4, 2).astype(np.float64))
            break
    # Kandidaten 2: aus RANSAC-Geraden
    pts = cnt.reshape(-1, 2).astype(np.float64)
    if len(pts) > 3000:
        pts = pts[:: len(pts) // 3000 + 1]
    lines = _ransac_lines(pts)
    ang = [np.arctan2(l[1], l[0]) % np.pi for l in lines]
    from itertools import combinations
    for combo in combinations(range(len(lines)), 4):
        for pa, pb in (((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))):
            A = [combo[pa[0]], combo[pa[1]]]
            B = [combo[pb[0]], combo[pb[1]]]
            def adiff(i, j):
                d = abs(ang[i] - ang[j])
                return min(d, np.pi - d)
            if adiff(*A) > 0.5 or adiff(*B) > 0.5 or adiff(A[0], B[0]) < 0.6:
                continue
            P = [_intersect(lines[a_], lines[b_]) for a_ in A for b_ in B]
            if any(p is None for p in P):
                continue
            P = np.array(P)
            c = P.mean(axis=0)
            P = P[np.argsort(np.arctan2(P[:, 1] - c[1], P[:, 0] - c[0]))]
            if not cv2.isContourConvex(P.astype(np.float32).reshape(-1, 1, 2)):
                continue
            candidates.append(P)
    if not candidates:
        return None
    best = max(candidates, key=lambda q: _quad_iou(q, filled))
    corners = order_corners((best / k).astype(np.float32))
    return refine_corners(bgr, corners)


def refine_corners(bgr: np.ndarray, corners: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    c = corners.reshape(-1, 1, 2).astype(np.float32).copy()
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.01)
    try:
        cv2.cornerSubPix(gray, c, (15, 15), (-1, -1), crit)
    except cv2.error:
        return corners
    out = c.reshape(4, 2)
    # Subpixel nur übernehmen, wenn die Ecke sichtbar ist (kleine Verschiebung)
    moved = np.linalg.norm(out - corners, axis=1)
    return np.where((moved < 4)[:, None], out, corners).astype(np.float32)


def homography(corners: np.ndarray) -> np.ndarray:
    """Original-Pixel -> entzerrte Pixel."""
    dst = mm_to_rect_px(PAPER_CORNERS_MM).astype(np.float32)
    return cv2.getPerspectiveTransform(np.asarray(corners, np.float32), dst)


def rectify(bgr: np.ndarray, corners: np.ndarray) -> np.ndarray:
    return cv2.warpPerspective(bgr, homography(corners), (RECT_W, RECT_H), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)
