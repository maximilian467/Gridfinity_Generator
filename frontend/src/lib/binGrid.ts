/** Fächer-Einlage: Maße wie im Backend (geometry/layout.py grid_compartments). */
export const PITCH = 42
export const LIP_MARGIN = 2.6         // Randbreite des Stapelrands: dort beginnt der nutzbare Innenbereich
export const BIN_TOL = 0.5
export const MIN_SIDE = 6             // schmalere Fächer lehnt das Backend ab

/** Außenmaß der Einlage in mm. */
export const binOuter = (gx: number, gy: number): [number, number] => [gx * PITCH - BIN_TOL, gy * PITCH - BIN_TOL]

/** Maße eines Fachs bei gleichmäßiger Teilung in cols x rows mit Wandstärke wall. */
export function cellSize(gx: number, gy: number, cols: number, rows: number, wall = 1.6): [number, number] {
  const [ox, oy] = binOuter(gx, gy)
  const ix = ox - 2 * LIP_MARGIN, iy = oy - 2 * LIP_MARGIN
  return [(ix - (cols - 1) * wall) / cols, (iy - (rows - 1) * wall) / rows]
}
