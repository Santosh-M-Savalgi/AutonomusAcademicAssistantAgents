import type { UseQueryOptions } from '@tanstack/react-query'
import type { AxiosError } from 'axios'
import type { ApiError } from '@/types'

export type QueryOpts<T> = Omit<UseQueryOptions<T, AxiosError<ApiError>>, 'queryKey' | 'queryFn'>
