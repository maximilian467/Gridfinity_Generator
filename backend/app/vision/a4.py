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


def find_a4_corners(bgr: np.ndarray, work_max: int = 1600) -> np.ndarray | None:
    """Findet die vier Ecken des Blattes (Originalpixel, subpixel-verfeinert)."""
    h, w = bgr.shape[:2]
    k = min(1.0, work_max / max(h, w))
    small = cv2.resize(bgr, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else bgr
    lab = cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_BGR2Lab)
    L = lab[:, :, 0]
    chroma = np.hypot(lab[:, :, 1].astype(np.float32) - 128, lab[:, :, 2].astype(np.float32) - 128)
    thr, _ = cv2.threshold(L, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = ((L > thr) & (chroma < 25)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    cnt = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(cnt) < 0.05 * small.shape[0] * small.shape[1]:
        return None
    hull = cv2.convexHull(cnt)
    quad = None
    per = cv2.arcLength(hull, True)
    for eps in np.linspace(0.005, 0.08, 40):
        ap = cv2.approxPolyDP(hull, eps * per, True)
        if len(ap) == 4:
            quad = ap.reshape(4, 2).astype(np.float32)
            break
    if quad is None:
        quad = cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float32)
    corners = order_corners(quad / k)
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
    return out if np.max(np.linalg.norm(out - corners, axis=1)) < 20 else corners


def homography(corners: np.ndarray) -> np.ndarray:
    """Original-Pixel -> entzerrte Pixel."""
    dst = mm_to_rect_px(PAPER_CORNERS_MM).astype(np.float32)
    return cv2.getPerspectiveTransform(np.asarray(corners, np.float32), dst)


def rectify(bgr: np.ndarray, corners: np.ndarray) -> np.ndarray:
    return cv2.warpPerspective(bgr, homography(corners), (RECT_W, RECT_H), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)
