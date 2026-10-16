/** Nachgeladene Programmteile (Vite-Chunks), die nicht ankommen.
 *
 * Zwei Ursachen: (1) nach einem Deploy hat die offene Seite noch alte Dateinamen -> einmal neu laden hilft;
 * (2) etwas im Netz (Firmen-Proxy, Virenscanner) hält die Datei zurück -> erklären statt leer bleiben. */

export function isChunkLoadError(e: unknown): boolean {
  const m = e instanceof Error ? `${e.name} ${e.message}` : String(e)
  return /dynamically imported module|Importing a module script failed|error loading dynamically imported module|ChunkLoadError|Unable to preload CSS/i.test(m)
}

const KEY = 'chunk-reload-at'

/** Nach einem Deploy: höchstens einmal je Minute automatisch neu laden (keine Endlosschleife). */
export function reloadOnceForStaleChunks(now = Date.now(), store: Pick<Storage, 'getItem' | 'setItem'> = sessionStorage,
  reload: () => void = () => window.location.reload()): boolean {
  let last = 0
  try { last = Number(store.getItem(KEY) || 0) } catch { /* ohne Speicher: nicht neu laden */ return false }
  if (now - last < 60_000) return false
  try { store.setItem(KEY, String(now)) } catch { return false }
  reload()
  return true
}
