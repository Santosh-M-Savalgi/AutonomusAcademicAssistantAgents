import { QueryClient } from '@tanstack/react-query'

const STALE_TIME = 5 * 60 * 1000 // 5 minutes
const GC_TIME = 30 * 60 * 1000 // 30 minutes

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
      refetchOnWindowFocus: false,
      staleTime: STALE_TIME,
      gcTime: GC_TIME,
    },
    mutations: {
      retry: 1,
    },
  },
})

/**
 * Helper to eagerly invalidate and refetch a query key after mutations.
 * Use in onSuccess callbacks instead of manual invalidateQueries calls
 * to ensure consistent cache behavior.
 */
export function invalidateAndRefetch(queryKeys: string[][]) {
  return Promise.all(
    queryKeys.map((key) =>
      queryClient.invalidateQueries({ queryKey: key, refetchType: 'active' })
    )
  )
}
