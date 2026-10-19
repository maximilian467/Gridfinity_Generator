"""Pydantic-Schemas (Spiegel: frontend/src/lib/types.ts). Alle Maße in mm."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Coord = Annotated[float, Field(ge=-2000, le=2000)]
Angle = Annotated[float, Field(ge=-3600, le=3600)]
Slot = Annotated[int, Field(ge=1, le=16)]
Point2 = Annotated[list[float], Field(min_length=2, max_length=2)]


class Profile(BaseModel):
    ds: float = 0.5
    s: list[float]
    bottom: list[float]   # Ruhelage: min(bottom) = 0 (aus bottom_points interpoliert, falls gesetzt)
    top: list[float]
    bottom_points: list[list[float]] | None = None   # veraltet (Stützpunkte); ersetzt durch levels
    levels: list[list[float]] | None = None          # Ebenen [a, b, z]: Taschenboden in Stufen (editierbar)
    measured: list[float] | None = None              # gemessene Unterseite (nur Anzeige)
    fit_version: int = 1                             # 2 = Neigung auf Ebenen optimiert


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
    side_skipped: bool = False            # ohne Seitenfoto: ebene Unterseite, Dicke von Hand
    thickness_mm: float | None = Field(None, ge=0.5, le=300)   # Dicke von Hand (nur ohne Seitenfoto)
    uniform_thickness: bool = False       # überall gleich dick: Draufsicht mit dieser Dicke korrigieren
    photos: dict[str, dict] = {}
    owner_id: int | None = None           # setzt nur der Server
    project_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,40}$")   # im Projekt gescannt


class Placement(BaseModel):
    object_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    x: Coord = 0.0
    y: Coord = 0.0
    rot_deg: Angle = 0.0
    side_down: Literal["A", "B"] = "A"


class GripRecess(BaseModel):
    shape: Literal["stadium", "rect", "circle"] = "stadium"
    x: Coord
    y: Coord
    w: float = Field(ge=2, le=200)
    l: float = Field(0.0, ge=0, le=500)
    rot_deg: Angle = 0.0
    depth_below: float = Field(10.0, ge=0, le=100)
    rounded: bool = True          # U-förmiger Boden (Finger gleitet unter das Werkzeug)
    attach: int | None = Field(None, ge=0, le=11)   # an Platzierung gekoppelt: quer mittig, nur entlang der Achse
    s: float | None = Field(None, ge=-50, le=1000)   # Position entlang der Werkzeugachse (mm ab Ursprung)
    auto_length: bool = True                         # gekoppelt: Länge = Taschenbreite + 2 x Überstand
    edge_r: float = Field(1.0, ge=0, le=15)          # Rundung der Oberkante (weicher Übergang)
    angle_deg: float = Field(0.0, ge=-80, le=80)     # gekoppelt: Schrägstellung gegenüber quer zur Werkzeugachse


class Compartment(BaseModel):
    x: Coord
    y: Coord
    w: float = Field(ge=1, le=600)
    l: float = Field(ge=1, le=600)
    radius: float = Field(3.0, ge=0, le=50)
    depth: float | None = Field(15.0, ge=0.5, le=200)   # None = so tief wie möglich
    polygon: Annotated[list[Point2], Field(max_length=4000)] | None = None   # freie Form (automatische Kästen); sonst Rechteck x,y,w,l
    generated: bool = False                    # von 'Kästen erzeugen' angelegt (wird beim Neu-Erzeugen ersetzt)


class ColorSlots(BaseModel):
    body: Slot = 1
    pocket: Slot = 2
    grip: Slot = 3
    compartment: Slot = 2


class ColorSkin(BaseModel):
    floor: float = Field(0.6, ge=0.2, le=5)
    wall: float = Field(0.8, ge=0.2, le=5)
    show_top_ring: bool = True


Hex = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class PartColors(BaseModel):
    """Druckfarben je Teil (Anzeige und Zuordnung der Filament-Slots)."""
    body: Hex = "#3b3f45"
    pocket: Hex = "#f26b1d"
    grip: Hex = "#f26b1d"
    compartment: Hex = "#3b3f45"


class InsertSpec(BaseModel):
    id: str = Field("", max_length=40)
    name: str = Field("Einlage", max_length=120)
    owner_id: int | None = None           # setzt nur der Server (Angaben des Clients zählen nicht)
    created_at: str = Field("", max_length=40)   # setzt nur der Server beim Anlegen
    grid_x: int | None = Field(None, ge=1, le=12)
    grid_y: int | None = Field(None, ge=1, le=12)
    height_u: int | None = Field(None, ge=1, le=30)
    height_mm: float | None = Field(None, ge=10, le=250)    # feste Gesamthöhe inkl. Stapelrand (hat Vorrang)
    sink: float = Field(0.65, ge=0.2, le=1.0)              # Werkzeug sinkt zu diesem Anteil seiner Dicke ein
    depth_mm: float | None = Field(None, ge=1, le=200)     # Taschentiefe von Hand (hat Vorrang vor sink)
    stacking_lip: bool = True
    magnets: bool = False
    clearance_xy: float = Field(2.5, ge=0, le=10)
    clearance_end: float = Field(1.0, ge=0, le=20)
    clearance_z: float = Field(0.4, ge=0, le=10)
    overhang: float = Field(0.0, ge=-50, le=50)
    step_tol: float = Field(1.0, ge=0.1, le=50)
    min_zone_len: float = Field(8.0, ge=0.5, le=200)
    max_zones: int = Field(8, ge=1, le=40)
    floor_min: float = Field(1.5, ge=0.4, le=20)
    min_wall: float = Field(1.6, ge=0.4, le=20)
    smooth_mm: float = Field(3.0, ge=0, le=10)             # Glättung der Taschenkontur (kleine Zacken/Kerben verschwinden)
    auto_center: bool = True           # Inhalt mittig in der Einlage ausrichten
    auto_grip: bool = True             # Greifmulde quer unter jedem Werkzeug erzeugen
    grip_width: float = Field(20.0, ge=4, le=80)
    grip_overhang: float = Field(15.0, ge=0, le=100)        # Mulde ragt je Seite so weit über die Tasche hinaus
    grip_depth_below: float = Field(8.0, ge=0, le=100)
    auto_compartments: bool = False    # freie Flächen mit Kästen füllen
    comp_min_size: float = Field(20.0, ge=5, le=300)
    comp_wall: float = Field(1.6, ge=0.4, le=20)
    comp_depth: float | None = Field(None, ge=0, le=200)    # None = so tief wie möglich
    comp_follow: bool = True           # Kastenwand folgt der Werkzeugkontur (sonst gerade Rechtecke)
    placements: Annotated[list[Placement], Field(max_length=12)] = []
    grip_recesses: Annotated[list[GripRecess], Field(max_length=40)] = []
    compartments: Annotated[list[Compartment], Field(max_length=60)] = []
    colors: ColorSlots = Field(default_factory=ColorSlots)
    color_skin: ColorSkin = Field(default_factory=ColorSkin)
    color_hex: PartColors = Field(default_factory=PartColors)
    project_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,40}$")
    overrides: Annotated[list[str], Field(max_length=40)] = []   # Felder, die von der Projektvorlage abweichen


class BaseplateSpec(BaseModel):
    drawer_x: float = Field(ge=20, le=2000)
    drawer_y: float = Field(ge=20, le=2000)
    bed_x: float = Field(256.0, ge=50, le=1000)
    bed_y: float = Field(256.0, ge=50, le=1000)
    clearance: float = Field(0.5, ge=0, le=50)
    magnets: bool = False
    one_sided: bool = False
    disabled: Annotated[list[Annotated[list[int], Field(min_length=2, max_length=2)]], Field(max_length=2500)] = []   # abgewählte Zellen [ix, iy]


# ---- Projekte (Schublade als digitaler Klon) --------------------------------------

# Felder einer Einlage, die die Projektvorlage vorgibt (Liste hier erweitern/kürzen genügt)
TEMPLATE_FIELDS = ("height_mm", "sink", "depth_mm", "stacking_lip", "magnets", "clearance_xy", "clearance_end", "clearance_z",
                   "floor_min", "min_wall", "smooth_mm", "grip_width", "grip_overhang",
                   "grip_depth_below", "comp_min_size", "comp_wall", "comp_depth", "comp_follow", "color_hex",
                   "color_skin")


class InsertTemplate(BaseModel):
    """Mustervorlage: Grundeinstellungen aller Einlagen eines Projekts (Standardwerte wie InsertSpec)."""
    height_mm: float | None = Field(None, ge=10, le=250)
    sink: float = Field(0.65, ge=0.2, le=1.0)
    depth_mm: float | None = Field(None, ge=1, le=200)
    stacking_lip: bool = True
    magnets: bool = False
    clearance_xy: float = Field(2.5, ge=0, le=10)
    clearance_end: float = Field(1.0, ge=0, le=20)
    clearance_z: float = Field(0.4, ge=0, le=10)
    floor_min: float = Field(1.5, ge=0.4, le=20)
    min_wall: float = Field(1.6, ge=0.4, le=20)
    smooth_mm: float = Field(3.0, ge=0, le=10)
    auto_grip: bool = True            # nur beim Anlegen: Greifmulde setzen (wird nicht vererbt)
    grip_width: float = Field(20.0, ge=4, le=80)
    grip_overhang: float = Field(15.0, ge=0, le=100)
    grip_depth_below: float = Field(8.0, ge=0, le=100)
    comp_min_size: float = Field(20.0, ge=5, le=300)
    comp_wall: float = Field(1.6, ge=0.4, le=20)
    comp_depth: float | None = Field(None, ge=0, le=200)
    comp_follow: bool = True
    color_hex: PartColors = Field(default_factory=PartColors)
    color_skin: ColorSkin = Field(default_factory=ColorSkin)


class DrawerPlacement(BaseModel):
    """Einlage im Raster der Schublade: linke untere Zelle (ix, iy), gedreht um 90° oder nicht."""
    insert_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    ix: int = Field(ge=0, le=60)
    iy: int = Field(ge=0, le=60)
    rot: Literal[0, 90] = 0


class ProjectSpec(BaseModel):
    id: str = Field("", max_length=40)
    name: str = Field("Schublade", max_length=120)
    owner_id: int | None = None           # setzt nur der Server
    created_at: str = Field("", max_length=40)
    drawer: BaseplateSpec = Field(default_factory=lambda: BaseplateSpec(drawer_x=500, drawer_y=350))
    drawer_h: float | None = Field(None, ge=5, le=1000)      # Innenhöhe der Schublade (Warnung, wenn zu hoch)
    template: InsertTemplate = Field(default_factory=InsertTemplate)
    placements: Annotated[list[DrawerPlacement], Field(max_length=200)] = []
    notes: str = Field("", max_length=2000)
    archived: bool = False                # "Löschen" archiviert nur (Daten bleiben, solange Platz kein Problem ist)
    archived_at: str = Field("", max_length=40)
