import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { Card, StatCard, SectionHeader, Button, Badge, Skeleton } from '@/components/ui'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui'
import { MiniRoadmap } from '@/components/LearningRoadmap'
import { useDashboard, useLearningPath, useRecommendations, useTopicProgress } from '@/services/learningApi'
import { useNavigate } from 'react-router-dom'
import { ROUTES } from '@/constants'
import { BookOpen, Zap, TrendingUp, Clock, ArrowRight, Sparkles, Target, ChevronRight, Brain } from 'lucide-react'
import { cn } from '@/utils/cn'
import { useAuth } from '@/contexts/AuthContext'

/* ─── Helpers ──────────────────────────────────────────────── */

function formatDate(): string {
  return new Intl.DateTimeFormat('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date())
}

function formatStudyTime(minutes: number): string {
  if (minutes < 60) return `${minutes}m`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

/* ─── Stagger animation config ────────────────────────────── */

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.06 },
  },
}

const itemVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.4, ease: 'easeOut' },
  },
}

/* ─── Inner Skeleton Loaders ──────────────────────────────── */

function DashboardSkeleton() {
  return (
    <div className="space-y-6" aria-label="Loading dashboard">
      {/* Welcome skeleton */}
      <div className="space-y-2">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-4 w-48" />
      </div>

      {/* Stats skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="bg-surface border border-surface-border rounded-lg p-5 space-y-3"
          >
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-8 w-16" />
          </div>
        ))}
      </div>

      {/* Two-column skeleton */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="bg-surface border border-surface-border rounded-lg p-6 space-y-3"
            >
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-4/5" />
            </div>
          ))}
        </div>
        <div className="space-y-6">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="bg-surface border border-surface-border rounded-lg p-6 space-y-3"
            >
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ─── Percentage Circle ───────────────────────────────────── */

function PercentageCircle({ value, color, size = 80, strokeWidth = 6 }: {
  value: number
  color: string
  size?: number
  strokeWidth?: number
}) {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (value / 100) * circumference

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
      aria-label={`${Math.round(value)}% mastery`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-surface-border"
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1, ease: 'easeOut', delay: 0.3 }}
          className={color}
        />
      </svg>
      <span className="absolute font-display font-semibold text-lg text-text-primary tabular-nums">
        {Math.round(value)}%
      </span>
    </div>
  )
}

/* ─── Activity Card ───────────────────────────────────────── */

function ActivityCard({ timestamp, event_type, topic }: {
  timestamp: string
  event_type: string
  topic: string
}) {
  const time = new Date(timestamp)
  const timeStr = time.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })

  const eventLabel = event_type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

  return (
    <div className="flex items-start gap-3 py-3 first:pt-0 last:pb-0 border-b border-surface-border last:border-0">
      <div className="h-2 w-2 rounded-full bg-primary/60 mt-2 shrink-0" aria-hidden="true" />
      <div className="flex-1 min-w-0">
        <p className="text-sm text-text-primary truncate">{eventLabel}</p>
        <p className="text-xs text-text-muted truncate mt-0.5">{topic}</p>
      </div>
      <time className="text-xs text-text-muted whitespace-nowrap shrink-0 pt-0.5">
        {timeStr}
      </time>
    </div>
  )
}

/* ─── Dashboard Page ──────────────────────────────────────── */

export function DashboardPage() {
  const navigate = useNavigate()
  const { user } = useAuth()

  const {
    data: dashboard,
    isLoading: dashLoading,
    isError: dashError,
    error: dashErr,
    refetch: dashRefetch,
  } = useDashboard()

  const {
    data: learningPath,
    isLoading: pathLoading,
  } = useLearningPath([])

  const {
    data: recommendations,
    isLoading: recsLoading,
  } = useRecommendations()

  /* Derive the first (highest-priority) recommendation */
  const topRecommendation = useMemo(() => {
    if (!recommendations || recommendations.length === 0) return null
    return recommendations.reduce((best, r) => (r.priority > best.priority ? r : best))
  }, [recommendations])

  /* Current topic id for MiniRoadmap */
  const currentTopicId = dashboard?.current_topic ?? null

  /* ── Empty: no dashboard data at all ──────────────────────── */

  if (!dashLoading && !dashError && dashboard === undefined) {
    return (
      <EmptyState
        title="Start your learning journey"
        description="Pick a topic or upload a syllabus to begin. Your progress will appear here."
        icon={<BookOpen className="h-12 w-12" />}
      />
    )
  }

  /* ── Error ────────────────────────────────────────────────── */

  if (dashError && !dashLoading) {
    return (
      <ErrorState
        title="Could not load dashboard"
        message={dashErr instanceof Error ? dashErr.message : 'An unexpected error occurred.'}
        onRetry={() => dashRefetch()}
      />
    )
  }

  /* ── Loading ──────────────────────────────────────────────── */

  if (dashLoading) {
    return <DashboardSkeleton />
  }

  /* ── Render ──────────────────────────────────────────────── */

  const username = user?.name ?? user?.email ?? 'Learner'
  const currentCourse = dashboard?.current_course
  const currentTopic = dashboard?.current_topic
  const overallCompletion = dashboard?.overall_completion ?? 0
  const overallMastery = dashboard?.overall_mastery ?? 0
  const averageQuizScore = dashboard?.average_quiz_score ?? 0
  const studyTimeMin = (dashboard?.daily_study_time_minutes ?? dashboard?.weekly_study_time_minutes ?? 0)
  const currentStreak = dashboard?.current_streak_days ?? 0
  const topicsLearned = dashboard?.recent_sessions ?? 0
  const recentActivity = dashboard?.recent_activity
  const hasActivity = Array.isArray(recentActivity) && recentActivity.length > 0

  return (
    <motion.div
      className="p-6 space-y-6 max-w-7xl mx-auto"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      aria-label="Dashboard page"
    >
      {/* ═══ Welcome Section ═══ */}
      <motion.div variants={itemVariants} className="space-y-1">
        <h1 className="font-display text-2xl font-bold text-text-primary">
          Welcome back, {username}
        </h1>
        <p className="text-sm text-text-secondary">{formatDate()}</p>
        {currentCourse && (
          <Badge variant="primary" size="sm" className="mt-2">
            <BookOpen className="h-3 w-3 mr-1" />
            {currentCourse}
          </Badge>
        )}
      </motion.div>

      {/* ═══ Stats Grid ═══ */}
      <motion.div
        variants={itemVariants}
        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"
      >
        <StatCard
          label="Current Streak"
          value={`${currentStreak} day${currentStreak === 1 ? '' : 's'}`}
          icon={<Zap className="h-4 w-4" />}
          variant="secondary"
        />
        <StatCard
          label="Topics Learned"
          value={topicsLearned}
          icon={<BookOpen className="h-4 w-4" />}
        />
        <StatCard
          label="Mastery Rate"
          value={`${Math.round(overallMastery)}%`}
          icon={<TrendingUp className="h-4 w-4" />}
        />
        <StatCard
          label="Study Time"
          value={formatStudyTime(studyTimeMin)}
          icon={<Clock className="h-4 w-4" />}
        />
      </motion.div>

      {/* ═══ Two-Column Layout ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* ─── Left Column (2/3) ────────────────────────────── */}
        <div className="lg:col-span-2 space-y-6">

          {/* Current Lesson */}
          <motion.div variants={itemVariants}>
            <Card padding="md" className="overflow-hidden">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-2">
                  {currentTopic ? (
                    <Brain className="h-5 w-5 text-primary" aria-hidden="true" />
                  ) : (
                    <BookOpen className="h-5 w-5 text-text-muted" aria-hidden="true" />
                  )}
                  <div>
                    <h3 className="font-display font-semibold text-text-primary text-base">
                      Current Lesson
                    </h3>
                    <p className="text-sm text-text-secondary mt-0.5">
                      {currentTopic ?? 'No active lesson'}
                    </p>
                  </div>
                </div>
                {overallCompletion > 0 && (
                  <Badge variant="primary" size="sm">
                    {Math.round(overallCompletion)}% complete
                  </Badge>
                )}
              </div>

              {/* Progress bar */}
              <div className="space-y-1.5 mb-5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-text-muted">Overall progress</span>
                  <span className="text-text-secondary font-medium tabular-nums">
                    {Math.round(overallCompletion)}%
                  </span>
                </div>
                <div
                  className="h-2 bg-surface-border rounded-full overflow-hidden"
                  role="progressbar"
                  aria-valuenow={overallCompletion}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Learning progress"
                >
                  <motion.div
                    className="h-full bg-primary rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${overallCompletion}%` }}
                    transition={{ duration: 0.8, ease: 'easeOut' }}
                  />
                </div>
              </div>

              {currentTopic ? (
                <Button
                  variant="primary"
                  size="md"
                  icon={<ArrowRight className="h-4 w-4" />}
                  onClick={() => navigate(`/lesson/${currentTopicId ?? ''}`)}
                  aria-label="Resume current lesson"
                >
                  Resume Learning
                </Button>
              ) : (
                <div className="flex items-center gap-2 text-sm text-text-muted">
                  <BookOpen className="h-4 w-4" />
                  <span>Select a topic to begin your next lesson</span>
                </div>
              )}
            </Card>
          </motion.div>

          {/* Mini Roadmap */}
          <motion.div variants={itemVariants}>
            <Card padding="md" className="overflow-hidden">
              <SectionHeader
                title="Your Learning Path"
                action={
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<ChevronRight className="h-4 w-4" />}
                    onClick={() => navigate('/roadmap')}
                    aria-label="View full learning roadmap"
                  >
                    View Full Roadmap
                  </Button>
                }
              />

              <div className="mt-4">
                {pathLoading ? (
                  <div className="space-y-3">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <Skeleton key={i} className="h-11 w-full rounded-lg" />
                    ))}
                  </div>
                ) : learningPath && learningPath.steps.length > 0 ? (
                  <MiniRoadmap
                    steps={learningPath.steps}
                    currentTopicId={currentTopicId}
                    onTopicClick={(topicId) => navigate(`/lesson/${topicId}`)}
                  />
                ) : (
                  <div className="flex flex-col items-center py-8 text-center">
                    <Target className="h-10 w-10 text-text-muted mb-3" aria-hidden="true" />
                    <p className="text-sm text-text-secondary">
                      Start learning to see your path
                    </p>
                    <p className="text-xs text-text-muted mt-1">
                      Complete lessons and your personalised roadmap will appear here
                    </p>
                  </div>
                )}
              </div>
            </Card>
          </motion.div>

          {/* Recent Activity */}
          <motion.div variants={itemVariants}>
            <Card padding="md" className="overflow-hidden">
              <SectionHeader
                title="Recent Activity"
                description={hasActivity ? 'Your latest learning events' : undefined}
              />

              <div className="mt-3">
                {hasActivity ? (
                  <div aria-label="Recent activity list">
                    {recentActivity.map((event, idx) => (
                      <ActivityCard
                        key={`${event.timestamp}-${idx}`}
                        timestamp={event.timestamp}
                        event_type={event.event_type}
                        topic={event.topic}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col items-center py-8 text-center">
                    <Clock className="h-10 w-10 text-text-muted mb-3" aria-hidden="true" />
                    <p className="text-sm text-text-secondary">No recent activity</p>
                    <p className="text-xs text-text-muted mt-1">
                      Start a lesson and your activity will show up here
                    </p>
                  </div>
                )}
              </div>
            </Card>
          </motion.div>
        </div>

        {/* ─── Right Column (1/3) ───────────────────────────── */}
        <div className="space-y-6">

          {/* AI Mentor Suggestion */}
          <motion.div variants={itemVariants}>
            <Card
              padding="md"
              className={cn(
                'border-primary/20 bg-gradient-to-br from-surface to-surface-hover overflow-hidden relative'
              )}
            >
              {/* Decorative sparkle */}
              <div className="absolute -top-2 -right-2 text-primary/10" aria-hidden="true">
                <Sparkles className="h-24 w-24" />
              </div>

              <div className="relative z-10">
                <div className="flex items-center gap-2 mb-3">
                  <Sparkles className="h-5 w-5 text-primary" aria-hidden="true" />
                  <h3 className="font-display font-semibold text-text-primary text-base">
                    AI Mentor
                  </h3>
                </div>

                <p className="text-sm text-text-secondary leading-relaxed mb-4">
                  {currentTopic
                    ? 'Continue where you stopped — your lesson is ready and waiting.'
                    : 'Pick a topic to start learning with personalised AI guidance.'}
                </p>

                <div className="flex items-center gap-3">
                  <Button
                    variant="primary"
                    size="md"
                    icon={<Sparkles className="h-4 w-4" />}
                    onClick={() => {
                      if (currentTopicId) navigate(`/lesson/${currentTopicId}`)
                      else navigate(ROUTES.GOAL)
                    }}
                    aria-label="Go to your current lesson"
                  >
                    Let&apos;s Go
                  </Button>
                  <span className="text-xs text-text-muted">
                    Powered by AI
                  </span>
                </div>
              </div>
            </Card>
          </motion.div>

          {/* Next Recommendation */}
          <motion.div variants={itemVariants}>
            <Card padding="md" className="overflow-hidden">
              <SectionHeader
                title="Next Recommendation"
                description="Personalised for you"
              />

              <div className="mt-4">
                {recsLoading ? (
                  <div className="space-y-3">
                    <Skeleton className="h-5 w-3/4" />
                    <Skeleton className="h-4 w-full" />
                    <Skeleton className="h-9 w-28" />
                  </div>
                ) : topRecommendation ? (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <Target className="h-4 w-4 text-secondary" aria-hidden="true" />
                      <h4 className="font-display font-medium text-text-primary text-sm">
                        {topRecommendation.topic_name}
                      </h4>
                    </div>
                    <p className="text-xs text-text-secondary leading-relaxed">
                      {topRecommendation.reason}
                    </p>
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={<ArrowRight className="h-3.5 w-3.5" />}
                      onClick={() => navigate(`/lesson/${topRecommendation.topic_id}`)}
                      aria-label={`Start lesson on ${topRecommendation.topic_name}`}
                    >
                      Start Topic
                    </Button>
                  </div>
                ) : (
                  <div className="flex flex-col items-center py-8 text-center">
                    <Sparkles className="h-10 w-10 text-text-muted mb-3" aria-hidden="true" />
                    <p className="text-sm text-text-secondary">No recommendations yet</p>
                    <p className="text-xs text-text-muted mt-1">
                      Complete more lessons to get personalised suggestions
                    </p>
                  </div>
                )}
              </div>
            </Card>
          </motion.div>

          {/* Progress Overview */}
          <motion.div variants={itemVariants}>
            <Card padding="md" className="overflow-hidden">
              <SectionHeader
                title="Progress Overview"
                description="Your learning metrics"
              />

              <div className="mt-6 space-y-6">
                {/* Mastery circle */}
                <div className="flex flex-col items-center text-center">
                  <PercentageCircle value={overallMastery} color="text-secondary" />
                  <p className="text-xs text-text-muted mt-2">Overall Mastery</p>
                </div>

                {/* Completion bar */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-text-secondary">Completion</span>
                    <span className="font-medium text-text-primary tabular-nums">
                      {Math.round(overallCompletion)}%
                    </span>
                  </div>
                  <div
                    className="h-2 bg-surface-border rounded-full overflow-hidden"
                    role="progressbar"
                    aria-valuenow={overallCompletion}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label="Overall completion"
                  >
                    <motion.div
                      className="h-full bg-primary rounded-full"
                      initial={{ width: 0 }}
                      animate={{ width: `${overallCompletion}%` }}
                      transition={{ duration: 0.8, ease: 'easeOut' }}
                    />
                  </div>
                </div>

                {/* Average quiz score */}
                <div className="flex items-center justify-between border-t border-surface-border pt-4">
                  <span className="text-xs text-text-secondary">Avg. Quiz Score</span>
                  <span className="font-display font-semibold text-text-primary tabular-nums">
                    {Math.round(averageQuizScore)}%
                  </span>
                </div>
              </div>
            </Card>
          </motion.div>
        </div>
      </div>
    </motion.div>
  )
}
