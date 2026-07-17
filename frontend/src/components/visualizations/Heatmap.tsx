import { cn } from '@/utils/cn'
import type { HeatmapData } from './types'

interface HeatmapProps {
  data: HeatmapData[]
  title?: string
  className?: string
  maxValue?: number
}

function getIntensity(value: number, max: number): string {
  if (max === 0) return 'bg-surface-border/30'
  const ratio = value / max
  if (ratio === 0) return 'bg-surface-border/20'
  if (ratio < 0.25) return 'bg-primary/20'
  if (ratio < 0.5) return 'bg-primary/40'
  if (ratio < 0.75) return 'bg-primary/60'
  return 'bg-primary/80'
}

export function Heatmap({ data, title, className, maxValue }: HeatmapProps) {
  if (!data || data.length === 0) return null

  const max = maxValue ?? Math.max(...data.map((d) => d.value), 1)

  // Group by week for display
  const weeks: HeatmapData[][] = []
  let currentWeek: HeatmapData[] = []

  // Sort by date
  const sorted = [...data].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())

  sorted.forEach((d) => {
    const day = new Date(d.date).getDay()
    if (day === 0 && currentWeek.length > 0) {
      weeks.push(currentWeek)
      currentWeek = []
    }
    currentWeek.push(d)
  })
  if (currentWeek.length > 0) weeks.push(currentWeek)

  const dayLabels = ['', 'Mon', '', 'Wed', '', 'Fri', '']

  return (
    <div className={cn('space-y-2', className)}>
      {title && (
        <p className="text-xs font-medium text-text-muted uppercase tracking-wider">{title}</p>
      )}
      <div className="flex gap-1">
        {/* Day labels */}
        <div className="flex flex-col gap-1 pt-0">
          {dayLabels.map((label, i) => (
            <div key={i} className="h-3 text-[8px] text-text-muted leading-3">
              {label}
            </div>
          ))}
        </div>

        {/* Heatmap grid */}
        <div className="flex gap-1 overflow-x-auto pb-1">
          {weeks.map((week, wi) => (
            <div key={wi} className="flex flex-col gap-1">
              {Array.from({ length: 7 }).map((_, di) => {
                const entry = week[di]
                return (
                  <div
                    key={di}
                    className={cn(
                      'h-3 w-3 rounded-sm transition-colors',
                      entry ? getIntensity(entry.value, max) : 'bg-transparent'
                    )}
                    title={entry ? `${entry.label ?? entry.date}: ${entry.value} activities` : undefined}
                    aria-label={entry ? `${entry.label ?? entry.date}: ${entry.value} activities` : undefined}
                  />
                )
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-1.5 text-[8px] text-text-muted">
        <span>Less</span>
        <div className="h-2.5 w-2.5 rounded-sm bg-surface-border/20" />
        <div className="h-2.5 w-2.5 rounded-sm bg-primary/20" />
        <div className="h-2.5 w-2.5 rounded-sm bg-primary/40" />
        <div className="h-2.5 w-2.5 rounded-sm bg-primary/60" />
        <div className="h-2.5 w-2.5 rounded-sm bg-primary/80" />
        <span>More</span>
      </div>
    </div>
  )
}
