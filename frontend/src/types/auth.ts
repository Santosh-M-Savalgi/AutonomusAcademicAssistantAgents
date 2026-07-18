export type User = {
  id: string
  email: string
  username: string
  role: string
  isActive: boolean
}

export type AuthTokens = {
  accessToken: string
  refreshToken: string
  tokenType: string
  expiresIn: number
}

export type AuthState = {
  user: User | null
  tokens: AuthTokens | null
  isAuthenticated: boolean
  isLoading: boolean
}

export type LoginPayload = {
  email_or_username: string
  password: string
}

export type RegisterPayload = {
  email: string
  username: string
  password: string
}

export type ApiError = {
  status: number
  message: string
  code?: string
  details?: unknown
}
