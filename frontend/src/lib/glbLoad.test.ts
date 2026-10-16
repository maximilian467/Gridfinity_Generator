import { describe, expect, it } from 'vitest'
import { fetchGlb, isGlb } from './glbLoad'

const GLB = new Uint8Array([0x67, 0x6c, 0x54, 0x46, 2, 0, 0, 0, 1, 2, 3, 4])
const b64 = (u: Uint8Array) => btoa(String.fromCharCode(...u))
const ok = (body: BodyInit, type = 'model/gltf-binary') => new Response(body, { status: 200, headers: { 'content-type': type } })

describe('3D-Modell laden (Vorschau leer hinter Proxy/Filter)', () => {
  it('erkennt GLB am Dateianfang', () => {
    expect(isGlb(GLB.buffer)).toBe(true)
    expect(isGlb(new TextEncoder().encode('<html>Blocked</html>').buffer)).toBe(false)
  })

  it('direkter Weg, wenn die Datei ankommt', async () => {
    const r = await fetchGlb('/x.glb', async () => ok(GLB))
    expect(r.via).toBe('direct')
    expect(new Uint8Array(r.bytes)).toEqual(GLB)
  })

  it('Proxy liefert eine Hinweisseite statt der Datei: Ersatzweg über JSON', async () => {
    const seen: string[] = []
    const r = await fetchGlb('/x.glb', async (u) => {
      seen.push(u)
      return u.endsWith('format=b64') ? ok(JSON.stringify({ b64: b64(GLB) }), 'application/json') : ok('<html>Zugriff blockiert</html>', 'text/html')
    })
    expect(seen).toEqual(['/x.glb', '/x.glb?format=b64'])
    expect(r.via).toBe('json')
    expect(new Uint8Array(r.bytes)).toEqual(GLB)
  })

  it('Netzwerkfehler (Anfrage blockiert): Ersatzweg über JSON', async () => {
    const r = await fetchGlb('/x.glb', async (u) => {
      if (!u.includes('format=b64')) throw new TypeError('Failed to fetch')
      return ok(JSON.stringify({ b64: b64(GLB) }), 'application/json')
    })
    expect(r.via).toBe('json')
  })

  it('beide Wege scheitern: verständliche Fehlermeldung statt leerer Ansicht', async () => {
    await expect(fetchGlb('/x.glb', async () => new Response('', { status: 403 }))).rejects.toThrow(/3D-Modell konnte nicht geladen werden.*HTTP 403/)
  })
})
