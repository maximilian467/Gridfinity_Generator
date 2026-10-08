import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { Copy, Cube, Plus, Scan, Trash } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import { Empty, Silhouette } from '../../components/ui'

export function Library() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const objects = useQuery({ queryKey: ['objects'], queryFn: api.objects })
  const inserts = useQuery({ queryKey: ['inserts'], queryFn: api.inserts })
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
      <section className="grid gap-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h1 className="text-xl font-semibold">Gescannte Objekte</h1>
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
            {objects.data.map((o) => (
              <article key={o.id} className="panel p-3 grid gap-2">
                <Silhouette contour={o.contour_mm} className="w-full h-24" />
                <div className="font-medium truncate">{o.name}</div>
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
          <h1 className="text-xl font-semibold">Einlagen</h1>
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
            {inserts.data.map((i) => (
              <div key={i.id} className="flex items-center gap-3 px-3 py-2">
                <Cube size={18} />
                <button className="font-medium text-left flex-1 truncate bg-transparent border-0 cursor-pointer p-0"
                  style={{ color: 'var(--ink)', font: 'inherit', fontWeight: 500 }} onClick={() => nav(`/insert/${i.id}`)}>
                  {i.name}
                </button>
                <span className="num text-xs" style={{ color: 'var(--ink-2)' }}>
                  {i.grid_x ?? 'auto'} x {i.grid_y ?? 'auto'} x {i.height_u ?? 'auto'} · {i.placements.length} Objekt(e)
                </span>
                <button className="btn btn-sm btn-quiet" aria-label="Duplizieren" onClick={() => dupIns.mutate(i.id)}><Copy size={14} /></button>
                <button className="btn btn-sm btn-quiet" aria-label="Löschen"
                  onClick={() => confirm(`"${i.name}" löschen?`) && delIns.mutate(i.id)}><Trash size={14} /></button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
