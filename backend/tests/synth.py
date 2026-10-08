"""Synthetische Fotos: A4 + extrudierter Körper, echte Lochkamera-Projektion."""
from __future__ import annotations

import cv2
import numpy as np

from app.vision.a4 import A4_H, A4_W

IMG_W, IMG_H = 4000, 3000


def camera(f35=26.0, height=420.0, tilt_deg=(2.0, -3.0), offset=(10.0, -8.0)):
    diag = float(np.hypot(IMG_W, IMG_H))
    f = f35 * diag / 43.27
    K = np.array([[f, 0, IMG_W / 2], [0, f, IMG_H / 2], [0, 0, 1.0]])
    rvec, _ = cv2.Rodrigues(cv2.Rodrigues(np.array([np.radians(tilt_deg[0]), 0, 0]))[0]
                            @ cv2.Rodrigues(np.array([0, np.radians(tilt_deg[1]), 0]))[0])
    R = cv2.Rodrigues(rvec)[0]
    p0 = np.array([A4_W / 2 + offset[0], A4_H / 2 + offset[1], 0.0])
    C = p0 - R.T @ np.array([0, 0, height])      # Kamera bei z = -height (oben)
    t = -R @ C
    return K, rvec, t, C


def project(K, rvec, t, pts3):
    out, _ = cv2.projectPoints(np.asarray(pts3, np.float64).reshape(-1, 1, 3), rvec, t, K, None)
    return out.reshape(-1, 2)


def render(poly_xy, height, cam, seed=0, noise=3.0, bg=70, tool=35):
    """poly_xy: Grundfläche in Papier-mm (Auflage auf z=0), height: Extrusionshöhe (nach oben)."""
    K, rvec, t, _ = cam
    rng = np.random.default_rng(seed)
    img = np.full((IMG_H, IMG_W, 3), bg, np.uint8)
    paper = project(K, rvec, t, [[0, 0, 0], [A4_W, 0, 0], [A4_W, A4_H, 0], [0, A4_H, 0]])
    cv2.fillConvexPoly(img, np.round(paper).astype(np.int32), (235, 238, 240), cv2.LINE_AA)
    base = np.hstack([poly_xy, np.zeros((len(poly_xy), 1))])
    top = np.hstack([poly_xy, -np.full((len(poly_xy), 1), float(height))])
    pb, pt = project(K, rvec, t, base), project(K, rvec, t, top)
    col = (tool, tool, tool + 5)
    n = len(poly_xy)
    for i in range(n):
        j = (i + 1) % n
        quad = np.round([pb[i], pb[j], pt[j], pt[i]]).astype(np.int32)
        cv2.fillPoly(img, [quad], col, cv2.LINE_AA)
    cv2.fillPoly(img, [np.round(pb).astype(np.int32)], col, cv2.LINE_AA)
    cv2.fillPoly(img, [np.round(pt).astype(np.int32)], col, cv2.LINE_AA)
    # weicher Schatten-Gradient + Rauschen + Unschärfe
    gx = np.linspace(0.9, 1.05, IMG_W)[None, :, None]
    img = np.clip(img.astype(np.float32) * gx, 0, 255)
    img = cv2.GaussianBlur(img, (0, 0), 1.2)
    img += rng.normal(0, noise, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def rot_rect(cx, cy, l, w, deg):
    a = np.radians(deg)
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    pts = np.array([[-l / 2, -w / 2], [l / 2, -w / 2], [l / 2, w / 2], [-l / 2, w / 2]])
    return pts @ R.T + [cx, cy]
