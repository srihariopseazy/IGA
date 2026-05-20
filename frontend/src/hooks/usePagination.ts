import { useState, useCallback } from 'react'

interface PaginationState {
  page: number
  perPage: number
  total: number
}

interface PaginationActions {
  setPage: (page: number) => void
  setPerPage: (perPage: number) => void
  setTotal: (total: number) => void
  nextPage: () => void
  prevPage: () => void
  goToFirstPage: () => void
  goToLastPage: () => void
  resetPagination: () => void
}

interface PaginationResult extends PaginationState, PaginationActions {
  totalPages: number
  hasNextPage: boolean
  hasPrevPage: boolean
  startIndex: number
  endIndex: number
  pageNumbers: number[]
}

export function usePagination(initialPage = 1, initialPerPage = 20): PaginationResult {
  const [page, setPageState] = useState(initialPage)
  const [perPage, setPerPageState] = useState(initialPerPage)
  const [total, setTotalState] = useState(0)

  const totalPages = Math.max(1, Math.ceil(total / perPage))
  const hasNextPage = page < totalPages
  const hasPrevPage = page > 1
  const startIndex = (page - 1) * perPage + 1
  const endIndex = Math.min(page * perPage, total)

  const setPage = useCallback(
    (newPage: number) => {
      const clampedPage = Math.max(1, Math.min(newPage, totalPages))
      setPageState(clampedPage)
    },
    [totalPages]
  )

  const setPerPage = useCallback((newPerPage: number) => {
    setPerPageState(newPerPage)
    setPageState(1)
  }, [])

  const setTotal = useCallback((newTotal: number) => {
    setTotalState(newTotal)
  }, [])

  const nextPage = useCallback(() => {
    if (hasNextPage) setPageState((p) => p + 1)
  }, [hasNextPage])

  const prevPage = useCallback(() => {
    if (hasPrevPage) setPageState((p) => p - 1)
  }, [hasPrevPage])

  const goToFirstPage = useCallback(() => setPageState(1), [])
  const goToLastPage = useCallback(() => setPageState(totalPages), [totalPages])

  const resetPagination = useCallback(() => {
    setPageState(initialPage)
    setPerPageState(initialPerPage)
    setTotalState(0)
  }, [initialPage, initialPerPage])

  // Generate visible page numbers (show at most 7 pages)
  const pageNumbers: number[] = []
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pageNumbers.push(i)
  } else {
    if (page <= 4) {
      pageNumbers.push(1, 2, 3, 4, 5, -1, totalPages)
    } else if (page >= totalPages - 3) {
      pageNumbers.push(1, -1, totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages)
    } else {
      pageNumbers.push(1, -1, page - 1, page, page + 1, -1, totalPages)
    }
  }

  return {
    page,
    perPage,
    total,
    totalPages,
    hasNextPage,
    hasPrevPage,
    startIndex,
    endIndex,
    pageNumbers,
    setPage,
    setPerPage,
    setTotal,
    nextPage,
    prevPage,
    goToFirstPage,
    goToLastPage,
    resetPagination,
  }
}
