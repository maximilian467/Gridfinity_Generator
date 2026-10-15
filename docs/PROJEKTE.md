# Projekte: Schublade als digitaler Klon

Ein Projekt ist eine Schublade: Baseplate nach Maß (Zellen einzeln abwählbar), alle Werkzeuge mit
ihren Einlagen, eine Mustervorlage für die Einstellungen und eine 2D/3D-Ansicht.

## Bausteine

| Teil | Datei |
|---|---|
| Datenmodell (`ProjectSpec`, `InsertTemplate`, `DrawerPlacement`, `TEMPLATE_FIELDS`) | `backend/app/schemas.py` |
| Speicher `data/projects/<id>/project.json` | `backend/app/storage.py` |
| API (`/api/projects`: CRUD, assign, generate, arrange, place, clone) | `backend/app/api/projects.py` |
| Anordnung im Raster | `backend/app/geometry/packing.py` |
| Baseplate (Zellmaske, Kacheln, Taschenprofil) | `backend/app/geometry/baseplate.py` |
| Werkzeug-Foto als Textur | `backend/app/vision/texture.py`, `GET /api/objects/{id}/texture` |
| Projektseite (Schublade, Werkzeuge, Vorlage, Baseplate) | `frontend/src/features/project/ProjectPage.tsx` |
| 3D-Klon | `frontend/src/features/project/Clone3D.tsx` |
| Rückfrage beim Überschreiben (Sprechblase) | `frontend/src/features/insert/Designer.tsx` (`patch`, `.override-bubble`) |

## Entscheidungen (und wie man sie umbaut)

1. **Einstellungen werden vererbt, nicht kopiert.** Ändert sich die Vorlage, schreibt der Server die Werte
   in alle Einlagen des Projekts, außer in Felder aus `InsertSpec.overrides`. Welche Felder die Vorlage
   vorgibt, steht nur in `TEMPLATE_FIELDS` (Backend) und `TEMPLATE_FIELDS` (Frontend, `lib/types.ts`).
   Ein Feld aus der Vorlage nehmen = es aus beiden Listen streichen.
2. **Einlagen liegen auf dem 42-mm-Raster** (ganze Zellen, Drehung 0/90°), wie Gridfinity-Bins in echt.
   Freie Positionen bräuchten nur `DrawerPlacement` mit mm statt Zellen und eine Kollisionsprüfung mit Polygonen.
3. **Anordnung: einfacher Algorithmus statt KI** (`packing.pack`): größte Einlage zuerst, Platz mit dem
   meisten Kontakt zu Wand/Nachbarn, Rest wird gemeldet und bleibt draußen. Austauschbar: Funktion `pack`
   mit derselben Signatur ersetzen (z. B. Suche über mehrere Reihenfolgen).
4. **Projekt löschen löscht keine Einlagen/Werkzeuge**; sie bleiben ohne Projekt in der Bibliothek.
5. **Farben je Teil** (`InsertSpec.color_hex`). Filament-Slots folgen den Farben (gleiche Farbe = gleicher
   Slot, `storage.slots_from_colors`). Wer Slots wieder von Hand wählen will: diese Funktion beim
   Speichern weglassen und die Slot-Auswahl im Designer zurückholen.
6. **3D-Klon im Browser aus dem Layout** (keine CAD-Rechnung): Einlagen als Körper mit Taschenböden je
   Zone, Werkzeuge als Kontur zwischen Unter- und Oberseite aus dem Seitenprofil, Foto der Draufsicht als
   Farbe. "Low-Poly" nimmt jeden n-ten Konturpunkt, "Detailliert" alle.
7. **Standardhöhe**: neue Projekte übernehmen die Standardhöhe (von Hand festgelegt oder Höhe der zuletzt
   angelegten Spitzzangen-Einlage) als Gesamthöhe der Vorlage; damit sind alle Einlagen gleich hoch.
8. **Scan im Projekt**: Werkzeug scannen legt das Objekt im Projekt an; "Einlage nach Projektvorlage"
   erzeugt die Einlage und ordnet sie gleich ein.
