import { motion } from 'framer-motion'
import { cn } from '@/utils/cn'
import { CheckCircle, Circle } from 'lucide-react'

interface TimelineEvent {
  id: string
  title: string
  description?: string
  date: string
  status: 'completed' | 'in_progress' | 'locked'
  type?: 'lesson' | 'quiz' | 'mastery' | 'milestone'
}

interface ProgressTimelineProps {
  events: TimelineEvent[]
  className?: string
}

const typeColors: Record<string, string> = {
  lesson: 'text-primary',
  quiz: 'text-secondary',
  mastery: 'text-secondary',
  milestone: 'text-success',
}

export function ProgressTimeline({ events, className }: ProgressTimelineProps) {
  if (!events || events.length === 0) return null

  return (
    <div className={cn('space-y-0', className)} role="list" aria-label="Progress timeline">
      {events.map((event, idx) => {
        const isLast = idx === events.length - 1

        return (
          <div key={event.id} className="relative flex gap-4 pb-6 last:pb-0" role="listitem">
            {/* Connector line */}
            {!isLast && (
              <div className="absolute left-[11px] top-6 bottom-0 w-px bg-surface-border" aria-hidden="true" />
            )}

            {/* Status indicator */}
            <div className="relative z-10 mt-0.5">
              {event.status === 'completed' ? (
                <CheckCircle className={cn('h-5 w-5', typeColors[event.type ?? 'lesson'])} />
              ) : event.status === 'in_progress' ? (
                <motion.div
                  animate={{ scale: [1, 1.2, 1] }}
                  transition={{ duration: 2, repeat: Infinity }}
                  className={cn('h-5 w-5 rounded-full border-2 flex items-center justify-center', typeColors[event.type ?? 'lesson'])}
                >
                  <div className="h-2 w-2 rounded-full bg-current" />
                </motion.div>
              ) : (
                <Circle className="h-5 w-5 text-text-muted" />
              )}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <h4 className={cn(
                  'text-sm font-medium',
                  event.status === 'completed' ? 'text-text-primary' : event.status === 'in_progress' ? 'text-text-primary' : 'text-text-muted'
                )}>
                  {event.title}
                </h4>
                {event.type === 'mastery' && (
                  <span className="text-[10px] font-medium text-secondary bg-secondary-muted px-1.5 py-0.5 rounded-full">
                    Mastered
                  </span>
                )}
              </div>
              {event.description && (
                <p className="text-xs text-text-secondary mt-0.5">{event.description}</p>
              )}
              <time className="text-[10px] text-text-muted mt-1 block">
                {new Date(event.date).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  hour: 'numeric',
                  minute: '2-digit',
                })}
              </time>
            </div>
          </div>
        )
      })}
    </div>
  )
}
