import { Component } from 'react'
import type { ReactNode } from 'react'
import { isChunkLoadError } from '../lib/chunkError'

/** Fängt Fehler beim Nachladen eines Programmteils (z. B. der 3D-Bibliothek) ab und erklärt sie.
 *  Liegt bewusst nicht im 3D-Chunk, damit die Meldung auch erscheint, wenn genau der fehlt. */
export class ChunkGuard extends Component<{ children: ReactNode; height: number; what: string }, { error: unknown }> {
  state: { error: unknown } = { error: null }

  static getDerivedStateFromError(error: unknown) {
    return { error }
  }

  render() {
    const e = this.state.error
    if (!e) return this.props.children
    const chunk = isChunkLoadError(e)
    return (
      <div className="panel grid place-items-center p-6 text-center" style={{ height: this.props.height }} role="alert">
        <div className="grid gap-2 max-w-[62ch]">
          <div className="font-semibold">{this.props.what} konnte nicht geladen werden</div>
          {chunk ? (
            <div className="text-sm" style={{ color: 'var(--ink-2)' }}>
              Ein Programmteil ist nicht im Browser angekommen. Nach einem Update hilft Neuladen. Bleibt es dabei, hält etwas in
              deinem Netz die Datei zurück (z. B. Firmen-Proxy oder Virenscanner): in einem anderen Netz (Zuhause, Handy-Hotspot)
              probieren oder die IT um Freigabe dieser Seite bitten.
            </div>
          ) : (
            <div className="text-sm" style={{ color: 'var(--ink-2)' }}>{e instanceof Error ? e.message : String(e)}</div>
          )}
          <div className="num text-xs" style={{ color: 'var(--ink-3)' }}>{e instanceof Error ? e.message : String(e)}</div>
          <div className="flex gap-2 justify-center">
            <button className="btn btn-sm btn-primary" onClick={() => window.location.reload()}>Seite neu laden</button>
            <button className="btn btn-sm" onClick={() => this.setState({ error: null })}>Nochmal versuchen</button>
          </div>
          <div className="hint mt-0">Die Dateien zum Herunterladen (3MF, STL) sind davon nicht betroffen.</div>
        </div>
      </div>
    )
  }
}
