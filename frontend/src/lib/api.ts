export interface SegmentResult {
  mask_url: string; overlay_url: string; contour_px: number[][]; area_mm2?: number
  touches_paper_edge?: boolean; sam_used?: boolean; hand_removed?: boolean; hand_frac?: number; hand_url?: string | null
  edit_contour_px?: [number, number][]
}

import type { AdminUser, AuditEntry, AuthConfig, BaseplateSpec, CloneData, DrawerPlacement, InsertSpec, Job, LayoutOut, Me, ObjectSpec, PhotoMeta, PlatePlan, ProjectSpec, TextureInfo } from './types'

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
  me: () => req<Me>('/auth/me'),
  authConfig: () => req<AuthConfig>('/auth/config'),
  logout: () => req('/auth/logout', json('POST')),
  logoutAll: () => req('/auth/logout-all', json('POST')),
  users: () => req<AdminUser[]>('/admin/users'),
  changeUser: (id: number, body: { status?: 'active' | 'disabled'; role?: 'admin' | 'user' }) =>
    req<AdminUser>(`/admin/users/${id}`, json('PUT', body)),
  deleteUser: (id: number) => req<{ ok: boolean; removed: number }>(`/admin/users/${id}`, json('DELETE')),
  audit: () => req<AuditEntry[]>('/admin/audit?limit=60'),
  objects: (all = false) => req<ObjectSpec[]>(all ? '/objects?all=true' : '/objects'),
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
  setLevels: (id: string, levels: [number, number, number][]) => req<ObjectSpec>(`/objects/${id}/levels`, json('PUT', { levels })),

  inserts: (all = false) => req<InsertSpec[]>(all ? '/inserts?all=true' : '/inserts'),
  insert: (id: string) => req<InsertSpec>(`/inserts/${id}`),
  setStandardHeight: (height_mm: number | null, source = '') =>
    req<{ height_mm: number | null; source: string | null }>('/inserts/standard-height', json('PUT', { height_mm, source })),
  standardHeight: () => req<{ height_mm: number | null; source: string | null }>('/inserts/standard-height'),
  createInsert: (spec: Partial<InsertSpec>) => req<InsertSpec>('/inserts', json('POST', spec)),
  saveInsert: (spec: InsertSpec) => req<InsertSpec>(`/inserts/${spec.id}`, json('PUT', spec)),
  deleteInsert: (id: string) => req(`/inserts/${id}`, json('DELETE')),
  duplicateInsert: (id: string) => req<InsertSpec>(`/inserts/${id}/duplicate`, json('POST')),
  layout: (spec: InsertSpec) => req<LayoutOut>(`/inserts/${spec.id}/layout`, json('POST', spec)),
  build: (spec: InsertSpec) => req<{ job_id: string }>(`/inserts/${spec.id}/build`, json('POST', spec)),
  autoCompartments: (spec: InsertSpec) =>
    req<{ compartments: InsertSpec['compartments']; reason: string | null; grid: [number, number] }>(`/inserts/${spec.id}/auto-compartments`, json('POST', spec)),
  editCompartments: (spec: InsertSpec, op: 'merge' | 'split' | 'cut', indices: number[], parts = 2, cut?: { axis: 'h' | 'v'; at: number }) =>
    req<{ compartments: InsertSpec['compartments'] }>(`/inserts/${spec.id}/compartments/edit`, json('POST', { spec, op, indices, parts, ...cut })),
  compartmentRect: (spec: InsertSpec, x0: number, y0: number, x1: number, y1: number) =>
    req<{ compartments: InsertSpec['compartments'] }>(`/inserts/${spec.id}/compartments/rect`, json('POST', { spec, x0, y0, x1, y1 })),
  compartmentAt: (spec: InsertSpec, x: number, y: number) =>
    req<{ compartments: InsertSpec['compartments'] }>(`/inserts/${spec.id}/compartments/at`, json('POST', { spec, x, y })),

  projects: (all = false, archived = false) => req<ProjectSpec[]>(`/projects?all=${all}&archived=${archived}`),
  project: (id: string) => req<ProjectSpec>(`/projects/${id}`),
  createProject: (name: string, drawer_x: number, drawer_y: number) => req<ProjectSpec>('/projects', json('POST', { name, drawer_x, drawer_y })),
  saveProject: (p: ProjectSpec) => req<ProjectSpec>(`/projects/${p.id}`, json('PUT', p)),
  archiveProject: (id: string) => req(`/projects/${id}`, json('DELETE')),
  restoreProject: (id: string) => req<ProjectSpec>(`/projects/${id}/restore`, json('POST')),
  assign: (pid: string, kind: 'insert' | 'object', id: string, member = true) => req(`/projects/${pid}/assign`, json('POST', { kind, id, member })),
  generate: (pid: string, object_ids: string[] | null = null, arrange = true) =>
    req<{ created: string[]; skipped: string[]; already?: string[]; placed?: string[]; left_out?: string[]; left_out_names?: string[]; unfinished_names?: string[] }>(`/projects/${pid}/generate`, json('POST', { object_ids, arrange })),
  arrange: (pid: string, mode: 'all' | 'missing') =>
    req<{ placed: string[]; left_out: string[]; left_out_names: string[]; unfinished_names?: string[] }>(`/projects/${pid}/arrange`, json('POST', { mode })),
  clone: (pid: string) => req<CloneData>(`/projects/${pid}/clone`),
  place: (pid: string, insert_id: string, placement: DrawerPlacement | null) =>
    req<{ ok: boolean; placements: DrawerPlacement[] }>(`/projects/${pid}/place`, json('POST', { insert_id, placement })),
  texture: (oid: string) => req<TextureInfo>(`/objects/${oid}/texture`),
  scanPair: (pid: string, top: File, side: File, name: string) => {
    const fd = new FormData(); fd.append('top', top); fd.append('side', side); fd.append('name', name)
    return req<{ id: string; name: string }>(`/projects/${pid}/scan-pair`, { method: 'POST', body: fd })
  },
  batchScan: (pid: string, object_ids: string[]) => req<{ job_id: string }>(`/projects/${pid}/batch-scan`, json('POST', { object_ids })),

  job: (id: string) => req<Job>(`/jobs/${id}`),
  planBaseplate: (spec: BaseplateSpec) => req<PlatePlan>('/baseplates/plan', json('POST', spec)),
  buildBaseplate: (spec: BaseplateSpec) => req<{ job_id: string }>('/baseplates/build', json('POST', spec)),
}
