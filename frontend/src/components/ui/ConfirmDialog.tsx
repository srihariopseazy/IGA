import React from 'react'
import { AlertTriangle, X } from 'lucide-react'

interface ConfirmDialogProps {
  open: boolean
  title: string
  message: string | React.ReactNode
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'warning' | 'default'
  confirmVariant?: string
  onConfirm: () => void
  onCancel: () => void
  loading?: boolean
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'default',
  onConfirm,
  onCancel,
  loading = false,
}: ConfirmDialogProps) {
  if (!open) return null

  const confirmButtonClass =
    variant === 'danger'
      ? 'bg-red-600 hover:bg-red-700 text-white'
      : variant === 'warning'
      ? 'bg-orange-600 hover:bg-orange-700 text-white'
      : 'bg-blue-600 hover:bg-blue-700 text-white'

  const iconClass =
    variant === 'danger'
      ? 'text-red-600 bg-red-100 dark:bg-red-900/30'
      : variant === 'warning'
      ? 'text-orange-600 bg-orange-100 dark:bg-orange-900/30'
      : 'text-blue-600 bg-blue-100 dark:bg-blue-900/30'

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div
        className="modal-content max-w-md p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-4">
          <div className={`w-10 h-10 rounded-full ${iconClass} flex items-center justify-center flex-shrink-0`}>
            <AlertTriangle size={20} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h3>
              <button
                onClick={onCancel}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 ml-2 flex-shrink-0"
              >
                <X size={18} />
              </button>
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-400 mb-6">{message}</p>
            <div className="flex items-center justify-end gap-3">
              <button
                onClick={onCancel}
                disabled={loading}
                className="btn-secondary text-sm px-4 py-2"
              >
                {cancelLabel}
              </button>
              <button
                onClick={onConfirm}
                disabled={loading}
                className={`${confirmButtonClass} font-medium px-4 py-2 rounded-lg text-sm transition-colors disabled:opacity-50 flex items-center gap-2`}
              >
                {loading && (
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                )}
                {confirmLabel}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
