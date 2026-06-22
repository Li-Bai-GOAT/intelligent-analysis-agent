import { create } from 'zustand'
import { Api } from '../api/client'
import type { User } from '../types'

interface AuthState {
  token: string | null
  user: User | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string) => Promise<void>
  logout: () => void
}

const savedToken = localStorage.getItem('token')
const savedUser = JSON.parse(localStorage.getItem('user') || 'null')

export const useAuthStore = create<AuthState>((set) => ({
  token: savedToken,
  user: savedUser,
  isAuthenticated: !!(savedToken && savedUser),

  login: async (username, password) => {
    const data = await Api.login(username, password)
    set({ token: data.access_token, user: data.user, isAuthenticated: true })
  },

  register: async (username, password) => {
    await Api.register(username, password)
    const data = await Api.login(username, password)
    set({ token: data.access_token, user: data.user, isAuthenticated: true })
  },

  logout: () => {
    Api.clearAuth()
    set({ token: null, user: null, isAuthenticated: false })
  },
}))
