# Betrieb auf dem Mini-PC

| | |
|---|---|
| Server | `ubuntu@100.91.112.44` (Tailscale, Hostname `buntu-1`) |
| Code | `~/apps/gridfinity` (Git-Repo, Push von Windows über das Remote `minipc`) |
| Container | `gridfinity`, lauscht nur auf `127.0.0.1:8090` |
| Öffentlich | Tailscale Funnel, `https://buntu-1.tail8569e8.ts.net` (Port 443, HTTPS, kostenlos) |
| Daten | `~/apps/gridfinity/data` (Scans, Einlagen, Exporte, SAM-Gewichte, `.secret`) |
| Login | `.env` auf dem Server (`APP_USER`, `APP_PASSWORD`) |

Die Home-Cloud auf demselben Rechner (`tailscale serve` auf Port 80, nur im Tailnet) bleibt davon unberührt.

## Aktualisieren

Auf Windows im Projektordner:

```powershell
git push minipc HEAD:main
ssh ubuntu@100.91.112.44 "cd ~/apps/gridfinity && docker compose up -d --build"
```

## Nützliche Befehle (auf dem Server)

```bash
cd ~/apps/gridfinity
docker compose logs -f gridfinity      # Logs
docker compose restart gridfinity      # Neustart
sudo tailscale funnel status           # was ist öffentlich?
sudo tailscale funnel --https=443 off  # öffentlichen Zugang abschalten
```

## Zugangsdaten ändern

`~/apps/gridfinity/.env` bearbeiten, dann `docker compose up -d`. Bestehende Sitzungen bleiben gültig,
bis `data/.secret` gelöscht wird (dann müssen sich alle neu anmelden).

## Sicherheit

- Login mit signiertem, HttpOnly-Session-Cookie (SameSite=Strict, Secure), max. 10 Fehlversuche je IP in 10 Minuten.
- **Das Passwort `admin` ist absichtlich schwach** (Wunsch des Nutzers). Die Seite ist öffentlich erreichbar;
  für mehr Schutz in `.env` ein starkes Passwort setzen oder den Funnel abschalten (dann nur im Tailnet).
- IDs werden geprüft (kein Pfad-Traversal), aus `data/` werden nur Bilder/Exporte ausgeliefert,
  Uploads sind auf Bildtypen und 40 MB begrenzt, alle Parameter haben Wertebereiche, Sicherheits-Header gesetzt,
  API-Doku in Produktion aus. Tests: `backend/tests/test_security.py`.
- Abhängigkeiten geprüft mit `npm audit` und `pip-audit` (keine bekannten Lücken, Stand 08.10.2026).
