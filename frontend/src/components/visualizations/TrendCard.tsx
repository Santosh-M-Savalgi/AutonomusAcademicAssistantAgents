import { motion } from 'framer-motion'
import { cn } from '@/utils/cn'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import type { TrendDirection } from './types'

interface TrendCardProps {
  label: string
  value: string | number
  trend?: TrendDirection
  trendValue?: string
  icon?: React.ReactNode
  variant?: 'primary' | 'secondary' | 'default'
  className?: string
}

const variantStyles = {
  primary: 'border-primary/20',
  secondary: 'border-secondary/20',
  default: 'border-surface-border',
}

const trendIcons: Record<TrendDirection, React.ReactNode> = {
  up: <TrendingUp className="h-3.5 w-3.5" />,
  down: <TrendingDown className="h-3.5 w-3.5" />,
  stable: <Minus className="h-3.5 w-3.5" />,
  neutral: <Minus className="h-3.5 w-3.5 text-text-muted" />,
}

const trendColors: Record<TrendDirection, string> = {
  up: 'text-success',
  down: 'text-danger',
  stable: 'text-text-secondary',
  neutral: 'text-text-muted',
}

export function TrendCard({
  label,
  value,
  trend,
  trendValue,
  icon,
  variant = 'default',
  className,
}: TrendCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={cn(
        'bg-surface border rounded-lg p-5 space-y-2',
        variantStyles[variant],
        className
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm text-text-secondary">{label}</span>
        <div className="flex items-center gap-2">
          {icon && (
            <span className={cn(variant === 'primary' ? 'text-primary' : variant === 'secondary' ? 'text-secondary' : 'text-text-muted')}>
              {icon}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-end gap-2">
        <span className="font-display text-2xl font-semibold text-text-primary tabular-nums">
          {value}
        </span>
        {trend && trendValue && (
          <span className={cn('flex items-center gap-0.5 text-xs font-medium mb-1', trendColors[trend])}>
            {trendIcons[trend]}
            {trendValue}
          </span>
        )}
      </div>
    </motion.div>
  )
}
