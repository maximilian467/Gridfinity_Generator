# Gridfinity-Einlagen-Generator

Aus zwei Fotos eines Werkzeugs (Draufsicht + Seitenansicht, jeweils auf A4) wird eine Gridfinity-Einlage erzeugt:
Tasche mit Spiel, gestufter Boden, Greifmulden, Fächer, Farbteile. Export als 3MF (Bambu Studio / OrcaSlicer), STL, STEP, Passform-Test. Dazu ein Baseplate-Generator.

## Starten
```powershell
scripts/start.ps1                      # baut das Frontend, alles auf einem freien Port (ab 8003, wird ausgegeben)
scripts/dev.ps1                        # Entwicklung mit Hot-Reload, freie Ports automatisch (oder -ApiPort/-WebPort)
```
SAM-Segmentierung (optional, bessere Masken): `scripts/download_models.ps1` lädt die Gewichte (160 MB) nach `data/models/`; ohne sie läuft die klassische Segmentierung.
Tests: `cd backend; uv run pytest`

## Ablauf
1. Bibliothek: "Objekt scannen" (oder "Demo-Zange anlegen" zum Ausprobieren ohne Fotos).
2. Wizard: Draufsicht hochladen, Blattecken prüfen, Maske prüfen; dasselbe mit dem Seitenfoto; Profil prüfen.
3. Einlage anlegen, Objekt platzieren, Greifmulden/Fächer ergänzen, "3D erzeugen und exportieren".
4. Zuerst den Passform-Test drucken und das Spiel anpassen.

Plan und Konventionen: `docs/PLAN.md`, `CLAUDE.md`. Synthetische Testfotos: `scripts/make_synthetic_photos.py`.

## Betrieb auf dem Mini-PC
Docker-Container auf `buntu-1` (Tailscale), öffentlich per Tailscale Funnel. Login: `admin@admin.com` / `admin` (in `.env` änderbar). Details und Update-Befehle: `docs/DEPLOYMENT.md`.
