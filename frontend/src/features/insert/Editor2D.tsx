import { useEffect, useRef, useState } from 'react'
import { Group, Layer, Line, Rect, Stage, Text } from 'react-konva'
import type { Compartment, GripRecess, InsertSpec, LayoutOut, ObjectSpec, PolyOut } from '../../lib/types'

export type Sel = { kind: 'placement' | 'grip' | 'comp' | 'proposal'; index: number } | null

const PAD = 28
const INNER = 2.6

function flat(poly: [number, number][], ox: number, oy: number, k: number): number[] {
  return poly.slice(0, -1).flatMap(([x, y]) => [(x - ox) * k, -(y - oy) * k])
}

function Polys({ polys, ox, oy, k, fill, stroke, dash }: {
  polys: PolyOut[]; ox: number; oy: number; k: number; fill: string; stroke: string; dash?: number[]
}) {
  return (
    <>
      {polys.map((p, i) => (
        <Line key={i} points={flat(p.exterior, ox, oy, k)} closed fill={fill} stroke={stroke} strokeWidth={1.25} dash={dash}
          listening />
      ))}
    </>
  )
}

export function Editor2D({ spec, layout, objects, sel, onSelect, onMove, proposals }: {
  spec: InsertSpec; layout: LayoutOut | undefined; objects: Record<string, ObjectSpec>
  sel: Sel; onSelect: (s: Sel) => void
  onMove: (s: NonNullable<Sel>, x: number, y: number) => void
  proposals: Compartment[]
}) {
  const wrap = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(800)
  useEffect(() => {
    const ro = new ResizeObserver(() => wrap.current && setW(wrap.current.clientWidth))
    if (wrap.current) ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])
  const [OX, OY] = layout?.outer ?? [41.5, 41.5]
  const k = (w - 2 * PAD) / OX
  const h = OY * k + 2 * PAD
  const px = (x: number) => PAD + x * k
  const py = (y: number) => PAD + (OY - y) * k
  const maxDepth = Math.max(1, ...(layout?.pieces.map((p) => p.depth) ?? [1]))
  const gx = layout?.grid_x ?? 1, gy = layout?.grid_y ?? 1

  const dragEnd = (s: NonNullable<Sel>) => (e: any) => {
    const x = (e.target.x() - PAD) / k, y = OY - (e.target.y() - PAD) / k
    onMove(s, Math.round(x * 10) / 10, Math.round(y * 10) / 10)
  }

  // Zonen-Beschriftung je Taschenstück: Mittelpunkt
  const label = (p: PolyOut) => {
    const xs = p.exterior.map((q) => q[0]), ys = p.exterior.map((q) => q[1])
    return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2]
  }

  return (
    <div ref={wrap} className="w-full">
      <Stage width={w} height={h} onMouseDown={(e) => e.target === e.target.getStage() && onSelect(null)}>
        <Layer>
          <Rect x={px(0)} y={py(OY)} width={OX * k} height={OY * k} fill="#ffffff" opacity={0.0} listening={false} />
          <Rect x={px(0)} y={py(OY)} width={OX * k} height={OY * k} stroke="#6b7480" strokeWidth={1.5} cornerRadius={3.75 * k}
            fill="rgba(128,138,148,0.08)" listening={false} />
          <Rect x={px(INNER)} y={py(OY - INNER)} width={(OX - 2 * INNER) * k} height={(OY - 2 * INNER) * k}
            stroke="#6b7480" strokeWidth={1} dash={[4, 4]} listening={false} />
          {Array.from({ length: gx + 1 }, (_, i) => (
            <Line key={'gx' + i} points={[px(i * 42 - (i === 0 ? 0 : i === gx ? 0.5 : 0.25)), py(0), px(i * 42 - (i === 0 ? 0 : i === gx ? 0.5 : 0.25)), py(OY)]}
              stroke="#8a929b" strokeWidth={0.75} dash={[2, 5]} listening={false} />
          ))}
          {Array.from({ length: gy + 1 }, (_, i) => (
            <Line key={'gy' + i} points={[px(0), py(i * 42 - (i === 0 ? 0 : i === gy ? 0.5 : 0.25)), px(OX), py(i * 42 - (i === 0 ? 0 : i === gy ? 0.5 : 0.25))]}
              stroke="#8a929b" strokeWidth={0.75} dash={[2, 5]} listening={false} />
          ))}

          {layout && spec.placements.map((pl, pi) => {
            const pieces = layout.pieces.filter((p) => p.placement === pi)
            const active = sel?.kind === 'placement' && sel.index === pi
            return (
              <Group key={'pl' + pi} x={px(pl.x)} y={py(pl.y)} draggable
                onMouseDown={() => onSelect({ kind: 'placement', index: pi })}
                onDragEnd={dragEnd({ kind: 'placement', index: pi })}>
                {pieces.map((pc, zi) => (
                  <Polys key={zi} polys={pc.polygons} ox={pl.x} oy={pl.y} k={k}
                    fill={`rgba(217,72,15,${0.12 + 0.5 * (pc.depth / maxDepth)})`}
                    stroke={active ? '#d9480f' : '#8f3a12'} />
                ))}
                {pieces.map((pc, zi) => pc.polygons.slice(0, 1).map((p) => {
                  const [cx, cy] = label(p)
                  return <Text key={'t' + zi} x={(cx - pl.x) * k - 14} y={-(cy - pl.y) * k - 5} width={28} align="center"
                    text={pc.depth.toFixed(1)} fontSize={10} fontFamily="Geist Mono Variable, monospace" fill="#1f2328" listening={false} />
                }))}
                <Text x={0} y={4} text={objects[pl.object_id]?.name ?? '?'} fontSize={10} fill="#1f2328" listening={false} />
                {active && <Rect x={-4} y={-4} width={8} height={8} fill="#d9480f" listening={false} />}
              </Group>
            )
          })}

          {layout && spec.grip_recesses.map((g: GripRecess, gi) => (
            <Group key={'g' + gi} x={px(g.x)} y={py(g.y)} draggable
              onMouseDown={() => onSelect({ kind: 'grip', index: gi })} onDragEnd={dragEnd({ kind: 'grip', index: gi })}>
              <Polys polys={layout.grips[gi]?.polygons ?? []} ox={g.x} oy={g.y} k={k} fill="rgba(31,111,235,0.30)"
                stroke={sel?.kind === 'grip' && sel.index === gi ? '#d9480f' : '#1f6feb'} />
              <Text x={-14} y={-5} width={28} align="center" text={(layout.grips[gi]?.depth ?? 0).toFixed(1)} fontSize={10}
                fontFamily="Geist Mono Variable, monospace" fill="#1f2328" listening={false} />
            </Group>
          ))}

          {layout && spec.compartments.map((c: Compartment, ci) => (
            <Group key={'c' + ci} x={px(c.x)} y={py(c.y)} draggable
              onMouseDown={() => onSelect({ kind: 'comp', index: ci })} onDragEnd={dragEnd({ kind: 'comp', index: ci })}>
              <Polys polys={layout.compartments[ci]?.polygons ?? []} ox={c.x} oy={c.y} k={k} fill="rgba(43,122,75,0.28)"
                stroke={sel?.kind === 'comp' && sel.index === ci ? '#d9480f' : '#2b7a4b'} />
              <Text x={4} y={-(c.l * k) / 2 - 5} text={c.depth.toFixed(0)} fontSize={10}
                fontFamily="Geist Mono Variable, monospace" fill="#1f2328" listening={false} />
            </Group>
          ))}

          {proposals.map((c, i) => (
            <Rect key={'pr' + i} x={px(c.x)} y={py(c.y + c.l)} width={c.w * k} height={c.l * k} stroke="#2b7a4b" dash={[6, 4]}
              strokeWidth={1.5} fill="rgba(43,122,75,0.10)" cornerRadius={c.radius * k}
              onMouseDown={() => onSelect({ kind: 'proposal', index: i })} />
          ))}
        </Layer>
      </Stage>
    </div>
  )
}
