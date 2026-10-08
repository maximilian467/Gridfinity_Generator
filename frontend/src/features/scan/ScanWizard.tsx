import { useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router'
import {
  ArrowLeft, ArrowRight, Camera, CheckCircle, Circle, CornersOut, Crop, Lightbulb, LockSimple, Ruler, UploadSimple,
} from '@phosphor-icons/react'
import { api, type SegmentResult } from '../../lib/api'
import type { ObjectSpec, PhotoMeta } from '../../lib/types'
import { BusyBar, Msg, Msgs, Stat, errText } from '../../components/ui'
import { CornerEditor } from './CornerEditor'
import { MaskEditor } from './MaskEditor'
import { ProfileStep } from './ProfileStep'

type View = 'top' | 'side'

interface StepDef { title: string; group: string; view?: View; kind: 'upload' | 'corners' | 'mask' | 'profile' }
const STEPS: StepDef[] = [
  { group: 'Draufsicht', title: 'Foto hochladen', view: 'top', kind: 'upload' },
  { group: 'Draufsicht', title: 'Blatt erkennen', view: 'top', kind: 'corners' },
  { group: 'Draufsicht', title: 'Umriss prüfen', view: 'top', kind: 'mask' },
  { group: 'Seitenansicht', title: 'Foto hochladen', view: 'side', kind: 'upload' },
  { group: 'Seitenansicht', title: 'Blatt erkennen', view: 'side', kind: 'corners' },
  { group: 'Seitenansicht', title: 'Umriss prüfen', view: 'side', kind: 'mask' },
  { group: 'Ergebnis', title: 'Profil und Maße', kind: 'profile' },
]

function stepDone(o: ObjectSpec, i: number): boolean {
  const s = STEPS[i]
  if (s.kind === 'profile') return !!o.profile && !!o.photos.side
  const ph = s.view ? o.photos[s.view] : undefined
  if (s.kind === 'upload') return !!ph
  if (s.kind === 'corners') return !!ph?.rectified_url
  return !!ph?.mask_url
}
function stepOpen(o: ObjectSpec, i: number): boolean {
  return i === 0 || stepDone(o, i - 1)
}

export function ScanWizard() {
  const { id = '' } = useParams()
  const obj = useQuery({ queryKey: ['object', id], queryFn: () => api.object(id) })
  const [step, setStep] = useState<number | null>(null)

  if (obj.isPending) return <div className="p-6"><div className="skeleton h-96 max-w-[1300px] mx-auto" /></div>
  if (obj.isError) return <div className="p-6 max-w-[900px] mx-auto"><Msg kind="err">{errText(obj.error)}</Msg></div>
  const o = obj.data
  const firstOpen = STEPS.findIndex((_, i) => !stepDone(o, i))
  const cur = step ?? (firstOpen === -1 ? 6 : firstOpen)

  return (
    <div className="grid lg:grid-cols-[272px_minmax(0,1fr)] min-h-[calc(100dvh-56px)]">
      <StepRail o={o} cur={cur} onGo={setStep} />
      <section className="min-w-0 flex flex-col">
        <StepBody key={cur} o={o} i={cur} go={setStep} />
      </section>
    </div>
  )
}

function StepRail({ o, cur, onGo }: { o: ObjectSpec; cur: number; onGo: (i: number) => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState(o.name)
  const save = () => name.trim() && name !== o.name &&
    api.renameObject(o.id, name.trim()).then(() => { qc.invalidateQueries({ queryKey: ['object', o.id] }); qc.invalidateQueries({ queryKey: ['objects'] }) })
  let lastGroup = ''
  return (
    <aside className="panel p-4 grid gap-4 content-start" style={{ borderRadius: 0, borderWidth: '0 1px 0 0', boxShadow: 'none' }}>
      <div>
        <label className="label" htmlFor="objname">Objekt</label>
        <input id="objname" className="input font-semibold" value={name} onChange={(e) => setName(e.target.value)} onBlur={save}
          onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()} />
      </div>
      <nav aria-label="Schritte" className="grid grid-cols-[minmax(0,1fr)] gap-0.5">
        {STEPS.map((s, i) => {
          const done = stepDone(o, i), open = stepOpen(o, i), active = i === cur
          const head = s.group !== lastGroup ? (lastGroup = s.group) : null
          return (
            <div key={i}>
              {head && <div className="text-xs font-semibold mt-3 mb-1" style={{ color: 'var(--ink-3)' }}>{head}</div>}
              <button disabled={!open && !done} onClick={() => onGo(i)} aria-current={active ? 'step' : undefined}
                className="w-full flex items-center gap-2.5 px-2 py-2 rounded text-left border-0 cursor-pointer disabled:cursor-not-allowed"
                style={{ background: active ? 'var(--accent-soft)' : 'transparent', color: !open && !done ? 'var(--ink-3)' : 'var(--ink)', font: 'inherit' }}>
                {done ? <CheckCircle size={18} weight="fill" color="var(--ok)" />
                  : !open ? <LockSimple size={18} /> : <Circle size={18} weight={active ? 'bold' : 'regular'} color={active ? 'var(--accent)' : undefined} />}
                <span className={active ? 'font-semibold' : ''}>{s.title}</span>
              </button>
            </div>
          )
        })}
      </nav>
      <div className="hint">Grün = erledigt. Jeder Schritt lässt sich später erneut öffnen und korrigieren.</div>
    </aside>
  )
}

/* ------------------------------------------------------------------ */

function StepHeader({ i, icon, children }: { i: number; icon: ReactNode; children: ReactNode }) {
  const s = STEPS[i]
  return (
    <header className="grid grid-cols-[minmax(0,1fr)] gap-2 max-w-[900px]">
      <div className="text-sm" style={{ color: 'var(--ink-3)' }}>Schritt {i + 1} von {STEPS.length} · {s.group}</div>
      <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">{icon}{s.title}</h1>
      <div className="max-w-[70ch]" style={{ color: 'var(--ink-2)' }}>{children}</div>
    </header>
  )
}

function ActionBar({ onBack, primary, secondary, status }: {
  onBack?: () => void
  primary?: { label: string; onClick: () => void; disabled?: boolean; busy?: boolean }
  secondary?: ReactNode
  status?: ReactNode
}) {
  return (
    <div className="actionbar mt-auto">
      {onBack && <button className="btn" onClick={onBack}><ArrowLeft size={16} /> Zurück</button>}
      <div className="flex-1 min-w-0 text-sm truncate" style={{ color: 'var(--ink-2)' }}>{status}</div>
      {secondary}
      {primary && (
        <button className="btn btn-primary" onClick={primary.onClick} disabled={primary.disabled || primary.busy}>
          {primary.busy ? 'Bitte warten …' : primary.label} {!primary.busy && <ArrowRight size={16} />}
        </button>
      )}
    </div>
  )
}

function StepBody({ o, i, go }: { o: ObjectSpec; i: number; go: (i: number) => void }) {
  const s = STEPS[i]
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ['object', o.id] })
  if (s.kind === 'upload') return <UploadStep o={o} i={i} view={s.view!} onDone={() => { refresh(); go(i + 1) }} go={go} />
  const ph = o.photos[s.view ?? 'top']
  if (s.kind === 'corners' && ph) return <CornersStep o={o} i={i} view={s.view!} photo={ph} refresh={refresh} go={go} />
  if (s.kind === 'mask' && ph?.rectified_url) return <MaskStep o={o} i={i} view={s.view!} photo={ph} refresh={refresh} go={go} />
  if (s.kind === 'profile') {
    if (!o.photos.top?.mask_url || !o.photos.side?.mask_url) {
      return (
        <div className="p-6 grid grid-cols-[minmax(0,1fr)] gap-4">
          <StepHeader i={i} icon={<Ruler size={26} />}>Hier werden beide Umrisse zu Maßen und einem Höhenprofil kombiniert.</StepHeader>
          <Msg kind="warn">Dafür werden beide Umrisse gebraucht. Es fehlt noch: {!o.photos.top?.mask_url && 'Draufsicht'} {!o.photos.side?.mask_url && 'Seitenansicht'}.</Msg>
          <ActionBar onBack={() => go(i - 1)} />
        </div>
      )
    }
    return <ProfileStep o={o} i={i} header={(c) => <StepHeader i={i} icon={<Ruler size={26} />}>{c}</StepHeader>}
      bar={(p) => <ActionBar onBack={() => go(i - 1)} {...p} />} />
  }
  return <div className="p-6"><Msg kind="warn">Dieser Schritt braucht zuerst den vorherigen.</Msg><button className="btn mt-3" onClick={() => go(i - 1)}>Zurück</button></div>
}

/* ------------------------------------------------------------------ */

const TIPS: Record<View, string[]> = {
  top: [
    'Werkzeug flach auf ein weißes A4-Blatt legen. Das ganze Blatt muss im Bild sein.',
    'Von oben fotografieren, Kamera möglichst parallel zum Blatt, etwa 30 bis 40 cm Abstand.',
    'Werkzeug ungefähr in die Blattmitte legen, keine Hand im Bild.',
    'Gleichmäßiges Licht, keine harten Schatten.',
    'Original-Foto verwenden (nicht über WhatsApp verschicken): sonst fehlen Auflösung und Brennweite.',
  ],
  side: [
    'Werkzeug hochkant auf die schmale Kante stellen und an einem Ende festhalten.',
    'Wieder von oben fotografieren, ganzes Blatt im Bild, gleicher Abstand wie bei der Draufsicht.',
    'Die Hand darf im Bild sein: sie wird anhand der Werkzeugfarbe aus der Draufsicht automatisch entfernt.',
    'Möglichst wenig vom Werkzeug mit den Fingern verdecken.',
  ],
}

function UploadStep({ o, i, view, onDone, go }: { o: ObjectSpec; i: number; view: View; onDone: () => void; go: (i: number) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const ph = o.photos[view]
  const up = useMutation({ mutationFn: (f: File) => api.uploadPhoto(o.id, view, f), onSuccess: onDone })
  const pick = (f?: File | null) => f && up.mutate(f)
  return (
    <>
      <div className="p-6 grid grid-cols-[minmax(0,1fr)] gap-5">
        <StepHeader i={i} icon={<Camera size={26} />}>
          {view === 'top'
            ? 'Das Foto von oben liefert den Umriss des Werkzeugs. Das A4-Blatt dient als Maßstab: aus seinen vier Ecken wird später auf 0,1 mm genau entzerrt.'
            : 'Das hochkant fotografierte Werkzeug liefert die Dicke entlang der Länge. Daraus entsteht der gestufte Taschenboden, auf dem das Werkzeug kippelfrei liegt.'}
        </StepHeader>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,1fr)_360px] max-w-[1200px]">
          <div className="panel grid place-items-center text-center p-8 gap-3"
            style={{ borderStyle: 'dashed', borderWidth: 2, minHeight: 300, borderColor: drag ? 'var(--accent)' : 'var(--line-2)', background: drag ? 'var(--accent-soft)' : undefined }}
            onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]) }}>
            {ph ? <img src={ph.preview_url} alt="Aktuelles Foto" className="max-h-56 rounded" style={{ border: '1px solid var(--line)' }} />
              : <UploadSimple size={40} color="var(--ink-3)" />}
            <div className="font-semibold">{ph ? 'Foto vorhanden. Neues Foto hierher ziehen, um es zu ersetzen.' : 'Foto hierher ziehen'}</div>
            <input ref={input} type="file" accept="image/*" hidden onChange={(e) => pick(e.target.files?.[0])} />
            <button className="btn" disabled={up.isPending} onClick={() => input.current?.click()}>
              <UploadSimple size={16} /> {ph ? 'Anderes Foto wählen' : 'Foto auswählen'}
            </button>
            {up.isPending && <div className="w-64"><BusyBar label="Lade hoch und suche das Blatt …" /></div>}
            {up.isError && <Msg kind="err">{errText(up.error)}</Msg>}
          </div>
          <aside className="panel p-4 grid gap-3 content-start">
            <h2 className="sect flex items-center gap-2"><Lightbulb size={16} /> So gelingt das Foto</h2>
            <ol className="m-0 pl-5 grid gap-2" style={{ color: 'var(--ink-2)' }}>
              {TIPS[view].map((t) => <li key={t}>{t}</li>)}
            </ol>
          </aside>
        </div>
      </div>
      <ActionBar onBack={i > 0 ? () => go(i - 1) : undefined}
        status={ph ? 'Foto ist vorhanden.' : 'Noch kein Foto hochgeladen.'}
        primary={{ label: 'Weiter', onClick: () => go(i + 1), disabled: !ph, busy: up.isPending }} />
    </>
  )
}

function CornersStep({ o, i, view, photo, refresh, go }: {
  o: ObjectSpec; i: number; view: View; photo: PhotoMeta; refresh: () => void; go: (i: number) => void
}) {
  const set = useMutation({ mutationFn: (c: number[][]) => api.setCorners(o.id, view, c), onSuccess: refresh })
  const pose = photo.pose
  return (
    <>
      <div className="p-6 grid grid-cols-[minmax(0,1fr)] gap-5">
        <StepHeader i={i} icon={<CornersOut size={26} />}>
          Die vier Ecken des A4-Blattes legen den Maßstab fest. Das Foto wird damit perspektivisch entzerrt (rechts):
          danach ist 1 Pixel genau 0,1 mm. Liegen die Punkte nicht exakt auf den Blattecken, einfach ziehen.
        </StepHeader>
        {photo.corners_found
          ? <Msg kind="ok">Blatt automatisch erkannt. Bitte kurz prüfen, ob alle vier Punkte auf den Ecken sitzen, auch wenn eine Ecke verdeckt ist.</Msg>
          : <Msg kind="warn">Das Blatt wurde nicht automatisch gefunden. Bitte die vier Punkte auf die Blattecken ziehen.</Msg>}
        <div className="grid grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-2 content-start">
            <h2 className="sect">Original mit Blattecken</h2>
            <CornerEditor photo={photo} busy={set.isPending} onChange={(c) => set.mutate(c)} />
          </div>
          <div className="grid grid-cols-[minmax(0,1fr)] gap-3 content-start">
            <h2 className="sect">Entzerrt (Kontrolle)</h2>
            {photo.rectified_url && (
              <img src={photo.rectified_url + '?v=' + encodeURIComponent(photo.corners_px.flat().map(Math.round).join('-'))}
                alt="Entzerrte Ansicht" className="w-full rounded" style={{ border: '1px solid var(--line)' }} />
            )}
            <div className="hint">Das weiße Blatt muss hier ein sauberes, gerades Rechteck sein.</div>
            {pose && (
              <div className="grid grid-cols-2 gap-2">
                <Stat k="Kamerahöhe" v={pose.C_mm[2].toFixed(0)} unit="mm" />
                <Stat k="Brennweite (KB)" v={photo.f35 ? photo.f35.toFixed(0) : '26'} unit={photo.f35 ? 'mm' : 'mm, geschätzt'} />
              </div>
            )}
            <Msgs items={pose?.warnings} />
          </div>
        </div>
        {set.isError && <Msg kind="err">{errText(set.error)}</Msg>}
      </div>
      <ActionBar onBack={() => go(i - 1)}
        status={set.isPending ? 'Entzerre mit den neuen Ecken …' : 'Ecken werden beim Loslassen sofort übernommen.'}
        primary={{ label: 'Weiter zum Umriss', onClick: () => go(i + 1), busy: set.isPending }} />
    </>
  )
}

function MaskStep({ o, i, view, photo, refresh, go }: {
  o: ObjectSpec; i: number; view: View; photo: PhotoMeta; refresh: () => void; go: (i: number) => void
}) {
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<SegmentResult | null>(null)
  return (
    <>
      <div className="p-6 grid grid-cols-[minmax(0,1fr)] gap-5">
        <StepHeader i={i} icon={<Crop size={26} />}>
          {view === 'top'
            ? 'Der Umriss des Werkzeugs wird automatisch erkannt (orange). Er wird später mit dem eingestellten Spiel zur Tasche. Fehler lassen sich mit Klicks oder dem Pinsel korrigieren.'
            : 'Die Silhouette des hochkant gestellten Werkzeugs (orange) ergibt die Dicke. Die haltende Hand wird automatisch erkannt und entfernt (grau schraffiert).'}
        </StepHeader>
        <MaskEditor key={view} oid={o.id} view={view} photo={photo} hasTopMask={!!o.photos.top?.mask_url}
          onMaskChanged={refresh} onBusy={setBusy} onResult={setRes} />
      </div>
      <ActionBar onBack={() => go(i - 1)}
        status={busy ? 'Erkenne Umriss …' : !photo.mask_url ? 'Noch kein Umriss vorhanden.' :
          res?.hand_removed ? `Umriss fertig, Hand entfernt (${Math.round((res.hand_frac ?? 0) * 100)} % der Fläche).` : 'Umriss fertig.'}
        primary={{ label: i === 5 ? 'Weiter zum Profil' : 'Weiter', onClick: () => go(i + 1), disabled: !photo.mask_url, busy }} />
    </>
  )
}
