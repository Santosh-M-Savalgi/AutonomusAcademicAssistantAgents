import { type ReactNode } from 'react'
import { cn } from '@/utils/cn'

interface CardProps {
  children: ReactNode
  className?: string
  hover?: boolean
  padding?: 'sm' | 'md' | 'lg'
}

const paddings = {
  sm: 'p-4',
  md: 'p-6',
  lg: 'p-8',
}

export function Card({ children, className, hover = false, padding = 'md' }: CardProps) {
  return (
    <div
      className={cn(
        'bg-surface border border-surface-border rounded-lg shadow-card transition-all duration-200',
        hover && 'hover:border-primary/30 hover:shadow-glow cursor-pointer',
        paddings[padding],
        className
      )}
    >
      {children}
    </div>
  )
}
