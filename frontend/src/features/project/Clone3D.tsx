import { Suspense, useEffect, useMemo, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { api } from '../../lib/api'
import { Segmented } from '../../components/ui'
import type { CloneData, CloneInsert, CloneTool, PolyOut, TextureInfo } from '../../lib/types'

/** Digitaler Klon der Schublade: Baseplate, Einlagen (vereinfachte Geometrie aus dem Layout) und auf Wunsch
 *  die Werkzeuge als Low-Poly-Körper mit dem Foto der Oberseite als Farbe. Einheiten mm, z nach oben (CAD). */

const BIN_TOL = 0.5
const LIP_H = 3.8
const LIP_MARGIN = 2.6
const BIN_R = 3.75

function roundedRect(x0: number, y0: number, w: number, h: number, r: number): THREE.Shape {
  const s = new THREE.Shape()
  r = Math.min(r, w / 2, h / 2)
  s.moveTo(x0 + r, y0)
  s.lineTo(x0 + w - r, y0); s.absarc(x0 + w - r, y0 + r, r, -Math.PI / 2, 0, false)
  s.lineTo(x0 + w, y0 + h - r); s.absarc(x0 + w - r, y0 + h - r, r, 0, Math.PI / 2, false)
  s.lineTo(x0 + r, y0 + h); s.absarc(x0 + r, y0 + h - r, r, Math.PI / 2, Math.PI, false)
  s.lineTo(x0, y0 + r); s.absarc(x0 + r, y0 + r, r, Math.PI, 1.5 * Math.PI, false)
  return s
}

function ringPath(pts: number[][], P: typeof THREE.Shape | typeof THREE.Path) {
  const p = new P()
  pts.forEach(([x, y], i) => (i ? p.lineTo(x, y) : p.moveTo(x, y)))
  return p
}

function polyShapes(polys: PolyOut[]): THREE.Shape[] {
  return polys.map((p) => {
    const s = ringPath(p.exterior, THREE.Shape) as THREE.Shape
    s.holes = p.holes.map((h) => ringPath(h, THREE.Path) as THREE.Path)
    return s
  })
}

const invisible = new THREE.MeshBasicMaterial({ visible: false })

function mat(color: string, extra: Partial<THREE.MeshStandardMaterialParameters> = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0.02, ...extra })
}

/** Baseplate: Kachel-Grundfläche minus Zellöffnungen, 4,75 mm hoch */
function Plate({ data }: { data: CloneData }) {
  const geo = useMemo(() => {
    const P = data.plan, pitch = data.pitch
    const active = new Set(P.active.map(([a, b]) => `${a},${b}`))
    const shapes: THREE.Shape[] = []
    for (const t of P.tiles) for (const g of t.polygons) {
      const s = ringPath(g.exterior, THREE.Shape) as THREE.Shape
      s.holes = g.holes.map((h) => ringPath(h, THREE.Path) as THREE.Path)
      for (const [i, j] of t.cells) {
        if (!active.has(`${i},${j}`)) continue
        const x = P.origin[0] + i * pitch, y = P.origin[1] + j * pitch
        const hole = roundedRect(x + 2.2, y + 2.2, pitch - 4.4, pitch - 4.4, 2)
        s.holes.push(new THREE.Path(hole.getPoints(4)))
      }
      shapes.push(s)
    }
    return new THREE.ExtrudeGeometry(shapes, { depth: P.plate_h, bevelEnabled: false, curveSegments: 4 })
  }, [data])
  return <mesh geometry={geo} material={mat('#8f959c')} />
}

/** Eine Einlage in eigenen Koordinaten (0..außen), oben offen mit Taschen, Mulden und Fächern */
function InsertBody({ ins }: { ins: CloneInsert }) {
  const parts = useMemo(() => {
    const L = ins.layout!
    const [ox, oy] = L.outer
    const zs = L.z_surface
    const c = ins.colors
    const outer = roundedRect(0, 0, ox, oy, BIN_R)
    const cut = polyShapes(ins.cut_union ?? [])
    const top = outer.clone()
    top.holes = cut.map((s) => new THREE.Path(s.getPoints()))
    const islands = cut.flatMap((s) => s.holes.map((h) => new THREE.Shape(h.getPoints())))
    const out: { geo: THREE.BufferGeometry; mat: THREE.Material | THREE.Material[]; z: number }[] = []
    // Außenwand und Deckfläche
    out.push({ geo: new THREE.ExtrudeGeometry(outer, { depth: zs, bevelEnabled: false, curveSegments: 6 }), mat: [invisible, mat(c.body)], z: 0 })
    out.push({ geo: new THREE.ShapeGeometry([top, ...islands], 6), mat: mat(c.body, { side: THREE.DoubleSide }), z: zs })
    // Stapelrand
    if (ins.total_height! - zs > 1) {
      const lip = roundedRect(0, 0, ox, oy, BIN_R)
      lip.holes = [new THREE.Path(roundedRect(LIP_MARGIN, LIP_MARGIN, ox - 2 * LIP_MARGIN, oy - 2 * LIP_MARGIN, 1.5).getPoints(6))]
      out.push({ geo: new THREE.ExtrudeGeometry(lip, { depth: LIP_H, bevelEnabled: false, curveSegments: 6 }), mat: mat(c.body), z: zs })
    }
    // Wände der Aussparungen (Farbe der Taschen) bis zum tiefsten Boden
    const zmin = Math.min(zs - 0.5, ...L.pieces.map((p) => p.z0), ...L.grips.map((g) => g.z0), ...L.compartments.map((q) => q.z0))
    for (const s of cut) {
      out.push({ geo: new THREE.ExtrudeGeometry(s, { depth: zs - zmin, bevelEnabled: false, curveSegments: 4 }),
        mat: [invisible, mat(c.pocket, { side: THREE.DoubleSide })], z: zmin })
    }
    // Böden
    const floor = (polys: PolyOut[], z: number, color: string) =>
      out.push({ geo: new THREE.ShapeGeometry(polyShapes(polys), 4), mat: mat(color, { side: THREE.DoubleSide }), z: z + 0.01 })
    L.pieces.forEach((p) => floor(p.polygons, p.z0, c.pocket))
    L.grips.forEach((g) => floor(g.polygons, g.z0, c.grip))
    L.compartments.forEach((q) => floor(q.polygons, q.z0, c.compartment))
    return out
  }, [ins])
  useEffect(() => () => parts.forEach((q) => { q.geo.dispose(); (Array.isArray(q.mat) ? q.mat : [q.mat]).forEach((m) => m !== invisible && m.dispose()) }), [parts])
  return <>{parts.map((p, i) => <mesh key={i} geometry={p.geo} material={p.mat} position={[0, 0, p.z]} />)}</>
}

function interp(xs: number[], ys: number[], x: number) {
  if (x <= xs[0]) return ys[0]
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1]
  let lo = 0, hi = xs.length - 1
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (xs[m] > x) hi = m; else lo = m }
  const t = (x - xs[lo]) / (xs[hi] - xs[lo] || 1)
  return ys[lo] + t * (ys[hi] - ys[lo])
}

/** Werkzeug: Kontur zwischen Unter- und Oberseite (aus dem Seitenprofil), Foto der Oberseite als Farbe */
function Tool({ t, quality }: { t: CloneTool; quality: 'low' | 'high' }) {
  const [tex, setTex] = useState<{ map: THREE.Texture; info: TextureInfo } | null>(null)
  useEffect(() => {
    if (!t.has_texture) return
    let alive = true
    api.texture(t.object_id).then((info) => {
      new THREE.TextureLoader().load(info.url, (map) => {
        map.colorSpace = THREE.SRGBColorSpace
        if (alive) setTex({ map, info })
      })
    }).catch(() => { /* ohne Foto: einfarbig */ })
    return () => { alive = false }
  }, [t.object_id, t.has_texture])
  const geo = useMemo(() => {
    const step = quality === 'high' ? 1 : Math.max(1, Math.round(t.contour.length / 90))
    const pts = t.contour.filter((_, i) => i % step === 0).map(([x, y]) => new THREE.Vector2(x, y))
    const g = new THREE.ExtrudeGeometry(new THREE.Shape(pts), { depth: 1, bevelEnabled: false, steps: quality === 'high' ? 4 : 1 })
    const pos = g.attributes.position
    const uv = g.attributes.uv
    const info = tex?.info
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i)
      const b = interp(t.s, t.bottom, x), top = interp(t.s, t.top, x)
      pos.setZ(i, t.z_rest + b + z * Math.max(top - b, 0.3))
      if (info) uv.setXY(i, (x - info.x0) / (info.x1 - info.x0 || 1), (y - info.y0) / (info.y1 - info.y0 || 1))
    }
    g.computeVertexNormals()
    return g
  }, [t, quality, tex])
  useEffect(() => () => geo.dispose(), [geo])
  useEffect(() => () => tex?.map.dispose(), [tex])
  // Oberseite/Unterseite mit Foto, Seitenwände in der mittleren Farbe des Werkzeugs
  const material = useMemo(() => tex
    ? [new THREE.MeshStandardMaterial({ map: tex.map, roughness: 0.6, alphaTest: 0.5 }), mat(tex.info.color ?? '#c9ccd1', { roughness: 0.6 })]
    : mat('#c9ccd1', { roughness: 0.5, metalness: 0.3 }), [tex])
  return (
    <group position={[t.x, t.y, 0]} rotation={[0, 0, (t.rot_deg * Math.PI) / 180]}>
      <mesh geometry={geo} material={material} />
    </group>
  )
}

/** Lage einer Einlage in der Schublade (Zelle links unten, Drehung um 90°) */
export function insertTransform(data: CloneData, ins: CloneInsert): { pos: [number, number, number]; rot: number } | null {
  if (!ins.placed || !ins.layout) return null
  const P = data.plan, pitch = data.pitch
  const x0 = P.origin[0] + ins.placed.ix * pitch + BIN_TOL / 2
  const y0 = P.origin[1] + ins.placed.iy * pitch + BIN_TOL / 2
  if (ins.placed.rot === 90) return { pos: [x0 + ins.layout.outer[1], y0, 0], rot: Math.PI / 2 }
  return { pos: [x0, y0, 0], rot: 0 }
}

function Scene({ data, showTools, quality, showPlate }: { data: CloneData; showTools: boolean; quality: 'low' | 'high'; showPlate: boolean }) {
  const [W, D] = [data.plan.tiles.length ? Math.max(...data.plan.tiles.map((t) => t.x0 + t.w)) : 300,
    data.plan.tiles.length ? Math.max(...data.plan.tiles.map((t) => t.y0 + t.h)) : 300]
  return (
    <group rotation={[-Math.PI / 2, 0, 0]} position={[-W / 2, 0, D / 2]}>
      {/* Schubladenboden */}
      <mesh position={[W / 2, D / 2, -0.6]}><boxGeometry args={[W + 2, D + 2, 1]} /><meshStandardMaterial color="#d8d4cc" /></mesh>
      {showPlate && <Plate data={data} />}
      {data.inserts.map((ins) => {
        const tr = insertTransform(data, ins)
        if (!tr) return null
        return (
          <group key={ins.id} position={tr.pos} rotation={[0, 0, tr.rot]}>
            <InsertBody ins={ins} />
            {showTools && ins.tools?.map((t, k) => <Tool key={k} t={t} quality={quality} />)}
          </group>
        )
      })}
    </group>
  )
}

export function Clone3D({ data, height = 560 }: { data: CloneData; height?: number }) {
  const [showTools, setShowTools] = useState(true)
  const [quality, setQuality] = useState<'low' | 'high'>('low')
  const [showPlate, setShowPlate] = useState(true)
  const span = Math.max(...data.plan.tiles.map((t) => Math.max(t.x0 + t.w, t.y0 + t.h)), 200)
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-2 items-center text-sm">
        <Segmented value={showTools ? 'tools' : 'inserts'} onChange={(v) => setShowTools(v === 'tools')}
          options={[{ value: 'inserts', label: 'Nur Einlagen' }, { value: 'tools', label: 'Mit Werkzeugen' }]} />
        {showTools && (
          <Segmented value={quality} onChange={setQuality}
            options={[{ value: 'low', label: 'Low-Poly' }, { value: 'high', label: 'Detailliert' }]} />
        )}
        <label className="inline-flex items-center gap-1.5"><input type="checkbox" checked={showPlate} onChange={(e) => setShowPlate(e.target.checked)} /> Baseplate</label>
      </div>
      <div className="panel" style={{ height }}>
        <Canvas camera={{ position: [0, span * 0.9, span * 0.75], fov: 35, near: 1, far: span * 10 }}>
          <color attach="background" args={['#eceae6']} />
          <hemisphereLight args={['#ffffff', '#8a8f98', 1.0]} />
          <directionalLight position={[span * 0.4, span, span * 0.3]} intensity={1.7} />
          <directionalLight position={[-span * 0.5, span * 0.4, -span * 0.4]} intensity={0.5} />
          <Suspense fallback={null}><Scene data={data} showTools={showTools} quality={quality} showPlate={showPlate} /></Suspense>
          <OrbitControls makeDefault />
        </Canvas>
      </div>
    </div>
  )
}
