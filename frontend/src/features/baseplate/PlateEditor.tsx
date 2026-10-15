import { useRef } from 'react'
import type { ReactNode } from 'react'
import type { PlatePlan } from '../../lib/types'

export const PITCH = 42
export const TILE_COLORS = ['#d9480f', '#1c7ed6', '#2f9e44', '#ae3ec9', '#f08c00', '#0c8599', '#e8590c', '#5c7cfa']

/** Draufsicht der Schublade: Zellen an-/abwählen (Klick oder Ziehen), Kacheln farbig umrandet.
 *  Schubladen-mm, y nach hinten = im Bild nach oben. children: weitere SVG-Ebenen in Schubladen-mm (y oben). */
export function PlateEditor({ drawer, plan, disabled, onToggle, children, height = 420, editable = true, showCells = true }: {
  drawer: [number, number]; plan: PlatePlan | undefined; disabled: [number, number][]
  onToggle?: (cells: [number, number][], on: boolean) => void; children?: ReactNode; height?: number | string
  editable?: boolean; showCells?: boolean
}) {
  const [W, D] = drawer
  const pad = 6
  const drag = useRef<{ on: boolean; seen: Set<string> } | null>(null)
  const off = new Set(disabled.map(([a, b]) => `${a},${b}`))
  const cells: [number, number][] = []
  if (plan) for (let i = 0; i < plan.cells_x; i++) for (let j = 0; j < plan.cells_y; j++) cells.push([i, j])
  const tileOf = new Map<string, number>()
  plan?.tiles.forEach((t) => t.cells.forEach(([a, b]) => tileOf.set(`${a},${b}`, t.n)))
  const hit = (i: number, j: number) => {
    if (!editable || !onToggle || !drag.current) return
    const k = `${i},${j}`
    if (drag.current.seen.has(k)) return
    drag.current.seen.add(k)
    onToggle([[i, j]], drag.current.on)
  }
  const flipY = (y: number) => D - y
  return (
    <svg viewBox={`${-pad} ${-pad} ${W + 2 * pad} ${D + 2 * pad}`} style={{ width: '100%', height, touchAction: 'none', userSelect: 'none', display: 'block' }}
      onPointerUp={() => { drag.current = null }} onPointerLeave={() => { drag.current = null }}>
      <defs>
        <pattern id="plate-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink-3)" strokeWidth="1.2" />
        </pattern>
      </defs>
      <rect x={0} y={0} width={W} height={D} fill="var(--surface)" stroke="var(--ink)" strokeWidth={1.5} rx={2} />
      {plan?.tiles.map((t) => t.polygons.map((p, k) => (
        <path key={`${t.n}-${k}`} fillRule="evenodd"
          d={[p.exterior, ...p.holes].map((r) => 'M' + r.map(([x, y]) => `${x},${flipY(y)}`).join('L') + 'Z').join(' ')}
          fill={`color-mix(in srgb, ${TILE_COLORS[(t.n - 1) % TILE_COLORS.length]} 8%, transparent)`}
          stroke={TILE_COLORS[(t.n - 1) % TILE_COLORS.length]} strokeWidth={1.2} />
      )))}
      {plan && showCells && cells.map(([i, j]) => {
        const x = plan.origin[0] + i * PITCH, y = plan.origin[1] + j * PITCH
        const isOff = off.has(`${i},${j}`)
        return (
          <g key={`${i},${j}`} style={{ cursor: editable ? 'pointer' : 'default' }}
            onPointerDown={(e) => {
              if (!editable) return
              try { (e.target as Element).releasePointerCapture(e.pointerId) } catch { /* egal */ }
              drag.current = { on: isOff, seen: new Set() }; hit(i, j)
            }}
            onPointerEnter={() => hit(i, j)}>
            <rect x={x + 1.5} y={flipY(y + PITCH) + 1.5} width={PITCH - 3} height={PITCH - 3} rx={4}
              fill={isOff ? 'url(#plate-hatch)' : 'color-mix(in srgb, var(--ink) 6%, transparent)'}
              stroke={isOff ? 'var(--ink-3)' : 'color-mix(in srgb, var(--ink) 25%, transparent)'} strokeWidth={0.8} strokeDasharray={isOff ? '3 2' : undefined} />
            {!isOff && tileOf.has(`${i},${j}`) && plan.tiles.length > 1 && (
              <text x={x + 5} y={flipY(y + PITCH) + 11} fontSize={8} fill="var(--ink-3)" pointerEvents="none">{tileOf.get(`${i},${j}`)}</text>
            )}
          </g>
        )
      })}
      <g transform={`translate(0 ${D}) scale(1 -1)`}>{children}</g>
    </svg>
  )
}
