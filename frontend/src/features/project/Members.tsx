import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { Crown, SignOut, UserMinus, UserPlus } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { Me, ProjectMember, ProjectSpec } from '../../lib/types'
import { Msg, errText } from '../../components/ui'

/** Wer am Projekt arbeitet. Der Besitzer (und Admins) fügt per E-Mail hinzu und entfernt;
 *  Mitglieder sehen die Liste und können das Projekt verlassen. */
export function Members({ p, me, onCount }: { p: ProjectSpec; me: Me | undefined; onCount: (members: number) => void }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const manage = p.access?.role !== 'member'
  const members = useQuery({ queryKey: ['members', p.id], queryFn: () => api.members(p.id) })
  const [email, setEmail] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const changed = (list?: ProjectMember[]) => {
    if (list) { qc.setQueryData(['members', p.id], list); onCount(list.length - 1) }
    else qc.invalidateQueries({ queryKey: ['members', p.id] })
    qc.invalidateQueries({ queryKey: ['projects'] })
    qc.invalidateQueries({ queryKey: ['project', p.id] })
  }
  const add = useMutation({
    mutationFn: () => api.addMember(p.id, email.trim()),
    onSuccess: (list) => {
      const m = list.find((u) => u.email === email.trim().toLowerCase())
      setNote(`${m?.name || m?.email || email.trim()} kann das Projekt jetzt bearbeiten.`); setEmail(''); changed(list)
    },
  })
  const remove = useMutation({
    mutationFn: (m: ProjectMember) => api.removeMember(p.id, m.id),
    onSuccess: (r, m) => {
      if (m.id === me?.id) { qc.invalidateQueries({ queryKey: ['projects'] }); nav('/?view=projects'); return }
      setNote(`${m.name || m.email} entfernt.${r.transferred ? ` ${r.transferred === 1 ? '1 Eintrag aus dem Projekt gehört' : `${r.transferred} Einträge aus dem Projekt gehören`} jetzt dir.` : ''}`)
      onCount(Math.max((p.access?.members ?? 1) - 1, 0))
      changed()
    },
  })
  const ask = (m: ProjectMember) => m.id === me?.id
    ? confirm(`Projekt "${p.name}" verlassen? Was du darin angelegt hast, bleibt im Projekt und gehört dann ${p.access?.owner || 'dem Besitzer'}.`)
    : confirm(`${m.name || m.email} aus dem Projekt entfernen? Was diese Person im Projekt angelegt hat, bleibt im Projekt und gehört dann dir.`)
  const valid = /^\S+@\S+\.\S+$/.test(email.trim())

  return (
    <section className="panel p-4 grid gap-3" aria-label="Mitglieder">
      <div className="grid gap-1">
        <h2 className="text-lg font-semibold">Gemeinsam bearbeiten</h2>
        <div className="hint mt-0">
          Mitglieder bearbeiten alles im Projekt: Schublade, Vorlage, Werkzeuge und Einlagen. Löschen können sie nur, was sie selbst angelegt haben;
          Mitglieder verwalten und das Projekt archivieren kann nur {manage ? 'du als Besitzer' : 'der Besitzer'}. Deine übrige Bibliothek bleibt privat.
        </div>
      </div>
      {members.isError && <Msg kind="err">{errText(members.error)}</Msg>}
      <ul className="grid gap-1 m-0 p-0 list-none">
        {(members.data ?? []).map((m) => (
          <li key={m.id} className="flex items-center gap-3 flex-wrap py-1.5" style={{ borderTop: '1px solid var(--line)' }}>
            <span className="grid min-w-0 flex-1">
              <span className="font-medium truncate">{m.name || m.email}{m.id === me?.id ? ' (du)' : ''}</span>
              {m.name && <span className="text-xs truncate" style={{ color: 'var(--ink-2)' }}>{m.email}</span>}
            </span>
            {m.status === 'pending' && <span className="chip chip-warn text-xs" title="Das Konto wartet noch auf Freischaltung durch einen Admin">wartet auf Freischaltung</span>}
            {m.role === 'owner'
              ? <span className="chip text-xs"><Crown size={12} /> Besitzer</span>
              : <span className="chip text-xs">Mitglied</span>}
            {m.role === 'member' && (manage || m.id === me?.id) && (
              <button className="btn btn-sm btn-quiet" disabled={remove.isPending} onClick={() => ask(m) && remove.mutate(m)}
                aria-label={m.id === me?.id ? 'Projekt verlassen' : `${m.name || m.email} entfernen`}>
                {m.id === me?.id ? <><SignOut size={14} /> Verlassen</> : <><UserMinus size={14} /> Entfernen</>}
              </button>
            )}
          </li>
        ))}
        {members.isPending && <li className="skeleton h-10" />}
      </ul>
      {manage && (
        <form className="flex gap-2 flex-wrap items-end" onSubmit={(e) => { e.preventDefault(); if (valid) add.mutate() }}>
          <label className="grid gap-1 flex-1" style={{ minWidth: 220 }}>
            <span className="label mb-0">Person hinzufügen (E-Mail ihres Kontos)</span>
            <input className="input" type="email" autoComplete="off" value={email} maxLength={200} placeholder="name@beispiel.de"
              onChange={(e) => { setEmail(e.target.value); setNote(null); add.reset() }} />
          </label>
          <button className="btn btn-primary" type="submit" disabled={!valid || add.isPending}><UserPlus size={16} /> Hinzufügen</button>
        </form>
      )}
      {manage && <div className="hint mt-0">Die Person braucht ein Konto: Sie meldet sich einmal an; neue Konten schaltet ein Admin frei.</div>}
      {add.isError && <Msg kind="err">{errText(add.error)}</Msg>}
      {remove.isError && <Msg kind="err">{errText(remove.error)}</Msg>}
      {note && <Msg kind="ok" onClose={() => setNote(null)}>{note}</Msg>}
    </section>
  )
}
