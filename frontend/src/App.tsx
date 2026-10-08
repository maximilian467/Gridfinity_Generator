import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Link, NavLink, Outlet, RouterProvider, createBrowserRouter } from 'react-router'
import { lazy, Suspense, useEffect, useState } from 'react'
import { Moon, SignOut, SquaresFour, Sun } from '@phosphor-icons/react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './lib/api'
import { Login } from './features/auth/Login'
import { getTheme, setTheme } from './lib/theme'
import { Library } from './features/library/Library'
import { ApiStatus } from './components/ui'

const ScanWizard = lazy(() => import('./features/scan/ScanWizard').then((m) => ({ default: m.ScanWizard })))
const Designer = lazy(() => import('./features/insert/Designer').then((m) => ({ default: m.Designer })))
const Baseplate = lazy(() => import('./features/baseplate/Baseplate').then((m) => ({ default: m.Baseplate })))

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false } } })

function Shell() {
  const [theme, setT] = useState(getTheme())
  const link = ({ isActive }: { isActive: boolean }) =>
    `px-3 h-14 inline-flex items-center border-b-2 ${isActive ? 'border-[var(--accent)]' : 'border-transparent'}`
  return (
    <div className="min-h-[100dvh] flex flex-col">
      <header className="panel flex items-center gap-6 px-4 h-14 shrink-0" style={{ borderRadius: 0, borderWidth: '0 0 1px 0' }}>
        <Link to="/" className="font-semibold tracking-tight no-underline inline-flex items-center gap-2" style={{ color: 'var(--ink)' }}>
          <SquaresFour size={20} weight="bold" color="var(--accent)" /> Gridfinity Einlagen
        </Link>
        <nav className="flex">
          <NavLink to="/" end className={link}>Bibliothek</NavLink>
          <NavLink to="/baseplate" className={link}>Baseplate</NavLink>
        </nav>
        <div className="flex-1" />
        <LogoutButton />
        <button className="btn btn-sm btn-quiet" aria-label={theme === 'dark' ? 'Helles Design' : 'Dunkles Design'}
          onClick={() => { const n = theme === 'dark' ? 'light' : 'dark'; setTheme(n); setT(n) }}>
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />} {theme === 'dark' ? 'Hell' : 'Dunkel'}
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
    ],
  },
])

function LogoutButton() {
  const qc2 = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, retry: false })
  if (!me.data?.auth) return null
  return (
    <button className="btn btn-sm btn-quiet" title={me.data.user}
      onClick={async () => { await api.logout().catch(() => {}); qc2.clear(); window.dispatchEvent(new Event('auth-required')) }}>
      <SignOut size={16} /> Abmelden
    </button>
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
