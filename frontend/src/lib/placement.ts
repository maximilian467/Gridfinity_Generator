import type { InsertSpec, ObjectSpec, Placement } from './types'

const MARGIN = 2.6 + 0.6   // Stapelrand-Innenkante + kleine Reserve

/** Achsparallele Ausdehnung der Tasche eines Objekts (Kontur + Spiel), gedreht um rot_deg um den Objekt-Ursprung. */
export function pocketBounds(obj: ObjectSpec, rotDeg: number, spec: Pick<InsertSpec, 'clearance_xy' | 'clearance_end'>) {
  const a = (rotDeg * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a)
  const ex = spec.clearance_xy + spec.clearance_end, ey = spec.clearance_xy
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const [px, py] of obj.contour_mm) {
    for (const [dx, dy] of [[-ex, -ey], [ex, ey], [-ex, ey], [ex, -ey]]) {
      const x = (px + dx) * c - (py + dy) * s, y = (px + dx) * s + (py + dy) * c
      x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y)
    }
  }
  return { x0, y0, x1, y1 }
}

/** Ordnet alle Objekte nebeneinander an (Mindestwand dazwischen), unten bündig. */
export function arrange(spec: InsertSpec, objects: Record<string, ObjectSpec>): Placement[] {
  let x = MARGIN
  return spec.placements.map((p) => {
    const o = objects[p.object_id]
    if (!o?.contour_mm.length) return p
    const b = pocketBounds(o, p.rot_deg, spec)
    const np = { ...p, x: round(x - b.x0), y: round(MARGIN - b.y0) }
    x += b.x1 - b.x0 + Math.max(spec.min_wall, 2)
    return np
  })
}

/** Neues Objekt senkrecht (Länge entlang y) rechts neben die vorhandenen setzen. */
export function placeNew(spec: InsertSpec, objects: Record<string, ObjectSpec>, obj: ObjectSpec): Placement {
  const gap = Math.max(spec.min_wall, 2)
  let right = MARGIN - gap
  for (const p of spec.placements) {
    const o = objects[p.object_id]
    if (!o) continue
    right = Math.max(right, p.x + pocketBounds(o, p.rot_deg, spec).x1)
  }
  const b = pocketBounds(obj, 90, spec)
  return { object_id: obj.id, x: round(right + gap - b.x0), y: round(MARGIN - b.y0), rot_deg: 90, side_down: 'A' }
}

const round = (v: number) => Math.round(v * 10) / 10
