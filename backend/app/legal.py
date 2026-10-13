"""Öffentliche Datenschutzerklärung (/datenschutz), ohne Login erreichbar.

Google verlangt sie, um den OAuth-Zustimmungsbildschirm zu veröffentlichen. Name und Kontakt des
Verantwortlichen kommen aus der Umgebung (CONTACT_NAME, CONTACT_EMAIL, optional CONTACT_ADDRESS),
damit keine persönlichen Daten im Code stehen.
"""
from __future__ import annotations

import os
from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from . import auth

router = APIRouter(include_in_schema=False)

STYLE = """
:root { --paper:#e8ebe8; --surface:#fbfbf9; --ink:#1b1f23; --ink-2:#444b52; --line:#d3d7d3; --accent:#d4430b; }
@media (prefers-color-scheme: dark) {
  :root { --paper:#121518; --surface:#1a1e22; --ink:#eceeea; --ink-2:#bcc2bf; --line:#2d343a; --accent:#ff7a3d; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.6 system-ui, sans-serif; }
main { max-width:720px; margin:0 auto; padding:32px 16px 64px; }
article { background:var(--surface); border:1px solid var(--line); border-radius:4px; padding:24px; }
h1 { font-size:1.5rem; margin:0 0 4px; letter-spacing:-0.01em; }
h2 { font-size:1.05rem; margin:28px 0 6px; }
p, li { color:var(--ink-2); max-width:65ch; }
ul { padding-left:20px; }
a { color:var(--accent); }
.stand { font-size:.875rem; color:var(--ink-2); margin:0 0 20px; }
.back { display:inline-block; margin-bottom:16px; }
"""


def _contact() -> str:
    name = escape(os.environ.get("CONTACT_NAME", "").strip() or "der Betreiber dieser Seite")
    email = escape(os.environ.get("CONTACT_EMAIL", "").strip())
    address = escape(os.environ.get("CONTACT_ADDRESS", "").strip())
    parts = [name] + ([address] if address else []) + ([f'E-Mail: <a href="mailto:{email}">{email}</a>'] if email else [])
    return "<br>".join(parts)


@router.get("/datenschutz", response_class=HTMLResponse)
def privacy() -> HTMLResponse:
    body = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Datenschutz | Gridfinity Einlagen</title><style>{STYLE}</style></head>
<body><main>
<a class="back" href="/">Zur App</a>
<article>
<h1>Datenschutzerklärung</h1>
<p class="stand">Gridfinity Einlagen, Stand: Oktober 2026</p>

<h2>Verantwortlich</h2>
<p>{_contact()}</p>

<h2>Worum es geht</h2>
<p>Gridfinity Einlagen ist ein privat betriebenes, nicht kommerzielles Werkzeug, um aus Fotos von Werkzeugen
passende Einlagen für den 3D-Druck zu erzeugen. Es gibt keine Werbung, kein Tracking und keine Analysedienste.</p>

<h2>Anmeldung mit Google</h2>
<p>Zur Anmeldung nutzt die App „Mit Google anmelden“ (Google Ireland Limited, Gordon House, Barrow Street,
Dublin 4, Irland). Dabei erhalten wir von Google nur deine Google-Kennung, deinen Namen und deine bestätigte
E-Mail-Adresse. Andere Daten aus deinem Google-Konto werden nicht abgefragt. Für die Anmeldung gelten zusätzlich
die <a href="https://policies.google.com/privacy" rel="noopener">Datenschutzhinweise von Google</a>.</p>
<p>Neue Konten werden erst nach Freischaltung durch einen Administrator nutzbar. Nicht freigeschaltete Konten
werden nach 30 Tagen automatisch gelöscht.</p>

<h2>Welche Daten gespeichert werden</h2>
<ul>
<li><b>Konto:</b> Google-Kennung, Name, E-Mail-Adresse, Rolle, Status, Zeitpunkte von Anlage, Freischaltung und letzter Anmeldung.</li>
<li><b>Sitzung:</b> ein Cookie mit einer zufälligen Sitzungskennung (30 Tage gültig), dazu IP-Adresse und Browserkennung der Sitzung.
Für die Google-Anmeldung wird kurzzeitig (10 Minuten) ein weiteres technisches Cookie gesetzt. Es gibt nur technisch notwendige Cookies.</li>
<li><b>Deine Inhalte:</b> hochgeladene Fotos, daraus berechnete Umrisse und Profile, Einlagen und erzeugte Druckdateien.
Sie sind nur für dich und die Administratoren sichtbar.</li>
<li><b>Protokoll:</b> Anmeldungen und Änderungen an Konten (Zeitpunkt, Aktion, IP-Adresse), um Missbrauch erkennen zu können.</li>
</ul>

<h2>Zweck und Rechtsgrundlage</h2>
<p>Die Daten werden nur verarbeitet, um dir die App bereitzustellen (Art. 6 Abs. 1 lit. b DSGVO) und um sie vor
Missbrauch zu schützen, etwa durch die Begrenzung von Anmeldeversuchen und das Protokoll (Art. 6 Abs. 1 lit. f DSGVO).</p>

<h2>Speicherort und Weitergabe</h2>
<p>Die App läuft auf einem eigenen Rechner des Betreibers in Deutschland. Die Verbindung aus dem Internet wird über
Tailscale (Tailscale Inc., Kanada) verschlüsselt an diesen Rechner weitergeleitet. Darüber hinaus werden keine Daten
an Dritte weitergegeben.</p>

<h2>Speicherdauer</h2>
<p>Konto und Inhalte bleiben gespeichert, bis du die Löschung verlangst oder ein Administrator das Konto löscht.
Dabei werden auch alle deine Inhalte gelöscht. Sitzungen enden spätestens nach 30 Tagen ohne Nutzung.</p>

<h2>Quellcode</h2>
<p>Die App ist Open Source (AGPL-3.0). Den Quellcode findest du unter
<a href="{escape(auth.source_url())}" rel="noopener">{escape(auth.source_url())}</a>.</p>

<h2>Deine Rechte</h2>
<p>Du hast das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit und
Widerspruch. Wende dich dazu an die oben genannte Kontaktadresse. Außerdem kannst du dich bei einer
Datenschutz-Aufsichtsbehörde beschweren.</p>
</article>
</main></body></html>"""
    return HTMLResponse(body)
