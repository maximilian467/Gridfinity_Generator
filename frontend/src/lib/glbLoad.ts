/** 3D-Modell (GLB) robust laden.
 *
 * Manche Netze (Firmen-Proxy, Virenscanner, Filter) blockieren 3D-Dateien oder liefern statt der Datei
 * eine Hinweisseite. Dann bliebe die 3D-Ansicht einfach leer. Deshalb: Datei selbst holen und am
 * Dateianfang ("glTF") prüfen; klappt das nicht, denselben Inhalt als JSON (base64) nachladen.
 * Ergebnis ist eine blob:-URL für den GLTF-Loader. */

export function isGlb(buf: ArrayBuffer): boolean {
  const b = new Uint8Array(buf, 0, Math.min(4, buf.byteLength))
  return b.length === 4 && b[0] === 0x67 && b[1] === 0x6c && b[2] === 0x54 && b[3] === 0x46     // "glTF"
}

export function b64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const bin = atob(b64)
  const out = new Uint8Array(new ArrayBuffer(bin.length))
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

type Fetch = (url: string) => Promise<Response>

/** Rückgabe: Bytes des Modells und der Weg, auf dem es kam (für die Fehlersuche). */
export async function fetchGlb(url: string, f: Fetch = (u) => fetch(u, { credentials: 'same-origin' })):
  Promise<{ bytes: ArrayBuffer; via: 'direct' | 'json' }> {
  let reason = ''
  try {
    const r = await f(url)
    if (r.ok) {
      const buf = await r.arrayBuffer()
      if (isGlb(buf)) return { bytes: buf, via: 'direct' }
      reason = 'Antwort war keine 3D-Datei (evtl. Filter/Proxy)'
    } else reason = `HTTP ${r.status}`
  } catch (e) {
    reason = e instanceof Error ? e.message : String(e)
  }
  try {
    const r = await f(url + (url.includes('?') ? '&' : '?') + 'format=b64')
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    const bytes = b64ToBytes((await r.json()).b64)
    if (!isGlb(bytes.buffer)) throw new Error('Inhalt ist keine 3D-Datei')
    return { bytes: bytes.buffer, via: 'json' }
  } catch (e) {
    throw new Error(`3D-Modell konnte nicht geladen werden (direkt: ${reason}; Ersatzweg: ${e instanceof Error ? e.message : e})`)
  }
}

/** Kann der Browser WebGL? (sonst gibt es keine 3D-Ansicht) */
export function webglAvailable(): boolean {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}
