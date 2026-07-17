import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { API_ENDPOINTS, APP } from '@/constants'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
})

// Request interceptor — attach auth token
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const stored = localStorage.getItem('aaa_auth_tokens')
    if (stored) {
      try {
        const tokens = JSON.parse(stored)
        if (tokens.accessToken) {
          config.headers.Authorization = `Bearer ${tokens.accessToken}`
        }
      } catch {
        // Ignore parse errors
      }
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor — handle token refresh
let isRefreshing = false
let failedQueue: Array<{
  resolve: (token: string) => void
  reject: (error: unknown) => void
}> = []

function processQueue(error: unknown, token: string | null = null) {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve(token!)
    }
  })
  failedQueue = []
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`
          return apiClient(originalRequest)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const stored = localStorage.getItem('aaa_auth_tokens')
        if (!stored) throw new Error('No tokens')

        const tokens = JSON.parse(stored)
        const response = await axios.post(API_ENDPOINTS.AUTH.REFRESH, {
          refresh_token: tokens.refreshToken,
        })

        const newTokens = {
          accessToken: response.data.access_token,
          refreshToken: response.data.refresh_token,
          tokenType: response.data.token_type,
          expiresIn: response.data.expires_in,
        }
        localStorage.setItem('aaa_auth_tokens', JSON.stringify(newTokens))

        processQueue(null, newTokens.accessToken)
        originalRequest.headers.Authorization = `Bearer ${newTokens.accessToken}`
        return apiClient(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        localStorage.removeItem('aaa_auth_tokens')
        localStorage.removeItem('aaa_user')
        window.location.href = '/login'
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)

export { apiClient }
