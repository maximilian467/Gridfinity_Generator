import { Component } from 'react'
import type { ReactNode } from 'react'
import { webglAvailable } from '../lib/glbLoad'

/** Statt einer leeren Fläche eine Meldung zeigen, wenn die 3D-Ansicht nicht laufen kann
 *  (kein WebGL, Grafiktreiber, Fehler beim Laden). */
export class ThreeGuard extends Component<{ children: ReactNode; height: number }, { error: string | null }> {
  state = { error: webglAvailable() ? null : 'Dieser Browser stellt kein WebGL bereit (Hardwarebeschleunigung aus oder Grafiktreiber blockiert).' }

  static getDerivedStateFromError(e: unknown) {
    return { error: e instanceof Error ? e.message : String(e) }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="panel grid place-items-center p-6 text-center" style={{ height: this.props.height }} role="alert">
        <div className="grid gap-2 max-w-[56ch]">
          <div className="font-semibold">3D-Ansicht nicht möglich</div>
          <div className="text-sm" style={{ color: 'var(--ink-2)' }}>{this.state.error}</div>
          <div className="hint mt-0">Die Dateien zum Herunterladen sind davon nicht betroffen.</div>
          <button className="btn btn-sm justify-self-center" onClick={() => this.setState({ error: null })}>Nochmal versuchen</button>
        </div>
      </div>
    )
  }
}
