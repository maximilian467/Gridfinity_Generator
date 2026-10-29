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
| Stapel-Scan (Oberfläche, EXIF-Sortierung, Paare) | `frontend/src/features/project/BatchScan.tsx` |
| Stapel-Scan (Job, Auswertung ohne HTTP) | `backend/app/build_tasks.py` (`batch_scan_job`), `backend/app/scan.py` |
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
9. **Stapel-Scan** ("Viele auf einmal"): Die Fotos werden im Browser nach EXIF-Aufnahmezeit (sonst Dateidatum,
   dann Name) sortiert und paarweise als Draufsicht + Seitenansicht zugeordnet; jedes Paar wird einzeln hochgeladen
   (`POST /projects/{id}/scan-pair`, legt das Werkzeug an), dann wertet `POST /projects/{id}/batch-scan` alles in
   einem Hintergrund-Job aus (A4-Blatt, Freistellen, Hand weg, Profil) und ruft danach `generate` auf. Fortschritt
   je Werkzeug schreibt der Worker über `jobs.report` (`progress.json`). Ein Fehler betrifft nur sein Werkzeug;
   der nicht geschaffte Schritt bleibt im Scan-Assistenten offen. Auto-Tausch vertauschter Ansichten gibt es nicht,
   nur eine Warnung ("dicker als breit").
10. **Blindstopfen** (`InsertSpec.blank`, `POST /inserts/plug`): Einlage ohne Taschen und Fächer, die freie Felder
    der Baseplate verschließt. Höhe ab `PLUG_MIN_H` = 5,5 mm (Fuß bis 5,0 mm + 0,5 mm Deckplatte; flacher zerfällt
    ein mehrfeldriger Stopfen in Einzelfüße). Unter 1 U gibt es keinen Stapelrand. Höhe und Stapelrand bestimmt der
    Stopfen immer selbst (`BLANK_OWN_FIELDS`, wirkt in `apply_template`), alles andere (Farben, Magnete) kommt aus
    der Vorlage. Stopfen zählen nicht zur Prüfung "Einlagen unterschiedlich hoch".
11. **Schrift** (`InsertSpec.texts`, `geometry/text.py`): Umriss aus DejaVu Sans (liegt matplotlib bei, also
    überall dieselbe Schrift) als shapely-Fläche; dieselbe Fläche zeigt der 2D-Editor und schneidet bzw. ergänzt das
    CAD. Stile: erhaben (Prisma auf der Oberfläche), bündig (oberste Schichten in Schriftfarbe), vertieft (Tasche,
    Boden in Schriftfarbe). Die Schrift wird auf die freie Oberfläche zugeschnitten (1,2 mm Abstand zu Taschen,
    Mulden, Fächern, Rand). Jede Schriftfarbe ist ein eigener Farbteil; Slots folgen `schemas.color_palette` und
    werden beim Export lückenlos durchnummeriert.
12. **Gemeinsame Projekte** (Tabelle `project_members`, Migration 0002; Regeln in `storage.py`): Der Besitzer
    fügt Nutzer per E-Mail als Mitglieder hinzu (Konto muss existieren, gesperrte gelten als nicht vorhanden,
    Fehlversuche begrenzt). Beteiligte (Besitzer und Mitglieder) sehen und bearbeiten alles mit `project_id` des
    Projekts, dazu die Werkzeuge in dessen Einlagen, sofern ihr Besitzer beteiligt ist (Bibliotheks-Werkzeuge
    eines Mitglieds). Neu in eine Einlage legen darf man nur eigene Werkzeuge oder solche desselben Projekts;
    in ein (anderes) Projekt verschieben nur der Besitzer des Eintrags. So kann niemand, was er über ein Projekt
    sieht, in ein anderes oder in seine Bibliothek weiterreichen. Nur der Projektbesitzer (und Admins) verwaltet
    Mitglieder und archiviert; löschen darf, wer den Eintrag angelegt hat oder wem das Projekt gehört.
    Entfernte oder austretende Mitglieder: ihre Einträge im Projekt gehen an den Besitzer über, ihre Bibliothek
    bleibt privat. Gelöschter Besitzer: das Projekt geht an das älteste Mitglied (ohne Mitglieder wird es
    gelöscht). Listen: `?shared=true` liefert zusätzlich die Projektsachen; ohne bleibt die Bibliothek privat.
13. **Schränke** (`ProjectSpec.kind = "cabinet"`, Schublade: `cabinet_id`; Regeln in `storage.participants`): Ein Schrank
    fasst Schubladen zusammen. Wer am Schrank beteiligt ist (Besitzer oder Mitglied), ist an allen seinen Schubladen
    beteiligt; der Schrankbesitzer verwaltet sie mit (`storage.project_owners`: Mitglieder, Archiv, Löschen).
    Schubladen behalten eigene Mitglieder. Zuordnen (`POST /projects/{id}/cabinet`) darf nur, wer die Schublade
    verwaltet, und nur in eigene Schränke (sonst bekämen fremde Schrank-Mitglieder ungefragt Zugriff). Einlagen und
    Werkzeuge liegen nie direkt im Schrank. Admins ordnen Nutzer in der Nutzerverwaltung Schränken wie Schubladen zu.
    UI: `CabinetPage.tsx`, Projektliste gruppiert nach Schrank.
14. **Mehrere Werkzeuge je Einlage**: "Werkzeug scannen" im Designer legt ein neues Werkzeug (im Projekt der Einlage)
    an und öffnet den Scan mit `?insert=<id>`; am Ende legt "In die Einlage legen" es neben die vorhandenen
    (`placeNew`), Lage und Drehung stellt man danach im Designer ein.
15. **Fachbeschriftung und Vordach** (`Compartment.label`, `CompLabel`; `layout._comp_labels`, `insert_cad.shelf_solid`):
    Schrift erhaben mittig auf dem Fachboden oder auf einem Vordach an einer Wand (Standard hinten). Das Vordach ist
    oben eben, vorn `SHELF_T` = 1,6 mm stark und darunter 45° zur Wand abgeschrägt (druckt ohne Stützen); seine
    Oberkante liegt um die Schrifthöhe unter der Oberfläche, so bleibt die Einlage stapelbar. Ohne Größe passt sich die
    Schrift an (Breite bzw. 60 % der Vordachtiefe). Schrift-Farbteile werden vor den Fächern zugeteilt, sonst nähme
    die Fächerhaut sie mit. Fächer-Einlage anlegen: `labels` (Lesereihenfolge hinten links zuerst) und `shelf`.
