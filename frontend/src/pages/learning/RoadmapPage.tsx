import { useState, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Card, Button, Badge, SectionHeader, Progress } from '@/components/ui'
import { LoadingState, ErrorState, EmptyState } from '@/components/ui'
import { LearningRoadmap } from '@/components/LearningRoadmap'
import { useLearningPath, useAdaptiveStatus } from '@/services/learningApi'
import {
  BookOpen,
  Map,
  Target,
  BarChart3,
  CheckCircle,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/utils/cn'

// ─── Layout Constants ──────────────────────────────────────────────

const modes = ['Standard', 'Beginner', 'Fast Track'] as const
type LearningMode = (typeof modes)[number]

// ─── Helpers ────────────────────────────────────────────────────────

function getModeIntensity(mode: string): string {
  switch (mode.toLowerCase()) {
    case 'standard':
      return 'bg-primary/10 text-primary border-primary/30'
    case 'beginner':
      return 'bg-secondary/10 text-secondary border-secondary/30'
    case 'fast track':
      return 'bg-purple-500/10 text-purple-400 border-purple-500/30'
    default:
      return 'bg-surface-border text-text-secondary border-surface-border'
  }
}

// ─── Component ─────────────────────────────────────────────────────

export function RoadmapPage() {
  const navigate = useNavigate()
  const [selectedMode, setSelectedMode] = useState<string>(modes[0])

  // ── Data hooks ──────────────────────────────────────────────────
  const {
    data: adaptiveStatus,
    isLoading: statusLoading,
    isError: statusError,
    refetch: refetchStatus,
  } = useAdaptiveStatus()

  // Use adaptive-status topic IDs if available, otherwise empty array
  // so the learning-path query stays enabled only when we have data.
  const topicIds = useMemo<string[]>(() => {
    if (adaptiveStatus?.current_topic_id) return [adaptiveStatus.current_topic_id]
    return []
  }, [adaptiveStatus])

  const masteryScores = useMemo(() => {
    if (!adaptiveStatus) return {}
    // Build a minimal mastery-scores map from the status distribution
    return Object.fromEntries(
      Object.entries(adaptiveStatus.state_distribution ?? {}).map(([k, v]) => [
        k,
        typeof v === 'number' ? v : 0,
      ])
    )
  }, [adaptiveStatus])

  const {
    data: learningPath,
    isLoading: pathLoading,
    isError: pathError,
    refetch: refetchPath,
  } = useLearningPath(topicIds, masteryScores, selectedMode.toLowerCase())

  // ── Derived values ──────────────────────────────────────────────
  const isLoading = statusLoading || pathLoading
  const isError = statusError || pathError

  const completedCount = learningPath?.completed_topics ?? 0
  const totalTopics = learningPath?.total_topics ?? 0
  const remainingCount = learningPath?.remaining_topics ?? 0
  const overallProgress = totalTopics > 0 ? (completedCount / totalTopics) * 100 : 0

  const currentTopicId = adaptiveStatus?.current_topic_id ?? null
  const steps = learningPath?.steps ?? []

  // Placeholder stats when no real data exists
  const quickStats = useMemo(
    () => ({
      avgMastery: steps.length
        ? Math.round(
            steps.reduce((sum, s) => sum + (s.mastery_score ?? 0) * 100, 0) /
              steps.length
          )
        : 0,
      masteredCount: steps.filter((s) => s.mastery_score >= 0.8).length,
    }),
    [steps]
  )

  // ── Callbacks ───────────────────────────────────────────────────
  const handleTopicClick = useCallback(
    (topicId: string) => {
      navigate(`/lesson/${topicId}`)
    },
    [navigate]
  )

  const handleRetry = useCallback(() => {
    refetchStatus()
    refetchPath()
  }, [refetchStatus, refetchPath])

  // ── Render: Loading ─────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#0A0D12] p-6">
        <LoadingState message="Loading your learning roadmap..." />
      </div>
    )
  }

  // ── Render: Error ───────────────────────────────────────────────
  if (isError) {
    return (
      <div className="min-h-screen bg-[#0A0D12] p-6">
        <ErrorState
          title="Failed to load roadmap"
          message="We couldn't load your learning path. Please check your connection and try again."
          onRetry={handleRetry}
        />
      </div>
    )
  }

  // ── Render: Empty / no path ─────────────────────────────────────
  if (!learningPath || steps.length === 0) {
    return (
      <div className="min-h-screen bg-[#0A0D12]">
        {/* Page header still visible so the user knows they are on the right page */}
        <div className="p-6 pb-0">
          {/* ── Header ─────────────────── */}
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35 }}
          >
            <div className="flex items-center gap-3 mb-1">
              <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary/10 text-primary">
                <Map className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-2xl font-display font-bold text-[#E7EAF0]">
                  Learning Roadmap
                </h1>
                <p className="text-sm text-[#8A94A6]">
                  Your personalized learning journey
                </p>
              </div>
            </div>
          </motion.div>
        </div>

        <EmptyState
          title="No learning path yet"
          description="Start learning to build your personalized roadmap. Your completed topics and progress will appear here as you go."
          icon={<Map className="h-12 w-12" />}
          action={
            <Button onClick={() => navigate('/learn')}>
              <BookOpen className="h-4 w-4 mr-2" />
              Start learning
            </Button>
          }
        />
      </div>
    )
  }

  // ── Render: Main Page ──────────────────────────────────────────
  return (
    <div className="min-h-screen bg-[#0A0D12]">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        {/* ── Page Header ─────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="mb-6"
        >
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary/10 text-primary shrink-0">
                <Map className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-2xl font-display font-bold text-[#E7EAF0]">
                  Learning Roadmap
                </h1>
                <p className="text-sm text-[#8A94A6]">
                  Your personalized learning journey
                </p>
              </div>
            </div>

            <Badge
              variant="primary"
              size="md"
              className={cn('capitalize', getModeIntensity(selectedMode))}
            >
              <Target className="h-3.5 w-3.5 mr-1.5" />
              {selectedMode}
            </Badge>
          </div>

          {/* Overall progress bar */}
          <div className="mt-4">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-medium text-[#8A94A6]">
                Overall Progress
              </span>
              <span className="font-mono text-xs text-[#8A94A6] tabular-nums">
                {completedCount} / {totalTopics} ({Math.round(overallProgress)}
                %)
              </span>
            </div>
            <Progress
              value={overallProgress}
              max={100}
              variant="primary"
              size="md"
              aria-label={`Overall progress: ${Math.round(overallProgress)} percent`}
            />
          </div>
        </motion.div>

        {/* ── Stats Row ─────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.08 }}
          className="grid grid-cols-3 gap-3 mb-8"
        >
          {[
            {
              label: 'Total Topics',
              value: totalTopics,
              icon: BarChart3,
              color: 'text-primary',
            },
            {
              label: 'Completed',
              value: completedCount,
              icon: CheckCircle,
              color: 'text-secondary',
            },
            {
              label: 'Remaining',
              value: remainingCount,
              icon: BookOpen,
              color: 'text-[#8A94A6]',
            },
          ].map((stat) => (
            <div
              key={stat.label}
              className="flex items-center gap-3 bg-[#12161D] border border-[#1E2430] rounded-lg px-4 py-3"
            >
              <div
                className={cn(
                  'flex items-center justify-center w-9 h-9 rounded-lg shrink-0',
                  stat.color === 'text-primary'
                    ? 'bg-primary/10'
                    : stat.color === 'text-secondary'
                      ? 'bg-secondary/10'
                      : 'bg-[#1E2430]/50'
                )}
              >
                <stat.icon
                  className={cn(
                    'h-4 w-4',
                    stat.color === 'text-primary'
                      ? 'text-primary'
                      : stat.color === 'text-secondary'
                        ? 'text-secondary'
                        : 'text-[#8A94A6]'
                  )}
                />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-[#8A94A6] truncate">{stat.label}</p>
                <p
                  className={cn(
                    'text-lg font-display font-bold tabular-nums',
                    stat.color
                  )}
                >
                  {stat.value}
                </p>
              </div>
            </div>
          ))}
        </motion.div>

        {/* ── Main Content: Roadmap + Sidebar ──────────────────── */}
        <div className="flex flex-col lg:flex-row gap-8">
          {/* Roadmap (full width on mobile, flex-1 on desktop) */}
          <motion.div
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.4, delay: 0.12 }}
            className="flex-1 min-w-0"
            aria-label="Learning roadmap timeline"
          >
            <Card padding="md" className="bg-[#12161D] border-[#1E2430]">
              <LearningRoadmap
                steps={steps}
                currentTopicId={currentTopicId}
                onTopicClick={handleTopicClick}
                aria-label="Learning path steps"
              />
            </Card>
          </motion.div>

          {/* Side panel (desktop only) */}
          <motion.aside
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.4, delay: 0.18 }}
            className="hidden lg:block w-72 shrink-0"
            aria-label="Roadmap details"
          >
            <div className="sticky top-6 space-y-5">
              {/* ── Topic count summary ──────────────────────────── */}
              <Card padding="sm" className="bg-[#12161D] border-[#1E2430]">
                <h3 className="text-sm font-display font-semibold text-[#E7EAF0] mb-3">
                  Path Summary
                </h3>
                <div className="space-y-2">
                  {[
                    { label: 'Total topics', value: totalTopics },
                    { label: 'Completed', value: completedCount },
                    { label: 'Remaining', value: remainingCount },
                  ].map((item) => (
                    <div
                      key={item.label}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-[#8A94A6]">{item.label}</span>
                      <span className="font-semibold text-[#E7EAF0] tabular-nums">
                        {item.value}
                      </span>
                    </div>
                  ))}
                </div>
              </Card>

              {/* ── Legend ────────────────────────────────────────── */}
              <Card padding="sm" className="bg-[#12161D] border-[#1E2430]">
                <h3 className="text-sm font-display font-semibold text-[#E7EAF0] mb-3">
                  Legend
                </h3>
                <div className="space-y-2.5">
                  {[
                    {
                      label: 'Completed',
                      dot: 'bg-secondary border-secondary',
                    },
                    { label: 'Current', dot: 'bg-primary border-primary' },
                    {
                      label: 'Available',
                      dot: 'bg-[#5C6575] border-[#5C6575]',
                    },
                    {
                      label: 'Locked',
                      dot: 'bg-transparent border-[#1E2430]',
                    },
                  ].map((entry) => (
                    <div
                      key={entry.label}
                      className="flex items-center gap-2.5"
                    >
                      <span
                        className={cn(
                          'w-3 h-3 rounded-full border',
                          entry.dot
                        )}
                        aria-hidden="true"
                      />
                      <span className="text-sm text-[#8A94A6]">
                        {entry.label}
                      </span>
                    </div>
                  ))}
                </div>
              </Card>

              {/* ── Learning mode selector (visual placeholder) ──── */}
              <Card padding="sm" className="bg-[#12161D] border-[#1E2430]">
                <h3 className="text-sm font-display font-semibold text-[#E7EAF0] mb-3">
                  Learning Mode
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {modes.map((mode) => (
                    <button
                      key={mode}
                      onClick={() => setSelectedMode(mode)}
                      className={cn(
                        'px-2.5 py-1 text-xs font-medium rounded-full border transition-all duration-200',
                        selectedMode === mode
                          ? getModeIntensity(mode)
                          : 'bg-[#181D27] border-[#1E2430] text-[#5C6575] hover:text-[#8A94A6] hover:border-[#8A94A6]/30'
                      )}
                      aria-pressed={selectedMode === mode}
                      aria-label={`Switch to ${mode} mode`}
                    >
                      {mode}
                    </button>
                  ))}
                </div>
              </Card>

              {/* ── Quick stats ──────────────────────────────────── */}
              <Card padding="sm" className="bg-[#12161D] border-[#1E2430]">
                <h3 className="text-sm font-display font-semibold text-[#E7EAF0] mb-3">
                  Quick Stats
                </h3>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-[#8A94A6]">Average mastery</span>
                    <span className="font-semibold text-[#E7EAF0] tabular-nums">
                      {quickStats.avgMastery}%
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-[#8A94A6]">Topics mastered</span>
                    <span className="font-semibold text-[#E7EAF0] tabular-nums">
                      {quickStats.masteredCount}
                    </span>
                  </div>
                </div>
              </Card>
            </div>
          </motion.aside>
        </div>
      </div>
    </div>
  )
}

export default RoadmapPage
