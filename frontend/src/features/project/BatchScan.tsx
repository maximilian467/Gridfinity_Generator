import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { ArrowsLeftRight, CaretLeft, CaretRight, CheckCircle, Images, PencilSimple, Plus, Trash, UploadSimple, X, XCircle } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { ScanItem } from '../../lib/types'
import { BusyBar, Msg, errText } from '../../components/ui'

/** Stapel-Scan: viele Fotos auf einmal, je Werkzeug Draufsicht + Seitenansicht (nach Aufnahmezeit gepaart).
 *  Die Paare werden einzeln hochgeladen; der Server wertet sie in einem Hintergrund-Job aus und erzeugt
 *  danach die Einlagen nach der Projektvorlage. Fehlgeschlagene Werkzeuge gehen in den Scan-Assistenten. */

interface Photo { key: string; file: File; url: string; time: number | null }
type Upload = { state: 'wait' | 'busy' | 'ok' | 'err'; id?: string; error?: string }

const STEP_LABEL: Record<NonNullable<ScanItem['step']>, string> = {
  a4: 'sucht das A4-Blatt', top: 'stellt die Draufsicht frei', side: 'stellt die Seitenansicht frei', profile: 'berechnet das Profil',
}

/** Aufnahmezeit aus EXIF (DateTimeOriginal + Sekundenbruchteil) in ms, sonst null. */
async function captureTime(f: File): Promise<number | null> {
  try {
    const b = new DataView(await f.slice(0, 256 * 1024).arrayBuffer())
    if (b.getUint16(0) !== 0xffd8) return null                    // kein JPEG
    let o = 2
    while (o + 4 < b.byteLength) {
      const m = b.getUint16(o)
      if (m === 0xffe1 && b.getUint32(o + 4) === 0x45786966) return tiffTime(b, o + 10)   // APP1 "Exif"
      if ((m & 0xff00) !== 0xff00 || m === 0xffda) return null
      o += 2 + b.getUint16(o + 2)
    }
  } catch { /* kein oder kaputtes EXIF */ }
  return null
}

function tiffTime(b: DataView, t: number): number | null {
  const le = b.getUint16(t) === 0x4949
  const u16 = (p: number) => b.getUint16(p, le), u32 = (p: number) => b.getUint32(p, le)
  const ifd = (start: number) => {
    const out = new Map<number, number>()
    for (let i = 0, n = u16(start); i < n; i++) out.set(u16(start + 2 + i * 12), start + 2 + i * 12)
    return out
  }
  const ascii = (e: number) => {
    const n = u32(e + 4), p = n > 4 ? t + u32(e + 8) : e + 8
    let s = ''
    for (let i = 0; i < n - 1; i++) s += String.fromCharCode(b.getUint8(p + i))
    return s
  }
  const ifd0 = ifd(t + u32(t + 4))
  let date: string | null = null, sub = ''
  const ptr = ifd0.get(0x8769)
  if (ptr !== undefined) {
    const ex = ifd(t + u32(ptr + 8))
    if (ex.has(0x9003)) date = ascii(ex.get(0x9003)!)
    if (ex.has(0x9291)) sub = ascii(ex.get(0x9291)!).replace(/\D/g, '')
  }
  if (!date && ifd0.has(0x0132)) date = ascii(ifd0.get(0x0132)!)
  const m = date?.match(/(\d{4}):(\d\d):(\d\d) (\d\d):(\d\d):(\d\d)/)
  if (!m) return null
  return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]).getTime() + (sub ? Number('0.' + sub) * 1000 : 0)
}

function byTime(a: Photo, b: Photo) {
  const d = (a.time ?? a.file.lastModified) - (b.time ?? b.file.lastModified)
  return d || a.file.name.localeCompare(b.file.name, undefined, { numeric: true })
}

const storeKey = (pid: string) => `batch-scan:${pid}`
function loadRun(pid: string): { jobId: string } | null {
  try { return JSON.parse(sessionStorage.getItem(storeKey(pid)) ?? 'null') } catch { return null }
}

export function BatchScan({ pid, firstNumber, onChanged, onClose }: {
  pid: string; firstNumber: number; onChanged: () => void; onClose: () => void
}) {
  const nav = useNavigate()
  const [photos, setPhotos] = useState<Photo[]>([])
  const [names, setNames] = useState<Record<number, string>>({})
  const [uploads, setUploads] = useState<Record<number, Upload>>({})
  const [phase, setPhase] = useState<'pick' | 'upload' | 'job'>(() => (loadRun(pid) ? 'job' : 'pick'))
  const [jobId, setJobId] = useState<string | null>(() => loadRun(pid)?.jobId ?? null)
  const [thumbs, setThumbs] = useState<Record<string, string>>({})     // Werkzeug-ID -> Vorschaubild (nur in dieser Sitzung)
  const [startErr, setStartErr] = useState<string | null>(null)
  const [drag, setDrag] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const urls = useRef<string[]>([])
  useEffect(() => () => urls.current.forEach((u) => URL.revokeObjectURL(u)), [])

  const add = async (files: FileList | File[] | null | undefined) => {
    const list = Array.from(files ?? []).filter((f) => /^image\//.test(f.type) || /\.(jpe?g|png|webp)$/i.test(f.name))
    const fresh = await Promise.all(list.map(async (file) => {
      const url = URL.createObjectURL(file)
      urls.current.push(url)
      return { key: `${file.name}-${file.size}-${file.lastModified}-${Math.random()}`, file, url, time: await captureTime(file) }
    }))
    setPhotos((ps) => [...ps, ...fresh].sort(byTime))
  }
  const pairs: Photo[][] = []
  for (let i = 0; i < photos.length; i += 2) pairs.push(photos.slice(i, i + 2))
  const complete = pairs.filter((q) => q.length === 2).length
  const nameOf = (i: number) => names[i] ?? `Werkzeug ${firstNumber + i}`
  const swapAt = (a: number, b: number) => setPhotos((ps) => {
    if (a < 0 || b < 0 || a >= ps.length || b >= ps.length) return ps
    const n = [...ps]; [n[a], n[b]] = [n[b], n[a]]; return n
  })
  const removeAt = (idx: number[]) => setPhotos((ps) => ps.filter((_, k) => !idx.includes(k)))

  const job = useQuery({
    queryKey: ['job', jobId], queryFn: () => api.job(jobId!), enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && q.state.data.status !== 'running' ? false : 1000),
  })
  const items = job.data?.items ?? []
  const nDone = items.filter((i) => i.status === 'done').length
  const finished = job.data && job.data.status !== 'running'
  useEffect(() => { if (jobId) onChanged() }, [nDone, finished]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {                                     // vergessener Job (Server-Neustart, abgelaufen)
    if (job.isError && phase === 'job') { try { sessionStorage.removeItem(storeKey(pid)) } catch { /* egal */ } }
  }, [job.isError]) // eslint-disable-line react-hooks/exhaustive-deps

  const start = async (ids: string[]) => {
    setStartErr(null)
    try {
      const r = await api.batchScan(pid, ids)
      setJobId(r.job_id)
      setPhase('job')
      try { sessionStorage.setItem(storeKey(pid), JSON.stringify({ jobId: r.job_id })) } catch { /* privat */ }
    } catch (e) { setStartErr(errText(e)) }
  }

  const run = async () => {
    setPhase('upload')
    const ids: string[] = [], th: Record<string, string> = {}
    const ups: Record<number, Upload> = {}
    pairs.forEach((q, i) => { if (q.length === 2) ups[i] = { state: 'wait' } })
    setUploads({ ...ups })
    for (let i = 0; i < pairs.length; i++) {
      const q = pairs[i]
      if (q.length !== 2) continue
      setUploads((u) => ({ ...u, [i]: { state: 'busy' } }))
      try {
        const r = await api.scanPair(pid, q[0].file, q[1].file, nameOf(i))
        ids.push(r.id); th[r.id] = q[0].url
        setUploads((u) => ({ ...u, [i]: { state: 'ok', id: r.id } }))
      } catch (e) {
        setUploads((u) => ({ ...u, [i]: { state: 'err', error: errText(e) } }))
      }
    }
    setThumbs(th)
    onChanged()
    if (ids.length) await start(ids)
    else setStartErr('Kein Fotopaar konnte hochgeladen werden.')
  }

  const reset = () => {
    try { sessionStorage.removeItem(storeKey(pid)) } catch { /* egal */ }
    setPhotos([]); setNames({}); setUploads({}); setJobId(null); setThumbs({}); setStartErr(null); setPhase('pick')
  }
  const close = () => { if (finished || phase === 'pick') reset(); onClose() }
  const uploadedIds = Object.values(uploads).filter((u) => u.state === 'ok').map((u) => u.id!)
  const gen = job.data?.checks?.generate as { created?: string[]; left_out_names?: string[] } | undefined

  return (
    <section className="panel p-4 grid gap-4" aria-label="Stapel-Scan">
      <div className="flex items-start gap-3">
        <Images size={26} weight="duotone" color="var(--accent)" className="mt-0.5 flex-none" />
        <div className="grid gap-1 flex-1 min-w-0">
          <h3 className="text-base font-semibold">Viele Werkzeuge auf einmal scannen</h3>
          <p className="text-sm m-0" style={{ color: 'var(--ink-2)', maxWidth: '75ch' }}>
            Je Werkzeug zwei Fotos auf dem A4-Blatt: zuerst von oben (Draufsicht), dann hochkant von der Seite (Seitenansicht).
            Die Fotos werden nach Aufnahmezeit sortiert und paarweise zugeordnet. Danach entstehen die Einlagen nach der Vorlage und werden in der Schublade angeordnet.
          </p>
        </div>
        <button className="btn btn-sm btn-quiet" onClick={close} title={finished || phase === 'pick' ? 'Schließen' : 'Ausblenden (läuft weiter)'}><X size={16} /></button>
      </div>

      {phase === 'pick' && (
        <>
          <div className="grid place-items-center text-center p-6 gap-2 rounded-[var(--radius)]"
            style={{ border: `2px dashed ${drag ? 'var(--accent)' : 'var(--line-2)'}`, background: drag ? 'var(--accent-soft)' : 'var(--surface-2)' }}
            onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); add(e.dataTransfer.files) }}>
            <UploadSimple size={30} color="var(--ink-3)" />
            <div className="font-semibold">{photos.length ? 'Weitere Fotos hierher ziehen' : 'Alle Fotos hierher ziehen'}</div>
            <input ref={input} type="file" accept="image/*" multiple hidden onChange={(e) => { add(e.target.files); e.target.value = '' }} />
            <button className="btn btn-sm" onClick={() => input.current?.click()}>
              {photos.length ? <><Plus size={14} /> Weitere Fotos</> : <><UploadSimple size={14} /> Fotos auswählen</>}</button>
          </div>
          {pairs.length > 0 && (
            <div className="grid gap-2">
              {pairs.map((q, i) => (
                <PairRow key={q.map((x) => x.key).join('|')} n={i + 1} pair={q} name={nameOf(i)}
                  onName={(v) => setNames((s) => ({ ...s, [i]: v }))}
                  onSwap={() => swapAt(2 * i, 2 * i + 1)} onMove={(k, d) => swapAt(2 * i + k, 2 * i + k + d)}
                  onRemovePhoto={(k) => removeAt([2 * i + k])} onRemove={() => removeAt([2 * i, 2 * i + 1])}
                  canLeft={(k) => 2 * i + k > 0} canRight={(k) => 2 * i + k < photos.length - 1} />
              ))}
              {photos.length % 2 === 1 && <Msg kind="warn">Ungerade Anzahl Fotos: Das letzte Foto hat keinen Partner und wird nicht ausgewertet. Mit den Pfeilen verschieben oder ein Foto entfernen.</Msg>}
              <div className="hint mt-0">Fehlt irgendwo ein Foto, verrutschen alle Paare danach: das überzählige Foto entfernen oder mit den Pfeilen verschieben. „Tauschen“ dreht Draufsicht und Seitenansicht eines Paars um.</div>
              <div className="flex flex-wrap gap-2 items-center">
                <button className="btn btn-primary" disabled={!complete} onClick={run}>
                  <CheckCircle size={16} /> {complete} {complete === 1 ? 'Werkzeug' : 'Werkzeuge'} auswerten</button>
                <button className="btn btn-quiet" onClick={reset}>Alle verwerfen</button>
              </div>
            </div>
          )}
        </>
      )}

      {phase === 'upload' && (
        <div className="grid gap-2">
          <BusyBar label={`Lade Fotopaare hoch: ${Object.values(uploads).filter((u) => u.state === 'ok' || u.state === 'err').length} von ${Object.keys(uploads).length}`} />
          <ul className="grid gap-1 m-0 p-0 list-none">
            {pairs.map((q, i) => uploads[i] && (
              <li key={i} className="flex items-center gap-3 text-sm">
                <img src={q[0].url} alt="" className="w-12 h-9 object-cover rounded" loading="lazy" />
                <span className="flex-1 truncate">{nameOf(i)}</span>
                <UploadChip u={uploads[i]} />
              </li>
            ))}
          </ul>
          {startErr && (
            <Msg kind="err">{startErr}
              {uploadedIds.length > 0 && <button className="btn btn-sm ml-2" onClick={() => start(uploadedIds)}>Auswertung erneut starten</button>}
            </Msg>
          )}
        </div>
      )}

      {phase === 'job' && (
        <div className="grid gap-3">
          {job.isError && <Msg kind="err">Der Stapel-Scan ist nicht mehr bekannt (Server neu gestartet?). Unfertige Werkzeuge lassen sich im Scan-Assistenten fertig machen.</Msg>}
          {job.data && !items.length && !finished && <BusyBar label="Starte die Auswertung …" />}
          {job.data && (items.length > 0 || finished) && (
            <>
              <div className="grid gap-1.5" aria-live="polite">
                <div className="flex items-baseline gap-2 text-sm">
                  <span className="font-semibold">{finished ? 'Stapel-Scan beendet' : 'Werte aus …'}</span>
                  <span className="num" style={{ color: 'var(--ink-2)' }}>{nDone} von {items.length} fertig{items.some((i) => i.status === 'error') ? ` · ${items.filter((i) => i.status === 'error').length} mit Fehler` : ''}</span>
                </div>
                <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--accent-soft)' }}>
                  <div className="h-full rounded-full" style={{ width: `${Math.round((finished ? 1 : job.data.progress) * 100)}%`, background: 'var(--accent)', transition: 'width .4s ease' }} />
                </div>
              </div>
              <ul className="grid gap-1.5 m-0 p-0 list-none">
                {items.map((it) => (
                  <li key={it.id} className="grid grid-cols-[48px_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 text-sm">
                    {thumbs[it.id] ? <img src={thumbs[it.id]} alt="" className="w-12 h-9 object-cover rounded" loading="lazy" />
                      : <span className="w-12 h-9 rounded" style={{ background: 'var(--surface-2)' }} />}
                    <span className="truncate font-medium">{it.name || '…'}</span>
                    <ItemChip it={it} />
                    {(it.error || it.warnings.length > 0) && (
                      <div className="col-start-2 col-span-2 flex flex-wrap items-center gap-2 text-xs">
                        {it.error && <span style={{ color: 'var(--err)' }}>{it.error}</span>}
                        {it.warnings.map((w) => <span key={w} style={{ color: 'var(--warn)' }}>{w}</span>)}
                        {(it.error || it.warnings.length > 0) && finished && (
                          <button className="btn btn-sm" onClick={() => nav(`/scan/${it.id}`)}><PencilSimple size={14} /> Im Scan-Assistenten bearbeiten</button>
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
              {job.data.status === 'error' && <Msg kind="err">{job.data.error}</Msg>}
              {job.data.warnings.map((w) => <Msg key={w} kind="warn">{w}</Msg>)}
              {job.data.status === 'done' && (
                <Msg kind={items.some((i) => i.status === 'error') || gen?.left_out_names?.length ? 'warn' : 'ok'}>
                  {nDone} {nDone === 1 ? 'Werkzeug' : 'Werkzeuge'} ausgewertet, {gen?.created?.length ?? 0} Einlage(n) nach der Vorlage erzeugt und angeordnet.
                  {items.some((i) => i.status === 'error') && ' Nicht fertige Werkzeuge im Scan-Assistenten nacharbeiten, danach an der Werkzeugkarte „Einlage“ wählen.'}
                  {gen?.left_out_names?.length ? ` Passt nicht mehr in die Schublade: ${gen.left_out_names.join(', ')}.` : ''}
                </Msg>
              )}
              {finished && <div><button className="btn btn-sm" onClick={reset}><Plus size={14} /> Neuer Stapel</button></div>}
            </>
          )}
          {!job.data && !job.isError && <BusyBar />}
        </div>
      )}
    </section>
  )
}

function PairRow({ n, pair, name, onName, onSwap, onMove, onRemovePhoto, onRemove, canLeft, canRight }: {
  n: number; pair: Photo[]; name: string; onName: (v: string) => void; onSwap: () => void
  onMove: (k: number, d: -1 | 1) => void; onRemovePhoto: (k: number) => void; onRemove: () => void
  canLeft: (k: number) => boolean; canRight: (k: number) => boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 p-2 rounded-[var(--radius)]" style={{ border: '1px solid var(--line)' }}>
      <span className="num w-6 text-right text-sm" style={{ color: 'var(--ink-3)' }}>{n}</span>
      <input className="input" style={{ width: 'min(220px, 100%)' }} value={name} maxLength={120} onChange={(e) => onName(e.target.value)} aria-label={`Name Werkzeug ${n}`} />
      <div className="flex items-center gap-2">
        {[0, 1].map((k) => (
          <div key={k} className="flex items-center gap-2">
            {k === 1 && <button className="btn btn-sm btn-quiet" onClick={onSwap} disabled={pair.length < 2} title="Draufsicht und Seitenansicht tauschen" aria-label="Tauschen"><ArrowsLeftRight size={16} /></button>}
            <figure className="m-0 grid gap-1">
              <figcaption className="text-xs" style={{ color: 'var(--ink-2)' }}>{k === 0 ? 'Draufsicht' : 'Seitenansicht'}</figcaption>
              {pair[k] ? (
                <div className="relative group">
                  <img src={pair[k].url} alt={pair[k].file.name} title={pair[k].file.name} loading="lazy" decoding="async"
                    className="w-28 h-20 object-cover rounded" style={{ border: '1px solid var(--line)' }} />
                  <div className="absolute inset-x-0 bottom-0 flex justify-between p-0.5">
                    <button className="thumb-btn" disabled={!canLeft(k)} onClick={() => onMove(k, -1)} title="Ein Foto nach vorn" aria-label="Nach vorn"><CaretLeft size={12} /></button>
                    <button className="thumb-btn" onClick={() => onRemovePhoto(k)} title="Foto entfernen (die Paare danach rücken nach)" aria-label="Foto entfernen"><X size={12} /></button>
                    <button className="thumb-btn" disabled={!canRight(k)} onClick={() => onMove(k, 1)} title="Ein Foto nach hinten" aria-label="Nach hinten"><CaretRight size={12} /></button>
                  </div>
                </div>
              ) : (
                <div className="w-28 h-20 rounded grid place-items-center text-xs" style={{ border: '1px dashed var(--warn)', color: 'var(--warn)' }}>fehlt</div>
              )}
            </figure>
          </div>
        ))}
      </div>
      <div className="flex-1" />
      <button className="btn btn-sm btn-quiet" onClick={onRemove} title="Paar entfernen" aria-label="Paar entfernen"><Trash size={14} /></button>
    </div>
  )
}

function UploadChip({ u }: { u: Upload }) {
  if (u.state === 'ok') return <span className="chip chip-ok text-xs"><CheckCircle size={12} /> hochgeladen</span>
  if (u.state === 'err') return <span className="chip chip-err text-xs" title={u.error}><XCircle size={12} /> {u.error}</span>
  return <span className="chip text-xs">{u.state === 'busy' ? 'lädt hoch …' : 'wartet'}</span>
}

function ItemChip({ it }: { it: ScanItem }) {
  if (it.status === 'done') return <span className="chip chip-ok text-xs num"><CheckCircle size={12} /> fertig · {it.length_mm?.toFixed(0)} x {it.width_mm?.toFixed(0)} mm</span>
  if (it.status === 'error') return <span className="chip chip-err text-xs"><XCircle size={12} /> unfertig</span>
  if (it.status === 'running') return <span className="chip text-xs" style={{ borderColor: 'var(--accent)', color: 'var(--ink)' }}><span className="pulse-dot" /> {it.step ? STEP_LABEL[it.step] : 'läuft'} …</span>
  return <span className="chip text-xs">wartet</span>
}
