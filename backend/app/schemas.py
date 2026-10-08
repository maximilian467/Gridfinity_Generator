"""Pydantic-Schemas (Spiegel: frontend/src/lib/types.ts). Alle Maße in mm."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Profile(BaseModel):
    ds: float = 0.5
    s: list[float]
    bottom: list[float]   # Ruhelage: min(bottom) = 0
    top: list[float]


class ObjectSpec(BaseModel):
    id: str
    name: str
    created_at: str = ""
    contour_mm: list[list[float]] = []   # objekt-lokal, x = Länge (0..L), y quer, CAD-y (oben)
    length_mm: float = 0.0
    width_mm: float = 0.0
    profile: Profile | None = None
    side_flip_lr: bool | None = None      # None = automatisch
    side_flip_ud: bool = False
    flip_lr_used: bool | None = None
    tilt_deg: float = 0.0
    profile_missing: list[bool] = []
    calipers: dict[str, float] = {}
    warnings: list[str] = []
    photos: dict[str, dict] = {}


class Placement(BaseModel):
    object_id: str
    x: float = 0.0
    y: float = 0.0
    rot_deg: float = 0.0
    side_down: Literal["A", "B"] = "A"


class GripRecess(BaseModel):
    shape: Literal["stadium", "rect", "circle"] = "stadium"
    x: float
    y: float
    w: float
    l: float = 0.0
    rot_deg: float = 0.0
    depth_below: float = 10.0
    rounded: bool = True          # U-förmiger Boden (Finger gleitet unter das Werkzeug)


class Compartment(BaseModel):
    x: float
    y: float
    w: float
    l: float
    radius: float = 3.0
    depth: float = 15.0
    polygon: list[list[float]] | None = None   # freie Form (automatische Kästen); sonst Rechteck x,y,w,l
    generated: bool = False                    # von 'Kästen erzeugen' angelegt (wird beim Neu-Erzeugen ersetzt)


class ColorSlots(BaseModel):
    body: int = 1
    pocket: int = 2
    grip: int = 3
    compartment: int = 2


class ColorSkin(BaseModel):
    floor: float = 0.6
    wall: float = 0.8
    show_top_ring: bool = True


class InsertSpec(BaseModel):
    id: str = ""
    name: str = "Einlage"
    grid_x: int | None = None
    grid_y: int | None = None
    height_u: int | None = None
    stacking_lip: bool = True
    magnets: bool = False
    clearance_xy: float = 1.5
    clearance_end: float = 1.0
    clearance_z: float = 0.4
    overhang: float = 0.0
    step_tol: float = 1.0
    min_zone_len: float = 8.0
    max_zones: int = 8
    floor_min: float = 1.5
    min_wall: float = 1.6
    smooth_mm: float = 1.5             # Glättung der Taschenkontur (kleine Zacken/Kerben verschwinden)
    auto_center: bool = True           # Inhalt mittig in der Einlage ausrichten
    auto_grip: bool = True             # Greifmulde quer unter jedem Werkzeug erzeugen
    grip_width: float = 16.0
    grip_overhang: float = 15.0        # Mulde ragt je Seite so weit über die Tasche hinaus
    grip_depth_below: float = 8.0
    auto_compartments: bool = False    # freie Flächen mit Kästen füllen
    comp_min_size: float = 20.0
    comp_wall: float = 1.6
    comp_depth: float | None = None    # None = so tief wie möglich
    placements: list[Placement] = []
    grip_recesses: list[GripRecess] = []
    compartments: list[Compartment] = []
    colors: ColorSlots = Field(default_factory=ColorSlots)
    color_skin: ColorSkin = Field(default_factory=ColorSkin)


class BaseplateSpec(BaseModel):
    drawer_x: float
    drawer_y: float
    bed_x: float = 256.0
    bed_y: float = 256.0
    clearance: float = 0.5
    magnets: bool = False
    one_sided: bool = False
