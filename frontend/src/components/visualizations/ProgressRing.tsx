import { motion } from 'framer-motion'
import { cn } from '@/utils/cn'

interface ProgressRingProps {
  value: number
  size?: number
  strokeWidth?: number
  color?: 'primary' | 'secondary' | 'success' | 'warning'
  label?: string
  showLabel?: boolean
  animated?: boolean
  className?: string
}

const ringColors = {
  primary: 'stroke-primary',
  secondary: 'stroke-secondary',
  success: 'stroke-success',
  warning: 'stroke-warning',
}

const trackColor = 'stroke-surface-border'

export function ProgressRing({
  value,
  size = 80,
  strokeWidth = 6,
  color = 'primary',
  label,
  showLabel = true,
  animated = true,
  className,
}: ProgressRingProps) {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = Math.min(Math.max(value, 0), 100)
  const offset = circumference - (clamped / 100) * circumference

  return (
    <div
      className={cn('relative inline-flex items-center justify-center', className)}
      style={{ width: size, height: size }}
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? `${Math.round(clamped)}% progress`}
    >
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className={trackColor}
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={animated ? { strokeDashoffset: circumference } : undefined}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1, ease: 'easeOut', delay: 0.2 }}
          className={ringColors[color]}
        />
      </svg>
      {showLabel && (
        <span className="absolute font-display font-semibold text-sm text-text-primary tabular-nums">
          {Math.round(clamped)}%
        </span>
      )}
    </div>
  )
}
