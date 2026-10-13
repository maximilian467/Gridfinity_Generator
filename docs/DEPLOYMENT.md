# Betrieb auf dem Mini-PC

| | |
|---|---|
| Server | `ubuntu@100.91.112.44` (Tailscale, Hostname `buntu-1`) |
| Code | `~/apps/gridfinity` (Git-Repo, Push von Windows über das Remote `minipc`) |
| Container | `gridfinity`, lauscht nur auf `127.0.0.1:8090` |
| Öffentlich | Tailscale Funnel, `https://buntu-1.tail8569e8.ts.net` (Port 443, HTTPS, kostenlos) |
| Daten | `~/apps/gridfinity/data` (Datenbank `app.db`, Scans, Einlagen, Exporte, SAM-Gewichte, `.secret`) |
| Login | Google-Konto (Freischaltung durch Admin) oder Notfall-Admin aus `.env` |

Die Home-Cloud auf demselben Rechner (`tailscale serve` auf Port 80, nur im Tailnet) bleibt davon unberührt.

## Aktualisieren

Auf Windows im Projektordner:

```powershell
git push minipc HEAD:main
ssh ubuntu@100.91.112.44 "cd ~/apps/gridfinity && docker compose up -d --build"
```

Die Datenbank wird beim Start automatisch angelegt bzw. migriert (Alembic).

## Anmeldung

- **Google:** Wer sich zum ersten Mal anmeldet, bekommt ein Konto im Status „wartet“. Ein Admin schaltet es unter
  **Nutzer** frei (dort auch sperren, Admin-Rechte, löschen, Protokoll). Höchstens 50 Konten warten gleichzeitig,
  nicht freigeschaltete verfallen nach 30 Tagen.
- **Admins:** Adressen aus `ADMIN_EMAILS` sind beim Google-Login sofort aktive Admins. Admins sehen die Daten aller
  Nutzer (in der Bibliothek „Daten aller Nutzer zeigen“). Altdaten aus der Zeit vor den Konten sehen nur Admins.
- **Notfall-Admin:** `APP_USER` / `APP_PASSWORD` unter „Admin-Zugang mit Passwort“. In Produktion nur aktiv, wenn
  das Passwort mindestens 16 Zeichen hat; `LOCAL_LOGIN=0` schaltet ihn ab.

### Google einrichten (einmalig)

1. <https://console.cloud.google.com> → neues Projekt (z. B. „Gridfinity“).
2. **APIs & Dienste → OAuth-Zustimmungsbildschirm**: Typ „Extern“, App-Name, Support-Adresse.
   Bereiche nur `openid`, `email`, `profile`. Danach **„App veröffentlichen“** (Status „In Produktion“).
   Im Testmodus kommen nur eingetragene Testnutzer rein. Für diese Basis-Bereiche prüft Google nichts.
3. **APIs & Dienste → Anmeldedaten → OAuth-Client-ID erstellen**, Typ „Webanwendung“.
   Autorisierte Weiterleitungs-URIs:
   - `https://buntu-1.tail8569e8.ts.net/api/auth/google/callback`
   - für die Entwicklung `http://localhost:5183/api/auth/google/callback` (Vite-Port aus `scripts/dev.ps1`)
4. Client-ID und Secret auf dem Server in `~/apps/gridfinity/.env` eintragen (Vorlage `.env.example`), dazu
   `PUBLIC_BASE_URL`, `ADMIN_EMAILS` und ein langes `APP_PASSWORD`. Dann `docker compose up -d`.

## Nützliche Befehle (auf dem Server)

```bash
cd ~/apps/gridfinity
docker compose logs -f gridfinity      # Logs
docker compose restart gridfinity      # Neustart
sudo tailscale funnel status           # was ist öffentlich?
sudo tailscale funnel --https=443 off  # öffentlichen Zugang abschalten
```

## Sicherung

Alles Wichtige liegt in `data/`. Die Datenbank im laufenden Betrieb konsistent sichern:

```bash
sqlite3 data/app.db ".backup data/app-backup.db"
```

## Sicherheit

- Sitzungen liegen in der Datenbank (nur der SHA-256 des Tokens), Cookie HttpOnly, Secure, SameSite=Lax, 30 Tage
  gleitend. Abmelden, „Auf allen Geräten abmelden“ und Sperren wirken sofort. Ändernde Anfragen von fremden Seiten
  lehnt der Server ab (Origin-Prüfung).
- Google-Login über OpenID Connect mit state, nonce und PKCE; Konten werden an Googles `sub` erkannt, nur
  bestätigte E-Mail-Adressen.
- Jeder sieht nur eigene Objekte, Einlagen, Dateien und Berechnungen; fremde IDs liefern 404
  (Test: `backend/tests/test_ownership.py`). Je Nutzer höchstens 300 Objekte bzw. Einlagen und eine laufende Berechnung.
- Passwort-Login: max. 10 Fehlversuche je IP in 10 Minuten.
- IDs werden geprüft (kein Pfad-Traversal), aus `data/` werden nur Bilder/Exporte ausgeliefert,
  Uploads sind auf Bildtypen und 40 MB begrenzt, alle Parameter haben Wertebereiche, Sicherheits-Header gesetzt,
  API-Doku in Produktion aus. Tests: `backend/tests/test_security.py`.
- Abhängigkeiten geprüft mit `npm audit` und `pip-audit` (keine bekannten Lücken, Stand 13.10.2026).
