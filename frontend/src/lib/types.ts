// Spiegel von backend/app/schemas.py

/** Ebene [a, b, z]: von a bis b (mm entlang der Länge) liegt der Taschenboden auf Höhe z */
export type Level = [number, number, number]
export interface Profile { ds: number; s: number[]; bottom: number[]; top: number[]; levels?: Level[] | null; measured?: number[] | null }

export interface PhotoMeta {
  original: string
  preview_url: string
  preview_scale: number
  size: [number, number]
  f35: number | null
  corners_found: boolean
  corners_px: [number, number][]
  pose?: { C_mm: [number, number, number]; f_px: number; f35_assumed: boolean; warnings: string[] }
  rectified_url?: string
  view_scale?: number
  rect_size?: [number, number]
  mask_url?: string
  overlay_url?: string
  hand_url?: string
  edit_contour_px?: [number, number][]
  cut_point_mm?: [number, number]
  fill_holes?: boolean
}

export interface ObjectSpec {
  id: string
  name: string
  owner_id?: number | null
  created_at: string
  contour_mm: [number, number][]
  length_mm: number
  width_mm: number
  profile: Profile | null
  side_flip_lr: boolean | null
  side_flip_ud: boolean
  flip_lr_used: boolean | null
  tilt_deg: number
  profile_missing: boolean[]
  calipers: Record<string, number>
  warnings: string[]
  photos: Record<string, PhotoMeta>
}

export interface Placement { object_id: string; x: number; y: number; rot_deg: number; side_down: 'A' | 'B' }
export interface GripRecess { shape: 'stadium' | 'rect' | 'circle'; x: number; y: number; w: number; l: number; rot_deg: number; depth_below: number; rounded?: boolean; attach?: number | null; s?: number | null; auto_length?: boolean; edge_r?: number }
export interface Compartment { x: number; y: number; w: number; l: number; radius: number; depth: number | null; polygon?: [number, number][] | null; generated?: boolean }

export interface InsertSpec {
  id: string
  name: string
  owner_id?: number | null
  grid_x: number | null
  grid_y: number | null
  height_u: number | null
  height_mm: number | null
  sink: number
  stacking_lip: boolean
  magnets: boolean
  clearance_xy: number
  clearance_end: number
  clearance_z: number
  overhang: number
  step_tol: number
  min_zone_len: number
  max_zones: number
  floor_min: number
  min_wall: number
  smooth_mm: number
  auto_center: boolean
  auto_grip: boolean
  grip_width: number
  grip_overhang: number
  grip_depth_below: number
  auto_compartments: boolean
  comp_min_size: number
  comp_wall: number
  comp_depth: number | null
  comp_follow: boolean
  placements: Placement[]
  grip_recesses: GripRecess[]
  compartments: Compartment[]
  colors: { body: number; pocket: number; grip: number; compartment: number }
  color_skin: { floor: number; wall: number; show_top_ring: boolean }
}

export interface PolyOut { exterior: [number, number][]; holes: [number, number][][] }
export interface LayoutOut {
  grid_x: number; grid_y: number; height_u: number; z_surface: number; total_height: number; sink: number[]; outer: [number, number]
  pieces: { placement: number; zone: number; z0: number; depth: number; polygons: PolyOut[] }[]
  grips: { z0: number; depth: number; polygons: PolyOut[]; auto: boolean; placement: number | null; rounded: boolean; params: GripRecess | null }[]
  compartments: { z0: number; depth: number; polygons: PolyOut[]; auto: boolean; max_depth: boolean }[]
  shift: [number, number]
  zones: { a: number; b: number; floor: number }[][]
  warnings: string[]
}

export interface Job {
  id: string; kind: string; status: 'running' | 'done' | 'error'; progress: number
  outputs: Record<string, string>; checks: Record<string, any>; warnings: string[]; error: string | null
}

export interface BaseplateSpec {
  drawer_x: number; drawer_y: number; bed_x: number; bed_y: number
  clearance: number; magnets: boolean; one_sided: boolean
}

export interface Me { user: string; id: number; name: string; role: 'admin' | 'user'; auth: boolean }
export interface AuthConfig { auth: boolean; google: boolean; local: boolean; source?: string }
export interface AdminUser {
  id: number; email: string; name: string; role: 'admin' | 'user'; status: 'pending' | 'active' | 'disabled'
  google: boolean; created_at: string; last_login_at: string | null; approved_at: string | null
  objects: number; inserts: number
}
export interface AuditEntry { ts: string; actor: string; action: string; target: string; ip: string }
