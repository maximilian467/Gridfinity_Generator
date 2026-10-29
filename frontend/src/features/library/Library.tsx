import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router'
import { Archive, Copy, Dresser, Cube, FolderSimple, Plus, Rectangle, Scan, SquaresFour, Trash, UsersThree } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import { Check, Empty, Msg, NumberField, Segmented, Silhouette, errText } from '../../components/ui'
import type { InsertSpec, ProjectSpec } from '../../lib/types'
import { NewBinForm } from '../insert/NewBinForm'
import { NewPlugForm } from '../insert/NewPlugForm'

function Projects({ showAll }: { showAll: boolean }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [archive, setArchive] = useState(false)
  const projects = useQuery({ queryKey: ['projects', showAll ? 'all' : 'mine', archive ? 'archived' : 'active'], queryFn: () => api.projects(showAll, archive) })
  // Zähler: auch was andere in gemeinsamen Projekten angelegt haben
  const inserts = useQuery({ queryKey: ['inserts', showAll ? 'all' : 'mine', 'shared'], queryFn: () => api.inserts(showAll, true) })
  const objects = useQuery({ queryKey: ['objects', showAll ? 'all' : 'mine', 'shared'], queryFn: () => api.objects(showAll, true) })
  const refresh = () => qc.invalidateQueries({ queryKey: ['projects'] })
  const archiveP = useMutation({ mutationFn: api.archiveProject, onSuccess: refresh })
  const restoreP = useMutation({ mutationFn: api.restoreProject, onSuccess: refresh })
  const [form, setForm] = useState<{ kind: 'drawer' | 'cabinet'; name: string; x: number; y: number; cabinet: string } | null>(null)
  const create = useMutation({
    mutationFn: () => form!.kind === 'cabinet' ? api.createCabinet(form!.name) : api.createProject(form!.name, form!.x, form!.y, form!.cabinet || null),
    onSuccess: (p) => { qc.invalidateQueries({ queryKey: ['projects'] }); nav(`/project/${p.id}`) },
  })
  const count = (p: ProjectSpec) => ({
    ins: (inserts.data ?? []).filter((i) => i.project_id === p.id).length,
    obj: (objects.data ?? []).filter((o) => o.project_id === p.id).length,
  })
  const list = projects.data ?? []
  const cabinets = list.filter((p) => p.kind === 'cabinet')
  const drawersOf = (cid: string) => list.filter((p) => p.kind !== 'cabinet' && p.cabinet_id === cid)
  const loose = list.filter((p) => p.kind !== 'cabinet' && !cabinets.some((c) => c.id === p.cabinet_id))
  const actions = (p: ProjectSpec) => p.access?.role === 'member' ? null : archive
    ? <button className="btn btn-sm" onClick={() => restoreP.mutate(p.id)} disabled={restoreP.isPending}>Wiederherstellen</button>
    : <button className="btn btn-sm btn-quiet" aria-label={`${p.name} löschen`} title="Löschen (wird archiviert, wiederherstellbar)"
      onClick={() => confirm(`${p.kind === 'cabinet' ? 'Schrank' : 'Projekt'} "${p.name}" löschen? Es wird archiviert und lässt sich wiederherstellen.`) && archiveP.mutate(p.id)}><Trash size={14} /></button>
  const drawerCard = (p: ProjectSpec) => {
    const c = count(p)
    return (
      <div key={p.id} className="panel p-4 flex gap-2 items-start">
        <button className="grid gap-1 text-left cursor-pointer flex-1 min-w-0 bg-transparent border-0 p-0" style={{ color: 'var(--ink)', font: 'inherit' }} onClick={() => nav(`/project/${p.id}`)}>
          <span className="inline-flex items-center gap-2 font-semibold"><FolderSimple size={18} color="var(--accent)" /> <span className="truncate">{p.name}</span></span>
          <span className="num text-sm" style={{ color: 'var(--ink-2)' }}>{p.drawer.drawer_x} x {p.drawer.drawer_y} mm · {c.obj} Werkzeuge · {c.ins} Einlagen</span>
          <span className="num text-xs" style={{ color: 'var(--ink-3)' }}>{archive && p.archived_at ? `archiviert am ${new Date(p.archived_at).toLocaleDateString('de-DE')}` : p.template.height_mm ? `alle ${p.template.height_mm} mm hoch` : 'Höhe automatisch'}</span>
          <SharedChip p={p} />
        </button>
        {actions(p)}
      </div>
    )
  }
  return (
    <section className="grid gap-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-xl font-semibold tracking-tight">{archive ? 'Archivierte Projekte' : 'Projekte'}</h1>
        <div className="flex gap-2 flex-wrap">
          <button className={`btn ${archive ? 'btn-on' : ''}`} onClick={() => setArchive((v) => !v)}><Archive size={16} /> {archive ? 'Zurück zu den Projekten' : 'Archiv'}</button>
          {!archive && <button className="btn" onClick={() => setForm({ kind: 'cabinet', name: 'Schrank', x: 500, y: 350, cabinet: '' })}><Dresser size={16} /> Neuer Schrank</button>}
          {!archive && <button className="btn btn-primary" onClick={() => setForm({ kind: 'drawer', name: 'Schublade', x: 500, y: 350, cabinet: '' })}><Plus size={16} /> Neue Schublade</button>}
        </div>
      </div>
      {form && (
        <div className={`panel p-3 grid gap-2 items-end ${form.kind === 'cabinet' ? 'md:grid-cols-[1fr_auto]' : 'md:grid-cols-[1fr_180px_140px_140px_auto]'}`}>
          <label className="grid gap-1"><span className="label mb-0">{form.kind === 'cabinet' ? 'Name des Schranks' : 'Name der Schublade'}</span>
            <input className="input" autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder={form.kind === 'cabinet' ? 'z. B. Werkstattschrank, Rollwagen' : 'z. B. Schreibtisch, Schublade oben'} /></label>
          {form.kind === 'drawer' && <>
            <label className="grid gap-1"><span className="label mb-0">Schrank</span>
              <select className="input" value={form.cabinet} onChange={(e) => setForm({ ...form, cabinet: e.target.value })}>
                <option value="">ohne Schrank</option>
                {cabinets.filter((c) => c.access?.role !== 'admin' || c.id === form.cabinet).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select></label>
            <NumberField label="Schublade Breite" value={form.x} step={1} min={50} onChange={(v) => setForm({ ...form, x: v })} />
            <NumberField label="Schublade Tiefe" value={form.y} step={1} min={50} onChange={(v) => setForm({ ...form, y: v })} />
          </>}
          <div className="flex gap-2">
            <button className="btn btn-primary" onClick={() => create.mutate()} disabled={create.isPending || !form.name.trim()}>Anlegen</button>
            <button className="btn" onClick={() => setForm(null)}>Abbrechen</button>
          </div>
          {create.isError && <Msg kind="err">{errText(create.error)}</Msg>}
        </div>
      )}
      {projects.isPending ? <div className="skeleton h-28" /> : !list.length ? (
        archive ? <Empty title="Archiv ist leer">Gelöschte Projekte landen hier und lassen sich wiederherstellen.</Empty> :
        <Empty title="Noch keine Projekte">Eine Schublade ist ein Projekt: Baseplate nach Maß, alle Werkzeuge mit ihren Einlagen und ein digitaler Klon in 3D. Ein Schrank fasst mehrere Schubladen zusammen und lässt sich als Ganzes mit anderen teilen.</Empty>
      ) : (
        <div className="grid gap-4">
          {cabinets.map((cab) => {
            const ds = drawersOf(cab.id)
            return (
              <div key={cab.id} className="panel p-3 grid gap-3">
                <div className="flex items-start gap-2">
                  <button className="grid gap-1 text-left cursor-pointer flex-1 min-w-0 bg-transparent border-0 p-0" style={{ color: 'var(--ink)', font: 'inherit' }} onClick={() => nav(`/project/${cab.id}`)}>
                    <span className="inline-flex items-center gap-2 font-semibold text-lg"><Dresser size={20} color="var(--accent)" /> <span className="truncate">{cab.name}</span></span>
                    <span className="text-sm" style={{ color: 'var(--ink-2)' }}>Schrank · {ds.length} {ds.length === 1 ? 'Schublade' : 'Schubladen'}</span>
                    <SharedChip p={cab} />
                  </button>
                  {!archive && cab.access?.role !== 'admin' && <button className="btn btn-sm" onClick={() => setForm({ kind: 'drawer', name: `Schublade ${ds.length + 1}`, x: 500, y: 350, cabinet: cab.id })}><Plus size={14} /> Schublade</button>}
                  {actions(cab)}
                </div>
                {ds.length > 0 && <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">{ds.map(drawerCard)}</div>}
              </div>
            )
          })}
          {loose.length > 0 && <>
            {cabinets.length > 0 && <h2 className="font-semibold" style={{ color: 'var(--ink-2)' }}>Schubladen ohne Schrank</h2>}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">{loose.map(drawerCard)}</div>
          </>}
        </div>
      )}
    </section>
  )
}

/** Geteilt: Mitglied ("von Anna") oder Besitzer mit Mitgliedern ("mit 2 Personen") */
function SharedChip({ p }: { p: ProjectSpec }) {
  const a = p.access
  if (!a || (a.role !== 'member' && !a.members)) return null
  return (
    <span className="chip text-xs w-fit" title={a.role === 'member' ? 'Mit dir geteilt: du kannst alles bearbeiten' : 'Gemeinsam bearbeitet'}>
      <UsersThree size={12} /> {a.role === 'member' ? `geteilt von ${a.owner}` : `mit ${a.members} ${a.members === 1 ? 'Person' : 'Personen'} geteilt`}
    </span>
  )
}

/** Inhalt einer Einlage für die Liste: Werkzeuge, sonst Fächer (Fächer-Einlage) oder Blindstopfen. */
function contents(i: InsertSpec): string {
  if (i.blank) return (i.texts ?? []).some((t) => t.text.trim()) ? `Blindstopfen „${i.texts!.map((t) => t.text).join(' ')}“` : 'Blindstopfen'
  if (i.placements.length || !i.compartments.length) return `${i.placements.length} Objekt(e)`
  return `${i.compartments.length} ${i.compartments.length === 1 ? 'Fach' : 'Fächer'}`
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
  const [binForm, setBinForm] = useState(false)
  const [plugForm, setPlugForm] = useState(false)
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
            {projects.data.filter((p) => p.kind !== 'cabinet').map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
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
          <div className="flex gap-2">
            <button className={`btn ${plugForm ? 'btn-on' : ''}`} onClick={() => { setPlugForm((v) => !v); setBinForm(false) }} title="Deckel für freie Felder der Baseplate, Höhe frei (auch sehr flach)">
              <Rectangle size={16} /> Neuer Blindstopfen
            </button>
            <button className={`btn ${binForm ? 'btn-on' : ''}`} onClick={() => { setBinForm((v) => !v); setPlugForm(false) }} title="Einlage ohne Werkzeug, nur mit Fächern (Sortierkasten)">
              <SquaresFour size={16} /> Neue Fächer-Einlage
            </button>
            <button className="btn btn-primary" onClick={() => newInsert.mutate()} disabled={newInsert.isPending}>
              <Plus size={16} /> Neue Einlage
            </button>
          </div>
        </div>
        {plugForm && <NewPlugForm onCancel={() => setPlugForm(false)}
          onCreated={(i) => { qc.invalidateQueries({ queryKey: ['inserts'] }); nav(`/insert/${i.id}`) }} />}
        {binForm && <NewBinForm onCancel={() => setBinForm(false)}
          onCreated={(i) => { qc.invalidateQueries({ queryKey: ['inserts'] }); nav(`/insert/${i.id}`) }} />}
        {inserts.isPending ? (
          <div className="skeleton h-16" />
        ) : !inserts.data?.length ? (
          <Empty title="Noch keine Einlagen">Lege eine Einlage an und platziere ein gescanntes Objekt darin, oder lege eine Fächer-Einlage ohne Werkzeug an.</Empty>
        ) : (
          <div className="panel divide-y" style={{ borderColor: 'var(--line)' }}>
            {inserts.data.filter((i) => match(i.project_id)).map((i) => (
              <div key={i.id} className="flex items-center gap-3 px-3 py-2">
                {i.blank ? <Rectangle size={18} /> : i.placements.length || !i.compartments.length ? <Cube size={18} /> : <SquaresFour size={18} />}
                <button className="font-medium text-left flex-1 truncate bg-transparent border-0 cursor-pointer p-0"
                  style={{ color: 'var(--ink)', font: 'inherit', fontWeight: 500 }} onClick={() => nav(`/insert/${i.id}`)}>
                  {i.name}
                </button>
                {foreign(i.owner_id) && <span className="chip text-xs">anderer Nutzer</span>}
                {pname(i.project_id) && <button className="chip text-xs cursor-pointer" onClick={() => nav(`/project/${i.project_id}`)}><FolderSimple size={12} /> {pname(i.project_id)}</button>}
                <span className="num text-xs" style={{ color: 'var(--ink-2)' }}>
                  {i.grid_x ?? 'auto'} x {i.grid_y ?? 'auto'} · {i.height_mm ? `${i.height_mm} mm` : i.height_u ? `${i.height_u} U` : 'Höhe auto'} · {contents(i)}
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
