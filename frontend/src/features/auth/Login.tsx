import { useState } from 'react'
import { SquaresFour } from '@phosphor-icons/react'
import { Msg } from '../../components/ui'

export function Login({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }),
      })
      if (!r.ok) {
        const j = await r.json().catch(() => ({}))
        throw new Error(typeof j.detail === 'string' ? j.detail : 'Anmeldung fehlgeschlagen')
      }
      onDone()
    } catch (x) {
      setErr(x instanceof Error && !/fetch/i.test(x.message) ? x.message : 'Server nicht erreichbar')
    } finally { setBusy(false) }
  }

  return (
    <div className="min-h-[100dvh] grid place-items-center px-4 drafting">
      <form onSubmit={submit} className="panel w-full max-w-[380px] p-6 grid gap-4">
        <div className="flex items-center gap-2 font-semibold text-lg">
          <SquaresFour size={22} weight="bold" color="var(--accent)" /> Gridfinity Einlagen
        </div>
        <div className="grid gap-1.5">
          <label className="label mb-0" htmlFor="email">E-Mail</label>
          <input id="email" className="input" type="email" autoComplete="username" required autoFocus
            value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="grid gap-1.5">
          <label className="label mb-0" htmlFor="pw">Passwort</label>
          <input id="pw" className="input" type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {err && <Msg kind="err">{err}</Msg>}
        <button className="btn btn-primary justify-center" disabled={busy}>{busy ? 'Melde an …' : 'Anmelden'}</button>
      </form>
    </div>
  )
}
