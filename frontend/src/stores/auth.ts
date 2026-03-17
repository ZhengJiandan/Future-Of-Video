import { create } from 'zustand'

const AUTH_STORAGE_KEY = 'pipeline_auth_session'

export interface AuthUser {
  id: string
  email: string
  name: string
  is_active: boolean
  created_at: string
  updated_at: string
}

interface AuthState {
  token: string | null
  user: AuthUser | null
  hydrated: boolean
  setAuth: (token: string, user: AuthUser) => void
  logout: () => void
  hydrate: () => void
}

const readStoredAuth = () => {
  if (typeof window === 'undefined') {
    return { token: null, user: null }
  }

  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY)
    if (!raw) {
      return { token: null, user: null }
    }
    const parsed = JSON.parse(raw) as { token?: string; user?: AuthUser }
    return {
      token: parsed.token || null,
      user: parsed.user || null,
    }
  } catch {
    return { token: null, user: null }
  }
}

const persistAuth = (token: string | null, user: AuthUser | null) => {
  if (typeof window === 'undefined') {
    return
  }

  if (!token || !user) {
    window.localStorage.removeItem(AUTH_STORAGE_KEY)
    return
  }

  window.localStorage.setItem(
    AUTH_STORAGE_KEY,
    JSON.stringify({
      token,
      user,
    }),
  )
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  user: null,
  hydrated: false,
  setAuth: (token, user) => {
    persistAuth(token, user)
    set({ token, user, hydrated: true })
  },
  logout: () => {
    persistAuth(null, null)
    set({ token: null, user: null, hydrated: true })
  },
  hydrate: () => {
    const stored = readStoredAuth()
    set({ token: stored.token, user: stored.user, hydrated: true })
  },
}))

export const getAccessToken = () => readStoredAuth().token
