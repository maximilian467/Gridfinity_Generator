import { useEffect, useState } from 'react'

export default function App() {
  const [status, setStatus] = useState('prüfe …')
  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => setStatus(d.status))
      .catch(() => setStatus('Backend nicht erreichbar'))
  }, [])
  return (
    <main className="p-8">
      <h1 className="text-2xl font-semibold">Gridfinity-Einlagen-Generator</h1>
      <p className="mt-2">Backend: {status}</p>
    </main>
  )
}
