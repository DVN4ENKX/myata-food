import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, getToken, setToken } from '@/lib/api'
import type { User } from '@/lib/types'

interface AuthState {
  user: User | null
  ready: boolean
  login: (username: string, secret: string, usePin: boolean) => Promise<User>
  logout: () => void
  can: (flag: Permission) => boolean
}

export type Permission =
  | 'can_manage_menu'
  | 'can_manage_hall'
  | 'can_manage_orders'
  | 'can_manage_users'
  | 'can_view_reports'

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    if (!getToken()) {
      setReady(true)
      return
    }
    api
      .get<User>('/auth/me')
      .then((me) => {
        if (!cancelled) setUser(me)
      })
      .catch(() => setToken(null))
      .finally(() => {
        if (!cancelled) setReady(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const onSignedOut = () => setUser(null)
    window.addEventListener('myata:signed-out', onSignedOut)
    return () => window.removeEventListener('myata:signed-out', onSignedOut)
  }, [])

  const login = useCallback(async (username: string, secret: string, usePin: boolean) => {
    const body = usePin ? { username, pin: secret } : { username, password: secret }
    const token = await api.post<{ access_token: string; user: User }>('/auth/login', body)
    setToken(token.access_token)
    setUser(token.user)
    return token.user
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  const can = useCallback(
    (flag: Permission) => {
      if (!user) return false
      if (user.role === 'owner' || user.role === 'admin') return true
      return Boolean(user[flag])
    },
    [user],
  )

  const value = useMemo<AuthState>(
    () => ({ user, ready, login, logout, can }),
    [user, ready, login, logout, can],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
