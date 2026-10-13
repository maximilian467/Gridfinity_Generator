import { useEffect, useState } from 'react'
import { CaretDown, GoogleLogo, HourglassMedium, SquaresFour } from '@phosphor-icons/react'
import { Msg } from '../../components/ui'
import type { AuthConfig } from '../../lib/types'

/** Rückmeldung vom Google-Login (Weiterleitung auf /?login=...). */
const RESULT: Record<string, { kind: 'err' | 'warn'; text: string }> = {
  error: { kind: 'err', text: 'Die Anmeldung mit Google hat nicht geklappt. Bitte erneut versuchen.' },
  disabled: { kind: 'err', text: 'Dieses Konto ist gesperrt. Wende dich an den Admin.' },
  full: { kind: 'warn', text: 'Gerade warten zu viele neue Konten auf Freischaltung. Bitte später erneut versuchen.' },
}

let lastResult: string | null = null

/** Liest ?login=... einmal aus und entfernt es aus der Adresse (wiederholbar, z. B. im StrictMode). */
function readResult(): string | null {
  const p = new URLSearchParams(window.location.search)
  const r = p.get('login')
  if (!r) return lastResult
  lastResult = r
  p.delete('login')
  const q = p.toString()
  window.history.replaceState(null, '', window.location.pathname + (q ? `?${q}` : ''))
  return r
}

export function Login({ onDone }: { onDone: () => void }) {
  const [result] = useState(readResult)
  const [cfg, setCfg] = useState<AuthConfig | null>(null)
  const [showLocal, setShowLocal] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    fetch('/api/auth/config').then((r) => r.json()).then((c: AuthConfig) => {
      setCfg(c)
      if (!c.google) setShowLocal(true)          // ohne Google gibt es nur den Passwort-Login
    }).catch(() => setCfg({ auth: true, google: false, local: true }))
  }, [])

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

  const brand = (
    <div className="flex items-center gap-2 font-semibold text-lg">
      <SquaresFour size={22} weight="bold" color="var(--accent)" /> Gridfinity Einlagen
    </div>
  )

  if (result === 'pending') {
    return (
      <div className="min-h-[100dvh] grid place-items-center px-4 drafting">
        <div className="panel w-full max-w-[420px] p-6 grid gap-4">
          {brand}
          <div className="flex gap-3 items-start">
            <HourglassMedium size={28} color="var(--accent)" className="shrink-0 mt-0.5" />
            <div className="grid gap-1.5">
              <h1 className="font-semibold text-base">Dein Konto wartet auf Freischaltung</h1>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--ink-2)' }}>
                Das Konto ist angelegt. Sobald ein Admin es freigeschaltet hat, kannst du dich hier mit Google anmelden.
              </p>
            </div>
          </div>
          <a className="btn justify-center no-underline" href="/">Zur Anmeldung</a>
        </div>
      </div>
    )
  }

  const msg = result ? RESULT[result] : undefined
  return (
    <div className="min-h-[100dvh] grid place-items-center px-4 drafting">
      <div className="panel w-full max-w-[380px] p-6 grid gap-5">
        {brand}
        {msg && <Msg kind={msg.kind}>{msg.text}</Msg>}
        {!cfg ? (
          <div className="skeleton h-10" />
        ) : (
          <>
            {cfg.google && (
              <div className="grid gap-2">
                <a className="btn btn-primary justify-center no-underline h-11" href="/api/auth/google/login">
                  <GoogleLogo size={18} weight="bold" /> Mit Google anmelden
                </a>
                <p className="text-xs leading-relaxed" style={{ color: 'var(--ink-3)' }}>
                  Neue Konten schaltet ein Admin frei.
                </p>
              </div>
            )}
            {cfg.local && cfg.google && (
              <button type="button" className="btn btn-sm btn-quiet justify-self-start" aria-expanded={showLocal}
                onClick={() => setShowLocal((v) => !v)}>
                <CaretDown size={14} style={{ transform: showLocal ? 'rotate(180deg)' : undefined, transition: 'transform .2s' }} />
                Admin-Zugang mit Passwort
              </button>
            )}
            {cfg.local && showLocal && (
              <form onSubmit={submit} className="grid gap-4" style={cfg.google ? { borderTop: '1px solid var(--line)', paddingTop: 16 } : undefined}>
                <div className="grid gap-1.5">
                  <label className="label mb-0" htmlFor="email">E-Mail</label>
                  <input id="email" className="input" type="email" autoComplete="username" required autoFocus={!cfg.google}
                    value={email} onChange={(e) => setEmail(e.target.value)} />
                </div>
                <div className="grid gap-1.5">
                  <label className="label mb-0" htmlFor="pw">Passwort</label>
                  <input id="pw" className="input" type="password" autoComplete="current-password" required
                    value={password} onChange={(e) => setPassword(e.target.value)} />
                </div>
                {err && <Msg kind="err">{err}</Msg>}
                <button className={`btn justify-center ${cfg.google ? '' : 'btn-primary'}`} disabled={busy}>
                  {busy ? 'Melde an …' : 'Anmelden'}
                </button>
              </form>
            )}
            <div className="flex gap-4 text-xs">
              <a href="/datenschutz" style={{ color: 'var(--ink-3)' }}>Datenschutz</a>
              {cfg.source && <a href={cfg.source} rel="noopener" style={{ color: 'var(--ink-3)' }}>Quellcode</a>}
            </div>
            {!cfg.google && !cfg.local && (
              <Msg kind="warn">Es ist keine Anmeldung eingerichtet. Bitte GOOGLE_CLIENT_ID/SECRET oder ein starkes APP_PASSWORD setzen.</Msg>
            )}
          </>
        )}
      </div>
    </div>
  )
}
