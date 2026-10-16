import { describe, expect, it } from 'vitest'
import { fetchGlb, isGlb } from './glbLoad'

const GLB = new Uint8Array([0x67, 0x6c, 0x54, 0x46, 2, 0, 0, 0, 1, 2, 3, 4])
const ok = (body: BodyInit, type = 'model/gltf-binary') => new Response(body, { status: 200, headers: { 'content-type': type } })

describe('3D-Modell laden: klare Meldung statt leerer Ansicht', () => {
  it('erkennt GLB am Dateianfang', () => {
    expect(isGlb(GLB.buffer)).toBe(true)
    expect(isGlb(new TextEncoder().encode('<html>Blocked</html>').buffer)).toBe(false)
  })

  it('liefert das Modell, wenn die Datei ankommt', async () => {
    expect(new Uint8Array(await fetchGlb('/x.glb', async () => ok(GLB)))).toEqual(GLB)
  })

  it('Hinweisseite statt Datei (Netzfilter): verständliche Meldung', async () => {
    await expect(fetchGlb('/x.glb', async () => ok('<html>Zugriff blockiert</html>', 'text/html'))).rejects.toThrow(/Statt des 3D-Modells/)
  })

  it('Anfrage kommt nicht durch: verständliche Meldung', async () => {
    await expect(fetchGlb('/x.glb', async () => { throw new TypeError('Failed to fetch') })).rejects.toThrow(/kam nicht an.*Failed to fetch/)
  })

  it('Serverfehler: Status in der Meldung', async () => {
    await expect(fetchGlb('/x.glb', async () => new Response('', { status: 403 }))).rejects.toThrow(/HTTP 403/)
  })
})
