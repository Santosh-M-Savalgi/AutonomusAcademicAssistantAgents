import { motion } from 'framer-motion'
import { cn } from '@/utils/cn'

interface DonutChartProps {
  segments: Array<{
    value: number
    color: string
    label: string
  }>
  size?: number
  strokeWidth?: number
  showLegend?: boolean
  animated?: boolean
  className?: string
}

export function DonutChart({
  segments,
  size = 160,
  strokeWidth = 24,
  showLegend = true,
  animated = true,
  className,
}: DonutChartProps) {
  if (!segments || segments.length === 0) return null

  const total = segments.reduce((sum, s) => sum + s.value, 0) || 1
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius

  let cumulative = 0

  return (
    <div className={cn('flex flex-col items-center', className)}>
      <div
        className="relative inline-flex items-center justify-center"
        style={{ width: size, height: size }}
        role="img"
        aria-label={`Donut chart: ${segments.map((s) => `${s.label} ${Math.round((s.value / total) * 100)}%`).join(', ')}`}
      >
        <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
          {/* Background track */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="#1E2430"
            strokeWidth={strokeWidth}
          />

          {/* Segments */}
          {segments.map((segment, i) => {
            const pct = segment.value / total
            const dashLength = pct * circumference
            const offset = -(cumulative / total) * circumference
            cumulative += segment.value

            return (
              <motion.circle
                key={i}
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={segment.color}
                strokeWidth={strokeWidth}
                strokeDasharray={`${dashLength} ${circumference - dashLength}`}
                strokeDashoffset={offset}
                strokeLinecap="butt"
                initial={animated ? { strokeDashoffset: circumference } : undefined}
                animate={{ strokeDashoffset: offset }}
                transition={{ duration: 0.8, delay: i * 0.1, ease: 'easeOut' }}
              />
            )
          })}
        </svg>

        {/* Center text */}
        <div className="absolute flex flex-col items-center">
          <span className="font-display text-xl font-bold text-text-primary tabular-nums">
            {total}
          </span>
          <span className="text-[10px] text-text-muted">Total</span>
        </div>
      </div>

      {/* Legend */}
      {showLegend && (
        <div className="flex flex-wrap justify-center gap-3 mt-3">
          {segments.map((segment, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-full shrink-0"
                style={{ backgroundColor: segment.color }}
                aria-hidden="true"
              />
              <span className="text-xs text-text-secondary">{segment.label}</span>
              <span className="text-xs text-text-muted tabular-nums">
                {Math.round((segment.value / total) * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
