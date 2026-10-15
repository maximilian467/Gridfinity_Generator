import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router'
import { Copy, Cube, FolderSimple, Plus, Scan, Trash } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import { Check, Empty, Msg, NumberField, Segmented, Silhouette, errText } from '../../components/ui'
import type { ProjectSpec } from '../../lib/types'

function Projects({ showAll }: { showAll: boolean }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const projects = useQuery({ queryKey: ['projects', showAll ? 'all' : 'mine'], queryFn: () => api.projects(showAll) })
  const inserts = useQuery({ queryKey: ['inserts', showAll ? 'all' : 'mine'], queryFn: () => api.inserts(showAll) })
  const objects = useQuery({ queryKey: ['objects', showAll ? 'all' : 'mine'], queryFn: () => api.objects(showAll) })
  const [form, setForm] = useState<{ name: string; x: number; y: number } | null>(null)
  const create = useMutation({
    mutationFn: () => api.createProject(form!.name, form!.x, form!.y),
    onSuccess: (p) => { qc.invalidateQueries({ queryKey: ['projects'] }); nav(`/project/${p.id}`) },
  })
  const count = (p: ProjectSpec) => ({
    ins: (inserts.data ?? []).filter((i) => i.project_id === p.id).length,
    obj: (objects.data ?? []).filter((o) => o.project_id === p.id).length,
  })
  return (
    <section className="grid gap-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-xl font-semibold tracking-tight">Projekte</h1>
        <button className="btn btn-primary" onClick={() => setForm({ name: 'Schublade', x: 500, y: 350 })}><Plus size={16} /> Neues Projekt</button>
      </div>
      {form && (
        <div className="panel p-3 grid gap-2 md:grid-cols-[1fr_140px_140px_auto] items-end">
          <label className="grid gap-1"><span className="label mb-0">Name</span>
            <input className="input" autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="z. B. Schreibtisch, Schublade oben" /></label>
          <NumberField label="Schublade Breite" value={form.x} step={1} min={50} onChange={(v) => setForm({ ...form, x: v })} />
          <NumberField label="Schublade Tiefe" value={form.y} step={1} min={50} onChange={(v) => setForm({ ...form, y: v })} />
          <div className="flex gap-2">
            <button className="btn btn-primary" onClick={() => create.mutate()} disabled={create.isPending || !form.name.trim()}>Anlegen</button>
            <button className="btn" onClick={() => setForm(null)}>Abbrechen</button>
          </div>
          {create.isError && <Msg kind="err">{errText(create.error)}</Msg>}
        </div>
      )}
      {projects.isPending ? <div className="skeleton h-28" /> : !projects.data?.length ? (
        <Empty title="Noch keine Projekte">Ein Projekt ist eine Schublade: Baseplate nach Maß, alle Werkzeuge mit ihren Einlagen und ein digitaler Klon in 3D.</Empty>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {projects.data.map((p) => {
            const c = count(p)
            return (
              <button key={p.id} className="panel p-4 grid gap-1 text-left cursor-pointer" style={{ color: 'var(--ink)', font: 'inherit' }} onClick={() => nav(`/project/${p.id}`)}>
                <span className="inline-flex items-center gap-2 font-semibold"><FolderSimple size={18} color="var(--accent)" /> {p.name}</span>
                <span className="num text-sm" style={{ color: 'var(--ink-2)' }}>{p.drawer.drawer_x} x {p.drawer.drawer_y} mm · {c.obj} Werkzeuge · {c.ins} Einlagen</span>
                <span className="num text-xs" style={{ color: 'var(--ink-3)' }}>{p.template.height_mm ? `alle ${p.template.height_mm} mm hoch` : 'Höhe automatisch'}</span>
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}

export function Library() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const isAdmin = me.data?.role === 'admin'
  const [all, setAll] = useState(false)
  const showAll = isAdmin && all
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'projects' ? 'projects' : 'all'
  const [pf, setPf] = useState<string>('')          // Projektfilter in der Gesamtansicht
  const projects = useQuery({ queryKey: ['projects', showAll ? 'all' : 'mine'], queryFn: () => api.projects(showAll) })
  const pname = (id?: string | null) => projects.data?.find((p) => p.id === id)?.name
  const match = (id?: string | null) => !pf || (pf === '-' ? !id : id === pf)
  const objects = useQuery({ queryKey: ['objects', showAll ? 'all' : 'mine'], queryFn: () => api.objects(showAll) })
  const inserts = useQuery({ queryKey: ['inserts', showAll ? 'all' : 'mine'], queryFn: () => api.inserts(showAll) })
  const foreign = (owner?: number | null) => showAll && owner != null && owner !== me.data?.id
  const refresh = () => { qc.invalidateQueries({ queryKey: ['objects'] }); qc.invalidateQueries({ queryKey: ['inserts'] }) }

  const scan = useMutation({
    mutationFn: () => api.createObject('Neues Objekt'),
    onSuccess: (o) => nav(`/scan/${o.id}`),
  })
  const demo = useMutation({ mutationFn: api.createDemo, onSuccess: refresh })
  const newInsert = useMutation({
    mutationFn: () => api.createInsert({ name: 'Neue Einlage' }),
    onSuccess: (i) => nav(`/insert/${i.id}`),
  })
  const delObj = useMutation({ mutationFn: api.deleteObject, onSuccess: refresh })
  const delIns = useMutation({ mutationFn: api.deleteInsert, onSuccess: refresh })
  const dupIns = useMutation({ mutationFn: api.duplicateInsert, onSuccess: refresh })

  return (
    <div className="max-w-[1200px] mx-auto px-4 py-6 grid gap-10">
      <div className="-mb-4 flex items-center gap-3 flex-wrap">
        <Segmented value={view} onChange={(v) => setParams(v === 'projects' ? { view: 'projects' } : {})}
          options={[{ value: 'all', label: 'Alles anzeigen' }, { value: 'projects', label: 'Projekte' }]} />
        {view === 'all' && !!projects.data?.length && (
          <select className="input" style={{ width: 220 }} value={pf} onChange={(e) => setPf(e.target.value)} aria-label="Nach Projekt filtern">
            <option value="">Alle Projekte</option>
            <option value="-">Ohne Projekt</option>
            {projects.data.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        )}
        <div className="flex-1" />
        {isAdmin && me.data?.auth && <Check label="Daten aller Nutzer zeigen" checked={all} onChange={setAll} />}
      </div>
      {view === 'projects' ? <Projects showAll={showAll} /> : <>
      <section className="panel p-4 grid gap-3 md:grid-cols-3">
        {[
          ['1', 'Werkzeug scannen', 'Zwei Fotos auf einem A4-Blatt: von oben und hochkant. Das Blatt ist der Maßstab.'],
          ['2', 'Einlage gestalten', 'Werkzeug platzieren, Spiel einstellen, Greifmulden und Fächer ergänzen.'],
          ['3', 'Drucken', 'Erst den Passform-Test, dann die Einlage als 3MF mit Farbteilen für Bambu Studio oder Orca.'],
        ].map(([n, t, d]) => (
          <div key={n} className="flex gap-3">
            <span className="num grid place-items-center shrink-0 w-7 h-7 rounded-full font-semibold" style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>{n}</span>
            <div><div className="font-semibold">{t}</div><div className="text-sm" style={{ color: 'var(--ink-2)' }}>{d}</div></div>
          </div>
        ))}
      </section>
      <section className="grid gap-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h1 className="text-xl font-semibold tracking-tight">Gescannte Objekte</h1>
          <div className="flex gap-2">
            <button className="btn" onClick={() => demo.mutate()} disabled={demo.isPending}>Demo-Zange anlegen</button>
            <button className="btn btn-primary" onClick={() => scan.mutate()} disabled={scan.isPending}>
              <Scan size={16} /> Objekt scannen
            </button>
          </div>
        </div>
        {objects.isPending ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-44" />)}</div>
        ) : objects.isError ? (
          <div className="msg msg-err">Backend nicht erreichbar: {String(objects.error)}</div>
        ) : objects.data.length === 0 ? (
          <Empty title="Noch keine Objekte">
            Fotografiere ein Werkzeug von oben und von der Seite, jeweils auf einem A4-Blatt. Zum Ausprobieren ohne Fotos gibt es die Demo-Zange.
          </Empty>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {objects.data.filter((o) => match(o.project_id)).map((o) => (
              <article key={o.id} className="panel p-3 grid gap-2">
                <Silhouette contour={o.contour_mm} className="w-full h-32" />
                <div className="font-medium truncate">{o.name}</div>
                {pname(o.project_id) && <button className="chip w-fit text-xs cursor-pointer" onClick={() => nav(`/project/${o.project_id}`)}><FolderSimple size={12} /> {pname(o.project_id)}</button>}
                {foreign(o.owner_id) && <span className="chip w-fit text-xs">anderer Nutzer</span>}
                <div className="num text-xs" style={{ color: 'var(--ink-2)' }}>
                  {o.profile ? `${o.length_mm.toFixed(1)} x ${o.width_mm.toFixed(1)} mm` : 'noch nicht fertig gescannt'}
                </div>
                <div className="flex gap-1 mt-1">
                  <button className="btn btn-sm" onClick={() => nav(`/scan/${o.id}`)}>Bearbeiten</button>
                  <button className="btn btn-sm btn-quiet" aria-label="Löschen"
                    onClick={() => confirm(`"${o.name}" löschen?`) && delObj.mutate(o.id)}><Trash size={14} /></button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="grid gap-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h1 className="text-xl font-semibold tracking-tight">Einlagen</h1>
          <button className="btn btn-primary" onClick={() => newInsert.mutate()} disabled={newInsert.isPending}>
            <Plus size={16} /> Neue Einlage
          </button>
        </div>
        {inserts.isPending ? (
          <div className="skeleton h-16" />
        ) : !inserts.data?.length ? (
          <Empty title="Noch keine Einlagen">Lege eine Einlage an und platziere ein gescanntes Objekt darin.</Empty>
        ) : (
          <div className="panel divide-y" style={{ borderColor: 'var(--line)' }}>
            {inserts.data.filter((i) => match(i.project_id)).map((i) => (
              <div key={i.id} className="flex items-center gap-3 px-3 py-2">
                <Cube size={18} />
                <button className="font-medium text-left flex-1 truncate bg-transparent border-0 cursor-pointer p-0"
                  style={{ color: 'var(--ink)', font: 'inherit', fontWeight: 500 }} onClick={() => nav(`/insert/${i.id}`)}>
                  {i.name}
                </button>
                {foreign(i.owner_id) && <span className="chip text-xs">anderer Nutzer</span>}
                {pname(i.project_id) && <button className="chip text-xs cursor-pointer" onClick={() => nav(`/project/${i.project_id}`)}><FolderSimple size={12} /> {pname(i.project_id)}</button>}
                <span className="num text-xs" style={{ color: 'var(--ink-2)' }}>
                  {i.grid_x ?? 'auto'} x {i.grid_y ?? 'auto'} · {i.height_mm ? `${i.height_mm} mm` : i.height_u ? `${i.height_u} U` : 'Höhe auto'} · {i.placements.length} Objekt(e)
                </span>
                <button className="btn btn-sm btn-quiet" aria-label="Duplizieren" onClick={() => dupIns.mutate(i.id)}><Copy size={14} /></button>
                <button className="btn btn-sm btn-quiet" aria-label="Löschen"
                  onClick={() => confirm(`"${i.name}" löschen?`) && delIns.mutate(i.id)}><Trash size={14} /></button>
              </div>
            ))}
          </div>
        )}
      </section>
      </>}
    </div>
  )
}
