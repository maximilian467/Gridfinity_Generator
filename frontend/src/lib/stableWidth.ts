import { useCallback, useEffect, useRef, useState } from 'react'

/** Gemessene Breiten mit Zeitpunkt (ms) */
export type WidthHistory = { w: number; t: number }[]

const FLIP_MS = 600       // so schnell hin und her = Rückkopplung, kein echtes Ändern der Fenstergröße
const FLIP_PX = 40        // eine Scrollleiste ist schmaler

/**
 * Nächste Breite für eine Zeichenfläche, deren Höhe von der Breite abhängt.
 *
 * Rückkopplung: Fläche wird höher -> Seite bekommt eine Scrollleiste -> Breite schrumpft -> Fläche wird
 * flacher -> Scrollleiste verschwindet -> Breite wächst ... Das Bild zittert. Springt die Breite schnell
 * zwischen zwei nahen Werten hin und her (A, B, A), bleibt die kleinere: dann passt die Fläche auch mit
 * Scrollleiste und nichts schaltet mehr um. Echte Größenänderungen (langsam oder groß) gehen durch.
 */
export function settleWidth(hist: WidthHistory, measured: number, now: number): { width: number; hist: WidthHistory } {
  const w = Math.round(measured)
  const h = [...hist.filter((e) => now - e.t <= FLIP_MS), { w, t: now }].slice(-6)
  const seen = [...new Set(h.map((e) => e.w))]
  const flipping = h.length >= 3 && seen.length === 2 && Math.abs(seen[0] - seen[1]) <= FLIP_PX
    && h.slice(-3).some((e, i, a) => i > 0 && e.w !== a[i - 1].w)
  return { width: flipping ? Math.min(...seen) : w, hist: h }
}

/** Breite eines Elements (ResizeObserver) ohne Zittern durch die Scrollleiste.
 *  Rückgabe [ref, Breite]: ref ans Element hängen. Als Callback-Ref, damit auch ein Element, das erst
 *  nach dem ersten Rendern erscheint, beobachtet wird (sonst bliebe die Startbreite stehen). */
export function useStableWidth<T extends HTMLElement>(initial: number, max = Infinity): [(el: T | null) => void, number] {
  const [width, setWidth] = useState(initial)
  const [el, setEl] = useState<T | null>(null)
  const hist = useRef<WidthHistory>([])
  const ref = useCallback((node: T | null) => setEl(node), [])
  useEffect(() => {
    if (!el) return
    const ro = new ResizeObserver(() => {
      const r = settleWidth(hist.current, Math.min(max, el.clientWidth), performance.now())
      hist.current = r.hist
      setWidth((cur) => (cur === r.width ? cur : r.width))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [el, max])
  return [ref, width]
}
