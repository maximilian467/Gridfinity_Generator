import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { Dresser, FolderSimple, Plus, Trash, UsersThree } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { ProjectSpec } from '../../lib/types'
import { Empty, Msg, NumberField, errText } from '../../components/ui'
import { Members } from './Members'

/** Schrank: fasst Schubladen zusammen. Wer am Schrank beteiligt ist, bearbeitet alle seine Schubladen. */
export function CabinetPage({ initial }: { initial: ProjectSpec }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [p, setP] = useState<ProjectSpec>(initial)
  const [share, setShare] = useState(false)
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const projects = useQuery({ queryKey: ['projects', 'mine', 'active'], queryFn: () => api.projects(false, false) })
  const inserts = useQuery({ queryKey: ['inserts', 'mine', 'shared'], queryFn: () => api.inserts(false, true) })
  const isMember = p.access?.role === 'member'
  const drawers = (projects.data ?? []).filter((d) => d.kind !== 'cabinet' && d.cabinet_id === p.id)
  // eigene Schubladen ohne Schrank: lassen sich hier einräumen (nur in eigene Schränke)
  const loose = (projects.data ?? []).filter((d) => d.kind !== 'cabinet' && !d.cabinet_id && d.access?.role === 'owner')
  const [form, setForm] = useState<{ name: string; x: number; y: number } | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['projects'] })
  const create = useMutation({
    mutationFn: () => api.createProject(form!.name, form!.x, form!.y, p.id),
    onSuccess: (d) => { refresh(); nav(`/project/${d.id}`) },
  })
  const move = useMutation({ mutationFn: ({ id, to }: { id: string; to: string | null }) => api.setCabinet(id, to), onSuccess: refresh })
  const del = useMutation({ mutationFn: () => api.archiveProject(p.id), onSuccess: () => { refresh(); nav('/?view=projects') } })

  const first = useRef(true)
  useEffect(() => {
    if (first.current) { first.current = false; return }
    const t = setTimeout(() => api.saveProject(p).then((s) => { qc.setQueryData(['project', p.id], s); refresh() }), 700)
    return () => clearTimeout(t)
  }, [p.name, p.notes]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="max-w-[1200px] mx-auto px-4 py-5 grid gap-4">
      <header className="flex flex-wrap items-center gap-3">
        <Dresser size={26} color="var(--accent)" />
        <input className="input text-xl font-semibold tracking-tight" style={{ width: 'min(420px, 100%)' }} value={p.name}
          onChange={(e) => setP({ ...p, name: e.target.value })} aria-label="Name des Schranks" />
        <span className="chip">Schrank · {drawers.length} {drawers.length === 1 ? 'Schublade' : 'Schubladen'}</span>
        <button className={`btn btn-sm ${share ? 'btn-on' : ''}`} onClick={() => setShare((v) => !v)} aria-expanded={share}>
          <UsersThree size={14} /> {isMember ? `geteilt von ${p.access?.owner}` : p.access?.members ? `Geteilt (${p.access.members})` : 'Teilen'}
        </button>
        <div className="flex-1" />
        {!isMember && <button className="btn btn-sm btn-quiet" onClick={() => confirm(`Schrank "${p.name}" löschen? Er wird archiviert, die Schubladen bleiben.`) && del.mutate()}><Trash size={14} /> Löschen</button>}
      </header>
      {share && <>
        <Msg kind="info">Wer am Schrank beteiligt ist, sieht und bearbeitet alle Schubladen darin. Einzelne Schubladen lassen sich zusätzlich mit weiteren Personen teilen.</Msg>
        <Members p={p} me={me.data} onCount={(n) => setP((q) => q.access ? { ...q, access: { ...q.access, members: n } } : q)} />
      </>}
      {p.archived && <Msg kind="info">Dieser Schrank ist archiviert.</Msg>}

      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="font-semibold text-lg flex-1">Schubladen</h2>
        {!isMember && loose.length > 0 && (
          <select className="input" style={{ width: 240 }} value="" onChange={(e) => e.target.value && move.mutate({ id: e.target.value, to: p.id })} aria-label="Schublade einräumen">
            <option value="">+ Vorhandene Schublade einräumen …</option>
            {loose.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        )}
        <button className="btn btn-primary" onClick={() => setForm({ name: `Schublade ${drawers.length + 1}`, x: 500, y: 350 })}><Plus size={16} /> Neue Schublade</button>
      </div>
      {move.isError && <Msg kind="err">{errText(move.error)}</Msg>}
      {form && (
        <div className="panel p-3 grid gap-2 md:grid-cols-[1fr_140px_140px_auto] items-end">
          <label className="grid gap-1"><span className="label mb-0">Name</span>
            <input className="input" autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="z. B. oben links" /></label>
          <NumberField label="Breite" unit="mm" value={form.x} step={1} min={50} onChange={(v) => setForm({ ...form, x: v })} />
          <NumberField label="Tiefe" unit="mm" value={form.y} step={1} min={50} onChange={(v) => setForm({ ...form, y: v })} />
          <div className="flex gap-2">
            <button className="btn btn-primary" onClick={() => create.mutate()} disabled={create.isPending || !form.name.trim()}>Anlegen</button>
            <button className="btn" onClick={() => setForm(null)}>Abbrechen</button>
          </div>
          {create.isError && <Msg kind="err">{errText(create.error)}</Msg>}
        </div>
      )}
      {projects.isPending ? <div className="skeleton h-28" /> : !drawers.length ? (
        <Empty title="Noch keine Schubladen">Lege die Schubladen dieses Schranks an. Jede hat ihre eigene Baseplate, Einlagen und Werkzeuge.</Empty>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {drawers.map((d) => {
            const n = (inserts.data ?? []).filter((i) => i.project_id === d.id).length
            return (
              <div key={d.id} className="panel p-4 flex gap-2 items-start">
                <button className="grid gap-1 text-left cursor-pointer flex-1 min-w-0 bg-transparent border-0 p-0" style={{ color: 'var(--ink)', font: 'inherit' }} onClick={() => nav(`/project/${d.id}`)}>
                  <span className="inline-flex items-center gap-2 font-semibold"><FolderSimple size={18} color="var(--accent)" /> <span className="truncate">{d.name}</span></span>
                  <span className="num text-sm" style={{ color: 'var(--ink-2)' }}>{d.drawer.drawer_x} x {d.drawer.drawer_y} mm · {n} Einlagen</span>
                </button>
                {(d.access?.role === 'owner' || !isMember) && (
                  <button className="btn btn-sm btn-quiet" title="Aus dem Schrank nehmen (Schublade bleibt erhalten)"
                    onClick={() => confirm(`"${d.name}" aus dem Schrank nehmen? Die Beteiligten des Schranks verlieren den Zugriff.`) && move.mutate({ id: d.id, to: null })}>Herausnehmen</button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
