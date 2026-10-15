"""Segmentierung auf dem entzerrten Bild (Plan C).

1. Papiermodell: Farbe des Blattes wird über das ganze Bild glatt geschätzt (Beleuchtungsverlauf).
   Vordergrund ist, was deutlich dunkler oder farbiger als das Papier an dieser Stelle ist; weiche
   Schatten bleiben darunter. Damit zählt jede Werkzeugfarbe, nicht nur "dunkler als Papier".
2. Auswahl: Flächen, die den Blattrand berühren, sind Hand oder Tischkante und werden nur gewählt,
   wenn sonst nichts da ist. Klicks fügen Flächen hinzu (Auswählen) oder nehmen sie weg (Entfernen).
3. Verfeinerung mit SAM 2.1 (falls Gewichte unter data/models/): Box um die Auswahl, Punkte im Inneren,
   Klicks und Hand als Gegenpunkte. Passt SAM nicht zur Auswahl, bleibt die klassische Maske.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..config import ROOT
from .a4 import A4_H, A4_W, MARGIN_MM, PX_PER_MM, RECT_H, RECT_W

SAM_WEIGHTS = ROOT / "data" / "models" / "sam2.1_b.pt"
NEG_RADIUS_MM = 5.0
FG_DARK = 22.0          # Lab-L: so viel dunkler als das Papier (Schatten bleiben darunter)
FG_BRIGHT = 35.0        # heller als das Papier (selten, z. B. Glanz)
FG_COLOR = 9.0          # Lab-ab-Abstand zur Papierfarbe
MIN_AREA_MM2 = 80.0     # kleinere Flächen sind Lochung, Krümel, Schrift
EDGE_MM = 2.5           # Band am Blattrand: was hier liegt, kommt von außen (Hand, Tisch)


def paper_rect_px(inset_mm: float = 1.0) -> tuple[int, int, int, int]:
    x0 = int((MARGIN_MM + inset_mm) * PX_PER_MM)
    y0 = int((MARGIN_MM + inset_mm) * PX_PER_MM)
    x1 = int((MARGIN_MM + A4_W - inset_mm) * PX_PER_MM)
    y1 = int((MARGIN_MM + A4_H - inset_mm) * PX_PER_MM)
    return x0, y0, x1, y1


def _paper_inside(shape, inset_mm: float = 1.0) -> np.ndarray:
    x0, y0, x1, y1 = paper_rect_px(inset_mm)
    m = np.zeros(shape[:2], bool)
    m[y0:y1, x0:x1] = True
    return m


def paper_model(rect_bgr: np.ndarray, k: int = 8) -> np.ndarray:
    """Papierfarbe (Lab, float32) je Pixel: auf 1/k verkleinert die Papierpixel finden und
    ihre Farbe mit normierter Faltung glatt über Werkzeug und Schatten fortsetzen."""
    sm = cv2.resize(rect_bgr, None, fx=1 / k, fy=1 / k, interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(sm, cv2.COLOR_BGR2Lab).astype(np.float32)
    inside = _paper_inside(rect_bgr.shape, 2.0)[::k, ::k][:lab.shape[0], :lab.shape[1]]
    # Startwert: großer Median (ca. 50 mm) übergeht Werkzeuge, folgt aber dem Lichtverlauf
    med = np.stack([cv2.medianBlur(np.ascontiguousarray(lab[..., c]).astype(np.uint8), 61) for c in range(3)], -1)
    L = lab[..., 0]
    chroma = np.hypot(lab[..., 1] - 128, lab[..., 2] - 128)
    m = inside & (np.linalg.norm(lab - med.astype(np.float32), axis=-1) < 8)         & (L > np.median(L[inside]) * 0.8) & (chroma < 20)
    if m.sum() < 100:                                   # Werkzeug füllt fast das Blatt
        m = inside & (L > np.median(L[inside]) * 0.8) & (chroma < 20)
    sig = 12.0                                          # ca. 10 mm
    bg = np.empty_like(lab)
    for _ in range(3):
        w = cv2.GaussianBlur(m.astype(np.float32), (0, 0), sig) + 1e-6
        for c in range(3):
            bg[..., c] = cv2.GaussianBlur(lab[..., c] * m, (0, 0), sig) / w
        m = inside & (np.linalg.norm(lab - bg, axis=-1) < 8)
        if m.sum() < 100:
            break
    return cv2.resize(bg, (rect_bgr.shape[1], rect_bgr.shape[0]), interpolation=cv2.INTER_LINEAR)


def paper_diff(rect_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Abstand zum Papier je Pixel: (dL = wie viel dunkler, dab = wie viel farbiger)."""
    bg = paper_model(rect_bgr)
    lab = cv2.cvtColor(cv2.GaussianBlur(rect_bgr, (0, 0), 1.0), cv2.COLOR_BGR2Lab).astype(np.float32)
    dL = bg[..., 0] - lab[..., 0]
    dab = np.hypot(lab[..., 1] - bg[..., 1], lab[..., 2] - bg[..., 2])
    return dL, dab


def foreground(rect_bgr: np.ndarray, diff=None) -> np.ndarray:
    """Alles auf dem Blatt, was sich deutlich vom Papier abhebt (bool)."""
    dL, dab = diff if diff is not None else paper_diff(rect_bgr)
    fg = ((dL > FG_DARK) | (dL < -FG_BRIGHT) | (dab > FG_COLOR)) & _paper_inside(rect_bgr.shape)
    fg = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
    return fg > 0


def refine_edges(mask: np.ndarray, diff, band_mm: float = 1.5) -> np.ndarray:
    """Kante pixelgenau: im Randband zählt ein Pixel zum Werkzeug, wenn es sich mindestens halb so
    stark vom Papier abhebt wie das Werkzeug gleich daneben (Mitte der Kante, je Farbe des
    Werkzeugs eigene Schwelle). Schmale Teile ohne sicheres Inneres (Spitzen, Haken) bleiben."""
    dL, dab = diff
    D = np.hypot(dL, 2.0 * dab)
    m = (mask > 0).astype(np.uint8)
    r = int(band_mm * PX_PER_MM)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    inner = cv2.erode(m, k)
    band = (cv2.dilate(m, k) > 0) & (inner == 0)
    sig = 3 * PX_PER_MM
    w = cv2.GaussianBlur(inner.astype(np.float32), (0, 0), sig)
    obj = cv2.GaussianBlur(D * inner, (0, 0), sig) / (w + 1e-6)
    thr = np.maximum(0.5 * obj, 12.0)
    sure = w > 0.03                                    # genug Inneres in der Nähe für eine Schwelle
    new = (inner > 0) | (band & sure & (D > thr)) | (band & ~sure & (m > 0))
    new = cv2.morphologyEx(new.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.morphologyEx(new, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))


def _at(lab: np.ndarray, pts, r: int = 10) -> set[int]:
    """Komponenten-Labels in der Nähe der Punkte (Klick muss nicht pixelgenau sitzen)."""
    out: set[int] = set()
    for (x, y) in pts:
        xi, yi = int(x), int(y)
        win = lab[max(yi - r, 0):yi + r + 1, max(xi - r, 0):xi + r + 1]
        ids = win[win > 0]
        if ids.size:
            out.add(int(np.bincount(ids).argmax()))
    return out


def select_tool(fg: np.ndarray, pos=(), neg=()) -> np.ndarray:
    """Werkzeug-Komponenten wählen (uint8 0/1). Ohne Klicks: größte Fläche, die nicht am Blattrand
    hängt (sonst wäre es die Hand); hängt alles am Rand (Werkzeug in der Hand), die größte."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg.astype(np.uint8), connectivity=8)
    if n <= 1:
        return np.zeros(fg.shape, np.uint8)
    edge = _paper_inside(fg.shape, 1.0) & ~_paper_inside(fg.shape, 1.0 + EDGE_MM)
    at_edge = set(np.unique(lab[edge]).tolist()) - {0}
    area = stats[:, cv2.CC_STAT_AREA]
    big = [i for i in range(1, n) if area[i] >= MIN_AREA_MM2 * PX_PER_MM ** 2]
    removed = _at(lab, neg)
    inner = [i for i in big if i not in at_edge and i not in removed]
    rest = [i for i in big if i not in removed]
    keep = set()
    if inner or rest:
        keep.add(max(inner or rest, key=lambda i: area[i]))
    keep |= _at(lab, pos)
    keep -= removed
    m = np.isin(lab, list(keep)).astype(np.uint8)
    # Entfernen-Klick auf der gewählten Fläche (z. B. Hand hängt am Werkzeug): dort ausschneiden
    punched = False
    for (x, y) in neg:
        if 0 <= int(y) < m.shape[0] and 0 <= int(x) < m.shape[1] and m[int(y), int(x)]:
            cv2.circle(m, (int(x), int(y)), int(NEG_RADIUS_MM * PX_PER_MM), 0, -1)
            punched = True
    if punched:                                          # abgetrennte Krümel weg
        n2, lab2, st2, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        ok = [i for i in range(1, n2) if st2[i, cv2.CC_STAT_AREA] >= MIN_AREA_MM2 * PX_PER_MM ** 2]
        m = np.isin(lab2, ok + list(_at(lab2, pos, 2))).astype(np.uint8)
    return m


def largest_with(m: np.ndarray, pos=()) -> np.ndarray:
    """Größte Komponente plus alle, die einen Auswählen-Klick enthalten."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    if n <= 1:
        return np.zeros(m.shape, np.uint8)
    keep = {1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))} | _at(lab, pos, 2)
    return np.isin(lab, list(keep)).astype(np.uint8)


def touches_edge(m: np.ndarray, mm: float = EDGE_MM + 1.0) -> bool:
    """Reicht die Maske bis an den Blattrand? Nur dann kann eine Hand daran hängen."""
    edge = _paper_inside(m.shape, 0.0) & ~_paper_inside(m.shape, mm)
    return bool(((m > 0) & edge).sum() > 20 * PX_PER_MM)


def fill_holes(m: np.ndarray) -> np.ndarray:
    """Löcher im Inneren schließen (kein Hohlraum im Werkzeug), Außenform bleibt."""
    m = (m > 0).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = np.zeros_like(m)
    cv2.drawContours(out, cnts, -1, 1, -1)
    return out


def classical_mask(rect_bgr: np.ndarray, pos=(), neg=()) -> np.ndarray:
    """pos/neg: Punkte in entzerrten Pixeln (x, y). Rückgabe uint8 0/255."""
    diff = paper_diff(rect_bgr)
    return largest_with(refine_edges(select_tool(foreground(rect_bgr, diff), pos, neg), diff), pos) * 255


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
    """Eine Maske für ein Objekt aus allen Punkten (und optional einer Box)."""
    model = _get_sam()
    pts = [list(map(float, p)) for p in list(pos) + list(neg)]
    lbl = [1] * len(pos) + [0] * len(neg)
    # Form (1, N, 2): alle Punkte beschreiben EIN Objekt (flach (N, 2) wären N getrennte Objekte)
    kw = {"points": [pts], "labels": [lbl]} if pts else {}
    if box is not None:
        kw["bboxes"] = [list(map(float, box))]
    res = model(rect_bgr, **kw, verbose=False)[0]
    if res.masks is None or len(res.masks.data) == 0:
        return np.zeros(rect_bgr.shape[:2], np.uint8)
    m = res.masks.data[0].cpu().numpy()
    m = cv2.resize(m.astype(np.uint8), (RECT_W, RECT_H), interpolation=cv2.INTER_NEAREST)
    return m * 255


def interior_points(m: np.ndarray, n: int = 5) -> list[list[float]]:
    """Punkte sicher im Inneren, entlang der Längsachse verteilt (je Abschnitt der tiefste Punkt)."""
    dt = cv2.distanceTransform((m > 0).astype(np.uint8), cv2.DIST_L2, 5)
    ys, xs = np.nonzero(dt > max(2.0, 0.4 * float(dt.max())))
    if len(xs) == 0:
        return []
    P = np.column_stack([xs, ys]).astype(np.float64)
    c = P.mean(axis=0)
    _, _, vt = np.linalg.svd(P[:: max(1, len(P) // 5000)] - c, full_matrices=False)
    t = (P - c) @ vt[0]
    edges = np.linspace(t.min(), t.max() + 1e-6, n + 1)
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        sel = np.nonzero((t >= a) & (t < b))[0]
        if len(sel):
            j = sel[np.argmax(dt[ys[sel], xs[sel]])]
            out.append([float(xs[j]), float(ys[j])])
    return out


def sam_refine(rect_bgr: np.ndarray, cand: np.ndarray, pos=(), neg=(), avoid=None) -> np.ndarray | None:
    """Klassische Auswahl mit SAM schärfen. None, wenn SAM nicht zur Auswahl passt."""
    c = cand > 0
    if c.sum() < 100:
        return None
    ys, xs = np.nonzero(c)
    pad = 3 * PX_PER_MM
    px = [p[0] for p in pos] + [xs.min(), xs.max()]
    py = [p[1] for p in pos] + [ys.min(), ys.max()]
    box = [max(min(px) - pad, 0), max(min(py) - pad, 0), min(max(px) + pad, RECT_W - 1), min(max(py) + pad, RECT_H - 1)]
    inner = interior_points(cand)
    negs = list(neg)
    if avoid is not None and avoid.any():
        negs += interior_points(avoid, 3)
    m = sam_mask(rect_bgr, list(pos) + inner, negs, box) > 0
    if m.sum() < 100:
        return None
    core = cv2.erode(c.astype(np.uint8), np.ones((15, 15), np.uint8))
    for (x, y) in neg:                                        # weggeklickte Stellen zählen nicht
        cv2.circle(core, (int(x), int(y)), int(2 * NEG_RADIUS_MM * PX_PER_MM), 0, -1)
    core = core > 0
    cover = (m & core).sum() / max(core.sum(), 1)            # SAM muss das sichere Innere enthalten
    grow = m.sum() / max(c.sum(), 1)                          # und darf nicht ausufern (Schatten, Blatt)
    clicked = bool(len(pos) or len(neg))                      # mit Klicks darf SAM mehr ändern
    if cover < (0.75 if clicked else 0.9) or grow > (3.0 if clicked else 1.6) or grow < 0.5:
        return None
    if avoid is not None:
        m &= ~(avoid > 0)
    return largest_with(m, pos)


def segment(rect_bgr: np.ndarray, pos=(), neg=(), use_sam: bool = True, holes: bool = True) -> np.ndarray:
    diff = paper_diff(rect_bgr)
    cand = select_tool(foreground(rect_bgr, diff), pos, neg)
    out = None
    if use_sam and sam_available() and cand.any():
        try:
            out = sam_refine(rect_bgr, cand, pos, neg)       # SAM entscheidet, was dazugehört
        except Exception:  # noqa: BLE001 - ohne SAM weiter
            out = None
    if out is None:
        out = cand
    out = largest_with(refine_edges(out, diff), pos)     # die Kante kommt pixelgenau aus dem Bild
    return out * 255
