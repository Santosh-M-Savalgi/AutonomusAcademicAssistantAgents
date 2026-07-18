import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Card, Button, Badge, Progress } from '@/components/ui'
import { LoadingState, ErrorState, EmptyState } from '@/components/ui'
import { useRoadmap } from '@/services/learningApi'
import { useLearningJourney } from '@/contexts/LearningContext'
import { ROUTES } from '@/constants'
import {
  BookOpen,
  Target,
  CheckCircle,
  Play,
  ArrowRight,
  ChevronRight,
} from 'lucide-react'

export function LearningPage() {
  const navigate = useNavigate()
  const { syllabusId, learningGoal } = useLearningJourney()

  const {
    data: roadmapData,
    isLoading,
    isError,
    refetch,
  } = useRoadmap(syllabusId)

  // ── No syllabus yet ──────────────────────────────────────────────
  if (!syllabusId) {
    return (
      <div className="p-6">
        <EmptyState
          title="No learning path yet"
          description="Start by creating a learning goal, and your personalized curriculum will appear here."
          icon={<BookOpen className="h-12 w-12" />}
          action={
            <Button onClick={() => navigate(ROUTES.GOAL)}>
              <BookOpen className="h-4 w-4 mr-2" />
              Create Learning Goal
            </Button>
          }
        />
      </div>
    )
  }

  // ── Loading ──────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="p-6">
        <LoadingState message="Loading your learning progress..." />
      </div>
    )
  }

  // ── Error ────────────────────────────────────────────────────────
  if (isError) {
    return (
      <div className="p-6">
        <ErrorState
          title="Failed to load progress"
          message="Could not load your learning data. Please try again."
          onRetry={() => refetch()}
        />
      </div>
    )
  }

  // ── No data ──────────────────────────────────────────────────────
  if (!roadmapData) {
    return (
      <div className="p-6">
        <EmptyState
          title="No learning data"
          description="Your learning progress will appear here once you start studying."
          icon={<BookOpen className="h-12 w-12" />}
        />
      </div>
    )
  }

  const {
    title,
    overall_progress_pct,
    completed_count,
    total_count,
    current_topic_id,
    current_topic_name,
    next_topic_id,
    next_topic_name,
    roadmap,
    progress,
  } = roadmapData

  const completedSteps = roadmap.filter((s) => s.is_completed)
  const upcomingSteps = roadmap.filter((s) => !s.is_completed && !s.is_blocked)
  const blockedSteps = roadmap.filter((s) => s.is_blocked)

  const handleTopicClick = (topicId: string) => {
    const step = roadmap.find((s) => s.topic_id === topicId)
    const topic = roadmapData.topics?.find((t) => t.id === topicId)
    navigate(`/lesson/${topicId}`, {
      state: {
        topicId,
        topicName: step?.topic_name ?? topic?.name ?? topicId,
        topicDescription: topic?.description ?? '',
        topicDifficulty: step?.difficulty ?? 'beginner',
        sessionId: roadmapData.session_id,
      },
    })
  }

  return (
    <div className="p-6 space-y-6">
      {/* ── Header ─────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
      >
        <h1 className="text-2xl font-display font-bold text-[#E7EAF0] mb-1">
          {learningGoal || title || 'Learning'}
        </h1>
        <p className="text-sm text-[#8A94A6]">Your learning journey</p>
      </motion.div>

      {/* ── Progress Card ──────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, delay: 0.05 }}
      >
        <Card padding="md" className="bg-[#12161D] border-[#1E2430]">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-[#8A94A6]">Progress</span>
            <span className="text-lg font-display font-bold text-[#E7EAF0] tabular-nums">
              {Math.round(overall_progress_pct)}%
            </span>
          </div>
          <Progress
            value={overall_progress_pct}
            max={100}
            variant="primary"
            size="md"
            aria-label={`Progress: ${Math.round(overall_progress_pct)} percent`}
          />
          <div className="flex items-center gap-4 mt-3 text-xs text-[#8A94A6]">
            <span className="flex items-center gap-1">
              <CheckCircle className="h-3.5 w-3.5 text-secondary" />
              {completed_count} completed
            </span>
            <span className="flex items-center gap-1">
              <BookOpen className="h-3.5 w-3.5 text-[#8A94A6]" />
              {total_count - completed_count} remaining
            </span>
          </div>
        </Card>
      </motion.div>

      {/* ── Current Topic ──────────────────────────────────────── */}
      {current_topic_name && current_topic_id && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.1 }}
        >
          <Card padding="md" className="bg-[#12161D] border-primary/20">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-primary/10">
                  <Play className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <p className="text-xs text-[#8A94A6]">Current Topic</p>
                  <p className="text-sm font-semibold text-[#E7EAF0]">
                    {current_topic_name}
                  </p>
                </div>
              </div>
              <Button
                variant="primary"
                size="sm"
                onClick={() => handleTopicClick(current_topic_id)}
              >
                Resume <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          </Card>
        </motion.div>
      )}

      {/* ── Completed Topics ───────────────────────────────────── */}
      {completedSteps.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.15 }}
        >
          <h2 className="text-sm font-display font-semibold text-[#E7EAF0] mb-3 flex items-center gap-2">
            <CheckCircle className="h-4 w-4 text-secondary" />
            Completed
          </h2>
          <div className="space-y-2">
            {completedSteps.map((step) => (
              <div
                key={step.topic_id}
                onClick={() => handleTopicClick(step.topic_id)}
                className="cursor-pointer"
              >
              <Card
                padding="sm"
                className="bg-[#12161D] border-secondary/10 hover:border-secondary/30 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <CheckCircle className="h-4 w-4 text-secondary shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-[#E7EAF0]">
                        {step.topic_name}
                      </p>
                      <p className="text-xs text-[#8A94A6]">
                        {step.difficulty} · Score: {Math.round(step.mastery_score * 100)}%
                      </p>
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 text-[#5C6575]" />
                </div>
              </Card>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {/* ── Upcoming Topics ────────────────────────────────────── */}
      {upcomingSteps.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.2 }}
        >
          <h2 className="text-sm font-display font-semibold text-[#E7EAF0] mb-3 flex items-center gap-2">
            <Target className="h-4 w-4 text-primary" />
            Upcoming
          </h2>
          <div className="space-y-2">
            {upcomingSteps.slice(0, 5).map((step) => (
              <div
                key={step.topic_id}
                onClick={() => handleTopicClick(step.topic_id)}
                className="cursor-pointer"
              >
              <Card
                padding="sm"
                className="bg-[#12161D] border-[#1E2430] hover:border-primary/30 transition-colors"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex items-center justify-center w-4 h-4 rounded-full border border-[#5C6575] shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-[#E7EAF0]">
                        {step.topic_name}
                      </p>
                      <p className="text-xs text-[#8A94A6]">{step.difficulty}</p>
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 text-[#5C6575]" />
                </div>
              </Card>
              </div>
            ))}
          </div>
          {upcomingSteps.length > 5 && (
            <Button
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => navigate(ROUTES.ROADMAP)}
            >
              View all {upcomingSteps.length} topics
              <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          )}
        </motion.div>
      )}

      {/* ── Next Topic CTA ─────────────────────────────────────── */}
      {next_topic_id && next_topic_name && !current_topic_id && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.25 }}
        >
          <Card padding="md" className="bg-[#12161D] border-[#1E2430]">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-[#8A94A6]">Next Topic</p>
                <p className="text-sm font-semibold text-[#E7EAF0]">
                  {next_topic_name}
                </p>
              </div>
              <Button
                variant="primary"
                size="sm"
                onClick={() => handleTopicClick(next_topic_id)}
              >
                Start <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          </Card>
        </motion.div>
      )}
    </div>
  )
}
