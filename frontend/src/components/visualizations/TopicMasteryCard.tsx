import { motion } from 'framer-motion'
import { cn } from '@/utils/cn'
import { ProgressRing } from './ProgressRing'
import { AnimatedCounter } from './AnimatedCounter'

interface TopicMasteryCardProps {
  topicName: string
  mastery: number
  completion: number
  quizScore?: number
  lastStudied?: string | null
  needsReview?: boolean
  isWeak?: boolean
  isMastered?: boolean
  className?: string
}

export function TopicMasteryCard({
  topicName,
  mastery,
  completion,
  quizScore,
  lastStudied,
  needsReview,
  isWeak,
  isMastered,
  className,
}: TopicMasteryCardProps) {
  const ringColor = isMastered ? 'secondary' : isWeak ? 'warning' : 'primary'

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'bg-surface border border-surface-border rounded-lg p-4 flex items-center gap-4',
        needsReview && 'border-warning/30',
        isMastered && 'border-secondary/20',
        isWeak && 'border-danger/20',
        className
      )}
    >
      <ProgressRing
        value={isMastered ? 100 : mastery}
        size={64}
        strokeWidth={5}
        color={ringColor}
      />
      <div className="flex-1 min-w-0">
        <h4 className="font-display text-sm font-semibold text-text-primary truncate">
          {topicName}
        </h4>
        <div className="flex items-center gap-3 mt-1 text-xs text-text-muted">
          <span>
            Mastery: <span className="text-text-secondary tabular-nums">{Math.round(mastery)}%</span>
          </span>
          {quizScore !== undefined && (
            <span>
              Quiz: <span className="text-text-secondary tabular-nums">{Math.round(quizScore)}%</span>
            </span>
          )}
          <span>
            Progress: <span className="text-text-secondary tabular-nums">{Math.round(completion)}%</span>
          </span>
        </div>
        {lastStudied && (
          <p className="text-xs text-text-muted mt-1">
            Last studied: {new Date(lastStudied).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </p>
        )}
      </div>
      {needsReview && (
        <span className="shrink-0 text-xs font-medium text-warning bg-warning/10 px-2 py-1 rounded-full">
          Review
        </span>
      )}
      {isMastered && (
        <span className="shrink-0 text-xs font-medium text-secondary bg-secondary-muted px-2 py-1 rounded-full">
          Mastered
        </span>
      )}
    </motion.div>
  )
}
