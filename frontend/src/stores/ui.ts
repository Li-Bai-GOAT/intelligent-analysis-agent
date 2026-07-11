import { create } from 'zustand'

type Page = 'auth' | 'app' | 'admin'
type RightTab = 'plan' | 'files' | 'terminal'
type AdminTab = 'knowledge' | 'prompt' | 'sandbox'

interface UiState {
  page: Page
  rightTab: RightTab
  adminTab: AdminTab
  sidebarCollapsed: boolean
  setPage: (page: Page) => void
  setRightTab: (tab: RightTab) => void
  setAdminTab: (tab: AdminTab) => void
  toggleSidebar: () => void
}

export const useUiStore = create<UiState>((set) => ({
  page: 'auth',
  rightTab: 'files',
  adminTab: 'knowledge',
  sidebarCollapsed: false,
  setPage: (page) => set({ page }),
  setRightTab: (tab) => set({ rightTab: tab }),
  setAdminTab: (tab) => set({ adminTab: tab }),
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
}))
