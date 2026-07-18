import { useMemo, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/utils/cn'
import { Check, Lock, ChevronRight, BookOpen } from 'lucide-react'
import type { LearningPathStep } from '@/types/learning'

interface RoadmapNode {
  id: string
  label: string
  status: 'completed' | 'current' | 'locked' | 'available'
  difficulty: string
  depth: number
  mastery_score: number
}

interface LearningRoadmapProps {
  steps: LearningPathStep[]
  currentTopicId?: string | null
  onTopicClick?: (topicId: string) => void
  className?: string
  compact?: boolean
}

function getNodeStatus(
  step: LearningPathStep,
  currentTopicId?: string | null
): RoadmapNode['status'] {
  if (step.is_completed) return 'completed'
  if (step.topic_id === currentTopicId) return 'current'
  if (step.is_blocked) return 'locked'
  return 'available'
}

function getDifficultyColor(difficulty: string): string {
  switch (difficulty.toLowerCase()) {
    case 'beginner':
      return 'text-success'
    case 'intermediate':
      return 'text-secondary'
    case 'advanced':
      return 'text-danger'
    default:
      return 'text-text-secondary'
  }
}

function StatusIcon({ status }: { status: RoadmapNode['status'] }) {
  switch (status) {
    case 'completed':
      return <Check className="h-4 w-4" />
    case 'current':
      return <BookOpen className="h-4 w-4" />
    case 'locked':
      return <Lock className="h-4 w-4" />
    default:
      return <ChevronRight className="h-4 w-4" />
  }
}

export function LearningRoadmap({
  steps,
  currentTopicId,
  onTopicClick,
  className,
  compact = false,
}: LearningRoadmapProps) {
  const nodes: RoadmapNode[] = useMemo(
    () =>
      steps.map((s) => ({
        id: s.topic_id,
        label: s.topic_name,
        status: getNodeStatus(s, currentTopicId),
        difficulty: s.difficulty,
        depth: s.depth,
        mastery_score: s.mastery_score,
      })),
    [steps, currentTopicId]
  )

  const handleClick = useCallback(
    (node: RoadmapNode) => {
      if (node.status !== 'locked' && onTopicClick) {
        onTopicClick(node.id)
      }
    },
    [onTopicClick]
  )

  if (nodes.length === 0) return null

  return (
    <div
      className={cn(
        'relative',
        compact ? 'py-2' : 'py-6',
        className
      )}
      role="list"
      aria-label="Learning roadmap"
    >
      {/* Vertical connecting line */}
      <div className="absolute left-6 top-0 bottom-0 w-px bg-surface-border" aria-hidden="true" />

      {/* Nodes */}
      <div className="space-y-0">
        {nodes.map((node, index) => {
          const isLast = index === nodes.length - 1
          const isClickable = node.status !== 'locked'

          return (
            <motion.div
              key={node.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.05, duration: 0.3 }}
              className={cn(
                'relative flex items-start gap-4 pb-6',
                isLast && 'pb-0',
                compact && 'pb-4'
              )}
              role="listitem"
            >
              {/* Timeline dot */}
              <button
                onClick={() => handleClick(node)}
                disabled={!isClickable}
                aria-label={`${node.label} — ${node.status.replace('_', ' ')}`}
                className={cn(
                  'relative z-10 flex items-center justify-center w-12 h-12 rounded-full border-2 shrink-0 transition-all duration-300',
                  node.status === 'completed' &&
                    'bg-secondary border-secondary text-text-inverse shadow-glow-secondary',
                  node.status === 'current' &&
                    'bg-primary border-primary text-text-inverse shadow-glow',
                  node.status === 'available' &&
                    'bg-surface border-primary/40 text-primary hover:bg-primary-muted hover:border-primary',
                  node.status === 'locked' &&
                    'bg-surface border-surface-border text-text-muted cursor-not-allowed opacity-50'
                )}
              >
                {/* Animated glow for current node */}
                {node.status === 'current' && (
                  <motion.span
                    className="absolute inset-0 rounded-full bg-primary/20"
                    animate={{ scale: [1, 1.3, 1] }}
                    transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
                  />
                )}
                <span className="relative z-10">
                  <StatusIcon status={node.status} />
                </span>
              </button>

              {/* Content */}
              <div
                className={cn(
                  'flex-1 min-w-0 pt-2.5',
                  node.status === 'locked' && 'opacity-40'
                )}
              >
                <button
                  onClick={() => handleClick(node)}
                  disabled={!isClickable}
                  className={cn(
                    'text-left w-full transition-colors',
                    isClickable ? 'cursor-pointer' : 'cursor-default'
                  )}
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3
                      className={cn(
                        'font-display font-semibold transition-colors',
                        compact ? 'text-sm' : 'text-base',
                        node.status === 'completed' && 'text-secondary',
                        node.status === 'current' && 'text-primary',
                        (node.status === 'available' || node.status === 'locked') &&
                          'text-text-primary'
                      )}
                    >
                      {node.label}
                    </h3>
                    <span
                      className={cn(
                        'text-xs font-medium px-1.5 py-0.5 rounded-full bg-surface-border/50',
                        getDifficultyColor(node.difficulty)
                      )}
                    >
                      {node.difficulty}
                    </span>
                  </div>
                </button>

                {!compact && node.mastery_score > 0 && (
                  <div className="mt-1 flex items-center gap-2">
                    <div className="flex-1 max-w-[120px] h-1 bg-surface-border rounded-full overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${node.mastery_score * 100}%` }}
                        transition={{ duration: 0.8, delay: 0.2 }}
                        className={cn(
                          'h-full rounded-full',
                          node.status === 'completed' ? 'bg-secondary' : 'bg-primary'
                        )}
                      />
                    </div>
                    <span className="font-mono text-xs text-text-muted tabular-nums">
                      {Math.round(node.mastery_score * 100)}%
                    </span>
                  </div>
                )}
              </div>
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}

// ─── Animated Edge (reusable for SVG connections) ─────────────

interface RoadmapEdgeProps {
  fromX: number
  fromY: number
  toX: number
  toY: number
  animated?: boolean
  completed?: boolean
  className?: string
}

export function RoadmapEdge({
  fromX,
  fromY,
  toX,
  toY,
  animated = false,
  completed = false,
  className,
}: RoadmapEdgeProps) {
  const midY = (fromY + toY) / 2
  const path = `M ${fromX} ${fromY} C ${fromX} ${midY}, ${toX} ${midY}, ${toX} ${toY}`

  return (
    <svg
      className={cn('absolute inset-0 pointer-events-none', className)}
      style={{ width: '100%', height: '100%' }}
      aria-hidden="true"
    >
      <defs>
        {animated && (
          <linearGradient id="edge-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="var(--color-primary)" />
            <stop offset="100%" stopColor="var(--color-primary)" stopOpacity="0.3" />
          </linearGradient>
        )}
      </defs>
      <path
        d={path}
        fill="none"
        stroke={completed ? 'var(--color-secondary)' : 'var(--color-surface-border)'}
        strokeWidth={2}
        strokeLinecap="round"
        className={cn(animated && 'animate-dash')}
      />
    </svg>
  )
}

// ─── Mini Roadmap (compact preview for dashboard) ────────────

interface MiniRoadmapProps {
  steps: LearningPathStep[]
  currentTopicId?: string | null
  onTopicClick?: (topicId: string) => void
  className?: string
}

export function MiniRoadmap({ steps, currentTopicId, onTopicClick, className }: MiniRoadmapProps) {
  // Show first 4 topics + indicator
  const displaySteps = steps.slice(0, 4)
  const hasMore = steps.length > 4
  const remaining = steps.length - 4

  return (
    <div className={cn('space-y-2', className)}>
      {displaySteps.map((step, i) => {
        const status = getNodeStatus(step, currentTopicId)
        return (
          <motion.button
            key={step.topic_id}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.05 }}
            onClick={() => {
              if (status !== 'locked' && onTopicClick) onTopicClick(step.topic_id)
            }}
            disabled={status === 'locked'}
            className={cn(
              'flex items-center gap-3 w-full text-left p-2.5 rounded-lg transition-all duration-200',
              status === 'current' && 'bg-primary-muted border border-primary/20',
              status === 'completed' && 'hover:bg-surface-hover',
              status === 'available' && 'hover:bg-surface-hover',
              status === 'locked' && 'opacity-40 cursor-not-allowed'
            )}
            aria-label={`${step.topic_name} — ${status}`}
          >
            {/* Dot indicator */}
            <div
              className={cn(
                'h-2.5 w-2.5 rounded-full shrink-0',
                status === 'completed' && 'bg-secondary',
                status === 'current' && 'bg-primary shadow-glow',
                status === 'available' && 'bg-text-muted',
                status === 'locked' && 'bg-surface-border'
              )}
            />
            {/* Topic name */}
            <span
              className={cn(
                'text-sm flex-1 truncate',
                status === 'completed' && 'text-secondary',
                status === 'current' && 'text-primary font-medium',
                (status === 'available' || status === 'locked') && 'text-text-secondary'
              )}
            >
              {step.topic_name}
            </span>
            {/* Mastery badge */}
            {step.mastery_score > 0 && (
              <span className="font-mono text-xs text-text-muted tabular-nums">
                {Math.round(step.mastery_score * 100)}%
              </span>
            )}
          </motion.button>
        )
      })}
      {hasMore && (
        <div className="flex items-center gap-2 px-3 py-2">
          <div className="h-2 w-2 rounded-full bg-surface-border" />
          <span className="text-xs text-text-muted">+{remaining} more topics</span>
        </div>
      )}
    </div>
  )
}
