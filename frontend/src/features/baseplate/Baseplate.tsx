import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { DownloadSimple } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { BaseplateSpec } from '../../lib/types'
import { Check, Msgs, NumberField } from '../../components/ui'

const BEDS: [string, number, number][] = [
  ['Bambu X1 / P1 / A1 (256 x 256)', 256, 256],
  ['Bambu A1 mini (180 x 180)', 180, 180],
  ['Prusa MK4 (250 x 210)', 250, 210],
]

export function Baseplate() {
  const [spec, setSpec] = useState<BaseplateSpec>({
    drawer_x: 500, drawer_y: 350, bed_x: 256, bed_y: 256, clearance: 0.5, magnets: false, one_sided: false,
  })
  const [jobId, setJobId] = useState<string | null>(null)
  const patch = (p: Partial<BaseplateSpec>) => setSpec((s) => ({ ...s, ...p }))
  const build = useMutation({ mutationFn: () => api.buildBaseplate(spec), onSuccess: (r) => setJobId(r.job_id) })
  const job = useQuery({
    queryKey: ['job', jobId], queryFn: () => api.job(jobId!), enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 1000 : false),
  })
  const done = job.data?.status === 'done' ? job.data : null
  const tiles = (done?.checks.tiles ?? []) as { n: number; cx: number; cy: number; w: number; h: number }[]

  return (
    <div className="max-w-[1100px] mx-auto px-4 py-6 grid gap-6 md:grid-cols-[320px_1fr]">
      <section className="panel p-4 grid gap-3 content-start">
        <h1 className="text-xl font-semibold">Baseplate für die Schublade</h1>
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="Schublade Breite" value={spec.drawer_x} step={1} min={50} onChange={(v) => patch({ drawer_x: v })} />
          <NumberField label="Schublade Tiefe" value={spec.drawer_y} step={1} min={50} onChange={(v) => patch({ drawer_y: v })} />
        </div>
        <div>
          <label className="label" htmlFor="bed">Druckbett</label>
          <select id="bed" className="input" value={BEDS.findIndex((b) => b[1] === spec.bed_x && b[2] === spec.bed_y)}
            onChange={(e) => { const b = BEDS[+e.target.value]; if (b) patch({ bed_x: b[1], bed_y: b[2] }) }}>
            {BEDS.map((b, i) => <option key={b[0]} value={i}>{b[0]}</option>)}
            <option value={-1}>Frei</option>
          </select>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="Bett x" value={spec.bed_x} step={1} min={50} onChange={(v) => patch({ bed_x: v })} />
          <NumberField label="Bett y" value={spec.bed_y} step={1} min={50} onChange={(v) => patch({ bed_y: v })} />
        </div>
        <NumberField label="Spiel zur Schublade (je Seite)" value={spec.clearance} step={0.1} min={0} onChange={(v) => patch({ clearance: v })} />
        <Check label="Rand nur einseitig" checked={spec.one_sided} onChange={(v) => patch({ one_sided: v })} />
        <Check label="Magnetlöcher" checked={spec.magnets} onChange={(v) => patch({ magnets: v })} />
        <button className="btn btn-primary justify-center" disabled={build.isPending || job.data?.status === 'running'} onClick={() => build.mutate()}>
          {job.data?.status === 'running' ? 'Erzeuge …' : 'Kacheln erzeugen'}
        </button>
        {build.isError && <div className="msg msg-err">{String(build.error).replace('Error: ', '')}</div>}
        {job.data?.status === 'error' && <div className="msg msg-err">{job.data.error}</div>}
      </section>

      <section className="grid gap-3 content-start">
        {!done ? (
          <div className="panel p-6" style={{ borderStyle: 'dashed', color: 'var(--ink-2)' }}>
            Der Kachelplan erscheint nach dem Erzeugen. Zellen sind 42 mm, überschüssige Breite wird als massiver Rand an den Außenkanten verteilt.
          </div>
        ) : (
          <>
            <div className="panel p-3">
              <img src={done.outputs.plan} alt="Kachelplan" className="w-full" style={{ maxHeight: 420, objectFit: 'contain' }} />
            </div>
            <div className="num text-sm">
              {done.checks.cells_x} x {done.checks.cells_y} Zellen, Restrand {done.checks.rest_x} / {done.checks.rest_y} mm,
              {' '}{tiles.length} Kacheln
            </div>
            <div className="flex flex-wrap gap-2">
              {tiles.map((t) => <span key={t.n} className="panel px-2 py-1 num text-xs">#{t.n}: {t.cx} x {t.cy} Zellen ({t.w} x {t.h} mm)</span>)}
            </div>
            <Msgs items={done.warnings} />
            <a className="btn btn-primary justify-center no-underline w-fit" style={{ color: 'var(--accent-ink)' }}
              href={done.outputs.zip} download="baseplate_kacheln.zip"><DownloadSimple size={16} /> STL der Kacheln (ZIP)</a>
          </>
        )}
      </section>
    </div>
  )
}
