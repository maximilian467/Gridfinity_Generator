import { useEffect, useState } from 'react'

export type ThemePref = 'light' | 'dark'

export function getTheme(): ThemePref {
  try { const t = localStorage.getItem('theme'); if (t === 'dark' || t === 'light') return t } catch { /* privat */ }
  return 'light'
}
export function setTheme(t: ThemePref) {
  document.documentElement.dataset.theme = t
  try { localStorage.setItem('theme', t) } catch { /* privat */ }
}
export function initTheme() { document.documentElement.dataset.theme = getTheme() }

const names = ['ink', 'ink-2', 'line', 'line-2', 'grid', 'accent', 'surface', 'surface-2', 'blue', 'green', 'paper'] as const
export type Tokens = Record<(typeof names)[number], string>

function read(): Tokens {
  const cs = getComputedStyle(document.documentElement)
  return Object.fromEntries(names.map((n) => [n, cs.getPropertyValue('--' + n).trim()])) as Tokens
}

/** Konva kann keine CSS-Variablen: konkrete Werte, aktualisiert beim Themenwechsel. */
export function useTokens(): Tokens {
  const [t, setT] = useState<Tokens>(read)
  useEffect(() => {
    const mo = new MutationObserver(() => setT(read()))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => mo.disconnect()
  }, [])
  return t
}

export function alpha(hex: string, a: number): string {
  const h = hex.replace('#', '')
  const n = h.length === 3 ? h.split('').map((c) => c + c).join('') : h
  const r = parseInt(n.slice(0, 2), 16), g = parseInt(n.slice(2, 4), 16), b = parseInt(n.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${a})`
}
