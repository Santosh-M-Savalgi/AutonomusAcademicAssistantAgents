import { cn } from '@/utils/cn'

interface ProgressProps {
  value: number
  max?: number
  size?: 'sm' | 'md'
  variant?: 'primary' | 'secondary'
  showLabel?: boolean
  className?: string
}

export function Progress({
  value,
  max = 100,
  size = 'md',
  variant = 'primary',
  showLabel = false,
  className,
}: ProgressProps) {
  const pct = Math.min(Math.max((value / max) * 100, 0), 100)

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <div
        className={cn(
          'flex-1 bg-surface-border rounded-full overflow-hidden',
          size === 'sm' ? 'h-1.5' : 'h-2'
        )}
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
      >
        <div
          className={cn(
            'h-full rounded-full transition-all duration-500 ease-out',
            variant === 'primary' ? 'bg-primary' : 'bg-secondary'
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      {showLabel && (
        <span className="font-mono text-xs text-text-secondary tabular-nums">
          {Math.round(pct)}%
        </span>
      )}
    </div>
  )
}
