import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Link, NavLink, Outlet, RouterProvider, createBrowserRouter } from 'react-router'
import { lazy, Suspense } from 'react'
import { Library } from './features/library/Library'

const ScanWizard = lazy(() => import('./features/scan/ScanWizard').then((m) => ({ default: m.ScanWizard })))
const Designer = lazy(() => import('./features/insert/Designer').then((m) => ({ default: m.Designer })))
const Baseplate = lazy(() => import('./features/baseplate/Baseplate').then((m) => ({ default: m.Baseplate })))

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false, retry: false } } })

function Shell() {
  const link = ({ isActive }: { isActive: boolean }) =>
    `px-3 h-14 inline-flex items-center border-b-2 ${isActive ? 'border-[var(--accent)]' : 'border-transparent'}`
  return (
    <div className="min-h-[100dvh] flex flex-col">
      <header className="panel flex items-center gap-6 px-4 h-14 shrink-0" style={{ borderRadius: 0, borderWidth: '0 0 1px 0' }}>
        <Link to="/" className="font-semibold tracking-tight no-underline" style={{ color: 'var(--ink)' }}>
          Gridfinity Einlagen
        </Link>
        <nav className="flex">
          <NavLink to="/" end className={link}>Bibliothek</NavLink>
          <NavLink to="/baseplate" className={link}>Baseplate</NavLink>
        </nav>
      </header>
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

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
