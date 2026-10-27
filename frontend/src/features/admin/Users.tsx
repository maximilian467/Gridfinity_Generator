import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { Check as CheckIcon, Crown, FolderSimple, Prohibit, ShieldCheck, ShieldSlash, Trash, ArrowCounterClockwise, UserMinus } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { AdminUser } from '../../lib/types'
import { Empty, Initials, Msg, errText } from '../../components/ui'

const ACTIONS: Record<string, string> = {
  login_local: 'Anmeldung mit Passwort', login_google: 'Anmeldung mit Google', signup_pending: 'Neues Konto, wartet',
  signup_admin: 'Neues Admin-Konto', approve: 'Freigeschaltet', enable: 'Entsperrt', disable: 'Gesperrt',
  role_admin: 'Zum Admin gemacht', role_user: 'Admin-Rechte entzogen', delete_user: 'Gelöscht', logout_all: 'Überall abgemeldet',
  project_member_add: 'Zu Projekt hinzugefügt', project_member_remove: 'Aus Projekt entfernt', project_member_leave: 'Projekt verlassen',
}

const when = (iso: string | null) => (iso ? new Date(iso + (iso.endsWith('Z') || iso.includes('+') ? '' : 'Z'))
  .toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }) : 'nie')

export function Users() {
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const users = useQuery({ queryKey: ['admin-users'], queryFn: api.users })
  const [showLog, setShowLog] = useState(false)
  const [openProjects, setOpenProjects] = useState<number | null>(null)
  const log = useQuery({ queryKey: ['admin-audit'], queryFn: api.audit, enabled: showLog })
  const [err, setErr] = useState('')
  const refresh = () => { qc.invalidateQueries({ queryKey: ['admin-users'] }); qc.invalidateQueries({ queryKey: ['admin-audit'] }) }
  const change = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Parameters<typeof api.changeUser>[1] }) => api.changeUser(id, body),
    onSuccess: () => { setErr(''); refresh() }, onError: (e) => setErr(errText(e)),
  })
  const remove = useMutation({
    mutationFn: api.deleteUser, onSuccess: () => { setErr(''); refresh() }, onError: (e) => setErr(errText(e)),
  })

  const del = (u: AdminUser) => {
    const data = u.objects + u.inserts
    const q = data ? `${u.email} löschen? Dabei werden auch ${u.objects} Objekt(e) und ${u.inserts} Einlage(n) gelöscht.`
      : `${u.email} löschen?`
    if (confirm(q)) remove.mutate(u.id)
  }

  const pending = users.data?.filter((u) => u.status === 'pending') ?? []
  const others = users.data?.filter((u) => u.status !== 'pending') ?? []
  const busy = change.isPending || remove.isPending

  return (
    <div className="max-w-[1000px] mx-auto px-4 py-6 grid gap-8">
      <h1 className="text-xl font-semibold tracking-tight">Nutzer</h1>
      {err && <Msg kind="err">{err}</Msg>}
      {users.isPending ? (
        <div className="grid gap-2">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-14" />)}</div>
      ) : users.isError ? (
        <Msg kind="err">{errText(users.error)}</Msg>
      ) : (
        <>
          <section className="grid gap-3">
            <h2 className="font-semibold">Wartet auf Freischaltung</h2>
            {pending.length === 0 ? (
              <Empty title="Niemand wartet">Wer sich zum ersten Mal mit Google anmeldet, erscheint hier.</Empty>
            ) : (
              <div className="panel divide-y divide-(--line)" style={{ borderColor: 'var(--accent)' }}>
                {pending.map((u) => (
                  <div key={u.id} className="grid gap-2 md:grid-cols-[1fr_auto] md:items-center px-3 py-3">
                    <Who u={u} sub={`angemeldet am ${when(u.created_at)}`} />
                    <div className="flex gap-2">
                      <button className="btn btn-sm btn-primary" disabled={busy}
                        onClick={() => change.mutate({ id: u.id, body: { status: 'active' } })}>
                        <CheckIcon size={14} weight="bold" /> Freischalten
                      </button>
                      <button className="btn btn-sm" disabled={busy} onClick={() => del(u)}>Ablehnen</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="grid gap-3">
            <h2 className="font-semibold">Konten</h2>
            <div className="panel divide-y divide-(--line)">
              {others.map((u) => {
                const self = u.id === me.data?.id
                const open = openProjects === u.id
                return (
                  <div key={u.id} className="grid gap-2 md:grid-cols-[1fr_auto] md:items-center px-3 py-3"
                    style={{ opacity: u.status === 'disabled' ? 0.65 : 1 }}>
                    <Who u={u} self={self}
                      sub={`zuletzt da: ${when(u.last_login_at)} | ${u.objects} Objekt(e), ${u.inserts} Einlage(n)`} />
                    <div className="flex gap-1 flex-wrap">
                      {u.status !== 'disabled' && (
                        <button className={`btn btn-sm ${open ? 'btn-on' : 'btn-quiet'}`} aria-expanded={open}
                          title="Projekte, an denen die Person mitarbeitet" onClick={() => setOpenProjects(open ? null : u.id)}>
                          <FolderSimple size={14} /> Projekte{u.projects ? ` (${u.projects})` : ''}
                        </button>
                      )}
                      {u.role === 'admin' ? (
                        <button className="btn btn-sm btn-quiet" disabled={busy || self} title="Admin-Rechte entziehen"
                          onClick={() => change.mutate({ id: u.id, body: { role: 'user' } })}>
                          <ShieldSlash size={14} /> Kein Admin
                        </button>
                      ) : (
                        <button className="btn btn-sm btn-quiet" disabled={busy || u.status !== 'active'} title="Zum Admin machen"
                          onClick={() => confirm(`${u.email} zum Admin machen? Admins sehen die Daten aller Nutzer.`)
                            && change.mutate({ id: u.id, body: { role: 'admin' } })}>
                          <ShieldCheck size={14} /> Admin
                        </button>
                      )}
                      {u.status === 'disabled' ? (
                        <button className="btn btn-sm btn-quiet" disabled={busy}
                          onClick={() => change.mutate({ id: u.id, body: { status: 'active' } })}>
                          <ArrowCounterClockwise size={14} /> Entsperren
                        </button>
                      ) : (
                        <button className="btn btn-sm btn-quiet" disabled={busy || self}
                          onClick={() => confirm(`${u.email} sperren? Die Person wird sofort abgemeldet.`)
                            && change.mutate({ id: u.id, body: { status: 'disabled' } })}>
                          <Prohibit size={14} /> Sperren
                        </button>
                      )}
                      <button className="btn btn-sm btn-quiet" aria-label="Löschen" disabled={busy || self} onClick={() => del(u)}>
                        <Trash size={14} />
                      </button>
                    </div>
                    {open && <UserProjects u={u} onChange={refresh} />}
                  </div>
                )
              })}
            </div>
          </section>
        </>
      )}

      <section className="grid gap-3">
        <button className="btn btn-sm btn-quiet justify-self-start" aria-expanded={showLog} onClick={() => setShowLog((v) => !v)}>
          {showLog ? 'Protokoll ausblenden' : 'Protokoll anzeigen'}
        </button>
        {showLog && (log.isPending ? <div className="skeleton h-24" /> : log.isError ? <Msg kind="err">{errText(log.error)}</Msg> : (
          <div className="panel overflow-x-auto">
            <table className="w-full text-sm">
              <thead style={{ color: 'var(--ink-3)' }}>
                <tr className="text-left"><th className="px-3 py-2 font-medium">Zeit</th><th className="px-3 py-2 font-medium">Ereignis</th>
                  <th className="px-3 py-2 font-medium">Betrifft</th><th className="px-3 py-2 font-medium">Von</th></tr>
              </thead>
              <tbody>
                {log.data.map((r, i) => (
                  <tr key={i} style={{ borderTop: '1px solid var(--line)' }}>
                    <td className="num px-3 py-1.5 whitespace-nowrap">{when(r.ts)}</td>
                    <td className="px-3 py-1.5">{ACTIONS[r.action] ?? r.action}</td>
                    <td className="px-3 py-1.5 truncate max-w-[260px]">{r.target}</td>
                    <td className="px-3 py-1.5 truncate max-w-[200px]" style={{ color: 'var(--ink-2)' }}>{r.actor}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </section>
    </div>
  )
}

/** Admin: Projekte einer Person; hinzufügen (zu jedem Projekt) und als Mitglied entfernen. */
function UserProjects({ u, onChange }: { u: AdminUser; onChange: () => void }) {
  const qc = useQueryClient()
  const mine = useQuery({ queryKey: ['admin-user-projects', u.id], queryFn: () => api.userProjects(u.id) })
  const all = useQuery({ queryKey: ['projects', 'all', 'active'], queryFn: () => api.projects(true, false) })
  const done = () => {
    qc.invalidateQueries({ queryKey: ['admin-user-projects', u.id] }); qc.invalidateQueries({ queryKey: ['projects'] }); onChange()
  }
  const add = useMutation({ mutationFn: (pid: string) => api.addMember(pid, u.email), onSuccess: done })
  const remove = useMutation({ mutationFn: (pid: string) => api.removeMember(pid, u.id), onSuccess: done })
  const have = new Set((mine.data ?? []).map((p) => p.id))
  const free = (all.data ?? []).filter((p) => !have.has(p.id))
  const busy = add.isPending || remove.isPending
  return (
    <div className="md:col-span-2 grid gap-2 rounded-md p-3" style={{ background: 'var(--surface-2)' }}>
      {mine.isPending ? <div className="skeleton h-8" /> : !mine.data?.length
        ? <div className="hint mt-0">Noch in keinem Projekt.</div>
        : (
          <ul className="grid gap-1 m-0 p-0 list-none">
            {mine.data.map((p) => (
              <li key={p.id} className="flex items-center gap-2 flex-wrap">
                <Link className="font-medium truncate flex-1 min-w-0" to={`/project/${p.id}`} style={{ color: 'var(--ink)' }}>{p.name}</Link>
                {p.archived && <span className="chip text-xs">archiviert</span>}
                {p.role === 'owner'
                  ? <span className="chip text-xs"><Crown size={12} /> Besitzer</span>
                  : <>
                    <span className="chip text-xs">Mitglied</span>
                    <button className="btn btn-sm btn-quiet" disabled={busy} aria-label={`Aus ${p.name} entfernen`}
                      onClick={() => confirm(`${u.name || u.email} aus "${p.name}" entfernen? Was die Person dort angelegt hat, bleibt im Projekt und gehört dann dem Besitzer.`) && remove.mutate(p.id)}>
                      <UserMinus size={14} /> Entfernen
                    </button>
                  </>}
              </li>
            ))}
          </ul>
        )}
      {free.length > 0 && (
        <select className="input" style={{ maxWidth: 340 }} value="" disabled={busy} aria-label="Zu Projekt hinzufügen"
          onChange={(e) => e.target.value && add.mutate(e.target.value)}>
          <option value="">+ Zu Projekt hinzufügen …</option>
          {free.map((p) => <option key={p.id} value={p.id}>{p.name}{p.access?.owner ? ` (von ${p.access.owner})` : ''}</option>)}
        </select>
      )}
      {add.isError && <Msg kind="err">{errText(add.error)}</Msg>}
      {remove.isError && <Msg kind="err">{errText(remove.error)}</Msg>}
    </div>
  )
}

function Who({ u, sub, self }: { u: AdminUser; sub: string; self?: boolean }) {
  return (
    <div className="flex items-center gap-3 min-w-0">
      <Initials name={u.name || u.email} />
      <div className="min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium truncate">{u.name || u.email}</span>
          {u.role === 'admin' && <span className="chip text-xs" style={{ borderColor: 'var(--accent)', color: 'var(--accent)' }}>Admin</span>}
          {u.status === 'disabled' && <span className="chip chip-err text-xs">gesperrt</span>}
          {self && <span className="chip text-xs">du</span>}
        </div>
        <div className="text-xs truncate" style={{ color: 'var(--ink-2)' }}>{u.name ? `${u.email} | ` : ''}{sub}</div>
      </div>
    </div>
  )
}
