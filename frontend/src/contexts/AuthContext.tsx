import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'
import { authApi } from '@/api'
import type { User, AuthTokens, LoginPayload, RegisterPayload } from '@/types'

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (payload: LoginPayload) => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | null>(null)

function getStoredTokens(): AuthTokens | null {
  try {
    const stored = localStorage.getItem('aaa_auth_tokens')
    return stored ? JSON.parse(stored) : null
  } catch {
    return null
  }
}

function getStoredUser(): User | null {
  try {
    const stored = localStorage.getItem('aaa_user')
    return stored ? JSON.parse(stored) : null
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(getStoredUser)
  const [isLoading, setIsLoading] = useState(true)

  const isAuthenticated = !!user && !!getStoredTokens()

  const login = useCallback(async (payload: LoginPayload) => {
    const { user: userData, tokens } = await authApi.login(payload)
    localStorage.setItem('aaa_auth_tokens', JSON.stringify(tokens))
    localStorage.setItem('aaa_user', JSON.stringify(userData))
    setUser(userData)
  }, [])

  const register = useCallback(async (payload: RegisterPayload) => {
    await authApi.register(payload)
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      // Ignore server errors on logout
    }
    localStorage.removeItem('aaa_auth_tokens')
    localStorage.removeItem('aaa_user')
    setUser(null)
  }, [])

  // Verify session on mount
  useEffect(() => {
    const verify = async () => {
      const tokens = getStoredTokens()
      if (!tokens) {
        setIsLoading(false)
        return
      }
      try {
        const userData = await authApi.me()
        localStorage.setItem('aaa_user', JSON.stringify(userData))
        setUser(userData)
      } catch {
        localStorage.removeItem('aaa_auth_tokens')
        localStorage.removeItem('aaa_user')
        setUser(null)
      } finally {
        setIsLoading(false)
      }
    }
    verify()
  }, [])

  return (
    <AuthContext.Provider value={{ user, isAuthenticated, isLoading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return ctx
}
