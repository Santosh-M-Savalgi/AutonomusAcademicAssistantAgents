import { cn } from '@/utils/cn'

interface ChartLegendProps {
  items: Array<{
    label: string
    color: string
    value?: string | number
  }>
  className?: string
}

export function ChartLegend({ items, className }: ChartLegendProps) {
  return (
    <div className={cn('flex flex-wrap gap-4', className)}>
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-2">
          <span
            className="h-2.5 w-2.5 rounded-full shrink-0"
            style={{ backgroundColor: item.color }}
            aria-hidden="true"
          />
          <span className="text-xs text-text-secondary">{item.label}</span>
          {item.value !== undefined && (
            <span className="text-xs font-medium text-text-primary tabular-nums">{item.value}</span>
          )}
        </div>
      ))}
    </div>
  )
}
