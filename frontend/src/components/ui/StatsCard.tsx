import React from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { formatNumber } from '@/utils/helpers'

interface StatsCardProps {
  label: string
  value: number | string
  icon?: React.ComponentType<{ size?: number; className?: string }>
  iconColor?: string
  iconBg?: string
  trend?: number // percentage change, positive = up, negative = down
  trendLabel?: string
  suffix?: string
  prefix?: string
  loading?: boolean
  onClick?: () => void
  className?: string
}

export function StatsCard({
  label,
  value,
  icon: Icon,
  iconColor = 'text-blue-600',
  iconBg = 'bg-blue-100 dark:bg-blue-900/30',
  trend,
  trendLabel,
  suffix,
  prefix,
  loading = false,
  onClick,
  className = '',
}: StatsCardProps) {
  const displayValue = typeof value === 'number' ? formatNumber(value) : value

  const TrendIcon = trend === undefined || trend === 0
    ? Minus
    : trend > 0 ? TrendingUp : TrendingDown

  const trendColor = trend === undefined || trend === 0
    ? 'text-slate-500'
    : trend > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'

  if (loading) {
    return (
      <div className={`card p-6 ${className}`}>
        <div className="animate-pulse">
          <div className="flex items-start justify-between mb-4">
            <div className="w-10 h-10 rounded-xl bg-slate-200 dark:bg-slate-700" />
          </div>
          <div className="h-8 w-24 bg-slate-200 dark:bg-slate-700 rounded mb-2" />
          <div className="h-4 w-32 bg-slate-200 dark:bg-slate-700 rounded" />
        </div>
      </div>
    )
  }

  return (
    <div
      className={`card p-6 ${onClick ? 'cursor-pointer hover:shadow-md transition-shadow' : ''} ${className}`}
      onClick={onClick}
    >
      <div className="flex items-start justify-between mb-4">
        {Icon && (
          <div className={`w-10 h-10 rounded-xl ${iconBg} flex items-center justify-center flex-shrink-0`}>
            <Icon size={20} className={iconColor} />
          </div>
        )}
      </div>
      <div className="flex items-baseline gap-1 mb-1">
        {prefix && <span className="text-lg text-slate-500 dark:text-slate-400">{prefix}</span>}
        <span className="text-2xl font-bold text-slate-900 dark:text-white">{displayValue}</span>
        {suffix && <span className="text-sm text-slate-500 dark:text-slate-400">{suffix}</span>}
      </div>
      <p className="text-sm text-slate-600 dark:text-slate-400 mb-2">{label}</p>
      {trend !== undefined && (
        <div className={`flex items-center gap-1 text-xs font-medium ${trendColor}`}>
          <TrendIcon size={12} />
          <span>{Math.abs(trend)}% {trendLabel || (trend >= 0 ? 'increase' : 'decrease')}</span>
        </div>
      )}
    </div>
  )
}
