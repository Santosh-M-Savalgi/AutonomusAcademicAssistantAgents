import { cn } from '@/utils/cn'

interface RouteTransitionLoaderProps {
  className?: string
}

export function RouteTransitionLoader({ className }: RouteTransitionLoaderProps) {
  return (
    <div
      className={cn(
        'flex items-center justify-center min-h-[60vh] w-full',
        className
      )}
      role="status"
      aria-label="Loading page"
    >
      <div className="flex flex-col items-center gap-3">
        <div className="h-8 w-8 border-2 border-surface-border border-t-primary rounded-full animate-spin" />
        <p className="text-sm text-text-muted">Loading...</p>
      </div>
    </div>
  )
}
