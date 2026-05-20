import { QueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      gcTime: 10 * 60 * 1000, // 10 minutes
      retry: (failureCount, error: unknown) => {
        const err = error as { response?: { status?: number } }
        // Don't retry on 4xx errors except 429
        if (err?.response?.status && err.response.status >= 400 && err.response.status < 500 && err.response.status !== 429) {
          return false
        }
        return failureCount < 2
      },
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
      onError: (error: unknown) => {
        const err = error as { response?: { data?: { detail?: string; message?: string } }; message?: string }
        const message =
          err?.response?.data?.detail ||
          err?.response?.data?.message ||
          err?.message ||
          'An unexpected error occurred'
        toast.error(message)
      },
    },
  },
})
