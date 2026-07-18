import { cn } from '@/utils/cn'
import { type ReactNode } from 'react'

interface AvatarProps {
  src?: string
  alt?: string
  name?: string
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const sizes = {
  sm: 'h-8 w-8 text-xs',
  md: 'h-10 w-10 text-sm',
  lg: 'h-12 w-12 text-base',
}

function getInitials(name: string): string {
  return name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
}

export function Avatar({ src, alt, name, size = 'md', className }: AvatarProps) {
  if (src) {
    return (
      <img
        src={src}
        alt={alt || name || 'Avatar'}
        className={cn('rounded-full object-cover', sizes[size], className)}
      />
    )
  }

  return (
    <div
      className={cn(
        'rounded-full bg-primary-muted text-primary font-medium flex items-center justify-center',
        sizes[size],
        className
      )}
      aria-label={alt || name || 'Avatar'}
    >
      {name ? getInitials(name) : <UserIcon />}
    </div>
  )
}

function UserIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="5" r="3" />
      <path d="M2 14c0-3.3 2.7-6 6-6s6 2.7 6 6" />
    </svg>
  )
}

// -- StatCard --

interface StatCardProps {
  label: string
  value: string | number
  icon?: ReactNode
  trend?: 'up' | 'down'
  trendValue?: string
  variant?: 'primary' | 'secondary'
}

export function StatCard({ label, value, icon, trend, trendValue, variant = 'primary' }: StatCardProps) {
  return (
    <div className="bg-surface border border-surface-border rounded-lg p-5 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm text-text-secondary">{label}</span>
        {icon && (
          <span className={cn(variant === 'primary' ? 'text-primary' : 'text-secondary')}>
            {icon}
          </span>
        )}
      </div>
      <div className="flex items-end gap-2">
        <span className="font-display text-2xl font-semibold text-text-primary tabular-nums">
          {value}
        </span>
        {trend && trendValue && (
          <span
            className={cn(
              'text-xs font-medium mb-1',
              trend === 'up' ? 'text-success' : 'text-danger'
            )}
          >
            {trend === 'up' ? '↑' : '↓'} {trendValue}
          </span>
        )}
      </div>
    </div>
  )
}
