# Plan: Gridfinity-Einlagen-Generator (Web-App)

## Context
Ziel ist eine lokal laufende Web-App, die aus **zwei Fotos** eines Werkzeugs (Draufsicht + Seitenprofil, jeweils auf einem DIN-A4-Blatt als Maßstab) automatisch eine **Gridfinity-Einlage** erzeugt: Tasche mit Spiel nach Wahl, **gestufter Taschenboden** (Werkzeug liegt kippelfrei auf), Greifmulden, optionale Fächer/Kästen, Gridfinity-Füße + Stapelrand. Ausgabe: **3MF für Bambu Studio / OrcaSlicer mit getrennten Teilen pro Farbfläche** (im Slicer einzeln einfärbbar), dazu STL und STEP. Nebenfunktion: **Baseplate-Generator** für Schubladen.

Hintergrund: Eine frühere Sonnet-Session hat eine Spitzzangen-Einlage (3×5) per Hand gebaut. Learnings daraus, die dieser Plan adressiert:
- Kontur aus verkleinertem Bild + manuelle Rotation → falsch ausgerichtet. ⇒ Immer Originalauflösung, Homographie, PCA-Ausrichtung, Overlay-Kontrolle im UI.
- Dicken nur geschätzt, Perspektive verfälscht Werte. ⇒ Seitenprofil-Foto mit gleicher A4-Kalibrierung + **Parallaxenkorrektur** + optionale Messschieber-Werte.
- Spitze passte nicht, 0,8 mm Spiel zu eng. ⇒ Spiel-Presets, separate Längszugabe an den Enden, Default 1,5 mm.
- Farben nur per Pinsel möglich. ⇒ Mehrteiliges 3MF.
- Einzelteile statt ein Körper / eingeschlossener Zweitkörper. ⇒ Automatische Geometrie-Checks (gültig, wasserdicht, Körperanzahl).
- Probedruck lieferte die besten Infos. ⇒ Export „Passform-Test“ (dünne Konturplatte).

Getroffene Entscheidungen (mit Nutzer geklärt):
- Seitenfoto: Werkzeug **hochkant auf das A4-Blatt gestellt** (mit Fingern gehalten), **von oben** fotografiert. Finger werden per Segmentierung ignoriert.
- Slicer: **Bambu Studio + OrcaSlicer** → Bambu-3MF-Format.
- **Mehrere Werkzeuge pro Einlage** ab Version 1.
- **Baseplate-Generator** als Nebenfeature.
- Hardware: kein NVIDIA-GPU auf diesem Rechner → alles CPU-tauglich.

---

## Architektur-Entscheidungen

| Bereich | Entscheidung | Begründung |
|---|---|---|
| Frontend | **React 19 + TypeScript + Vite**, Tailwind CSS v4, zustand (State), TanStack Query (API), react-router, **react-konva** (2D-Editoren), **@react-three/fiber + drei** (3D-Vorschau) | React passt: komplexe interaktive Editoren, bestes Ökosystem für Canvas/3D. Kein Grund für Alternative. |
| Design | Projekt-Skill **design-taste-frontend** (kopiert aus `C:\Users\maxim\Documents\coden\developer_island\.claude\skills\design-taste-frontend`) | Vom Nutzer gewünscht, verhindert generischen Look. |
| Backend | **Python 3.11 + FastAPI + uvicorn**, Paketmanager **uv** (vorhanden) | CAD-Kernel (OCCT) und Bildverarbeitung sind in Python am stärksten. |
| CAD | **CadQuery** (OpenCascade) + **cq-gridfinity** (`cqgridfinity`) für Bin/Baseplate-Grundkörper | Echte B-Rep → robuste Booleans, STEP-Export, korrekte Gridfinity-Profile ohne Eigenbau. |
| 2D-Geometrie | **shapely 2.x** (Offsets, Schnitte, Kollisionsprüfung) | Toleranz-Offsets und Layoutprüfung schnell ohne CAD. |
| Bildverarbeitung | **OpenCV** (A4-Erkennung, Homographie, Kanten), **SAM 2.1 via `ultralytics`** (Segmentierung mit Klick-Prompts, CPU), **MediaPipe Hand Landmarker** (Finger → negative Prompts, optional) | Lokal, präzise, kein Cloud-Zwang. Klassische Kantenverfeinerung bringt Genauigkeit auf ~0,1 mm Rasterauflösung. |
| Mesh/Export | **trimesh** (STL-Check, GLB-Vorschau), eigener **Bambu-3MF-Writer** (zipfile + lxml), CadQuery Assembly → STEP mit Farben | 3MF mit Teilen + Filamentzuordnung = einzeln einfärbbare Flächen. |
| Persistenz | Dateisystem: `data/objects/<id>/…`, `data/inserts/<id>/…` (JSON + Bilder + Outputs), keine DB | Einfach, self-host-tauglich, leicht zu sichern. |
| Jobs | `concurrent.futures.ProcessPoolExecutor` (CAD-Builds sind CPU-lastig), Job-Status per Polling | Keine Extra-Infrastruktur nötig. |
| Betrieb lokal | Dev: `uvicorn` (Port 8000) + `vite` (Port 5173, Proxy `/api`→8000). Prod-lokal: FastAPI liefert gebautes Frontend aus `frontend/dist` aus. | Ein Prozess im Prod-Modus. |
| Später | Docker Compose auf dem Mini-PC (SSH), kostenlose Erreichbarkeit via Cloudflare Tunnel o. ä. | Erst nach Phase 7, nicht jetzt umsetzen. |

---

## Konventionen (verbindlich, verhindert Spiegel-/Rotationsfehler)
- Einheiten intern **immer mm** (float). Winkel in Grad nur im UI, intern Radiant.
- **Papier-Koordinaten**: Ursprung linke obere A4-Ecke, x nach rechts, y nach unten (Bildkonvention), A4 immer als 297 (x) × 210 (y) mm abgebildet (Hoch-/Querformat wird über Seitenlängen erkannt).
- **Entzerrtes Bild**: 10 px/mm, plus 40 mm Rand rundherum (Werkzeug/Finger dürfen überstehen) → 3770 × 2900 px. Pixel (u,v) ↔ mm (u/10 − 40, v/10 − 40).
- **Objekt-lokal**: nach PCA-Ausrichtung liegt die Längsachse auf +x, `s` = Position entlang der Länge (0 = linkes Ende), y quer; Konvertierung Bild→CAD: `y_cad = −y_img` (Blick von oben bleibt Blick von oben, **keine Spiegelung**).
- **Einlage/CAD**: Ursprung = linke untere Außenecke der Einlage, x rechts, y oben (vom Betrachter weg), z oben; z = 0 Unterkante Füße.
- Pflicht-Test: asymmetrische Testform (L-Form) muss nach dem gesamten Pipeline-Durchlauf in der 3D-Draufsicht **nicht gespiegelt** erscheinen.

---

## Repo-Struktur
```
gridfinity_generator/
  CLAUDE.md                      # Projektregeln (Konventionen oben, Befehle, Teststrategie)
  .claude/skills/design-taste-frontend/SKILL.md
  backend/
    pyproject.toml               # uv-Projekt
    app/
      main.py                    # FastAPI-App, Router, Static-Files, CORS (dev)
      config.py                  # Pfade, Defaults
      schemas.py                 # pydantic v2: ObjectSpec, InsertSpec, BaseplateSpec, Job
      storage.py                 # JSON lesen/schreiben in data/
      jobs.py                    # ProcessPoolExecutor, Job-Registry
      api/objects.py, api/inserts.py, api/baseplates.py, api/jobs.py
      vision/
        exif.py                  # Orientierung, Brennweite (35mm-äquiv.)
        a4.py                    # A4-Ecken finden, Homographie, Entzerrung
        pose.py                  # Kamerapose (solvePnP), Parallaxenkorrektur
        segment.py               # SAM2 + Hand-Landmarks → Maske
        refine.py                # Kantenverfeinerung im Randband
        contour.py               # Maske → Kontur (mm), Glätten, Löcher füllen, PCA
        profile.py               # Seitenprofil b(s), t(s), Ruhelage, Abgleich mit Draufsicht
      geometry/
        gridfinity.py            # Bin-Grundkörper, Baseplate (cq-gridfinity-Wrapper)
        layout.py                # 2D-Layout: Platzierung, Offsets, Kollisionen, Auto-Rastergröße
        zones.py                 # Stufenzonen aus Profil
        cutters.py               # Taschen/Mulden/Fächer → CadQuery-Cutter
        insert_cad.py            # Zusammenbau Einlage + Farbteile
        color_parts.py           # Farbschichten erzeugen
        checks.py                # Gültigkeit, Wasserdichtheit, Körperanzahl, Volumen
        baseplate.py             # Schubladen-Aufteilung
      export/
        stl.py, step.py, glb.py, threemf_bambu.py, fit_test.py
    tests/                       # pytest, inkl. synthetische Testbilder
  frontend/
    src/
      main.tsx, router.tsx, styles.css
      lib/api.ts, lib/types.ts   # Typen spiegeln backend/app/schemas.py
      store/                     # zustand-Stores
      components/                # UI-Bausteine (Button, Slider, NumberField, Panel, Stepper…)
      features/library/          # Startseite: Objekte + Einlagen
      features/scan/             # Scan-Wizard (Foto → Ecken → Maske → Profil)
      features/insert/           # Einlagen-Designer (2D-Layout, Parameter, 3D, Export)
      features/baseplate/
  data/                          # gitignored
  docs/PLAN.md, docs/samples/, docs/reference/
  scripts/dev.ps1                # startet Backend + Frontend
```

---

## Datenmodell (Kern, pydantic + TS-Spiegel)
```text
ObjectSpec
  id, name, created_at
  photos.top / photos.side: { original_path, corners_px[4], exif_focal_35mm?, rectified_path,
                              mask_path, prompts{pos[], neg[]}, camera_pose{C_mm[3]}? }
  contour_mm: [[x,y]...]            # Draufsicht, objekt-lokal, parallaxenkorrigiert
  length_mm, width_mm
  profile: { ds:0.5, s[], bottom[], top[] }  # Ruhelage: min(bottom)=0
  side_flip_lr, side_flip_ud: bool
  calipers: { length?, max_thickness? }      # optionale Messschieber-Werte (skalieren)
  warnings: []

InsertSpec
  id, name, grid_x, grid_y (oder auto), height_u (oder auto), stacking_lip: bool, magnets: bool
  clearance_xy, clearance_end, clearance_z, overhang, step_tol, min_zone_len, floor_min, min_wall
  placements: [{ object_id, x, y, rot_deg, side_down:"A"|"B" }]
  grip_recesses: [{ shape:"stadium"|"rect"|"circle", x, y, w, l, rot_deg, depth_below }]
  compartments:  [{ x, y, w, l, radius, depth }]
  colors: { body:1, pocket:2, grip:3, compartment:2 }   # Filament-Slots
  color_skin: { floor:0.6, wall:0.8, show_top_ring:true }
```

### Einstellungen & Defaults
| Parameter | Default | Bedeutung |
|---|---|---|
| `clearance_xy` | 1.5 mm | Spiel pro Seite. Presets im UI: Presspassung 0.3 · Normal 1.0 · Locker 2.0 · Frei 0–4 |
| `clearance_end` | 1.0 mm | Zusätzliches Spiel nur an beiden Längsenden (Spitze!) |
| `clearance_z` | 0.4 mm | Abstand Taschenboden unter Werkzeug |
| `overhang` | 0 mm | >0: Werkzeug ragt über Oberfläche (Warnung: nicht stapelbar); <0: versenkt |
| `step_tol` | 1.0 mm | max. Höhenabweichung innerhalb einer Stufenzone |
| `min_zone_len` | 8 mm | kürzere Zonen werden zusammengelegt |
| `max_zones` | 8 | |
| `floor_min` | 1.5 mm | Mindestmaterial über Fußoberkante (z ≥ 4.75 + floor_min) |
| `min_wall` | 1.6 mm | Mindestwand zwischen Taschen/Fächern; Warnung darunter |
| Rand innen | 2.6 mm | Abstand aller Cutter zur Außenkante (Stapelrand-Breite) |
| Grip `depth_below` | 10 mm | Mulde unter dem angrenzenden Taschenboden |
| Fach `radius` | 3 mm | Eckradius |

---

## Algorithmen (präzise Vorgaben)

### A. A4-Erkennung & Entzerrung (`vision/a4.py`)
1. Bild laden, `PIL.ImageOps.exif_transpose`, volle Auflösung behalten. EXIF `FocalLengthIn35mmFilm` lesen.
2. Kandidaten: Lab-Farbraum, hell (L hoch) + geringe Sättigung → Binärmaske, morph. Close, größte Kontur → `approxPolyDP` auf 4 Punkte. Fallback: Canny + `findContours`. Ecken ordnen (TL,TR,BR,BL); längere Seite = 297 mm.
3. Subpixel: `cv2.cornerSubPix` auf die 4 Ecken.
4. UI zeigt Ecken als ziehbare Punkte mit Lupe; Nutzer bestätigt/korrigiert → `PUT …/corners`.
5. `cv2.getPerspectiveTransform` + `warpPerspective` (INTER_CUBIC) in das 10-px/mm-Raster mit 40 mm Rand.

### B. Kamerapose & Parallaxenkorrektur (`vision/pose.py`)
- Intrinsik: `f_px = f35 * diag_px / 43.27`, Hauptpunkt = Bildmitte. Fehlt EXIF → 26 mm annehmen + Warnung „Brennweite unbekannt“.
- `cv2.solvePnP` mit A4-Ecken (mm, z=0) → Kamerazentrum `C` in Papierkoordinaten (`C = −Rᵀt`, Vorzeichen so, dass `C_z > 0`).
- Ein Silhouettenpunkt `p` (Papierebene) stammt von einem Objektpunkt auf Höhe `h`: **`X_xy = C_xy + (1 − h/C_z)·(p − C_xy)`**.
- Draufsicht: `h(s) = (bottom(s)+top(s))/2`. Seitenfoto: `h(s) = halbe Objektbreite bei s` aus der Draufsicht.
- Iteration: (1) beide Konturen unkorrigiert, (2) Seite mit Breite aus Draufsicht korrigieren, (3) Draufsicht mit Profil korrigieren, (4) Seite erneut. 2 Durchläufe genügen.
- Warnung, wenn `C_z < 300 mm` („höher halten / 2×-Zoom nutzen“).

### C. Segmentierung (`vision/segment.py`, `refine.py`)
1. Auf dem **entzerrten** Bild arbeiten.
2. Auto-Vorschlag positiver Prompt: dunkelste große Komponente auf dem Papier (Otsu) → Bounding-Box + Schwerpunkt als Prompt.
3. MediaPipe Hand Landmarker (Tasks-API, `hand_landmarker.task`) → alle Landmarks als **negative** Prompts. Wenn MediaPipe sich nicht installieren lässt (Abhängigkeitskonflikt), Feature weglassen; Nutzer setzt negative Klicks manuell. Keine Hautfarben-Heuristik (rote/gelbe Isolierungen würden fälschlich entfernt).
4. SAM 2.1 (`ultralytics.SAM("sam2.1_b.pt")`, CPU) mit Box + Punkten → Maske.
5. **Kantenverfeinerung**: Band = Maskenrand ±1.5 mm (15 px). Papier-Helligkeit = Median von L im Ring außerhalb des Bands, Objekt = Median innerhalb der Maske; Schwelle = Mittelwert. Band-Pixel neu klassifizieren, morph. Open/Close 3 px, nur die mit dem SAM-Kern verbundene Komponente behalten.
6. Nutzer kann im Masken-Editor (react-konva) Pinsel (hinzufügen/radieren) und Klicks (+/−, löst SAM neu aus) verwenden; manuelle Maske wird als PNG hochgeladen.

> **Umsetzungsnotizen Phase 3 (Abweichungen):**
> - Segmentierung ist primär **klassisch** (Otsu auf Lab-L innerhalb des Blattes + Klicks wählen/entfernen Regionen + Kantenverfeinerung). SAM 2.1 wird genutzt, sobald `data/models/sam2.1_b.pt` existiert (Download erfordert Freigabe durch den Nutzer); MediaPipe-Hände sind (noch) nicht integriert, negative Klicks/Radierer übernehmen das.
> - **Parallaxenkorrektur** nicht als Eckpunkt-Formel, sondern per **Visual Hull**: ein Punkt q der Papierebene gehört zum Fußabdruck, wenn die Projektionen seiner senkrechten Strecke (Höhen `bottom(s)`..`top(s)`; Seitenfoto: 0..`Breite(s)`) in der Silhouette liegen (`profile.correct_polygon`). Eckpunkt-Klassifizierung (außen=oben/innen=unten) erzeugte Spitzen an den Verbindungskanten.
> - Synthetische Tests (Lochkamera-Rendering, Rauschen, Unschärfe): Länge ±0.1, Breite ±0.15, Dicke ±0.3 mm.

### D. Kontur (`vision/contour.py`)
- Größte Außenkontur, **Löcher füllen** (Default an, z. B. Lücke zwischen Zangengriffen), Douglas-Peucker 0.1 mm, `shapely.make_valid`.
- PCA → Längsachse auf +x drehen, `s=0` am linken Ende. Länge/Breite berechnen und im UI als Maßlinien anzeigen.
- Optional `calipers.length` → globaler Skalierungsfaktor auf Draufsicht und Profil.

### E. Seitenprofil & Ruhelage (`vision/profile.py`)
1. Seiten-Silhouette entzerren, segmentieren, PCA ausrichten wie D.
2. Abgleich mit Draufsicht: Spiegelung links/rechts automatisch per Korrelation der normierten Ausdehnungsprofile beider Ansichten wählen; im UI überschreibbar (`side_flip_lr`). Oben/unten (`side_flip_ud`) = welche Seite beim Liegen unten ist, UI-Toggle.
3. Längen angleichen: Seitenprofil auf Draufsicht-Länge skalieren; Abweichung > 3 % → Warnung.
4. Für jedes `s` (Raster 0.5 mm): `bottom(s)` = unterer, `top(s)` = oberer Maskenrand in mm. Spalten ohne Maske (Finger entfernt) linear interpolieren und im UI rot markieren.
5. **Ruhelage**: untere konvexe Hülle von `(s, bottom(s))`; das Hüllsegment, unter dem der Flächenschwerpunkt der Silhouette liegt, wird horizontal gedreht; dann `bottom -= min(bottom)`. Kippwinkel > 5° → Hinweis.
6. `calipers.max_thickness` (optional) → Profil in z skalieren.
7. UI: Profilkurve (SVG) mit ziehbaren Stützpunkten zur manuellen Korrektur.

### F. Stufenzonen (`geometry/zones.py`)
Eingabe: `bottom(s)` (Ruhelage), Taschenausdehnung in s von `−(clearance_xy+clearance_end)` bis `L + clearance_xy + clearance_end`.
1. Außerhalb [0, L] Randwert halten.
2. Verschiebungstoleranz: `f(s) = minimum_filter1d(bottom, Fenster ±(clearance_xy+clearance_end))` (scipy).
3. Greedy von links: Zone erweitern, solange `max(f) − min(f) ≤ step_tol`; Zonenboden = `min(f)`.
4. Zonen < `min_zone_len` mit dem Nachbarn verschmelzen, dessen Boden tiefer ist (Boden = Minimum beider). Mehr als `max_zones` → Nachbarpaar mit kleinstem Höhenunterschied verschmelzen, bis Limit erreicht.
5. Absolute Höhen: `z_surface = 7·height_u`; `T = max(top)`; `z_rest = z_surface − T + overhang`; Zonenboden `z_i = z_rest + floor_i − clearance_z`.
6. **Auto-Höhe**: kleinstes `height_u`, sodass alle Zonenböden und Muldenböden ≥ `4.75 + floor_min`.

### G. CAD-Aufbau (`geometry/*.py`)
1. Grundkörper: `cqgridfinity.GridfinityBox(grid_x, grid_y, height_u, solid=True, holes=magnets, no_lip=not stacking_lip)`. Maße per Test gegen Spec prüfen (siehe Verifikation). Falls cq-gridfinity unbrauchbar: Profile selbst nach Spec (unten) bauen.
2. Taschen-Cutter pro Objekt: Taschenkontur `B = buffer(contour, clearance_xy, join_style=round)`; Längszugabe als Minkowski-Summe mit der Strecke [−clearance_end, +clearance_end] auf der x-Achse: `O = union(translate(B, dx, 0) für dx in linspace(−clearance_end, +clearance_end, 9))`, danach `simplify(0.05)`. (Nicht skalieren – das verzerrt die Kontur.)
   Für jede Zone i: `O ∩ Streifen[a_i − 0.05, b_i + 0.05]` (Überlappung 0.05 mm gegen koplanare Flächen) → Polygon → Prisma von `z_i` bis `z_surface + 5` (durch den Stapelrand). Dann Platzierung (Rotation, Translation) anwenden.
3. Greifmulden: Form (Stadion/Rechteck/Kreis) → Prisma von `z_grip = (Boden der tiefsten berührten Zone) − depth_below` bis oben.
4. Fächer: abgerundetes Rechteck → Prisma von `z_surface − depth` bis oben.
5. Alle Cutter mit 2D-Prüfung vorab (shapely): innerhalb Innenbereich (Außenmaß − 2·2.6 mm), Abstände ≥ `min_wall` → sonst Warnung (Build trotzdem möglich).
6. `body = base − union(alle Cutter)`.

### H. Farbteile (`geometry/color_parts.py`)
Für jede Farbgruppe g in Priorität **Greifmulde > Tasche > Fach**:
- „gewachsener“ Cutter: gleiche Polygone, XY um `color_skin.wall` gepuffert, Böden um `color_skin.floor` abgesenkt, oben bis `z_surface + 5` (bei `show_top_ring=false` nur bis `z_surface − 0.6`).
- `part_g = (body ∩ grown_g) − (bereits vergebene Teile)`.
- `body_main = body − union(part_g)`.
- Checks: jedes Teil gültiger Solid, `Σ Volumen(Teile) ≈ Volumen(body)` (±0.1 %), Vereinigung = genau **1** Körper.

### I. Exporte (`export/*.py`)
- **3MF (Bambu/Orca)**: ein Objekt „Einlage“ mit mehreren Parts (Körper, Taschen, Greifmulden, Fächer), Namen + Filament-Slot je Part in `Metadata/model_settings.config`. **Vorgehen**: Nutzer erzeugt in Bambu Studio eine Referenz (ein Objekt aus 2 Teilen, unterschiedliche Filamente, als Projekt-3MF speichern) → `docs/reference/bambu_reference.3mf`; Struktur analysieren und minimal nachbauen. Fallback, falls Metadaten zicken: Standard-3MF mit mehreren Objekten (Bambu fragt dann „als ein Objekt mit mehreren Teilen laden?“ → Ja).
- **STL**: vereinigter Körper (eine Datei) + ZIP mit einer STL pro Farbteil.
- **STEP**: `cq.Assembly` mit Farben je Teil.
- **GLB**: Vorschau für three.js (trimesh, Farbe pro Teil).
- **Passform-Test**: 3 mm dicke Platte (Bin-Außenmaß, ohne Füße) mit durchgehender Taschenkontur → schneller Probedruck für XY-Spiel.
- Tessellierung: lineare Toleranz 0.02 mm, Winkel 0.2 rad.

### J. Baseplate (`geometry/baseplate.py`)
- Eingaben: Schublade B×T (mm), Druckbett (Presets: Bambu X1/P1 256×256, A1 256×256, A1 mini 180×180, frei), Spiel zur Schublade (Default 0.5 mm/Seite), Magnetlöcher ja/nein.
- `n = floor((Maß − 2·Spiel)/42)`; Rest wird als massiver Rand auf beide Seiten verteilt (Option: einseitig).
- Aufteilen in Kacheln ≤ Druckbett (gleichmäßig), Randstreifen nur an Außenkanten. Generator: `cqgridfinity.GridfinityBaseplate` + Randverlängerung.
- Ausgabe: ZIP mit STL je Kachel + Übersichtsbild (SVG) mit Kachelnummern.

### Gridfinity-Spec (für Tests / Fallback)
Raster 42.0 mm; Bin-Außenmaß `n·42 − 0.5`; Außenradius 3.75 mm (Bin), 4.0 mm (Baseplate). Fußprofil von unten: 0.8 mm Fase 45°, 1.8 mm senkrecht, 2.15 mm Fase 45° = 4.75 mm; Fußunterseite 35.6 mm, Radius 0.8 mm. Höheneinheit 7 mm (Körperhöhe = 7·u ohne Stapelrand). Stapelrand +4.4 mm (Profil 0.7 / 1.8 / 1.9 mm). Baseplate-Profil 0.7 / 1.8 / 2.15 = 4.65 mm. Magnete Ø 6.5 × 2.4 mm, ±13 mm vom Zellmittelpunkt.

---

## API (FastAPI, Präfix `/api`)
```
GET  /health
POST /objects                                  {name} → ObjectSpec
GET  /objects, GET /objects/{id}, DELETE /objects/{id}
POST /objects/{id}/photos/{view}               multipart (view=top|side) → corners_px, exif, Bild-URL
PUT  /objects/{id}/photos/{view}/corners       {corners_px} → rectified-URL, camera_pose
POST /objects/{id}/photos/{view}/segment       {pos[], neg[], auto_hands} → mask-URL, contour-Vorschau
PUT  /objects/{id}/photos/{view}/mask          PNG (manuelle Korrektur)
POST /objects/{id}/profile                     {side_flip_lr?, side_flip_ud?, calipers?, profile_overrides?} → contour, profile, warnings
POST /inserts, GET /inserts, GET/PUT /inserts/{id}
POST /inserts/{id}/layout                      → 2D-Polygone (Taschen, Zonen, Mulden, Fächer), auto grid/height, warnings  (schnell, nur shapely)
POST /inserts/{id}/build                       → {job_id}
POST /baseplates/build                         → {job_id}
GET  /jobs/{id}                                → {status, progress, outputs{glb,3mf,stl,parts_zip,step,fit_test}, checks, error}
GET  /files/...                                → statische Dateien aus data/
```

---

## Frontend (UI-Flow, Deutsch)
Design-Read vorgeben (vor dem Bauen mit dem Skill bestätigen): *„Präzises Werkstatt-Werkzeug für Maker – Sprache technischer Zeichnungen: warmes Papierweiß, Graphit-Tinte, ein Signal-Akzent (Sicherheitsorange), feine 42-mm-Rasterlinien als Motiv, Maßlinien/Bemaßungen als UI-Element, Monospace-Ziffern für alle Maße. Kein Lila-Gradient, kein Glassmorphism, kein Inter.“* Hinweis: Der Skill ist für Landingpages gedacht – nur seine Anti-Default- und Typografie-/Farbregeln anwenden, Layout ist eine Werkzeug-App.

1. **Bibliothek** (`/`): Karten für gescannte Objekte (Silhouette als SVG) und Einlagen; „Objekt scannen“, „Neue Einlage“, „Baseplate“.
2. **Scan-Wizard** (`/scan/:id`), Stepper:
   1. Anleitung + Upload Draufsicht (Tipps: diffuses Licht, Kamera senkrecht, 2×-Zoom, ganzes A4 sichtbar, dunkle Unterlage um das Blatt).
   2. Ecken prüfen (ziehbar, Lupe).
   3. Maske prüfen (Overlay, +/− Klicks, Pinsel, Radierer, Rückgängig).
   4. Upload Seitenfoto (Anleitung mit Skizze: hochkant stellen, an den Enden festhalten, Finger möglichst außerhalb der Silhouette) → Ecken → Maske.
   5. **Profil prüfen**: Draufsicht-Kontur und Seitenprofil übereinander entlang s, Spiegel-Toggles, Maße (Länge, Breite, max. Dicke), optionale Messschieber-Felder, Profil-Stützpunkte ziehbar, Warnungen. Speichern.
3. **Einlagen-Designer** (`/insert/:id`), dreigeteilt:
   - Links: Parameter-Panel (Raster/Höhe auto oder fix, Spiel-Presets, Überstand, Stapelrand, Magnete, Farben je Gruppe mit Filament-Slot).
   - Mitte: **2D-Editor** (react-konva) im mm-Maßstab mit 42-mm-Raster: Objekte hinzufügen, verschieben, drehen (frei + 90°-Snap), Greifmulden/Fächer zeichnen und ändern, Stufenzonen farbig mit Tiefe beschriftet, Kollisionen rot. Ruft `/layout` debounced (300 ms) auf.
   - Rechts/Tab: **3D-Vorschau** (GLB, Farbteile in ihren Farben, Orbit, Schnittebene entlang Objektachse) nach Klick auf „3D erzeugen“ (Job mit Fortschritt).
   - Export-Leiste: 3MF (Bambu/Orca), STL, Teile-ZIP, STEP, Passform-Test. Anzeige der Checks (1 Körper, wasserdicht, Volumen, Druckgewicht ca.).
4. **Baseplate** (`/baseplate`): Formular + 2D-Kachelplan + Download.

---

## Umsetzungsphasen (Reihenfolge einhalten, jede Phase mit Abnahmekriterium)

**Phase 0 – Setup**
- `git init`, `.gitignore` (data/, node_modules, .venv, dist, *.pt, *.task), diesen Plan als `docs/PLAN.md`, `CLAUDE.md` (Konventionen, Befehle, „nach jeder Phase Tests grün + Commit“).
- Taste-Skill nach `.claude/skills/design-taste-frontend/` kopieren.
- `backend`: `uv init`, Abhängigkeiten: fastapi, uvicorn[standard], pydantic, python-multipart, numpy, scipy, opencv-python-headless, pillow, shapely, cadquery, cqgridfinity, trimesh, lxml, ultralytics, mediapipe; dev: pytest, httpx. **Zuerst prüfen, dass cadquery + ultralytics + mediapipe gemeinsam unter Python 3.11/Windows installierbar sind** (numpy-Versionskonflikte!). Bei Konflikt: mediapipe weglassen und im Plan vermerken.
- `frontend`: `npm create vite@latest` (react-ts), Tailwind v4, Router, zustand, TanStack Query, react-konva, three, @react-three/fiber, @react-three/drei.
- `scripts/dev.ps1` startet beide. Abnahme: `/api/health` ok, Frontend zeigt Platzhalterseite über Proxy, `uv run pytest` grün. Erster Commit.

**Phase 1 – Gridfinity-Kern**
- `geometry/gridfinity.py`, `checks.py`, `export/stl.py`, `export/step.py`.
- Tests: 3×5×6-Bin solid mit Rand → Bounding Box 125.5 × 209.5 × **45.8** mm (±0.05; **Abweichung**: cq-gridfinity hat 3.8 mm Stapelrand statt 4.4; ohne Stapelrand wird selbst bei z=42 plan abgeschnitten, da `no_lip` der Lib nur das Innenprofil ändert), Körperoberkante z=42.0, 15 Füße (Querschnitt bei z=1 mm → 15 Flächen à 35.6+…), gültig, 1 Körper, STL wasserdicht. Baseplate 3×3: 126 × 126 × **4.75** (**Abweichung**: cq-gridfinity-Baseplate ist 4.75 mm hoch statt 4.65).

**Phase 2 – Einlagen-Geometrie ohne Fotos**
- `zones.py`, `layout.py`, `cutters.py`, `insert_cad.py`, `color_parts.py`, alle Exporte inkl. `threemf_bambu.py`, `glb.py`, `fit_test.py`.
- Testobjekt: synthetische Zange (Kontur ≈ 160 × 50 mm, Profil mit Zonen ähnlich der alten Session: Spitze 11 mm, Backen 13 mm, Fingerschutz 28 mm, Griffansatz 23 mm, Griffe 19.5 mm) in 3×5.
- Tests: Zonenalgorithmus (Unit-Tests mit konstruierten Profilen), L-Form nicht gespiegelt, Farbteil-Volumen-Summe, 1 Körper nach Union, keine Cutter außerhalb Innenbereich.
- **Nutzer einbinden**: Referenz-3MF aus Bambu Studio anfordern; erzeugtes 3MF vom Nutzer in Bambu Studio öffnen lassen (Teile einzeln einfärbbar?). Erst danach weiter.

**Phase 3 – Bildverarbeitung**
- `exif.py`, `a4.py`, `pose.py`, `segment.py`, `refine.py`, `contour.py`, `profile.py`.
- Synthetische Testbilder (OpenCV): A4 + bekannte Form, perspektivisch verzerrt + Rauschen + Schatten → Ziel: Konturfehler < 0.3 mm, A4-Ecken < 1 px. Parallaxe-Test: synthetisch projizierter Quader bekannter Höhe → korrigierte Breite ±0.3 mm.
- Echte Fotos: Nutzer um Fotos der Zange bitten (Draufsicht + Seitenansicht nach neuer Anleitung) → `docs/samples/`. Ergebnis gegen bekannte Werte prüfen (Länge 160 mm, Fingerschutz ≈ 28 mm).

**Phase 4 – API, Speicher, Jobs**
- Alle Endpunkte oben, `storage.py`, `jobs.py`. Tests mit `httpx`/TestClient: kompletter Durchlauf mit synthetischen Bildern bis Downloads.

**Phase 5 – Frontend**
- Skill `design-taste-frontend` laden, Design-Read ausgeben, Design-Tokens (Farben, Typo, Abstände) in `styles.css` festlegen.
- Bibliothek → Scan-Wizard → Einlagen-Designer → Export. 3D-Vorschau mit Farbteilen.
- Abnahme im Browser (Claude-Browser-Pane): kompletter Flow mit Beispielfotos, Screenshots prüfen, keine Konsolenfehler, Layout ab 1280 px Breite gut (Mobil nur Upload-Schritte nutzbar).

**Phase 6 – Komfort**
- Auto-Fächer: freie Fläche = Innenbereich − buffer(Taschen ∪ Mulden, min_wall); auf 1-mm-Raster größte achsparallele Rechtecke greedy (max. N, Mindestgröße 20 × 20 mm) vorschlagen, Nutzer übernimmt/verwirft.
- Baseplate-Seite.
- Objekt mehrfach verwendbar (Bibliothek), Einlage duplizieren.

**Phase 7 – Realtest**
- Mit der echten Zange: Passform-Test drucken lassen, Spiel anpassen, dann volle Einlage. Abweichungen in `docs/LEARNINGS.md` notieren.

**Später (nicht jetzt)**: Dockerfile (Backend inkl. Frontend-Build), docker-compose auf dem Mini-PC per SSH, kostenlose Domain/Tunnel.

---

## Verifikation (Ende-zu-Ende)
1. `cd backend; uv run pytest` – alle Tests grün (Spec-Maße, Zonen, Spiegelung, Farbteile, Vision mit synthetischen Bildern, API-Flow).
2. `scripts/dev.ps1`, im Browser: Objekt aus `docs/samples/` scannen → Profil plausibel → Einlage 3×5 → 3D-Vorschau → alle Exporte laden.
3. Check-Panel zeigt: 1 Körper, wasserdicht, Teilvolumen-Summe = Gesamtvolumen.
4. Nutzer öffnet 3MF in Bambu Studio/Orca: Teile in der Objektliste, Filament je Teil wählbar, druckt als ein Teil.
5. Nutzer druckt Passform-Test, misst im Slicer (z. B. Muldenkante → Taschenende) und vergleicht mit App-Maßen.

---

## Startprompt für die neue Sonnet-5.5-Session
```
Du setzt das Projekt „Gridfinity-Einlagen-Generator“ in C:\Users\maxim\Documents\coden\gridfinity_generator um.
Der vollständige, verbindliche Plan liegt in docs/PLAN.md – lies ihn komplett, bevor du irgendetwas tust.

Regeln:
- Arbeite strikt Phase für Phase (0 → 7). Beginne jetzt mit Phase 0. Eine Phase gilt erst als fertig,
  wenn ihr Abnahmekriterium erfüllt ist und `uv run pytest` grün ist. Danach committen und mir kurz
  berichten (was gebaut, welche Tests, offene Punkte), dann mit der nächsten Phase weitermachen.
- Halte dich exakt an die Konventionen (mm, Koordinatensysteme, keine Spiegelung) und an die Defaults.
  Weiche nur ab, wenn etwas technisch nicht geht – dann begründen und docs/PLAN.md aktualisieren.
- Miss Geometrie immer nach (Bounding Box, Querschnitte, Körperanzahl, Wasserdichtheit) statt dem Code
  zu vertrauen. Bei Bildverarbeitung immer Originalauflösung und Overlay-Bilder zur Kontrolle.
- Stopp-Punkte, an denen du mich fragen musst: (1) Abhängigkeitskonflikte in Phase 0,
  (2) Referenz-3MF aus Bambu Studio + Test des erzeugten 3MF in Phase 2,
  (3) echte Fotos der Zange in Phase 3, (4) Design-Read vor Phase 5.
- Für das Frontend den Projekt-Skill design-taste-frontend verwenden (nur Anti-Default-, Typo- und
  Farbregeln; Layout ist eine Werkzeug-App, keine Landingpage). UI-Sprache Deutsch.
- Wenn etwas im Plan unklar ist, frag nach statt zu raten.
```
