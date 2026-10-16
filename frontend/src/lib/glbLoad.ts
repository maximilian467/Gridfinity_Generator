/** 3D-Modell (GLB) laden und prüfen.
 *
 * Kommt statt der Datei etwas anderes an (z. B. eine Hinweisseite eines Netzfilters) oder gar nichts,
 * soll die 3D-Ansicht nicht einfach leer bleiben, sondern sagen, woran es liegt. */

export function isGlb(buf: ArrayBuffer): boolean {
  const b = new Uint8Array(buf, 0, Math.min(4, buf.byteLength))
  return b.length === 4 && b[0] === 0x67 && b[1] === 0x6c && b[2] === 0x54 && b[3] === 0x46     // "glTF"
}

type Fetch = (url: string) => Promise<Response>

export async function fetchGlb(url: string, f: Fetch = (u) => fetch(u, { credentials: 'same-origin' })): Promise<ArrayBuffer> {
  let r: Response
  try {
    r = await f(url)
  } catch (e) {
    throw new Error(`3D-Modell kam nicht an (${e instanceof Error ? e.message : e}). Hält evtl. ein Proxy oder Virenscanner im Netz die Datei zurück?`)
  }
  if (!r.ok) throw new Error(`3D-Modell konnte nicht geladen werden (HTTP ${r.status}).`)
  const buf = await r.arrayBuffer()
  if (!isGlb(buf)) {
    throw new Error('Statt des 3D-Modells kam etwas anderes an (z. B. eine Hinweisseite eines Netzfilters). '
      + 'In einem anderen Netz probieren oder die IT um Freigabe bitten.')
  }
  return buf
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
