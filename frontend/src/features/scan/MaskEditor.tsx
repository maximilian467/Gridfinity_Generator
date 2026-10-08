import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ArrowCounterClockwise, BezierCurve, Eraser, Hand, MagicWand, MagnifyingGlassMinus, MagnifyingGlassPlus, MinusCircle, PaintBrush, PlusCircle } from '@phosphor-icons/react'
import { api, type SegmentResult } from '../../lib/api'
import type { PhotoMeta } from '../../lib/types'
import { BusyBar, Check, Msg, errText } from '../../components/ui'

type Mode = 'points' | 'pos' | 'neg' | 'brush' | 'erase'
const PX_PER_MM_VIEW = 5   // entzerrtes Anzeigebild: 0.5 * 10 px/mm

function loadImg(url: string): Promise<HTMLImageElement> {
  return new Promise((res, rej) => {
    const i = new window.Image()
    i.onload = () => res(i)
    i.onerror = rej
    i.src = url
  })
}

/** Maske (weiß auf schwarz) -> Canvas mit Alpha = Maske. */
async function maskCanvas(url: string | undefined | null, W: number, H: number): Promise<HTMLCanvasElement> {
  const m = document.createElement('canvas'); m.width = W; m.height = H
  if (!url) return m
  const g = m.getContext('2d')!
  const im = await loadImg(url + '?t=' + Date.now())
  g.drawImage(im, 0, 0, W, H)
  const d = g.getImageData(0, 0, W, H)
  for (let i = 0; i < d.data.length; i += 4) { const v = d.data[i] > 127 ? 255 : 0; d.data[i] = d.data[i + 1] = d.data[i + 2] = 255; d.data[i + 3] = v }
  g.putImageData(d, 0, 0)
  return m
}

function tinted(src: HTMLCanvasElement, fill: string | CanvasPattern): HTMLCanvasElement {
  const t = document.createElement('canvas'); t.width = src.width; t.height = src.height
  const g = t.getContext('2d')!
  g.drawImage(src, 0, 0)
  g.globalCompositeOperation = 'source-in'
  g.fillStyle = fill
  g.fillRect(0, 0, t.width, t.height)
  return t
}

function stripes(ctx: CanvasRenderingContext2D): CanvasPattern {
  const p = document.createElement('canvas'); p.width = 12; p.height = 12
  const g = p.getContext('2d')!
  g.fillStyle = 'rgba(60,60,60,0.25)'; g.fillRect(0, 0, 12, 12)
  g.strokeStyle = 'rgba(40,40,40,0.75)'; g.lineWidth = 3
  g.beginPath(); g.moveTo(-3, 15); g.lineTo(15, -3); g.stroke()
  return ctx.createPattern(p, 'repeat')!
}

export function MaskEditor({ oid, view, photo, hasTopMask, onMaskChanged, onBusy, onResult }: {
  oid: string; view: 'top' | 'side'; photo: PhotoMeta; hasTopMask: boolean
  onMaskChanged: () => void; onBusy?: (b: boolean) => void; onResult?: (r: SegmentResult) => void
}) {
  const [W, H] = [Math.round(photo.rect_size![0] * photo.view_scale!), Math.round(photo.rect_size![1] * photo.view_scale!)]
  const disp = useRef<HTMLCanvasElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const maskC = useRef<HTMLCanvasElement | null>(null)
  const handC = useRef<HTMLCanvasElement | null>(null)
  const bg = useRef<HTMLImageElement | null>(null)
  const undo = useRef<Uint8Array[]>([])
  const undoPoly = useRef<number[][][]>([])
  const [mode, setMode] = useState<Mode>('points')
  const poly = useRef<number[][]>(photo.edit_contour_px ?? [])
  const dragIdx = useRef<number | null>(null)
  const [radius, setRadius] = useState(3)
  const [zoom, setZoom] = useState(1)
  const [fill, setFill] = useState(photo.fill_holes ?? true)
  const [removeHand, setRemoveHand] = useState(true)
  const [pos, setPos] = useState<number[][]>([])
  const [neg, setNeg] = useState<number[][]>([])
  const [busy, setBusyState] = useState(false)
  const [err, setErr] = useState('')
  const [info, setInfo] = useState<SegmentResult | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [tick, setTick] = useState(0)
  const [undoN, setUndoN] = useState(0)
  const painting = useRef(false)
  const last = useRef<[number, number] | null>(null)
  const setBusy = (b: boolean) => { setBusyState(b); onBusy?.(b) }

  const redraw = useCallback(() => {
    const c = disp.current
    if (!c || !bg.current) return
    const g = c.getContext('2d')!
    g.clearRect(0, 0, W, H)
    g.drawImage(bg.current, 0, 0, W, H)
    if (handC.current) g.drawImage(tinted(handC.current, stripes(g)), 0, 0)
    if (maskC.current) {
      g.drawImage(tinted(maskC.current, mode === 'points' ? 'rgba(255,106,31,0.18)' : 'rgba(255,106,31,0.55)'), 0, 0)
    }
    const P = poly.current
    if (mode === 'points' && P.length > 2) {
      const sc = c.clientWidth ? c.width / c.clientWidth : 1          // Canvas-px je Bildschirm-px
      g.lineJoin = 'round'
      g.strokeStyle = '#ff6a1f'; g.lineWidth = 2.5 * sc
      g.beginPath(); P.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); g.stroke()
      for (let i = 0; i < P.length; i++) {
        const [x, y] = P[i]
        g.fillStyle = i === dragIdx.current ? '#ff6a1f' : '#ffffff'
        g.strokeStyle = '#c2410c'; g.lineWidth = 2 * sc
        g.beginPath(); g.arc(x, y, 5 * sc, 0, 7); g.fill(); g.stroke()
      }
    }
    g.lineWidth = 3
    for (const [list, col] of [[pos, '#1f9d55'], [neg, '#e5322d']] as const) {
      for (const p of list) {
        const x = p[0] * photo.view_scale!, y = p[1] * photo.view_scale!
        g.fillStyle = '#fff'; g.beginPath(); g.arc(x, y, 10, 0, 7); g.fill()
        g.strokeStyle = col; g.beginPath(); g.arc(x, y, 10, 0, 7); g.stroke()
        g.beginPath(); g.moveTo(x - 5, y); g.lineTo(x + 5, y); if (col === '#1f9d55') { g.moveTo(x, y - 5); g.lineTo(x, y + 5) } g.stroke()
      }
    }
  }, [W, H, pos, neg, photo.view_scale, mode])

  const loadMasks = useCallback(async (maskUrl?: string | null, handUrl?: string | null) => {
    maskC.current = await maskCanvas(maskUrl, W, H)
    handC.current = handUrl ? await maskCanvas(handUrl, W, H) : null
    setTick((t) => t + 1)
  }, [W, H])

  const runSegment = useCallback(async (p: number[][], n: number[][], rh = removeHand, fh = fill) => {
    setBusy(true); setErr('')
    try {
      const r = await api.segment(oid, view, { pos: p, neg: n, fill_holes: fh, remove_hand: rh })
      setInfo(r); onResult?.(r)
      poly.current = r.edit_contour_px ?? []
      undo.current = []; setUndoN(0)
      await loadMasks(r.mask_url, r.hand_url)
      onMaskChanged()
    } catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }, [oid, view, removeHand, fill, loadMasks, onMaskChanged]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        bg.current = await loadImg(photo.rectified_url! + '?t=' + Date.now())
      } catch { setErr('Entzerrtes Bild konnte nicht geladen werden. Backend erreichbar?'); return }
      if (!alive) return
      setLoaded(true)
      if (photo.mask_url) {
        await loadMasks(photo.mask_url, photo.hand_url)
        if (!poly.current.length) await upload()          // Editierpunkte für ältere Masken nachholen
      } else {
        await runSegment([], [])                          // automatischer Vorschlag beim ersten Öffnen
      }
      fitToTool()
    })()
    return () => { alive = false }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { redraw() }, [redraw, tick, loaded])

  const fitToTool = () => {
    const P = poly.current, box = scroller.current
    if (P.length < 3 || !box) return
    const xs = P.map((q) => q[0]), ys = P.map((q) => q[1])
    const bw = Math.max(...xs) - Math.min(...xs), bh = Math.max(...ys) - Math.min(...ys)
    const z = Math.round(Math.max(1, Math.min(4, 0.85 * W / bw, 0.7 * H / Math.max(bh, 1))) * 10) / 10
    setZoom(z)
    requestAnimationFrame(() => {
      const f = (box.clientWidth * z) / W
      box.scrollLeft = ((Math.min(...xs) + Math.max(...xs)) / 2) * f - box.clientWidth / 2
      box.scrollTop = ((Math.min(...ys) + Math.max(...ys)) / 2) * f - box.clientHeight / 2
      redraw()
    })
  }

  const snapshot = () => {
    const d = maskC.current!.getContext('2d')!.getImageData(0, 0, W, H).data
    const a = new Uint8Array(W * H)
    for (let i = 0; i < a.length; i++) a[i] = d[i * 4 + 3]
    undo.current.push(a)
    undoPoly.current.push(poly.current.map((q) => [...q]))
    if (undo.current.length > 15) { undo.current.shift(); undoPoly.current.shift() }
    setUndoN(undo.current.length)
  }
  const upload = async (keepPoints = false) => {
    const out = document.createElement('canvas'); out.width = W; out.height = H
    const g = out.getContext('2d')!
    g.fillStyle = '#000'; g.fillRect(0, 0, W, H)
    g.drawImage(maskC.current!, 0, 0)
    const blob: Blob = await new Promise((r) => out.toBlob((b) => r(b!), 'image/png'))
    setBusy(true); setErr('')
    try {
      const r = await api.uploadMask(oid, view, blob, fill)
      if (r.edit_contour_px && !keepPoints) poly.current = r.edit_contour_px
      setTick((t) => t + 1); onMaskChanged()
    }
    catch (e) { setErr(errText(e)) } finally { setBusy(false) }
  }
  const restore = async () => {
    const a = undo.current.pop()
    const pp = undoPoly.current.pop()
    if (pp) poly.current = pp
    setUndoN(undo.current.length)
    if (!a || !maskC.current) return
    const g = maskC.current.getContext('2d')!
    const d = g.createImageData(W, H)
    for (let i = 0; i < a.length; i++) { d.data[i * 4] = d.data[i * 4 + 1] = d.data[i * 4 + 2] = 255; d.data[i * 4 + 3] = a[i] }
    g.putImageData(d, 0, 0)
    redraw(); await upload(mode === 'points')
  }

  const pt = (e: React.PointerEvent): [number, number] => {
    const r = disp.current!.getBoundingClientRect()
    return [((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H]
  }
  const stroke = (a: [number, number], b: [number, number]) => {
    const g = maskC.current!.getContext('2d')!
    g.globalCompositeOperation = mode === 'erase' ? 'destination-out' : 'source-over'
    g.strokeStyle = '#fff'
    g.lineCap = 'round'; g.lineWidth = radius * 2 * PX_PER_MM_VIEW
    g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke()
    g.globalCompositeOperation = 'source-over'
  }
  const rasterize = () => {
    const g = maskC.current!.getContext('2d')!
    g.clearRect(0, 0, W, H)
    g.fillStyle = '#fff'
    g.beginPath(); poly.current.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); g.fill()
  }
  const hit = (p: [number, number]) => {
    const sc = disp.current!.width / disp.current!.clientWidth
    const R = 9 * sc
    const P = poly.current
    let best = -1, bd = R
    P.forEach(([x, y], i) => { const d = Math.hypot(x - p[0], y - p[1]); if (d < bd) { bd = d; best = i } })
    if (best >= 0) return { kind: 'vertex' as const, i: best }
    for (let i = 0; i < P.length; i++) {            // Nähe zu einer Kante -> Punkt einfügen
      const a = P[i], b = P[(i + 1) % P.length]
      const dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy || 1
      const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
      if (Math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1]) < R * 0.8) return { kind: 'edge' as const, i }
    }
    return null
  }
  const down = (e: React.PointerEvent) => {
    if (busy || !maskC.current) return
    const p = pt(e)
    if (mode === 'points') {
      const h = hit(p)
      if (!h) return
      if (h.kind === 'vertex' && (e.button === 2 || e.altKey)) {          // Punkt löschen
        if (poly.current.length > 3) { snapshot(); poly.current = poly.current.filter((_, i) => i !== h.i); rasterize(); redraw(); void upload(true) }
        return
      }
      snapshot()
      if (h.kind === 'edge') { poly.current = [...poly.current.slice(0, h.i + 1), [p[0], p[1]], ...poly.current.slice(h.i + 1)]; dragIdx.current = h.i + 1 }
      else dragIdx.current = h.i
      ;(e.target as Element).setPointerCapture(e.pointerId)
      redraw()
      return
    }
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
    if (dragIdx.current !== null) {
      const p = pt(e)
      poly.current = poly.current.map((q, i) => (i === dragIdx.current ? [p[0], p[1]] : q))
      requestAnimationFrame(redraw)
      return
    }
    if (!painting.current) return
    const p = pt(e); stroke(last.current!, p); last.current = p
    requestAnimationFrame(redraw)
  }
  const up = () => {
    if (dragIdx.current !== null) { dragIdx.current = null; rasterize(); redraw(); void upload(true); return }
    if (painting.current) { painting.current = false; void upload() }
  }

  const tool = (m: Mode, label: string, icon: ReactNode, hint: string) => (
    <button className={`btn justify-start ${mode === m ? 'btn-on' : ''}`} onClick={() => setMode(m)} title={hint} aria-pressed={mode === m}>
      {icon} {label}
    </button>
  )

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
      <div className="grid grid-cols-[minmax(0,1fr)] gap-2 min-w-0">
        <div ref={scroller} className="relative panel overflow-auto" style={{ maxHeight: '64vh' }}>
          <canvas ref={disp} width={W} height={H}
            style={{ width: `${zoom * 100}%`, display: 'block', touchAction: 'none',
              cursor: busy ? 'progress' : mode === 'points' ? 'pointer' : mode === 'pos' || mode === 'neg' ? 'crosshair' : 'cell' }}
            onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
            onContextMenu={(e) => e.preventDefault()} />
          {(busy || !loaded) && (
            <div className="absolute inset-x-0 top-0 p-3" style={{ background: 'color-mix(in srgb, var(--surface) 85%, transparent)' }}>
              <BusyBar label={loaded ? 'Erkenne Umriss …' : 'Lade Bild …'} />
            </div>
          )}
        </div>
        {err && <Msg kind="err">{err}</Msg>}
      </div>

      <aside className="grid grid-cols-[minmax(0,1fr)] gap-4 content-start">
        <section className="grid grid-cols-[minmax(0,1fr)] gap-2">
          <h2 className="sect">Legende</h2>
          <div className="flex items-center gap-2 text-sm"><span className="swatch" style={{ background: 'rgba(255,106,31,0.75)' }} /> Werkzeug-Umriss (wird zur Tasche)</div>
          <div className="flex items-center gap-2 text-sm"><span className="swatch" style={{ background: '#fff', border: '2px solid #c2410c', borderRadius: 99 }} /> ziehbarer Konturpunkt</div>
          {view === 'side' && <div className="flex items-center gap-2 text-sm"><span className="swatch" style={{ background: 'repeating-linear-gradient(45deg,#555 0 3px,#bbb 3px 6px)' }} /> Hand, automatisch entfernt</div>}
          <div className="flex items-center gap-2 text-sm"><PlusCircle size={14} color="#1f9d55" /> / <MinusCircle size={14} color="#e5322d" /> gesetzte Klicks</div>
        </section>

        <section className="grid grid-cols-[minmax(0,1fr)] gap-2">
          <h2 className="sect">Korrigieren</h2>
          {tool('points', 'Punkte verschieben', <BezierCurve size={16} />, 'Punkte der Kontur ziehen; Klick auf die Linie fügt einen Punkt ein, Rechtsklick löscht')}
          {mode === 'points' && <div className="hint mt-0">Punkt ziehen = verschieben. Klick auf die Linie = Punkt einfügen. Rechtsklick (oder Alt+Klick) = Punkt löschen.</div>}
          {tool('pos', 'Auswählen', <PlusCircle size={16} />, 'Klick auf einen Teil des Werkzeugs, der fehlt')}
          {tool('neg', 'Entfernen', <MinusCircle size={16} />, 'Klick auf etwas, das fälschlich dazugehört')}
          {tool('brush', 'Pinsel', <PaintBrush size={16} />, 'Fläche von Hand hinzufügen')}
          {tool('erase', 'Radierer', <Eraser size={16} />, 'Fläche von Hand wegnehmen')}
          {(mode === 'brush' || mode === 'erase') && (
            <label className="grid grid-cols-[minmax(0,1fr)] gap-1 text-sm">Pinselgröße <span className="num">{radius} mm</span>
              <input type="range" min={0.5} max={15} step={0.5} value={radius} onChange={(e) => setRadius(+e.target.value)} />
            </label>
          )}
          <div className="flex gap-2">
            <button className="btn btn-sm flex-1" onClick={restore} disabled={!undoN || busy}><ArrowCounterClockwise size={14} /> Rückgängig</button>
            <button className="btn btn-sm flex-1" disabled={busy}
              onClick={() => { setPos([]); setNeg([]); void runSegment([], []) }}><MagicWand size={14} /> Neu erkennen</button>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm" style={{ color: 'var(--ink-2)' }}>Zoom</span>
            <button className="btn btn-sm" onClick={() => setZoom((z) => Math.max(1, Math.round(z / 1.5 * 10) / 10))} disabled={zoom <= 1} aria-label="Verkleinern"><MagnifyingGlassMinus size={14} /></button>
            <span className="num text-sm w-10 text-center">{zoom.toFixed(1)}x</span>
            <button className="btn btn-sm" onClick={() => setZoom((z) => Math.min(4, Math.round(z * 1.5 * 10) / 10))} disabled={zoom >= 4} aria-label="Vergrößern"><MagnifyingGlassPlus size={14} /></button>
            <button className="btn btn-sm" onClick={fitToTool} disabled={poly.current.length < 3}>Auf Werkzeug</button>
          </div>
        </section>

        <section className="grid grid-cols-[minmax(0,1fr)] gap-2">
          <h2 className="sect">Optionen</h2>
          <Check label="Löcher im Umriss füllen" checked={fill} onChange={(v) => { setFill(v); void runSegment(pos, neg, removeHand, v) }} />
          {view === 'side' && (
            <>
              <Check label="Hand automatisch entfernen" checked={removeHand} onChange={(v) => { setRemoveHand(v); void runSegment(pos, neg, v) }} />
              {!hasTopMask && <div className="hint">Braucht den Umriss der Draufsicht (Farbmodell des Werkzeugs).</div>}
            </>
          )}
        </section>

        {info && (
          <section className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
            <h2 className="sect">Ergebnis</h2>
            {info.hand_removed && <Msg kind="ok"><span className="inline-flex items-center gap-1"><Hand size={14} /> Hand erkannt und entfernt.</span></Msg>}
            {info.touches_paper_edge && <Msg kind="warn">Der Umriss berührt den Blattrand. Ragt das Werkzeug über das Blatt? Dann geht die Kontur dort verloren.</Msg>}
            {info.area_mm2 !== undefined && <div className="hint num">Fläche {Math.round(info.area_mm2)} mm²{info.sam_used ? ' · KI-Segmentierung (SAM)' : ''}</div>}
          </section>
        )}
      </aside>
    </div>
  )
}
