import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowCounterClockwise, Eraser, MinusCircle, PaintBrush, PlusCircle } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { PhotoMeta } from '../../lib/types'
import { Check, Msgs } from '../../components/ui'

type Mode = 'pos' | 'neg' | 'brush' | 'erase'
const PX_PER_MM_VIEW = 5   // entzerrtes Anzeigebild: 0.5 * 10 px/mm

function loadImg(url: string): Promise<HTMLImageElement> {
  return new Promise((res, rej) => {
    const i = new window.Image()
    i.onload = () => res(i)
    i.onerror = rej
    i.src = url
  })
}

export function MaskEditor({ oid, view, photo, onMaskChanged }: {
  oid: string; view: 'top' | 'side'; photo: PhotoMeta; onMaskChanged: () => void
}) {
  const [W, H] = [Math.round(photo.rect_size![0] * photo.view_scale!), Math.round(photo.rect_size![1] * photo.view_scale!)]
  const disp = useRef<HTMLCanvasElement>(null)
  const maskC = useRef<HTMLCanvasElement | null>(null)
  const bg = useRef<HTMLImageElement | null>(null)
  const undo = useRef<Uint8Array[]>([])
  const [mode, setMode] = useState<Mode>('pos')
  const [radius, setRadius] = useState(3)
  const [zoom, setZoom] = useState(1)
  const [fill, setFill] = useState(photo.fill_holes ?? true)
  const [pos, setPos] = useState<number[][]>([])
  const [neg, setNeg] = useState<number[][]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [info, setInfo] = useState<{ edge?: boolean; sam?: boolean }>({})
  const [tick, setTick] = useState(0)
  const painting = useRef(false)
  const last = useRef<[number, number] | null>(null)

  const redraw = useCallback(() => {
    const c = disp.current, m = maskC.current
    if (!c || !bg.current) return
    const g = c.getContext('2d')!
    g.clearRect(0, 0, W, H)
    g.drawImage(bg.current, 0, 0, W, H)
    if (m) {
      const t = document.createElement('canvas'); t.width = W; t.height = H
      const tg = t.getContext('2d')!
      tg.drawImage(m, 0, 0)
      tg.globalCompositeOperation = 'source-in'
      tg.fillStyle = 'rgba(255,106,31,0.55)'
      tg.fillRect(0, 0, W, H)
      g.drawImage(t, 0, 0)
    }
    g.lineWidth = 3
    for (const [list, col] of [[pos, '#1fb35a'], [neg, '#e5322d']] as const) {
      g.strokeStyle = col
      for (const p of list) { g.beginPath(); g.arc(p[0] * photo.view_scale!, p[1] * photo.view_scale!, 9, 0, 7); g.stroke() }
    }
  }, [W, H, pos, neg, photo.view_scale])

  const loadMask = useCallback(async (url?: string) => {
    const m = document.createElement('canvas'); m.width = W; m.height = H
    const g = m.getContext('2d')!
    if (url) {
      const im = await loadImg(url + '?t=' + Date.now())
      g.drawImage(im, 0, 0, W, H)
      // weiß -> deckend, schwarz -> transparent
      const d = g.getImageData(0, 0, W, H)
      for (let i = 0; i < d.data.length; i += 4) { const v = d.data[i] > 127 ? 255 : 0; d.data[i] = d.data[i + 1] = d.data[i + 2] = 255; d.data[i + 3] = v }
      g.putImageData(d, 0, 0)
    }
    maskC.current = m
    setTick((t) => t + 1)
  }, [W, H])

  useEffect(() => {
    let alive = true
    ;(async () => {
      bg.current = await loadImg(photo.rectified_url! + '?t=' + Date.now())
      if (!alive) return
      await loadMask(photo.mask_url)
    })()
    return () => { alive = false }
  }, [photo.rectified_url, photo.mask_url, loadMask])
  useEffect(() => { redraw() }, [redraw, tick])

  const snapshot = () => {
    const d = maskC.current!.getContext('2d')!.getImageData(0, 0, W, H).data
    const a = new Uint8Array(W * H)
    for (let i = 0; i < a.length; i++) a[i] = d[i * 4 + 3]
    undo.current.push(a)
    if (undo.current.length > 15) undo.current.shift()
  }
  const restore = async () => {
    const a = undo.current.pop()
    if (!a || !maskC.current) return
    const g = maskC.current.getContext('2d')!
    const d = g.createImageData(W, H)
    for (let i = 0; i < a.length; i++) { d.data[i * 4] = d.data[i * 4 + 1] = d.data[i * 4 + 2] = 255; d.data[i * 4 + 3] = a[i] }
    g.putImageData(d, 0, 0)
    redraw(); await upload()
  }

  const upload = async () => {
    const m = maskC.current!
    const out = document.createElement('canvas'); out.width = W; out.height = H
    const g = out.getContext('2d')!
    g.fillStyle = '#000'; g.fillRect(0, 0, W, H)
    g.drawImage(m, 0, 0)   // weiß auf schwarz
    const blob: Blob = await new Promise((r) => out.toBlob((b) => r(b!), 'image/png'))
    setBusy(true); setErr('')
    try { const r = await api.uploadMask(oid, view, blob, fill); setInfo({}); void r; onMaskChanged() }
    catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  const runSegment = async (p: number[][], n: number[][]) => {
    setBusy(true); setErr('')
    try {
      const r = await api.segment(oid, view, { pos: p, neg: n, fill_holes: fill })
      setInfo({ edge: r.touches_paper_edge, sam: r.sam_used })
      undo.current = []
      await loadMask(r.mask_url)
      onMaskChanged()
    } catch (e) { setErr(String(e).replace('Error: ', '')) } finally { setBusy(false) }
  }

  useEffect(() => { if (!photo.mask_url) void runSegment([], []) /* Auto-Vorschlag */ }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const pt = (e: React.PointerEvent): [number, number] => {
    const r = disp.current!.getBoundingClientRect()
    return [((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H]
  }
  const stroke = (a: [number, number], b: [number, number]) => {
    const g = maskC.current!.getContext('2d')!
    g.globalCompositeOperation = mode === 'erase' ? 'destination-out' : 'source-over'
    g.strokeStyle = g.fillStyle = '#fff'
    g.lineCap = 'round'; g.lineWidth = radius * 2 * PX_PER_MM_VIEW
    g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke()
    g.globalCompositeOperation = 'source-over'
  }
  const down = (e: React.PointerEvent) => {
    const p = pt(e)
    if (mode === 'pos' || mode === 'neg') {
      const full = [p[0] / photo.view_scale!, p[1] / photo.view_scale!]
      const np = mode === 'pos' ? [...pos, full] : pos
      const nn = mode === 'neg' ? [...neg, full] : neg
      setPos(np); setNeg(nn); void runSegment(np, nn)
      return
    }
    ;(e.target as Element).setPointerCapture(e.pointerId)
    snapshot(); painting.current = true; last.current = p; stroke(p, p); redraw()
  }
  const move = (e: React.PointerEvent) => {
    if (!painting.current) return
    const p = pt(e); stroke(last.current!, p); last.current = p
    requestAnimationFrame(redraw)
  }
  const up = () => { if (painting.current) { painting.current = false; void upload() } }

  const tools: [Mode, string, React.ReactNode][] = [
    ['pos', 'Auswählen', <PlusCircle size={16} />], ['neg', 'Entfernen', <MinusCircle size={16} />],
    ['brush', 'Pinsel', <PaintBrush size={16} />], ['erase', 'Radierer', <Eraser size={16} />],
  ]
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {tools.map(([m, label, icon]) => (
          <button key={m} className={`btn btn-sm ${mode === m ? 'btn-on' : ''}`} onClick={() => setMode(m)}>{icon} {label}</button>
        ))}
        <button className="btn btn-sm" onClick={restore} disabled={!undo.current.length}><ArrowCounterClockwise size={16} /> Rückgängig</button>
        <button className="btn btn-sm btn-quiet" onClick={() => { setPos([]); setNeg([]); void runSegment([], []) }}>Auto-Vorschlag neu</button>
        <div className="flex items-center gap-2 ml-2">
          <span className="text-xs" style={{ color: 'var(--ink-2)' }}>Pinsel</span>
          <input type="range" min={0.5} max={15} step={0.5} value={radius} onChange={(e) => setRadius(+e.target.value)} aria-label="Pinselradius" />
          <span className="num text-xs">{radius} mm</span>
        </div>
        <div className="flex items-center gap-1 ml-2">
          {[1, 2, 4].map((z) => <button key={z} className={`btn btn-sm ${zoom === z ? 'btn-on' : ''}`} onClick={() => setZoom(z)}>{z}x</button>)}
        </div>
        <Check label="Löcher füllen" checked={fill} onChange={(v) => { setFill(v); }} />
      </div>
      <div className="overflow-auto panel" style={{ maxHeight: '68vh' }}>
        <canvas ref={disp} width={W} height={H}
          style={{ width: `${zoom * 100}%`, display: 'block', touchAction: 'none', cursor: mode === 'pos' || mode === 'neg' ? 'crosshair' : 'cell' }}
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} />
      </div>
      {busy && <div className="hint">Verarbeite …</div>}
      {err && <div className="msg msg-err">{err}</div>}
      <Msgs items={[
        ...(info.edge ? ['Die Maske berührt den Blattrand: Werkzeug ragt über das Blatt oder Hintergrund wurde erfasst.'] : []),
      ]} />
      <div className="hint">
        Grün = Auswahl, rot = Entfernen (je ein Klick). Fingerreste mit dem Radierer wegnehmen. Die orange Fläche ist die spätere Kontur.
        {info.sam ? ' (SAM aktiv)' : ''}
      </div>
    </div>
  )
}
