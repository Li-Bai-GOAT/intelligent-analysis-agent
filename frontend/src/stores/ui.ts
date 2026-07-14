import { create } from 'zustand'
import type { AdminSection } from '../admin/types'

type Page = 'auth' | 'app' | 'admin'
type RightTab = 'plan' | 'files' | 'terminal'

interface UiState {
  page: Page
  rightTab: RightTab
  adminTab: AdminSection
  sidebarCollapsed: boolean
  setPage: (page: Page) => void
  setRightTab: (tab: RightTab) => void
  setAdminTab: (tab: AdminSection) => void
  toggleSidebar: () => void
}

export const useUiStore = create<UiState>((set) => ({
  page: 'auth',
  rightTab: 'files',
  adminTab: 'overview',
  sidebarCollapsed: false,
  setPage: (page) => set({ page }),
  setRightTab: (tab) => set({ rightTab: tab }),
  setAdminTab: (tab) => set({ adminTab: tab }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
}))
