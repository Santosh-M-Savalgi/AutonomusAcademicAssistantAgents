import { apiClient } from './client'
import { API_ENDPOINTS } from '@/constants'
import type { LoginPayload, RegisterPayload, User, AuthTokens } from '@/types'

type TokenResponse = {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: {
    id: string
    email: string
    username: string
    role: string
    is_active: boolean
  }
}

function mapUser(u: TokenResponse['user']): User {
  return {
    id: u.id,
    email: u.email,
    username: u.username,
    role: u.role,
    isActive: u.is_active,
  }
}

function mapTokens(t: TokenResponse): AuthTokens {
  return {
    accessToken: t.access_token,
    refreshToken: t.refresh_token,
    tokenType: t.token_type,
    expiresIn: t.expires_in,
  }
}

export const authApi = {
  async login(payload: LoginPayload) {
    const { data } = await apiClient.post<TokenResponse>(
      API_ENDPOINTS.AUTH.LOGIN,
      payload
    )
    return {
      user: mapUser(data.user),
      tokens: mapTokens(data),
    }
  },

  async register(payload: RegisterPayload) {
    const { data } = await apiClient.post<{ message: string }>(
      API_ENDPOINTS.AUTH.REGISTER,
      payload
    )
    return data
  },

  async refresh(refreshToken: string) {
    const { data } = await apiClient.post<TokenResponse>(
      API_ENDPOINTS.AUTH.REFRESH,
      { refresh_token: refreshToken }
    )
    return {
      user: mapUser(data.user),
      tokens: mapTokens(data),
    }
  },

  async logout() {
    await apiClient.post(API_ENDPOINTS.AUTH.LOGOUT)
  },

  async me() {
    const { data } = await apiClient.get<{
      id: string
      email: string
      username: string
      role: string
      is_active: boolean
    }>(API_ENDPOINTS.AUTH.ME)
    return mapUser(data)
  },
}
