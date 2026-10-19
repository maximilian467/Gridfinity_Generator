import { describe, expect, it } from 'vitest'
import { MIN_SIDE, binOuter, cellSize } from './binGrid'

describe('cellSize', () => {
  it('teilt den Innenbereich abzüglich der Wände gleichmäßig', () => {
    expect(binOuter(2, 2)).toEqual([83.5, 83.5])
    const [w, h] = cellSize(2, 2, 2, 2)
    expect(w).toBeCloseTo((83.5 - 5.2 - 1.6) / 2, 6)
    expect(h).toBeCloseTo(w, 6)
    const [w3] = cellSize(3, 1, 3, 1, 2)
    expect(3 * w3 + 2 * 2).toBeCloseTo(125.5 - 5.2, 6)
  })
  it('erkennt zu feine Teilungen wie das Backend', () => {
    expect(cellSize(2, 2, 1, 12)[1]).toBeLessThan(MIN_SIDE)       // Backend: 422 'schmaler als 6 mm'
    expect(cellSize(3, 2, 12, 1)[0]).toBeGreaterThan(MIN_SIDE)
  })
})
