import { describe, expect, it } from 'vitest'
import { isChunkLoadError, reloadOnceForStaleChunks } from './chunkError'

describe('Nachgeladene Programmteile (3D-Vorschau: "Failed to fetch dynamically imported module")', () => {
  it('erkennt die Fehlermeldungen der Browser', () => {
    expect(isChunkLoadError(new TypeError('Failed to fetch dynamically imported module: https://x/assets/Preview3D-mt95_EUc.js'))).toBe(true)
    expect(isChunkLoadError(new TypeError('Importing a module script failed.'))).toBe(true)              // Safari
    expect(isChunkLoadError(new TypeError('error loading dynamically imported module'))).toBe(true)      // Firefox
    expect(isChunkLoadError(new Error('HTTP 403'))).toBe(false)
  })

  it('lädt nach einem Deploy einmal neu, aber nicht in einer Schleife', () => {
    const mem = new Map<string, string>()
    const store = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) }
    let reloads = 0
    const reload = () => { reloads++ }
    expect(reloadOnceForStaleChunks(1_000_000, store, reload)).toBe(true)
    expect(reloadOnceForStaleChunks(1_010_000, store, reload)).toBe(false)     // 10 s später: kein zweites Mal
    expect(reloadOnceForStaleChunks(1_100_000, store, reload)).toBe(true)      // später wieder erlaubt
    expect(reloads).toBe(2)
  })

  it('ohne Speicher (privater Modus) kein automatisches Neuladen', () => {
    const store = { getItem: () => { throw new Error('blocked') }, setItem: () => {} }
    expect(reloadOnceForStaleChunks(0, store, () => { throw new Error('darf nicht') })).toBe(false)
  })
})
