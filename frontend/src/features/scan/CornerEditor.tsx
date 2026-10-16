import { useEffect, useRef, useState } from 'react'
import { Circle, Image as KImage, Layer, Line, Stage } from 'react-konva'
import type { PhotoMeta } from '../../lib/types'
import { useStableWidth } from '../../lib/stableWidth'

function useImage(url?: string) {
  const [img, setImg] = useState<HTMLImageElement | null>(null)
  useEffect(() => {
    if (!url) { setImg(null); return }
    const i = new window.Image()
    i.onload = () => setImg(i)
    i.src = url
  }, [url])
  return img
}

const LOUPE = 160, ZOOM = 5

export function CornerEditor({ photo, onChange, busy }: {
  photo: PhotoMeta; onChange: (corners: number[][]) => void; busy: boolean
}) {
  const img = useImage(photo.preview_url)
  const [wrap, width] = useStableWidth<HTMLDivElement>(900, 1100)
  const k = photo.preview_scale
  const [pts, setPts] = useState<number[][]>(photo.corners_px.map((p) => [p[0] * k, p[1] * k]))
  const [active, setActive] = useState<number | null>(null)
  const loupe = useRef<HTMLDivElement>(null)

  useEffect(() => { setPts(photo.corners_px.map((p) => [p[0] * k, p[1] * k])) }, [photo.corners_px, k])

  const natW = img?.naturalWidth ?? photo.size[0] * k
  const natH = img?.naturalHeight ?? photo.size[1] * k
  const s = width / natW

  const moveLoupe = (p: number[]) => {
    const el = loupe.current
    if (!el) return
    el.style.backgroundImage = `url(${photo.preview_url})`
    el.style.backgroundSize = `${natW * ZOOM}px ${natH * ZOOM}px`
    el.style.backgroundPosition = `${-(p[0] * ZOOM - LOUPE / 2)}px ${-(p[1] * ZOOM - LOUPE / 2)}px`
  }

  return (
    <div className="grid gap-3">
      <div ref={wrap} className="relative w-full" style={{ maxWidth: 1100 }}>
        <Stage width={width} height={natH * s} style={{ cursor: 'crosshair', border: '1px solid var(--line)' }}>
          <Layer scaleX={s} scaleY={s}>
            {img && <KImage image={img} />}
            <Line points={pts.flat()} closed stroke="#ff6a1f" strokeWidth={2 / s} />
            {pts.map((p, i) => (
              <Circle key={i} x={p[0]} y={p[1]} radius={9 / s} stroke="#ff6a1f" strokeWidth={2 / s}
                fill={active === i ? 'rgba(255,106,31,0.35)' : 'rgba(255,255,255,0.01)'} draggable
                onDragStart={() => { setActive(i); moveLoupe(p) }}
                onDragMove={(e) => {
                  const np = [e.target.x(), e.target.y()]
                  setPts((old) => old.map((q, j) => (j === i ? np : q)))
                  moveLoupe(np)
                }}
                onDragEnd={(e) => {
                  setActive(null)
                  const next = pts.map((q, j) => (j === i ? [e.target.x(), e.target.y()] : q))
                  onChange(next.map((q) => [q[0] / k, q[1] / k]))
                }} />
            ))}
          </Layer>
        </Stage>
        <div ref={loupe} className="absolute top-2 right-2 pointer-events-none"
          style={{ width: LOUPE, height: LOUPE, border: '2px solid var(--accent)', borderRadius: 4,
            display: active === null ? 'none' : 'block', backgroundRepeat: 'no-repeat', background: '#222' }}>
          <div className="absolute inset-0" style={{
            background: 'linear-gradient(var(--accent),var(--accent)) center/1px 100% no-repeat, linear-gradient(var(--accent),var(--accent)) center/100% 1px no-repeat' }} />
        </div>
        {busy && <div className="absolute inset-0 grid place-items-center" style={{ background: 'rgba(0,0,0,.15)' }}>Entzerre …</div>}
      </div>
      <div className="hint">Ziehe die vier Punkte genau auf die Ecken des Blattes. Die Lupe oben rechts zeigt 5-fach vergrößert.</div>
    </div>
  )
}
