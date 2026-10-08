# Gridfinity-Einlagen-Generator

Aus zwei Fotos eines Werkzeugs (Draufsicht + Seitenansicht, jeweils auf A4) wird eine Gridfinity-Einlage erzeugt:
Tasche mit Spiel, gestufter Boden, Greifmulden, Fächer, Farbteile. Export als 3MF (Bambu Studio / OrcaSlicer), STL, STEP, Passform-Test. Dazu ein Baseplate-Generator.

## Starten
```powershell
scripts/start.ps1                      # baut das Frontend, alles auf http://localhost:8000
scripts/dev.ps1 -ApiPort 8010 -WebPort 5180   # Entwicklung mit Hot-Reload (Ports anpassen, falls belegt)
```
Tests: `cd backend; uv run pytest`

## Ablauf
1. Bibliothek: "Objekt scannen" (oder "Demo-Zange anlegen" zum Ausprobieren ohne Fotos).
2. Wizard: Draufsicht hochladen, Blattecken prüfen, Maske prüfen; dasselbe mit dem Seitenfoto; Profil prüfen.
3. Einlage anlegen, Objekt platzieren, Greifmulden/Fächer ergänzen, "3D erzeugen und exportieren".
4. Zuerst den Passform-Test drucken und das Spiel anpassen.

Plan und Konventionen: `docs/PLAN.md`, `CLAUDE.md`. Synthetische Testfotos: `scripts/make_synthetic_photos.py`.
