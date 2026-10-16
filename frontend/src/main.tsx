import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import { initTheme } from './lib/theme'
import { reloadOnceForStaleChunks } from './lib/chunkError'

initTheme()
// Nach einem Deploy kennt eine offene Seite noch alte Dateinamen: einmal neu laden statt Fehler
window.addEventListener('vite:preloadError', (e) => { if (reloadOnceForStaleChunks()) e.preventDefault() })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
