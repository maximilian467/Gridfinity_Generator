import { useEffect, useRef, useState } from 'react'
import { Group, Layer, Line, Rect, Stage, Text } from 'react-konva'
import { alpha, useTokens } from '../../lib/theme'
import type { InsertSpec, LayoutOut, ObjectSpec, PolyOut } from '../../lib/types'

export type Sel = { kind: 'placement' | 'grip' | 'comp'; index: number } | null

const PAD = 28
const INNER = 2.6
const MONO = 'Geist Mono Variable, monospace'

function flat(poly: [number, number][], ox: number, oy: number, k: number): number[] {
  return poly.slice(0, -1).flatMap(([x, y]) => [(x - ox) * k, -(y - oy) * k])
}

function Polys({ polys, ox, oy, k, fill, stroke, dash, width = 1.25 }: {
  polys: PolyOut[]; ox: number; oy: number; k: number; fill: string; stroke: string; dash?: number[]; width?: number
}) {
  return (
    <>
      {polys.map((p, i) => (
        <Line key={i} points={flat(p.exterior, ox, oy, k)} closed fill={fill} stroke={stroke} strokeWidth={width} dash={dash} />
      ))}
    </>
  )
}

function centroid(p: PolyOut): [number, number] {
  const xs = p.exterior.map((q) => q[0]), ys = p.exterior.map((q) => q[1])
  return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2]
}

/** Draufsicht der Einlage im mm-Maßstab. Positionen in der Spec gelten vor der automatischen
 *  Zentrierung; das Layout liefert die Verschiebung (shift) mit. */
export function Editor2D({ spec, layout, sel, onSelect, onMove, selectedComps = [], onPick, onPocketClick }: {
  spec: InsertSpec; layout: LayoutOut | undefined; objects?: Record<string, ObjectSpec>
  sel: Sel; onSelect: (s: Sel, additive?: boolean) => void; selectedComps?: number[]
  /** gesetzt: nächster Klick liefert die Layout-Position (mm) statt etwas auszuwählen */
  onPick?: (x: number, y: number) => void
  /** Klick in eine Tasche: Platzierung und Layout-Position (mm) */
  onPocketClick?: (pi: number, x: number, y: number) => void
  onMove: (s: NonNullable<Sel>, x: number, y: number) => void
}) {
  const tk = useTokens()
  const wrap = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(800)
  useEffect(() => {
    const ro = new ResizeObserver(() => wrap.current && setW(wrap.current.clientWidth))
    if (wrap.current) ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])
  const [OX, OY] = layout?.outer ?? [41.5, 41.5]
  const [sx, sy] = layout?.shift ?? [0, 0]
  // hochkant liegende Einlagen nicht höher als ~70 % des Fensters
  const kMaxH = (Math.max(320, window.innerHeight * 0.7) - 2 * PAD) / OY
  const k = Math.min((w - 2 * PAD) / OX, kMaxH)
  const h = OY * k + 2 * PAD
  const left = (w - OX * k) / 2
  const px = (x: number) => left + x * k
  const py = (y: number) => PAD + (OY - y) * k
  const maxDepth = Math.max(1, ...(layout?.pieces.map((p) => p.depth) ?? [1]))
  const gx = layout?.grid_x ?? 1, gy = layout?.grid_y ?? 1
  const manualGrips = layout?.grips.filter((g) => !g.auto) ?? []
  const autoGrips = layout?.grips.filter((g) => g.auto) ?? []
  const manualComps = layout?.compartments.filter((c) => !c.auto) ?? []
  const autoComps = layout?.compartments.filter((c) => c.auto) ?? []

  const attachedRot = (g: InsertSpec['grip_recesses'][number]) =>
    g.attach != null && spec.placements[g.attach] ? spec.placements[g.attach].rot_deg : null
  const dragEnd = (s: NonNullable<Sel>) => (e: any) => {
    e.target.setAttr('startAbs', null)
    const x = (e.target.x() - left) / k - sx, y = OY - (e.target.y() - PAD) / k - sy
    onMove(s, Math.round(x * 10) / 10, Math.round(y * 10) / 10)
  }
  const label = (x: number, y: number, t: string, ox = 0, oy = 0) => (
    <Text x={(x - ox) * k - 20} y={-(y - oy) * k - 6} width={40} align="center" text={t} fontSize={11}
      fontStyle="bold" fontFamily={MONO} fill={tk.ink} listening={false} />
  )
  const cellLine = (i: number, n: number) => i * 42 - (i === 0 ? 0 : i === n ? 0.5 : 0.25)

  return (
    <div ref={wrap} className="w-full" style={{ cursor: onPick ? 'crosshair' : undefined }}>
      <Stage width={w} height={h} onMouseDown={(e) => e.target === e.target.getStage() && onSelect(null)}>
        <Layer>
          <Rect x={px(0)} y={py(OY)} width={OX * k} height={OY * k} stroke={tk['line-2']} strokeWidth={2} cornerRadius={3.75 * k}
            fill={tk['surface-2']} listening={false} />
          {Array.from({ length: gx + 1 }, (_, i) => (
            <Line key={'gx' + i} points={[px(cellLine(i, gx)), py(0), px(cellLine(i, gx)), py(OY)]}
              stroke={tk['line-2']} strokeWidth={0.75} dash={[2, 5]} listening={false} />
          ))}
          {Array.from({ length: gy + 1 }, (_, i) => (
            <Line key={'gy' + i} points={[px(0), py(cellLine(i, gy)), px(OX), py(cellLine(i, gy))]}
              stroke={tk['line-2']} strokeWidth={0.75} dash={[2, 5]} listening={false} />
          ))}
          <Rect x={px(INNER)} y={py(OY - INNER)} width={(OX - 2 * INNER) * k} height={(OY - 2 * INNER) * k}
            stroke={tk['ink-2']} strokeWidth={1} dash={[5, 4]} listening={false} />

          {/* automatische Kästen (folgen der Kontur, nicht ziehbar) */}
          <Group x={px(0)} y={py(0)} listening={false}>
            {autoComps.map((c, i) => (
              <Group key={'ac' + i}>
                <Polys polys={c.polygons} ox={0} oy={0} k={k} fill={alpha(tk.green, 0.22)} stroke={tk.green} />
                {c.polygons[0] && label(...centroid(c.polygons[0]), c.depth.toFixed(0))}
              </Group>
            ))}
          </Group>

          {/* Taschen je Objekt, inklusive automatischer Greifmulde */}
          {layout && spec.placements.map((pl, pi) => {
            const pieces = layout.pieces.filter((p) => p.placement === pi)
            const active = sel?.kind === 'placement' && sel.index === pi
            const ox = pl.x + sx, oy = pl.y + sy
            return (
              <Group key={'pl' + pi} x={px(ox)} y={py(oy)} draggable
                onMouseDown={(e) => {
                  onSelect({ kind: 'placement', index: pi })
                  const pos = e.target.getStage()?.getPointerPosition()
                  if (pos) onPocketClick?.(pi, (pos.x - left) / k, OY - (pos.y - PAD) / k)
                }}
                onDragEnd={dragEnd({ kind: 'placement', index: pi })}>
                {pieces.map((pc, zi) => (
                  <Polys key={zi} polys={pc.polygons} ox={ox} oy={oy} k={k}
                    fill={alpha(tk.accent, 0.16 + 0.5 * (pc.depth / maxDepth))} stroke={tk.accent} width={active ? 2.5 : 1.25} />
                ))}
                {autoGrips.filter((g) => g.placement === pi).map((g, j) => (
                  <Polys key={'ag' + j} polys={g.polygons} ox={ox} oy={oy} k={k} fill={alpha(tk.blue, 0.32)} stroke={tk.blue} dash={[6, 3]} />
                ))}
                {pieces.map((pc, zi) => pc.polygons.slice(0, 1).map((p) => (
                  <Group key={'t' + zi}>{label(...centroid(p), pc.depth.toFixed(1), ox, oy)}</Group>
                )))}
                {autoGrips.filter((g) => g.placement === pi).map((g, j) => g.polygons[0] && (
                  <Group key={'agl' + j}>{label(...centroid(g.polygons[0]), g.depth.toFixed(1), ox, oy)}</Group>
                ))}
              </Group>
            )
          })}

          {/* manuelle Greifmulden */}
          {layout && spec.grip_recesses.map((g, gi) => {
            const lg = manualGrips[gi]
            const c0 = g.attach != null && lg?.polygons[0] ? centroid(lg.polygons[0]) : null
            const ox = c0 ? c0[0] : g.x + sx, oy = c0 ? c0[1] : g.y + sy
            const act = sel?.kind === 'grip' && sel.index === gi
            return (
              <Group key={'g' + gi} x={px(ox)} y={py(oy)} draggable
                dragBoundFunc={attachedRot(g) === null ? undefined : function (this: any, pos) {
                  // nur entlang der Werkzeugachse (Bildschirm-y zeigt nach unten)
                  const a = (attachedRot(g)! * Math.PI) / 180, dx = Math.cos(a), dy = -Math.sin(a)
                  const st = this.getAttr('startAbs') ?? this.getAbsolutePosition()
                  const t = (pos.x - st.x) * dx + (pos.y - st.y) * dy
                  return { x: st.x + t * dx, y: st.y + t * dy }
                }}
                onDragStart={(e) => (e.target as any).setAttr('startAbs', e.target.getAbsolutePosition())}
                onMouseDown={() => onSelect({ kind: 'grip', index: gi })} onDragEnd={dragEnd({ kind: 'grip', index: gi })}>
                <Polys polys={lg?.polygons ?? []} ox={ox} oy={oy} k={k} fill={alpha(tk.blue, 0.32)}
                  stroke={act ? tk.accent : tk.blue} width={act ? 2.5 : 1.25} />
                {label(ox, oy, (lg?.depth ?? 0).toFixed(1), ox, oy)}
              </Group>
            )
          })}

          {/* manuelle Fächer */}
          {layout && spec.compartments.map((c, ci) => {
            const ox = c.x + sx, oy = c.y + sy
            const lc = manualComps[ci]
            const act = selectedComps.includes(ci) || (sel?.kind === 'comp' && sel.index === ci)
            return (
              <Group key={'c' + ci} x={px(ox)} y={py(oy)} draggable={!c.generated}
                onMouseDown={(e) => onSelect({ kind: 'comp', index: ci }, e.evt.shiftKey || e.evt.ctrlKey || e.evt.metaKey)}
                onDragEnd={dragEnd({ kind: 'comp', index: ci })}>
                <Polys polys={lc?.polygons ?? []} ox={ox} oy={oy} k={k} fill={alpha(tk.green, 0.3)}
                  stroke={act ? tk.accent : tk.green} width={act ? 2.5 : 1.25} />
                {lc?.polygons[0] && label(...centroid(lc.polygons[0]), lc.max_depth ? 'max' : lc.depth.toFixed(0), ox, oy)}
              </Group>
            )
          })}
          {onPick && (
            <Rect x={0} y={0} width={w} height={h} fill="transparent"
              onMouseDown={(e) => {
                e.cancelBubble = true
                const pos = e.target.getStage()!.getPointerPosition()!
                onPick(Math.round(((pos.x - left) / k) * 10) / 10, Math.round((OY - (pos.y - PAD) / k) * 10) / 10)
              }} />
          )}
        </Layer>
      </Stage>
    </div>
  )
}
