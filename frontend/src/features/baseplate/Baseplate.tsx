import { useEffect, useState } from 'react'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { DownloadSimple } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { BaseplateSpec } from '../../lib/types'
import { Check, Msg, Msgs, NumberField, errText } from '../../components/ui'
import { PlateEditor } from './PlateEditor'

export const BEDS: [string, number, number][] = [
  ['Bambu X1 / P1 / A1 (256 x 256)', 256, 256],
  ['Bambu A1 mini (180 x 180)', 180, 180],
  ['Prusa MK4 (250 x 210)', 250, 210],
]

function useDebounced<T>(v: T, ms: number): T {
  const [d, setD] = useState(v)
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t) }, [v, ms])
  return d
}

/** Einstellungen der Baseplate (Schublade, Druckbett, Rand); auch im Projekt verwendet. */
export function PlateSettings({ spec, patch }: { spec: BaseplateSpec; patch: (p: Partial<BaseplateSpec>) => void }) {
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-2">
        <NumberField label="Schublade Breite" value={spec.drawer_x} step={1} min={50} onChange={(v) => patch({ drawer_x: v })} hint="innen, links-rechts" />
        <NumberField label="Schublade Tiefe" value={spec.drawer_y} step={1} min={50} onChange={(v) => patch({ drawer_y: v })} hint="innen, vorne-hinten" />
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
      <Check label="Rand nur rechts und hinten (Raster in der linken vorderen Ecke)" checked={spec.one_sided} onChange={(v) => patch({ one_sided: v })} />
    </div>
  )
}

/** Zellen umschalten (Liste der abgewählten Zellen). on = Zelle wieder aktiv. */
export function toggleCells(disabled: [number, number][], cells: [number, number][], on: boolean): [number, number][] {
  const k = (c: [number, number]) => `${c[0]},${c[1]}`
  const set = new Map(disabled.map((c) => [k(c), c]))
  for (const c of cells) { if (on) set.delete(k(c)); else set.set(k(c), c) }
  return [...set.values()]
}

export function usePlatePlan(spec: BaseplateSpec | undefined) {
  const d = useDebounced(spec, 250)
  return useQuery({
    queryKey: ['plate-plan', JSON.stringify(d)], queryFn: () => api.planBaseplate(d!), placeholderData: keepPreviousData,
    enabled: !!d,
  })
}

/** Kacheln als STL erzeugen und herunterladen */
export function PlateBuild({ spec, disabled }: { spec: BaseplateSpec; disabled?: boolean }) {
  const [jobId, setJobId] = useState<string | null>(null)
  const build = useMutation({ mutationFn: () => api.buildBaseplate(spec), onSuccess: (r) => setJobId(r.job_id) })
  const job = useQuery({
    queryKey: ['job', jobId], queryFn: () => api.job(jobId!), enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 1000 : false),
  })
  const done = job.data?.status === 'done' ? job.data : null
  return (
    <div className="grid gap-2">
      <button className="btn btn-primary justify-center" disabled={disabled || build.isPending || job.data?.status === 'running'} onClick={() => build.mutate()}>
        {job.data?.status === 'running' ? 'Erzeuge …' : done ? 'Kacheln neu erzeugen' : 'Kacheln erzeugen (STL)'}
      </button>
      {build.isError && <Msg kind="err">{errText(build.error)}</Msg>}
      {job.data?.status === 'error' && <Msg kind="err">{job.data.error}</Msg>}
      {done && (
        <a className="btn justify-center no-underline" style={{ color: 'var(--ink)' }} href={done.outputs.zip} download="baseplate_kacheln.zip">
          <DownloadSimple size={16} /> STL der Kacheln (ZIP)</a>
      )}
      {done && <Msgs items={done.warnings} />}
    </div>
  )
}

export function Baseplate() {
  const [spec, setSpec] = useState<BaseplateSpec>({
    drawer_x: 500, drawer_y: 350, bed_x: 256, bed_y: 256, clearance: 0.5, magnets: false, one_sided: false, disabled: [],
  })
  const patch = (p: Partial<BaseplateSpec>) => setSpec((s) => ({ ...s, ...p }))
  const plan = usePlatePlan(spec)
  const p = plan.data

  return (
    <div className="max-w-[1200px] mx-auto px-4 py-6 grid gap-6 md:grid-cols-[320px_1fr]">
      <section className="panel p-4 grid gap-3 content-start">
        <h1 className="text-xl font-semibold">Baseplate für die Schublade</h1>
        <div className="hint mt-0">Für eine ganze Schublade mit Einlagen und 3D-Ansicht lieber ein Projekt in der Bibliothek anlegen.</div>
        <PlateSettings spec={spec} patch={patch} />
        <PlateBuild spec={spec} disabled={plan.isError} />
      </section>

      <section className="grid gap-3 content-start">
        {plan.isError && <Msg kind="err">{errText(plan.error)}</Msg>}
        <div className="panel p-3">
          <PlateEditor drawer={[spec.drawer_x, spec.drawer_y]} plan={p} disabled={spec.disabled ?? []}
            onToggle={(cells, on) => setSpec((s) => ({ ...s, disabled: toggleCells(s.disabled ?? [], cells, on) }))} />
        </div>
        <div className="hint mt-0">Zelle anklicken (oder über mehrere ziehen), um sie wegzulassen, z. B. eine Ecke mit Hindernis. Nochmal klicken holt sie zurück.</div>
        {p && (
          <div className="num text-sm" style={{ color: 'var(--ink-2)' }}>
            {p.cells_x} x {p.cells_y} Zellen ({p.active.length} aktiv) · Rand {p.rest_x} / {p.rest_y} mm · {p.tiles.length} Kacheln
          </div>
        )}
        {p && (
          <div className="flex flex-wrap gap-2">
            {p.tiles.map((t) => <span key={t.n} className="chip num">#{t.n}: {t.cells.length} Zellen, {t.w} x {t.h} mm</span>)}
          </div>
        )}
      </section>
    </div>
  )
}
