import { cn } from '@/utils/cn'
import { LoadingState, ErrorState } from '@/components/ui/States'

interface ChartContainerProps {
  title?: string
  description?: string
  isLoading?: boolean
  isError?: boolean
  isEmpty?: boolean
  emptyMessage?: string
  onRetry?: () => void
  children: React.ReactNode
  className?: string
  height?: number
}

export function ChartContainer({
  title,
  description,
  isLoading,
  isError,
  isEmpty,
  emptyMessage = 'No data available',
  onRetry,
  children,
  className,
  height,
}: ChartContainerProps) {
  if (isLoading) {
    return (
      <div className={cn('bg-surface border border-surface-border rounded-lg', className)}>
        {(title || description) && (
          <div className="px-6 pt-5 pb-2">
            {title && <h3 className="font-display font-semibold text-text-primary text-sm">{title}</h3>}
            {description && <p className="text-xs text-text-muted mt-0.5">{description}</p>}
          </div>
        )}
        <LoadingState message="Loading chart..." />
      </div>
    )
  }

  if (isError) {
    return (
      <div className={cn('bg-surface border border-surface-border rounded-lg', className)}>
        {(title || description) && (
          <div className="px-6 pt-5 pb-2">
            {title && <h3 className="font-display font-semibold text-text-primary text-sm">{title}</h3>}
            {description && <p className="text-xs text-text-muted mt-0.5">{description}</p>}
          </div>
        )}
        <ErrorState
          title="Failed to load chart"
          message="Unable to load this visualization."
          onRetry={onRetry}
        />
      </div>
    )
  }

  if (isEmpty) {
    return (
      <div className={cn('bg-surface border border-surface-border rounded-lg', className)}>
        {(title || description) && (
          <div className="px-6 pt-5 pb-2">
            {title && <h3 className="font-display font-semibold text-text-primary text-sm">{title}</h3>}
            {description && <p className="text-xs text-text-muted mt-0.5">{description}</p>}
          </div>
        )}
        <div className="flex flex-col items-center justify-center py-10 text-center">
          <p className="text-sm text-text-muted">{emptyMessage}</p>
        </div>
      </div>
    )
  }

  return (
    <div className={cn('bg-surface border border-surface-border rounded-lg', className)}>
      {(title || description) && (
        <div className="px-6 pt-5 pb-3 border-b border-surface-border">
          {title && <h3 className="font-display font-semibold text-text-primary text-sm">{title}</h3>}
          {description && <p className="text-xs text-text-muted mt-0.5">{description}</p>}
        </div>
      )}
      <div
        className="p-4"
        style={height ? { height } : undefined}
      >
        {children}
      </div>
    </div>
  )
}
