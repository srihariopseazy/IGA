import React from 'react'

export type BadgeVariant =
  | 'active' | 'inactive' | 'locked' | 'suspended' | 'pending'
  | 'approved' | 'rejected' | 'cancelled' | 'expired'
  | 'critical' | 'high' | 'medium' | 'low'
  | 'draft' | 'completed' | 'paused'
  | 'healthy' | 'unhealthy' | 'unknown'
  | 'open' | 'mitigated' | 'accepted' | 'resolved'
  | 'default'
  | 'success' | 'danger' | 'warning' | 'info'

const colors: Record<BadgeVariant, string> = {
  active: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
  inactive: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300',
  locked: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  suspended: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300',
  pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
  approved: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
  rejected: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  cancelled: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300',
  expired: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300',
  critical: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  high: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300',
  medium: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
  low: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
  draft: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300',
  completed: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
  paused: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300',
  healthy: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
  unhealthy: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  unknown: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-300',
  open: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  mitigated: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
  accepted: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
  resolved: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
  default: 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300',
  success: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300',
  danger: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  warning: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
  info: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
}

interface BadgeProps {
  variant?: BadgeVariant
  children: React.ReactNode
  className?: string
  size?: 'sm' | 'md'
}

export function Badge({ variant = 'default', children, className = '', size = 'sm' }: BadgeProps) {
  const sizeClasses = size === 'sm'
    ? 'px-2 py-0.5 text-xs'
    : 'px-2.5 py-1 text-sm'

  return (
    <span
      className={`inline-flex items-center ${sizeClasses} rounded-full font-medium ${colors[variant] || colors.default} ${className}`}
    >
      {children}
    </span>
  )
}

export function StatusDot({ status }: { status: string }) {
  const dotColors: Record<string, string> = {
    active: 'bg-green-500',
    healthy: 'bg-green-500',
    inactive: 'bg-slate-400',
    error: 'bg-red-500',
    unhealthy: 'bg-red-500',
    pending: 'bg-yellow-500',
    unknown: 'bg-slate-400',
  }
  const color = dotColors[status] || 'bg-slate-400'
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />
}
