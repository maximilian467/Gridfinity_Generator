import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Link, NavLink, Outlet, RouterProvider, createBrowserRouter } from 'react-router'
import { lazy, Suspense, useEffect, useState } from 'react'
import { Moon, SignOut, SquaresFour, Sun } from '@phosphor-icons/react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './lib/api'
import { Login } from './features/auth/Login'
import { getTheme, setTheme } from './lib/theme'
import { Library } from './features/library/Library'
import { ApiStatus, Initials } from './components/ui'

const ScanWizard = lazy(() => import('./features/scan/ScanWizard').then((m) => ({ default: m.ScanWizard })))
const Designer = lazy(() => import('./features/insert/Designer').then((m) => ({ default: m.Designer })))
const Baseplate = lazy(() => import('./features/baseplate/Baseplate').then((m) => ({ default: m.Baseplate })))
const Users = lazy(() => import('./features/admin/Users').then((m) => ({ default: m.Users })))

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false } } })

function Shell() {
  const [theme, setT] = useState(getTheme())
  const link = ({ isActive }: { isActive: boolean }) =>
    `px-3 h-14 inline-flex items-center border-b-2 ${isActive ? 'border-[var(--accent)]' : 'border-transparent'}`
  return (
    <div className="min-h-[100dvh] flex flex-col">
      <header className="panel flex items-center gap-3 md:gap-6 px-4 h-14 shrink-0" style={{ borderRadius: 0, borderWidth: '0 0 1px 0' }}>
        <Link to="/" className="font-semibold tracking-tight no-underline inline-flex items-center gap-2" style={{ color: 'var(--ink)' }}>
          <SquaresFour size={20} weight="bold" color="var(--accent)" /> <span className="hidden md:inline">Gridfinity Einlagen</span>
        </Link>
        <nav className="flex min-w-0 overflow-x-auto">
          <NavLink to="/" end className={link}>Bibliothek</NavLink>
          <NavLink to="/baseplate" className={link}>Baseplate</NavLink>
          <AdminLink className={link} />
        </nav>
        <div className="flex-1" />
        <UserMenu />
        <button className="btn btn-sm btn-quiet" aria-label={theme === 'dark' ? 'Helles Design' : 'Dunkles Design'}
          onClick={() => { const n = theme === 'dark' ? 'light' : 'dark'; setTheme(n); setT(n) }}>
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />} <span className="hidden md:inline">{theme === 'dark' ? 'Hell' : 'Dunkel'}</span>
        </button>
      </header>
      <ApiStatus />
      <main className="flex-1 min-h-0">
        <Suspense fallback={<div className="p-6"><div className="skeleton h-8 w-64" /></div>}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  )
}

const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { path: '/', element: <Library /> },
      { path: '/scan/:id', element: <ScanWizard /> },
      { path: '/insert/:id', element: <Designer /> },
      { path: '/baseplate', element: <Baseplate /> },
      { path: '/admin/users', element: <Users /> },
    ],
  },
])

function AdminLink({ className }: { className: (a: { isActive: boolean }) => string }) {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, retry: false })
  const isAdmin = me.data?.role === 'admin'
  const users = useQuery({ queryKey: ['admin-users'], queryFn: api.users, enabled: isAdmin, refetchInterval: 60_000 })
  if (!isAdmin) return null
  const waiting = users.data?.filter((u) => u.status === 'pending').length ?? 0
  return (
    <NavLink to="/admin/users" className={(a) => `${className(a)} gap-2`}>
      Nutzer
      {waiting > 0 && (
        <span className="num grid place-items-center min-w-5 h-5 px-1 rounded-full text-xs font-semibold"
          style={{ background: 'var(--accent)', color: 'var(--accent-ink)' }} title={`${waiting} wartet auf Freischaltung`}>
          {waiting}
        </span>
      )}
    </NavLink>
  )
}

function UserMenu() {
  const qc2 = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, retry: false })
  const [open, setOpen] = useState(false)
  if (!me.data?.auth) return null
  const out = async (all: boolean) => {
    await (all ? api.logoutAll() : api.logout()).catch(() => {})
    qc2.clear()
    window.dispatchEvent(new Event('auth-required'))
  }
  return (
    <div className="relative" onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false) }}>
      <button className="btn btn-sm btn-quiet" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen((v) => !v)}>
        <Initials name={me.data.name || me.data.user} size={24} />
        <span className="hidden sm:inline max-w-[160px] truncate">{me.data.name || me.data.user}</span>
      </button>
      {open && (
        <div role="menu" className="panel absolute right-0 top-full mt-1 z-20 w-64 p-2 grid gap-1" style={{ boxShadow: 'var(--shadow)' }}>
          <div className="px-2 py-1.5 text-sm">
            <div className="font-medium truncate">{me.data.name || me.data.user}</div>
            <div className="text-xs truncate" style={{ color: 'var(--ink-2)' }}>{me.data.user}</div>
          </div>
          <button role="menuitem" className="btn btn-sm btn-quiet justify-start" onClick={() => out(false)}>
            <SignOut size={16} /> Abmelden
          </button>
          <button role="menuitem" className="btn btn-sm btn-quiet justify-start" title="Alle Sitzungen auf allen Geräten beenden"
            onClick={() => out(true)}>
            <SignOut size={16} /> Auf allen Geräten abmelden
          </button>
        </div>
      )}
    </div>
  )
}

/** Zeigt die Anmeldung, solange keine gültige Sitzung besteht (oder sobald eine Anfrage 401 liefert). */
function AuthGate() {
  const [state, setState] = useState<'check' | 'in' | 'out'>('check')
  const check = () => fetch('/api/auth/me').then((r) => setState(r.ok ? 'in' : r.status === 401 ? 'out' : 'in')).catch(() => setState('in'))
  useEffect(() => {
    check()
    const onReq = () => setState('out')
    window.addEventListener('auth-required', onReq)
    return () => window.removeEventListener('auth-required', onReq)
  }, [])
  if (state === 'check') return <div className="p-6"><div className="skeleton h-8 w-64" /></div>
  if (state === 'out') return <Login onDone={() => { qc.clear(); setState('in') }} />
  return <RouterProvider router={router} />
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <AuthGate />
    </QueryClientProvider>
  )
}
