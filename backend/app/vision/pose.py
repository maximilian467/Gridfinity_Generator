"""Kamerapose aus dem A4-Blatt und Parallaxenkorrektur (Plan B).

Papier-Frame: x rechts, y unten, z in die Tischplatte. Die Kamera hat daher z < 0;
Höhe über dem Papier = -z.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .a4 import PAPER_CORNERS_MM

DEFAULT_F35 = 26.0
SENSOR_DIAG_35 = 43.27


@dataclass
class CameraPose:
    C_mm: tuple[float, float, float]   # (x, y, Höhe über Papier)
    f_px: float
    f35_assumed: bool = False
    warnings: tuple[str, ...] = ()


def intrinsics(shape_hw, f35: float | None) -> tuple[np.ndarray, bool]:
    h, w = shape_hw[:2]
    assumed = f35 is None
    f35 = DEFAULT_F35 if assumed else f35
    f_px = f35 * float(np.hypot(w, h)) / SENSOR_DIAG_35
    K = np.array([[f_px, 0, w / 2], [0, f_px, h / 2], [0, 0, 1]], np.float64)
    return K, assumed


def estimate_pose(corners_px, shape_hw, f35: float | None) -> CameraPose:
    K, assumed = intrinsics(shape_hw, f35)
    obj = np.hstack([PAPER_CORNERS_MM, np.zeros((4, 1))]).astype(np.float64)
    img = np.asarray(corners_px, np.float64).reshape(4, 1, 2)
    ok, rvec, tvec = cv2.solvePnP(obj, img, K, None, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        raise ValueError("solvePnP fehlgeschlagen")
    R, _ = cv2.Rodrigues(rvec)
    C = (-R.T @ tvec).ravel()
    warns = []
    if assumed:
        warns.append("Brennweite unbekannt (EXIF fehlt): 26 mm angenommen")
    height = -C[2]
    if height < 0:
        warns.append("Kamera unter Papierebene berechnet: Ecken prüfen")
        height = abs(height)
    if height < 300:
        warns.append(f"Kamerahöhe nur {height:.0f} mm: höher halten / 2×-Zoom nutzen")
    return CameraPose((float(C[0]), float(C[1]), float(height)), K[0, 0], assumed, tuple(warns))


def correct_points(pts_mm: np.ndarray, pose: CameraPose, h: np.ndarray | float) -> np.ndarray:
    """Punkte (Papierebene), die von Höhe h stammen -> wahre XY-Position.
    X = C_xy + (1 - h / C_h) * (p - C_xy)"""
    pts = np.asarray(pts_mm, float)
    c = np.array(pose.C_mm[:2])
    h = np.asarray(h, float).reshape(-1, 1) if np.ndim(h) else float(h)
    return c + (1.0 - h / pose.C_mm[2]) * (pts - c)
