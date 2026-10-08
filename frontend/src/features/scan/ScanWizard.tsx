import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router'
import { UploadSimple } from '@phosphor-icons/react'
import { api } from '../../lib/api'
import type { PhotoMeta } from '../../lib/types'
import { Msgs, Stepper } from '../../components/ui'
import { CornerEditor } from './CornerEditor'
import { MaskEditor } from './MaskEditor'
import { ProfileStep } from './ProfileStep'

const STEPS = ['Draufsicht', 'Ecken', 'Maske', 'Seitenfoto', 'Ecken', 'Maske', 'Profil']
type View = 'top' | 'side'

const TIPS: Record<View, string[]> = {
  top: [
    'Werkzeug flach auf ein weißes A4-Blatt legen, Blatt komplett im Bild.',
    'Diffuses Licht, keine harten Schatten. Dunkle Unterlage rund um das Blatt hilft der Erkennung.',
    'Kamera senkrecht darüber, möglichst weit weg und mit 2x-Zoom (mind. 30 cm Abstand).',
    'Werkzeug nahe der Blattmitte, direkt unter der Kamera.',
  ],
  side: [
    'Werkzeug hochkant auf die schmale Kante stellen und an den Enden festhalten.',
    'Finger möglichst außerhalb der Silhouette, sie lassen sich im nächsten Schritt wegradieren.',
    'Wieder von oben fotografieren, A4-Blatt komplett sichtbar, gleicher Abstand wie bei der Draufsicht.',
    'Länge und Lage ungefähr wie bei der Draufsicht (Spitze auf derselben Seite).',
  ],
}

export function ScanWizard() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const obj = useQuery({ queryKey: ['object', id], queryFn: () => api.object(id) })
  const [step, setStep] = useState<number | null>(null)

  if (obj.isPending) return <div className="p-6"><div className="skeleton h-64 max-w-[900px] mx-auto" /></div>
  if (obj.isError) return <div className="p-6"><div className="msg msg-err">Objekt nicht gefunden.</div></div>
  const o = obj.data
  const cur = step ?? (o.profile ? 6 : o.photos.side ? 5 : o.photos.top ? 2 : 0)
  const view: View = cur < 3 ? 'top' : 'side'
  const photo = o.photos[view]
  const refresh = () => qc.invalidateQueries({ queryKey: ['object', id] })
  const go = (i: number) => setStep(i)
  const canGo = (i: number) => i === 0 || i === 3 ? true : i < 3 ? !!o.photos.top : i < 6 ? !!o.photos.side : !!o.photos.side

  return (
    <div className="max-w-[1200px] mx-auto px-4 py-5 grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{o.name}</h1>
        <Stepper steps={STEPS} current={cur} onGo={(i) => canGo(i) && go(i)} />
      </div>

      {(cur === 0 || cur === 3) && <UploadStep key={view} id={id} view={view} has={!!photo} onDone={() => { refresh(); go(cur + 1) }} onSkip={() => go(cur + 1)} />}
      {(cur === 1 || cur === 4) && photo && <CornersStep key={view} id={id} view={view} photo={photo} onNext={() => { refresh(); go(cur + 1) }} refresh={refresh} />}
      {(cur === 2 || cur === 5) && photo?.rectified_url && (
        <div className="grid gap-3">
          <MaskEditor key={view} oid={id} view={view} photo={photo} onMaskChanged={refresh} />
          <div className="flex justify-end gap-2">
            <button className="btn" onClick={() => go(cur - 1)}>Zurück</button>
            <button className="btn btn-primary" disabled={!photo.mask_url} onClick={() => go(cur + 1)}>Weiter</button>
          </div>
        </div>
      )}
      {cur === 6 && (o.photos.top?.mask_url && o.photos.side?.mask_url
        ? <ProfileStep key={o.id} obj={o} />
        : <div className="msg msg-warn">Für das Profil werden beide Masken gebraucht.</div>)}
    </div>
  )
}

function UploadStep({ id, view, has, onDone, onSkip }: { id: string; view: View; has: boolean; onDone: () => void; onSkip: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const up = useMutation({ mutationFn: (f: File) => api.uploadPhoto(id, view, f), onSuccess: onDone })
  const pick = (f?: File | null) => f && up.mutate(f)
  return (
    <div className="grid gap-4 md:grid-cols-[1fr_340px]">
      <div className={`panel grid place-items-center text-center p-10 gap-3 ${drag ? 'border-[var(--accent)]' : ''}`}
        style={{ borderStyle: 'dashed', minHeight: 260 }}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]) }}>
        <UploadSimple size={32} />
        <div className="font-medium">{view === 'top' ? 'Foto der Draufsicht' : 'Foto der Seitenansicht'}</div>
        <div style={{ color: 'var(--ink-2)' }}>Bild hierher ziehen oder auswählen (Originalauflösung, JPEG/PNG)</div>
        <input ref={input} type="file" accept="image/*" hidden onChange={(e) => pick(e.target.files?.[0])} />
        <div className="flex gap-2">
          <button className="btn btn-primary" disabled={up.isPending} onClick={() => input.current?.click()}>
            {up.isPending ? 'Lade hoch …' : 'Foto wählen'}
          </button>
          {has && <button className="btn" onClick={onSkip}>Vorhandenes behalten</button>}
        </div>
        {up.isError && <div className="msg msg-err">{String(up.error).replace('Error: ', '')}</div>}
      </div>
      <aside className="panel p-4 grid gap-2 content-start">
        <h2 className="font-semibold">So gelingt das Foto</h2>
        <ul className="m-0 pl-4 grid gap-1.5" style={{ color: 'var(--ink-2)' }}>
          {TIPS[view].map((t) => <li key={t}>{t}</li>)}
        </ul>
      </aside>
    </div>
  )
}

function CornersStep({ id, view, photo, onNext, refresh }: {
  id: string; view: View; photo: PhotoMeta
  onNext: () => void; refresh: () => void
}) {
  const set = useMutation({ mutationFn: (c: number[][]) => api.setCorners(id, view, c), onSuccess: refresh })
  return (
    <div className="grid gap-3">
      {!photo.corners_found && <div className="msg msg-warn">Das Blatt wurde nicht automatisch gefunden. Bitte die Ecken von Hand setzen.</div>}
      <CornerEditor photo={photo} busy={set.isPending} onChange={(c) => set.mutate(c)} />
      <Msgs items={photo.pose?.warnings} />
      {photo.pose && (
        <div className="hint num">Kamerahöhe {photo.pose.C_mm[2].toFixed(0)} mm, Brennweite {photo.f35 ?? 'unbekannt'} mm (KB-äquiv.)</div>
      )}
      {photo.rectified_url && (
        <div className="grid gap-1">
          <div className="label">Entzerrte Vorschau (Blatt muss ein sauberes Rechteck sein)</div>
          <img src={photo.rectified_url + '?v=' + encodeURIComponent(photo.corners_px.flat().map(Math.round).join('-'))} alt="Entzerrte Ansicht"
            className="panel" style={{ maxWidth: 560 }} />
        </div>
      )}
      {set.isError && <div className="msg msg-err">{String(set.error)}</div>}
      <div className="flex justify-end">
        <button className="btn btn-primary" onClick={onNext} disabled={set.isPending}>Weiter zur Maske</button>
      </div>
    </div>
  )
}
