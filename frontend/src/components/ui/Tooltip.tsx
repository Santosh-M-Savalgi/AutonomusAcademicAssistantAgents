import { cn } from '@/utils/cn'
import { motion } from 'framer-motion'

interface TooltipProps {
  content: string
  children: React.ReactNode
  position?: 'top' | 'bottom' | 'left' | 'right'
  className?: string
}

export function Tooltip({ content, children, position = 'top', className }: TooltipProps) {
  const positions = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left: 'right-full top-1/2 -translate-y-1/2 mr-2',
    right: 'left-full top-1/2 -translate-y-1/2 ml-2',
  }

  return (
    <div className="relative group inline-flex">
      {children}
      <div
        className={cn(
          'absolute z-50 hidden group-hover:block pointer-events-none',
          positions[position]
        )}
      >
        <div className="px-2 py-1 text-xs text-text-primary bg-surface border border-surface-border rounded-md shadow-elevated whitespace-nowrap">
          {content}
        </div>
      </div>
    </div>
  )
}
