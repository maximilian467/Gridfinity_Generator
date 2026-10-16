import { Suspense, useEffect, useMemo, useState } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { Center, OrbitControls, useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { fetchGlb } from '../../lib/glbLoad'
import { ThreeGuard } from '../../components/ThreeGuard'
import { BusyBar } from '../../components/ui'

function Model({ url, clip }: { url: string; clip: number }) {
  const gltf = useGLTF(url)
  const { gl } = useThree()
  const [box, setBox] = useState<THREE.Box3 | null>(null)
  const plane = useMemo(() => new THREE.Plane(new THREE.Vector3(0, 0, -1), 1e4), [])

  useEffect(() => {
    gl.localClippingEnabled = true
    gltf.scene.traverse((o) => {
      const m = (o as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined
      for (const mat of Array.isArray(m) ? m : m ? [m] : []) {
        mat.side = THREE.DoubleSide
        mat.clippingPlanes = [plane]
      }
    })
  }, [gltf, gl, plane])

  useEffect(() => {
    const id = requestAnimationFrame(() => setBox(new THREE.Box3().setFromObject(gltf.scene)))
    return () => cancelAnimationFrame(id)
  }, [gltf])

  useEffect(() => {
    if (!box) return
    // clip = 1: alles sichtbar; 0: nichts. Schnitt von hinten nach vorn entlang der Objektachse (CAD-y).
    plane.constant = box.min.z + (box.max.z - box.min.z) * clip + (clip >= 1 ? 1 : 0)
  }, [box, clip, plane])

  return (
    <Center>
      <group rotation={[-Math.PI / 2, 0, 0]}><primitive object={gltf.scene} /></group>
    </Center>
  )
}

/** GLB selbst laden (mit Ersatzweg, falls ein Proxy die Datei blockiert) -> blob:-URL */
function useGlbUrl(url: string): { src: string | null; error: string | null } {
  const [st, setSt] = useState<{ src: string | null; error: string | null }>({ src: null, error: null })
  useEffect(() => {
    let alive = true
    let obj: string | null = null
    setSt({ src: null, error: null })
    fetchGlb(url)
      .then(({ bytes }) => {
        obj = URL.createObjectURL(new Blob([bytes], { type: 'model/gltf-binary' }))
        if (alive) setSt({ src: obj, error: null })
      })
      .catch((e) => alive && setSt({ src: null, error: e instanceof Error ? e.message : String(e) }))
    return () => { alive = false; if (obj) { useGLTF.clear(obj); URL.revokeObjectURL(obj) } }
  }, [url])
  return st
}

export function Preview3D({ url }: { url: string }) {
  const [clip, setClip] = useState(1)
  const glb = useGlbUrl(url)
  return (
    <div className="grid gap-2">
      <ThreeGuard height={520}>
        {glb.error ? (
          <div className="panel grid place-items-center p-6 text-center" style={{ height: 520 }} role="alert">
            <div className="grid gap-2 max-w-[60ch]"><div className="font-semibold">3D-Ansicht nicht möglich</div>
              <div className="text-sm" style={{ color: 'var(--ink-2)' }}>{glb.error}</div></div>
          </div>
        ) : !glb.src ? (
          <div className="panel grid place-items-center" style={{ height: 520 }}><div className="w-64"><BusyBar label="Lade 3D-Modell …" /></div></div>
        ) : (
          <div className="panel" style={{ height: 520 }}>
            <Canvas camera={{ position: [90, 140, 200], fov: 35, near: 1, far: 2000 }}>
              <hemisphereLight args={['#ffffff', '#8a8f98', 1.1]} />
              <directionalLight position={[120, 200, 80]} intensity={1.6} />
              <directionalLight position={[-100, 80, -120]} intensity={0.6} />
              <Suspense fallback={null}><Model url={glb.src} clip={clip} /></Suspense>
              <OrbitControls makeDefault />
            </Canvas>
          </div>
        )}
      </ThreeGuard>
      <label className="flex items-center gap-3 text-sm">
        Schnittebene (quer zur Einlage)
        <input type="range" min={0.02} max={1} step={0.01} value={clip} onChange={(e) => setClip(+e.target.value)} className="flex-1" />
        <span className="num w-12 text-right">{Math.round(clip * 100)} %</span>
      </label>
    </div>
  )
}
