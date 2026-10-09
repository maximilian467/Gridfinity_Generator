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


def test_corners_with_occluded_corner_and_bright_neighbour():
    import cv2
    cam = camera()
    img = render(rot_rect(150, 100, 100, 30, 20), 5, cam, seed=4)
    truth = project(*cam[:3], np.hstack([TRUE_CORNERS, np.zeros((4, 1))]))
    # Hand über der linken oberen Ecke, helles Etikett am rechten Blattrand
    tl = truth[0]
    cv2.ellipse(img, (int(tl[0] + 60), int(tl[1] + 40)), (260, 170), 20, 0, 360, (120, 150, 210), -1)
    tr, br = truth[1], truth[2]
    x = int(max(tr[0], br[0]))
    cv2.rectangle(img, (x - 5, int((tr[1] + br[1]) / 2) - 200), (x + 260, int((tr[1] + br[1]) / 2) + 200), (240, 242, 244), -1)
    c = find_a4_corners(img)
    assert c is not None
    assert np.abs(c - truth).max() < 4.0


def test_hand_removed_from_side_photo():
    import cv2
    from app.vision.hands import remove_hand
    L, W, T = 150.0, 38.0, 14.0
    top_img = render(rot_rect(140, 110, L, W, 25), T, camera(offset=(-10, 5)), seed=1, tool=60)
    side_poly = rot_rect(160, 100, L, T, 0)
    side_img = render(side_poly, W, camera(offset=(5, -10)), seed=2, tool=60)
    # "Hand": hautfarbene Fläche, die das linke Ende verdeckt und über den Blattrand ragt
    K, rvec, t, _ = camera(offset=(5, -10))
    end = project(K, rvec, t, [[160 - L / 2 + 5, 100, 0]])[0]
    cv2.ellipse(side_img, (int(end[0]) - 180, int(end[1])), (230, 150), 0, 0, 360, (95, 120, 175), -1)
    rects, masks = [], []
    for img in (top_img, side_img):
        r = rectify(img, find_a4_corners(img))
        rects.append(r)
        masks.append(segment(r, use_sam=False))
    b0 = mask_to_polygon(masks[1]).bounds
    assert (b0[3] - b0[1]) > T + 20          # Gegenprobe: ohne Entfernung ist die Hand in der Maske
    res = remove_hand(rects[1], masks[1], rects[0], masks[0])
    assert res.applied and res.removed_frac > 0.2
    got = mask_to_polygon(res.mask)
    b = got.bounds
    # Rest ist ein dünner Streifen (Dicke + Parallaxe), keine Handfläche mehr
    assert (b[3] - b[1]) < T + 8


def test_largest_polygon_handles_nested_collections():
    """Regression: make_valid lieferte GeometryCollection(MultiPolygon, LineString) -> Absturz im Profil."""
    from shapely.geometry import Polygon
    from app.vision.contour import largest_polygon
    spike = Polygon([(0, 0), (10, 0), (10, 10), (5, 10), (5, 15), (5, 10), (0, 10)])          # Nullbreite-Stachel
    bowtie_spike = Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 12), (0, 10)])             # Schleife + Stachel
    for g in (spike, bowtie_spike):
        p = largest_polygon(g)
        assert p is not None and p.geom_type == "Polygon" and p.area > 20
    import numpy as np
    m = np.zeros((300, 300), np.uint8)
    m[100:150, 100:200] = 255
    m[150:200, 200:250] = 255          # berührt die erste Fläche nur an einer Ecke
    assert mask_to_polygon(m).area > 40
