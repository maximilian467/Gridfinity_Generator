import numpy as np
import pytest

from app.vision.a4 import RECT_H, RECT_W, find_a4_corners, rect_px_to_mm, rectify
from app.vision.contour import mask_to_polygon
from app.vision.pose import estimate_pose
from app.vision.profile import build_object
from app.vision.segment import segment
from tests.synth import IMG_H, IMG_W, camera, project, render, rot_rect

F35 = 26.0
TRUE_CORNERS = np.array([[0, 0], [297, 0], [297, 210], [0, 210]], float)


def _scene(poly, obj_h, seed=0, **camkw):
    cam = camera(**camkw)
    return cam, render(poly, obj_h, cam, seed=seed)


def test_a4_corners_subpixel():
    cam, img = _scene(rot_rect(150, 100, 100, 30, 20), 10)
    c = find_a4_corners(img)
    truth = project(*cam[:3], np.hstack([TRUE_CORNERS, np.zeros((4, 1))]))
    assert c is not None
    assert np.abs(c - truth).max() < 1.5       # < ~0.15 mm (10 px/mm entzerrt ~ 1 px = 0.1 mm * ...)
    rect = rectify(img, c)
    assert rect.shape[:2] == (RECT_H, RECT_W)


def test_pose_height():
    cam, img = _scene(rot_rect(150, 100, 100, 30, 20), 10, height=420)
    c = find_a4_corners(img)
    pose = estimate_pose(c, img.shape, F35)
    assert pose.C_mm[2] == pytest.approx(420, rel=0.02)
    assert pose.C_mm[0] == pytest.approx(cam[3][0], abs=5)


def test_flat_contour_error_small():
    """Dünner Körper (Höhe 2 mm): Kontur nahe an der Wahrheit (Parallaxe vernachlässigbar)."""
    poly = rot_rect(150, 100, 120, 34, 25)
    cam, img = _scene(poly, 2.0)
    c = find_a4_corners(img)
    rect = rectify(img, c)
    m = segment(rect)
    got = mask_to_polygon(m)
    from shapely.geometry import Polygon
    truth = Polygon(poly)
    sym = got.symmetric_difference(truth).area
    assert sym / truth.length < 0.3          # mittlere Konturabweichung < 0.3 mm


def _object(L, W, T, seed=1):
    top_poly = rot_rect(140, 110, L, W, 25)
    cam_t, img_t = _scene(top_poly, T, seed=seed, offset=(-10, 5))
    # Seitenfoto: auf der Schmalkante stehend: Grundfläche L x T, Höhe W
    side_poly = rot_rect(160, 100, L, T, -15)
    cam_s, img_s = _scene(side_poly, W, seed=seed + 1, offset=(5, -10))
    out = []
    for img in (img_t, img_s):
        c = find_a4_corners(img)
        rect = rectify(img, c)
        out.append((mask_to_polygon(segment(rect)), estimate_pose(c, img.shape, F35)))
    return out


def test_parallax_box_dimensions():
    L, W, T = 160.0, 40.0, 15.0
    (top, tp), (side, sp) = _object(L, W, T)
    g = build_object(top, side, tp, sp, flip_lr=False)
    assert g.length == pytest.approx(L, abs=0.3)
    assert g.width == pytest.approx(W, abs=0.3)
    assert np.median(g.profile.top[10:-10]) == pytest.approx(T, abs=0.3)
    assert abs(g.profile.tilt_deg) < 1.0
    assert g.profile.bottom.min() == 0.0


def test_raw_side_thickness_is_wrong_without_correction():
    """Gegenprobe: Die unkorrigierte Silhouette des stehenden Körpers ist messbar zu dick."""
    from app.vision.contour import pca_frame, polygon_local
    L, W, T = 160.0, 40.0, 15.0
    (_, _), (side, _) = _object(L, W, T)
    b = polygon_local(side, pca_frame(side)).bounds
    assert (b[3] - b[1]) > T + 2.0


def test_lform_through_pipeline_not_mirrored():
    from shapely import affinity
    from shapely.geometry import Polygon
    L = Polygon([(0, 0), (120, 0), (120, 60), (80, 60), (80, 30), (0, 30)])
    # in Papierkoordinaten (y unten) gedreht/verschoben platzieren
    placed = affinity.translate(affinity.rotate(L, 33, origin=(0, 0)), 110, 70)
    cam = camera()
    img = render(np.array(placed.exterior.coords)[:-1], 2.0, cam, seed=3)
    c = find_a4_corners(img)
    got = mask_to_polygon(segment(rectify(img, c)))
    side_like = got                      # Seitenfoto nicht nötig: nur Frame/Orientierung prüfen
    from app.vision.contour import pca_frame, polygon_local
    loc = polygon_local(got, pca_frame(got))
    # Erwartung in CAD-Orientierung: Blick von oben, y_cad = -y_img (Form mit y gespiegelt = gleiche Ansicht)
    ref = affinity.scale(L, 1, -1, origin=(0, 0))
    best, best_m = 0.0, 0.0
    for rot in range(0, 360, 2):
        for mir, shape in ((False, ref), (True, L)):
            cand = affinity.rotate(shape, rot, origin=(0, 0))
            cand = affinity.translate(cand, loc.centroid.x - cand.centroid.x, loc.centroid.y - cand.centroid.y)
            iou = cand.intersection(loc).area / cand.union(loc).area
            if not mir:
                best = max(best, iou)
            else:
                best_m = max(best_m, iou)
    assert best > 0.97
    assert best_m < best - 0.05


def test_sam_path_matches_truth():
    from app.vision.segment import sam_available, sam_mask
    if not sam_available():
        pytest.skip("SAM-Gewichte fehlen (scripts/download_models.ps1)")
    from shapely.geometry import Polygon
    from app.vision.a4 import mm_to_rect_px
    poly = rot_rect(140, 110, 150, 38, 25)
    img = render(poly, 2.0, camera(), seed=1)
    rect = rectify(img, find_a4_corners(img))
    m = sam_mask(rect, [list(mm_to_rect_px([140, 110]))], [])
    got = mask_to_polygon(m)
    truth = Polygon(poly)
    assert got.symmetric_difference(truth).area / truth.length < 0.6
