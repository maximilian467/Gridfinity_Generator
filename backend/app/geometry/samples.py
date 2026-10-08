"""Synthetische Testobjekte (Zange, L-Form)."""
from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon

from ..schemas import ObjectSpec, Profile

# (Länge, Breite, Unterseite, Dicke) je Abschnitt: Spitze, Backen, Fingerschutz, Griffansatz, Griffe
PLIERS_SECTIONS = [(11, 6, 3.0, 5), (13, 14, 1.5, 8), (28, 40, 0.0, 14), (23, 40, 2.0, 18), (85, 50, 4.5, 22)]


def synthetic_pliers(oid: str = "pliers") -> ObjectSpec:
    ds = 0.5
    L = float(sum(sec[0] for sec in PLIERS_SECTIONS))
    s = np.arange(0, L + ds / 2, ds)
    width = np.zeros_like(s)
    bottom = np.zeros_like(s)
    top = np.zeros_like(s)
    x0 = 0.0
    for ln, w, bt, th in PLIERS_SECTIONS:
        m = (s >= x0) & (s <= x0 + ln + 1e-9)
        width[m], bottom[m], top[m] = w, bt, bt + th
        x0 += ln
    bottom -= bottom.min()
    top -= 0  # Dicke relativ bleibt; Ruhelage min(bottom)=0 gilt bereits
    upper = [(float(a), float(w) / 2) for a, w in zip(s, width)]
    lower = [(float(a), -float(w) / 2) for a, w in zip(s[::-1], width[::-1])]
    contour = Polygon(upper + lower).buffer(0)
    pts = [list(map(float, p)) for p in contour.exterior.coords][:-1]
    return ObjectSpec(id=oid, name="Spitzzange (synthetisch)", contour_mm=pts, length_mm=L,
                      width_mm=float(width.max()),
                      profile=Profile(ds=ds, s=s.tolist(), bottom=bottom.tolist(), top=top.tolist()))


def l_shape(oid: str = "lform") -> ObjectSpec:
    """Asymmetrisch: 60 x 20 Balken + 20 x 30 Nase an einem Ende nach +y."""
    pts = [[0, -10], [60, -10], [60, 20], [40, 20], [40, 10], [0, 10]]
    s = np.arange(0, 60.5, 0.5)
    return ObjectSpec(id=oid, name="L-Form", contour_mm=pts, length_mm=60.0, width_mm=30.0,
                      profile=Profile(ds=0.5, s=s.tolist(), bottom=[0.0] * len(s), top=[10.0] * len(s)))
