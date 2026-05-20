import React, { useState, useCallback, useEffect } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  flexRender,
  ColumnDef,
  SortingState,
  RowSelectionState,
} from '@tanstack/react-table'
import { ChevronUp, ChevronDown, ChevronsUpDown, ChevronLeft, ChevronRight, Download, Search, Loader2 } from 'lucide-react'
import { debounce, exportToCSV } from '@/utils/helpers'

interface DataTableProps<T> {
  data: T[]
  columns: ColumnDef<T, unknown>[]
  loading?: boolean
  totalRows?: number
  page?: number
  perPage?: number
  onPageChange?: (page: number) => void
  onPerPageChange?: (perPage: number) => void
  onSearch?: (query: string) => void
  searchPlaceholder?: string
  onRowSelectionChange?: (rows: T[]) => void
  exportFilename?: string
  emptyMessage?: string
  actions?: React.ReactNode
}

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

export function DataTable<T extends { id?: string }>({
  data,
  columns,
  loading = false,
  totalRows,
  page = 1,
  perPage = 20,
  onPageChange,
  onPerPageChange,
  onSearch,
  searchPlaceholder = 'Search...',
  onRowSelectionChange,
  exportFilename = 'export',
  emptyMessage = 'No data found',
  actions,
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [searchInput, setSearchInput] = useState('')

  const totalPages = totalRows ? Math.ceil(totalRows / perPage) : 1

  const debouncedSearch = useCallback(
    debounce((...args: unknown[]) => {
      const query = args[0] as string
      onSearch?.(query)
    }, 350),
    [onSearch]
  )

  useEffect(() => {
    debouncedSearch(searchInput)
  }, [searchInput, debouncedSearch])

  useEffect(() => {
    if (onRowSelectionChange) {
      const selectedRows = Object.keys(rowSelection)
        .filter((key) => rowSelection[key])
        .map((key) => data[parseInt(key)])
        .filter(Boolean)
      onRowSelectionChange(selectedRows)
    }
  }, [rowSelection, data, onRowSelectionChange])

  const selectionColumn: ColumnDef<T, unknown> = {
    id: 'select',
    header: ({ table }) => (
      <input
        type="checkbox"
        checked={table.getIsAllPageRowsSelected()}
        onChange={table.getToggleAllPageRowsSelectedHandler()}
        className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
      />
    ),
    cell: ({ row }) => (
      <input
        type="checkbox"
        checked={row.getIsSelected()}
        onChange={row.getToggleSelectedHandler()}
        onClick={(e) => e.stopPropagation()}
        className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
      />
    ),
    size: 40,
    enableSorting: false,
  }

  const allColumns = onRowSelectionChange ? [selectionColumn, ...columns] : columns

  const table = useReactTable({
    data,
    columns: allColumns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    manualPagination: !!onPageChange,
    pageCount: totalPages,
  })

  const handleExport = () => {
    const exportData = data.map((row) => {
      const obj: Record<string, unknown> = {}
      columns.forEach((col) => {
        if (col.id && col.id !== 'actions' && col.id !== 'select') {
          const key = (col as { accessorKey?: string }).accessorKey || col.id || ''
          if (key) obj[key] = (row as Record<string, unknown>)[key]
        }
      })
      return obj as Record<string, unknown>
    })
    exportToCSV(exportData, `${exportFilename}.csv`)
  }

  const SkeletonRow = () => (
    <tr>
      {allColumns.map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
        </td>
      ))}
    </tr>
  )

  return (
    <div className="card overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-3 p-4 border-b border-slate-200 dark:border-slate-700 flex-wrap">
        {onSearch && (
          <div className="relative flex-1 min-w-48">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder={searchPlaceholder}
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="input pl-9 py-1.5 text-sm"
            />
          </div>
        )}
        <div className="flex items-center gap-2 ml-auto">
          {actions}
          <button
            onClick={handleExport}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm btn-secondary"
          >
            <Download size={14} />
            Export CSV
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="table-header"
                    style={{ width: header.getSize() !== 150 ? header.getSize() : undefined }}
                  >
                    {header.isPlaceholder ? null : (
                      <div
                        className={`flex items-center gap-1 ${
                          header.column.getCanSort() ? 'cursor-pointer hover:text-slate-700 dark:hover:text-slate-200' : ''
                        }`}
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {header.column.getCanSort() && (
                          <span className="text-slate-400">
                            {header.column.getIsSorted() === 'asc' ? (
                              <ChevronUp size={13} />
                            ) : header.column.getIsSorted() === 'desc' ? (
                              <ChevronDown size={13} />
                            ) : (
                              <ChevronsUpDown size={13} />
                            )}
                          </span>
                        )}
                      </div>
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)
            ) : table.getRowModel().rows.length === 0 ? (
              <tr>
                <td
                  colSpan={allColumns.length}
                  className="px-4 py-12 text-center text-slate-500 dark:text-slate-400"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className={`hover:bg-slate-50 dark:hover:bg-slate-700/30 transition-colors ${
                    row.getIsSelected() ? 'bg-blue-50 dark:bg-blue-900/10' : ''
                  }`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="table-cell">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between px-4 py-3 border-t border-slate-200 dark:border-slate-700 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-500 dark:text-slate-400">
            {totalRows
              ? `${Math.min((page - 1) * perPage + 1, totalRows)}-${Math.min(page * perPage, totalRows)} of ${totalRows}`
              : `${data.length} rows`}
          </span>
          {onPerPageChange && (
            <select
              value={perPage}
              onChange={(e) => onPerPageChange(Number(e.target.value))}
              className="text-sm border border-slate-300 dark:border-slate-600 rounded-lg px-2 py-1 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300"
            >
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>{size} / page</option>
              ))}
            </select>
          )}
        </div>

        {onPageChange && totalPages > 1 && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => onPageChange(page - 1)}
              disabled={page <= 1}
              className="p-1.5 rounded text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              <ChevronLeft size={16} />
            </button>
            {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
              let pageNum: number
              if (totalPages <= 7) {
                pageNum = i + 1
              } else if (page <= 4) {
                pageNum = i + 1
                if (i === 5) return <span key="e1" className="px-1 text-slate-400">...</span>
                if (i === 6) pageNum = totalPages
              } else if (page >= totalPages - 3) {
                if (i === 0) pageNum = 1
                else if (i === 1) return <span key="e2" className="px-1 text-slate-400">...</span>
                else pageNum = totalPages - (6 - i)
              } else {
                if (i === 0) pageNum = 1
                else if (i === 1) return <span key="e3" className="px-1 text-slate-400">...</span>
                else if (i === 5) return <span key="e4" className="px-1 text-slate-400">...</span>
                else if (i === 6) pageNum = totalPages
                else pageNum = page - 2 + i
              }
              return (
                <button
                  key={pageNum}
                  onClick={() => onPageChange(pageNum)}
                  className={`w-8 h-8 flex items-center justify-center text-sm rounded ${
                    pageNum === page
                      ? 'bg-blue-600 text-white font-medium'
                      : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700'
                  }`}
                >
                  {pageNum}
                </button>
              )
            })}
            <button
              onClick={() => onPageChange(page + 1)}
              disabled={page >= totalPages}
              className="p-1.5 rounded text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-100 dark:hover:bg-slate-700"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        )}
      </div>

      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/50 dark:bg-slate-800/50 rounded-xl">
          <Loader2 size={24} className="animate-spin text-blue-600" />
        </div>
      )}
    </div>
  )
}
