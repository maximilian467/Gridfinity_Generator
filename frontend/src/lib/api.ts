export interface SegmentResult {
  mask_url: string; overlay_url: string; contour_px: number[][]; area_mm2?: number
  touches_paper_edge?: boolean; sam_used?: boolean; hand_removed?: boolean; hand_frac?: number; hand_url?: string | null
  edit_contour_px?: [number, number][]
}

import type { BaseplateSpec, InsertSpec, Job, LayoutOut, ObjectSpec, PhotoMeta } from './types'

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch('/api' + url, init)
  if (r.status === 401) {
    window.dispatchEvent(new Event('auth-required'))      // App zeigt die Anmeldung
    throw new Error('Bitte anmelden')
  }
  if (!r.ok) {
    let msg = r.statusText
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* leer */ }
    throw new Error(msg)
  }
  return r.json()
}
const json = (method: string, body?: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body),
})

export const api = {
  me: () => req<{ user: string; auth: boolean }>('/auth/me'),
  logout: () => req('/auth/logout', json('POST')),
  objects: () => req<ObjectSpec[]>('/objects'),
  object: (id: string) => req<ObjectSpec>(`/objects/${id}`),
  createObject: (name: string) => req<ObjectSpec>('/objects', json('POST', { name })),
  createDemo: () => req<ObjectSpec>('/objects/demo', json('POST')),
  renameObject: (id: string, name: string) => req<ObjectSpec>(`/objects/${id}`, json('PUT', { name })),
  deleteObject: (id: string) => req(`/objects/${id}`, json('DELETE')),
  uploadPhoto: (id: string, view: string, file: File) => {
    const fd = new FormData(); fd.append('file', file)
    return req<PhotoMeta>(`/objects/${id}/photos/${view}`, { method: 'POST', body: fd })
  },
  setCorners: (id: string, view: string, corners_px: number[][]) =>
    req<PhotoMeta>(`/objects/${id}/photos/${view}/corners`, json('PUT', { corners_px })),
  segment: (id: string, view: string, body: { pos: number[][]; neg: number[][]; fill_holes: boolean; remove_hand?: boolean }) =>
    req<SegmentResult>(
      `/objects/${id}/photos/${view}/segment`, json('POST', body)),
  uploadMask: (id: string, view: string, blob: Blob, fill_holes: boolean) => {
    const fd = new FormData(); fd.append('file', blob, 'mask.png')
    return req<SegmentResult>(`/objects/${id}/photos/${view}/mask?fill_holes=${fill_holes}`,
      { method: 'PUT', body: fd })
  },
  profile: (id: string, body: Record<string, unknown>) => req<ObjectSpec>(`/objects/${id}/profile`, json('POST', body)),

  inserts: () => req<InsertSpec[]>('/inserts'),
  insert: (id: string) => req<InsertSpec>(`/inserts/${id}`),
  createInsert: (spec: Partial<InsertSpec>) => req<InsertSpec>('/inserts', json('POST', spec)),
  saveInsert: (spec: InsertSpec) => req<InsertSpec>(`/inserts/${spec.id}`, json('PUT', spec)),
  deleteInsert: (id: string) => req(`/inserts/${id}`, json('DELETE')),
  duplicateInsert: (id: string) => req<InsertSpec>(`/inserts/${id}/duplicate`, json('POST')),
  layout: (spec: InsertSpec) => req<LayoutOut>(`/inserts/${spec.id}/layout`, json('POST', spec)),
  build: (spec: InsertSpec) => req<{ job_id: string }>(`/inserts/${spec.id}/build`, json('POST', spec)),
  autoCompartments: (spec: InsertSpec) =>
    req<{ compartments: InsertSpec['compartments'] }>(`/inserts/${spec.id}/auto-compartments`, json('POST', spec)),

  job: (id: string) => req<Job>(`/jobs/${id}`),
  buildBaseplate: (spec: BaseplateSpec) => req<{ job_id: string }>('/baseplates/build', json('POST', spec)),
}
