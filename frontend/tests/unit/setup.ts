import { vi } from 'vitest'

// The store under test calls window.setInterval / window.setTimeout for its
// pending-preview polling and plan timeout. No DOM is needed, so stub just the
// timer surface: polling becomes a no-op and tests stay deterministic.
vi.stubGlobal('window', {
  setInterval: () => 0,
  clearInterval: () => {},
  setTimeout: (fn: () => void, ms?: number) => globalThis.setTimeout(fn, ms),
  clearTimeout: (id: number) => globalThis.clearTimeout(id),
})

// src/api/client.ts reads localStorage at module load, which runs before any
// test can install a mock. An in-memory implementation keeps the import side
// effect working without pulling in jsdom.
const storage = new Map<string, string>()

vi.stubGlobal('localStorage', {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => {
    storage.set(key, String(value))
  },
  removeItem: (key: string) => {
    storage.delete(key)
  },
  clear: () => {
    storage.clear()
  },
  key: (index: number) => [...storage.keys()][index] ?? null,
  get length() {
    return storage.size
  },
})
