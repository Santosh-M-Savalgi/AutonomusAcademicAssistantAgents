import { useMemo, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Card, Button, Badge, SectionHeader, Progress } from '@/components/ui'
import { LoadingState, ErrorState, EmptyState } from '@/components/ui'
import { LearningRoadmap } from '@/components/LearningRoadmap'
import { useRoadmap } from '@/services/learningApi'
import { useLearningJourney } from '@/contexts/LearningContext'
import type { LearningPath, LearningPathStep } from '@/types/learning'
import { ROUTES } from '@/constants'
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
  const location = useLocation()
  const { syllabusId } = useLearningJourney()

  // ── Navigation state (from LearningGoalPage — first-load fast path) ──
  const navState = location.state as {
    syllabusId?: string
    sessionId?: string
    title?: string
    topics?: Array<{
      id: string; name: string; slug: string; description: string
      difficulty: string; prerequisites: string[]
    }>
    roadmap?: Array<{
      topic_id: string; topic_name: string; topic_slug: string
      difficulty: string; depth: number; mastery_score: number
      is_completed: boolean; is_blocked: boolean; unmet_prerequisites: string[]
    }>
    roadmapMode?: string
  } | null

  // ── API: fetch roadmap from backend (primary data source) ──────
  const {
    data: roadmapData,
    isLoading,
    isError,
    refetch,
  } = useRoadmap(syllabusId)

  // ── Derive learning path from API data ──────────────────────────
  const learningPath: LearningPath | null = useMemo(() => {
    if (!roadmapData?.roadmap) return null
    const steps = roadmapData.roadmap
    return {
      mode: roadmapData.roadmap_mode,
      total_topics: roadmapData.total_count,
      completed_topics: roadmapData.completed_count,
      remaining_topics: roadmapData.total_count - roadmapData.completed_count,
      next_topic_id: roadmapData.next_topic_id,
      is_complete: roadmapData.completed_count === roadmapData.total_count,
      steps: steps.map((r): LearningPathStep => ({
        topic_id: r.topic_id,
        topic_name: r.topic_name,
        topic_slug: r.topic_slug,
        difficulty: r.difficulty,
        depth: r.depth,
        mastery_score: r.mastery_score,
        is_completed: r.is_completed,
        is_blocked: r.is_blocked,
        unmet_prerequisites: r.unmet_prerequisites,
      })),
    }
  }, [roadmapData])

  const completedCount = learningPath?.completed_topics ?? 0
  const totalTopics = learningPath?.total_topics ?? 0
  const remainingCount = learningPath?.remaining_topics ?? 0
  const overallProgress = roadmapData?.overall_progress_pct ?? (
    totalTopics > 0 ? (completedCount / totalTopics) * 100 : 0
  )

  const currentTopicId = roadmapData?.current_topic_id ?? learningPath?.next_topic_id ?? null
  const currentTopicName = roadmapData?.current_topic_name ?? null
  const steps = learningPath?.steps ?? []
  const learningGoal = roadmapData?.learning_goal ?? ''
  const selectedMode = roadmapData?.roadmap_mode ?? 'standard'

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
      const step = steps.find((s) => s.topic_id === topicId)
      const topic = roadmapData?.topics?.find((t) => t.id === topicId)
      navigate(`/lesson/${topicId}`, {
        state: {
          topicId,
          topicName: step?.topic_name ?? topic?.name ?? topicId,
          topicDescription: topic?.description ?? '',
          topicDifficulty: step?.difficulty ?? 'beginner',
          sessionId: roadmapData?.session_id ?? '',
        },
      })
    },
    [navigate, steps, roadmapData]
  )

  const handleRetry = useCallback(() => {
    refetch()
  }, [refetch])

  // ── Loading ─────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#0A0D12] p-6">
        <LoadingState message="Loading your learning roadmap..." />
      </div>
    )
  }

  // ── Error ───────────────────────────────────────────────────────
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

  // ── Empty: no syllabus yet ─────────────────────────────────────
  if (!syllabusId) {
    return (
      <div className="min-h-screen bg-[#0A0D12]">
        <div className="p-6 pb-0">
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
            <Button onClick={() => navigate(ROUTES.GOAL)}>
              <BookOpen className="h-4 w-4 mr-2" />
              Start learning
            </Button>
          }
        />
      </div>
    )
  }

  // ── Empty: data loaded but no steps ─────────────────────────────
  if (steps.length === 0) {
    return (
      <div className="min-h-screen bg-[#0A0D12]">
        <div className="p-6 pb-0">
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
            <Button onClick={() => navigate(ROUTES.GOAL)}>
              <BookOpen className="h-4 w-4 mr-2" />
              Start learning
            </Button>
          }
        />
      </div>
    )
  }

  // ── Main Content ────────────────────────────────────────────────
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
                  {learningGoal || 'Learning Roadmap'}
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
                {completedCount} / {totalTopics} ({Math.round(overallProgress)}%)
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

          {/* Current topic indicator */}
          {currentTopicName && (
            <div className="mt-3 flex items-center gap-2 text-sm">
              <span className="text-[#8A94A6]">Currently:</span>
              <span className="font-medium text-[#E7EAF0]">{currentTopicName}</span>
              {currentTopicId && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleTopicClick(currentTopicId)}
                  className="ml-2"
                >
                  Resume <ChevronRight className="h-3.5 w-3.5 ml-0.5" />
                </Button>
              )}
            </div>
          )}
        </motion.div>

        {/* ── Stats Row ─────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.08 }}
          className="grid grid-cols-3 gap-3 mb-8"
        >
          {[
            { label: 'Total Topics', value: totalTopics, icon: BarChart3, color: 'text-primary' },
            { label: 'Completed', value: completedCount, icon: CheckCircle, color: 'text-secondary' },
            { label: 'Remaining', value: remainingCount, icon: BookOpen, color: 'text-[#8A94A6]' },
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
                <p className={cn('text-lg font-display font-bold tabular-nums', stat.color)}>
                  {stat.value}
                </p>
              </div>
            </div>
          ))}
        </motion.div>

        {/* ── Main Content: Roadmap + Sidebar ──────────────────── */}
        <div className="flex flex-col lg:flex-row gap-8">
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

          {/* Side panel */}
          <motion.aside
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.4, delay: 0.18 }}
            className="hidden lg:block w-72 shrink-0"
            aria-label="Roadmap details"
          >
            <div className="sticky top-6 space-y-5">
              <Card padding="sm" className="bg-[#12161D] border-[#1E2430]">
                <h3 className="text-sm font-display font-semibold text-[#E7EAF0] mb-3">
                  Path Summary
                </h3>
                <div className="space-y-2">
                  {[
                    { label: 'Total topics', value: totalTopics },
                    { label: 'Completed', value: completedCount },
                    { label: 'Remaining', value: remainingCount },
                    { label: 'Avg. Mastery', value: `${quickStats.avgMastery}%` },
                  ].map((row) => (
                    <div key={row.label} className="flex justify-between text-sm">
                      <span className="text-[#8A94A6]">{row.label}</span>
                      <span className="font-medium text-[#E7EAF0] tabular-nums">
                        {row.value}
                      </span>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </motion.aside>
        </div>
      </div>
    </div>
  )
}
