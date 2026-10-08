# Gridfinity-Einlagen-Generator

Verbindlicher Plan: `docs/PLAN.md`. Phase für Phase arbeiten; nach jeder Phase `uv run pytest` grün + Commit.

## Konventionen (verbindlich)
- Intern immer mm. Winkel intern Radiant, Grad nur im UI.
- Papier: Ursprung links oben, x rechts, y unten, A4 = 297×210 mm.
- Entzerrtes Bild: 10 px/mm + 40 mm Rand (3770×2900 px); mm = px/10 − 40.
- Objekt-lokal: Längsachse +x (PCA), `y_cad = −y_img`, KEINE Spiegelung.
- Einlage/CAD: Ursprung linke untere Außenecke, z=0 Unterkante Füße.
- Geometrie immer nachmessen (BBox, Querschnitte, Körper, wasserdicht).
- UI-Sprache Deutsch; Frontend-Stil: Skill `design-taste-frontend` (nur Anti-Default/Typo/Farbe).

## Befehle
- Backend-Tests: `cd backend; uv run pytest`
- Dev: `scripts/dev.ps1` (wählt freie Ports ab 8003/5183 selbst; Proxy /api)
- Frontend-Build: `cd frontend; npm run build` (FastAPI liefert `frontend/dist` aus)
