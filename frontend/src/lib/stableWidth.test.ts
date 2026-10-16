import { describe, expect, it } from 'vitest'
import { settleWidth, type WidthHistory } from './stableWidth'

/** Folge gemessener Breiten durchspielen, Rückgabe: tatsächlich verwendete Breiten */
function run(seq: [number, number][]): number[] {
  let hist: WidthHistory = []
  return seq.map(([w, t]) => {
    const r = settleWidth(hist, w, t)
    hist = r.hist
    return r.width
  })
}

describe('settleWidth (Zittern im Bearbeitungsfenster)', () => {
  it('Scrollleisten-Rückkopplung: schnelles Hin und Her endet auf der kleineren Breite und bleibt dort', () => {
    // 730 ohne Scrollleiste, 715 mit: wechselt alle paar ms
    const out = run([[730, 0], [715, 16], [730, 32], [715, 48], [730, 64], [715, 80], [730, 96]])
    expect(out.slice(2)).toEqual([715, 715, 715, 715, 715])
  })

  it('echtes Vergrößern/Verkleinern des Fensters geht durch', () => {
    expect(run([[800, 0], [760, 50], [700, 100], [650, 150]])).toEqual([800, 760, 700, 650])
  })

  it('langsame Wechsel (Nutzer ändert die Fenstergröße zurück) gelten nicht als Zittern', () => {
    expect(run([[730, 0], [715, 1000], [730, 2000]])).toEqual([730, 715, 730])
  })

  it('große Sprünge (z. B. Seitenleiste zu) gelten nicht als Zittern', () => {
    expect(run([[730, 0], [1030, 16], [730, 32]])).toEqual([730, 1030, 730])
  })

  it('rundet auf ganze Pixel (Bruchteile lösen kein Neuzeichnen aus)', () => {
    expect(run([[729.6, 0]])).toEqual([730])
  })
})
