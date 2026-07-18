import { useState, useCallback } from 'react'

export function useAuthForm() {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const clearError = useCallback(() => setError(null), [])

  const execute = useCallback(async <T>(fn: () => Promise<T>): Promise<T | null> => {
    setIsLoading(true)
    setError(null)
    try {
      const result = await fn()
      return result
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'An unexpected error occurred'
      // Handle Axios errors
      if (err && typeof err === 'object' && 'response' in err) {
        const axiosErr = err as { response?: { data?: { detail?: string } } }
        setError(axiosErr.response?.data?.detail || message)
      } else {
        setError(message)
      }
      return null
    } finally {
      setIsLoading(false)
    }
  }, [])

  return { isLoading, error, clearError, execute }
}
