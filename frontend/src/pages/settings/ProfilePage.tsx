import { useAuth } from '@/contexts/AuthContext'
import { motion } from 'framer-motion'
import {
  Card,
  Button,
  Badge,
  Progress,
  SectionHeader,
  Avatar,
  StatCard,
} from '@/components/ui'
import { Skeleton, LoadingState, ErrorState } from '@/components/ui'
import {
  useDashboard,
  useTopicProgress,
  useLearningStreak,
  useAdaptiveStatus,
  useLearningPath,
} from '@/services/learningApi'
import {
  BookOpen,
  Zap,
  TrendingUp,
  Clock,
  Target,
  Award,
  BrainCircuit,
  Calendar,
  CheckCircle,
  BarChart3,
  Star,
  Sparkles,
  Shield,
  ChevronRight,
  Medal,
  Trophy,
  Flame,
  Lightbulb,
  Activity,
  ArrowUp,
} from 'lucide-react'
import { AchievementsSection } from '@/pages/analytics/AchievementsSection'
import { cn } from '@/utils/cn'
import { formatDate, formatTime } from '@/utils/cn'

// ─── Animation variants ─────────────────────────────────────

const fadeUp = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
}

const stagger = {
  animate: {
    transition: { staggerChildren: 0.06 },
  },
}

// ─── Helpers ────────────────────────────────────────────────

function getInitials(username: string): string {
  return username
    .split(' ')
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
}

function relativeTime(dateStr: string): string {
  const now = Date.now()
  const then = new Date(dateStr).getTime()
  const diffMs = now - then
  const diffMin = Math.floor(diffMs / 60000)

  if (diffMin < 1) return 'Just now'
  if (diffMin < 60) return `${diffMin}m ago`

  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`

  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 30) return `${diffDay}d ago`

  return formatDate(dateStr)
}

function eventIcon(type: string) {
  switch (type) {
    case 'lesson_completed':
      return <BookOpen className="h-3.5 w-3.5 text-primary" />
    case 'quiz_completed':
      return <BrainCircuit className="h-3.5 w-3.5 text-secondary" />
    case 'topic_started':
      return <Target className="h-3.5 w-3.5 text-primary" />
    case 'topic_mastered':
      return <Award className="h-3.5 w-3.5 text-secondary" />
    default:
      return <Sparkles className="h-3.5 w-3.5 text-text-muted" />
  }
}

const stateColors: Record<string, string> = {
  not_started: 'bg-text-muted',
  in_progress: 'bg-primary',
  mastered: 'bg-secondary',
  struggling: 'bg-danger',
}

const stateLabels: Record<string, string> = {
  not_started: 'Not Started',
  in_progress: 'In Progress',
  mastered: 'Mastered',
  struggling: 'Struggling',
}

// ─── Loading skeleton ───────────────────────────────────────

function ProfilePageSkeleton() {
  return (
    <div className="space-y-6" aria-label="Loading profile">
      {/* Header skeleton */}
      <div className="flex flex-col sm:flex-row items-center sm:items-end gap-6 pb-8 border-b border-surface-border">
        <Skeleton variant="circular" className="h-24 w-24" />
        <div className="flex-1 space-y-3 text-center sm:text-left">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-3 w-28" />
        </div>
      </div>

      {/* Stats skeleton */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} variant="rectangular" className="h-24 rounded-lg" />
        ))}
      </div>

      {/* Two-column skeleton */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Skeleton variant="rectangular" className="h-32 rounded-lg" />
          <Skeleton variant="rectangular" className="h-64 rounded-lg" />
          <Skeleton variant="rectangular" className="h-48 rounded-lg" />
        </div>
        <div className="space-y-6">
          <Skeleton variant="rectangular" className="h-48 rounded-lg" />
          <Skeleton variant="rectangular" className="h-36 rounded-lg" />
          <Skeleton variant="rectangular" className="h-40 rounded-lg" />
        </div>
      </div>
    </div>
  )
}

// ─── Main Component ─────────────────────────────────────────

export function ProfilePage() {
  const { user } = useAuth()

  const {
    data: dashboard,
    isLoading: dashLoading,
    isError: dashError,
    refetch: dashRefetch,
  } = useDashboard()

  const {
    data: topics,
    isLoading: topicsLoading,
  } = useTopicProgress()

  const {
    data: streak,
    isLoading: streakLoading,
  } = useLearningStreak()

  const {
    data: adaptive,
    isLoading: adaptiveLoading,
  } = useAdaptiveStatus()

  const isLoading = dashLoading || topicsLoading || streakLoading || adaptiveLoading

  // ── Derived values ──────────────────────────────────────────

  const topicsMastered = topics?.filter((t) => t.mastery_percentage >= 80).length ?? 0
  const lessonsCompleted = dashboard?.recent_sessions ?? 0
  const currentStreak = streak?.current_streak_days ?? dashboard?.current_streak_days ?? 0
  const studyHours = dashboard?.daily_study_time_minutes ?? 0
  const masteryRate = dashboard?.overall_mastery ?? 0

  const displayTopics = topics?.slice(0, 6) ?? []
  const hasMoreTopics = (topics?.length ?? 0) > 6

  const activities = dashboard?.recent_activity ?? []

  // ── Render ─────────────────────────────────────────────────

  if (isLoading) return <ProfilePageSkeleton />

  if (dashError) {
    return (
      <ErrorState
        title="Failed to load profile"
        message="We couldn't fetch your profile data. Please try again."
        onRetry={() => dashRefetch()}
      />
    )
  }

  const username = user?.username ?? 'Student'
  const email = user?.email ?? ''
  const memberSince = user?.id ? 'Member' : ''

  return (
    <main className="space-y-8" aria-label="Student profile page">
      {/* ── Profile Header ─────────────────────────────────── */}
      <motion.section
        variants={fadeUp}
        initial="initial"
        animate="animate"
        transition={{ duration: 0.4 }}
        className="flex flex-col sm:flex-row items-center sm:items-end gap-6 pb-8 border-b border-surface-border"
        aria-label="Profile header"
      >
        <Avatar
          name={username}
          size="lg"
          className="h-24 w-24 text-2xl"
          aria-label={`${username}'s avatar`}
        />

        <div className="flex-1 text-center sm:text-left space-y-2">
          <h1
            className="font-display text-3xl font-bold text-text-primary"
            style={{ fontFamily: "'Cabinet Grotesk', sans-serif" }}
          >
            {username}
          </h1>
          <p className="text-text-secondary text-sm">{email}</p>
          <div className="flex items-center justify-center sm:justify-start gap-3 flex-wrap">
            {memberSince && (
              <span className="text-xs text-text-muted flex items-center gap-1">
                <Calendar className="h-3 w-3" />
                {memberSince}
              </span>
            )}
            <Badge variant="secondary" size="sm" className="gap-1">
              <Award className="h-3 w-3" />
              Level 1
            </Badge>
          </div>
        </div>

        <Button
          variant="ghost"
          size="sm"
          aria-label="Edit profile"
          onClick={() => {}}
          className="shrink-0"
        >
          Edit Profile
        </Button>
      </motion.section>

      {/* ── Stats Row ──────────────────────────────────────── */}
      <motion.section
        variants={stagger}
        initial="initial"
        animate="animate"
        className="grid grid-cols-2 lg:grid-cols-5 gap-4"
        aria-label="Learning statistics overview"
      >
        <motion.div variants={fadeUp}>
          <StatCard
            label="Topics Mastered"
            value={topicsMastered}
            icon={<CheckCircle className="h-4 w-4" />}
            variant="secondary"
          />
        </motion.div>
        <motion.div variants={fadeUp}>
          <StatCard
            label="Lessons Completed"
            value={lessonsCompleted}
            icon={<BookOpen className="h-4 w-4" />}
            variant="primary"
          />
        </motion.div>
        <motion.div variants={fadeUp}>
          <StatCard
            label="Current Streak"
            value={`${currentStreak}d`}
            icon={<Zap className="h-4 w-4" />}
            variant="secondary"
          />
        </motion.div>
        <motion.div variants={fadeUp}>
          <StatCard
            label="Study Hours"
            value={formatTime(studyHours)}
            icon={<Clock className="h-4 w-4" />}
            variant="primary"
          />
        </motion.div>
        <motion.div variants={fadeUp}>
          <StatCard
            label="Mastery Rate"
            value={`${Math.round(masteryRate)}%`}
            icon={<BrainCircuit className="h-4 w-4" />}
            variant="secondary"
          />
        </motion.div>
      </motion.section>

      {/* ── Two-Column Layout ──────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ── Left Column (2/3) ──────────────────────────── */}
        <div className="lg:col-span-2 space-y-6">
          {/* Current Course */}
          <motion.div variants={fadeUp} initial="initial" animate="animate" transition={{ delay: 0.1 }}>
            <Card aria-label="Current course">
              {dashboard?.current_course ? (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs text-text-muted font-medium uppercase tracking-wider">
                        Current Course
                      </p>
                      <h3 className="font-display text-lg font-semibold text-text-primary mt-1">
                        {dashboard.current_course}
                      </h3>
                    </div>
                    <Badge
                      variant="secondary"
                      size="md"
                      className="gap-1.5"
                    >
                      <Star className="h-3.5 w-3.5" />
                      {Math.round(dashboard.overall_mastery ?? 0)}% Mastery
                    </Badge>
                  </div>

                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-text-secondary">Overall Completion</span>
                      <span className="font-mono text-text-primary tabular-nums">
                        {Math.round(dashboard.overall_completion ?? 0)}%
                      </span>
                    </div>
                    <Progress
                      value={dashboard.overall_completion ?? 0}
                      variant="primary"
                      size="md"
                    />
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center py-8 text-center">
                  <BookOpen className="h-10 w-10 text-text-muted mb-3" />
                  <h3 className="font-display text-base font-semibold text-text-primary">
                    No active course
                  </h3>
                  <p className="text-sm text-text-secondary mt-1 max-w-xs">
                    Enroll in a course to start tracking your learning progress.
                  </p>
                </div>
              )}
            </Card>
          </motion.div>

          {/* Learning Progress */}
          <motion.div variants={fadeUp} initial="initial" animate="animate" transition={{ delay: 0.15 }}>
            <SectionHeader
              title="Learning Progress"
              icon={<BarChart3 className="h-5 w-5 text-primary" />}
              action={
                hasMoreTopics && (
                  <Button variant="ghost" size="sm" className="gap-1">
                    View all
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                )
              }
            />

            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
              {displayTopics.length > 0 ? (
                displayTopics.map((topic) => (
                  <Card key={topic.topic_id} padding="sm" hover aria-label={`${topic.topic_name} progress`}>
                    <div className="space-y-3">
                      {/* Topic header */}
                      <div className="flex items-start justify-between gap-2">
                        <h4 className="font-display text-sm font-semibold text-text-primary truncate">
                          {topic.topic_name}
                        </h4>
                        {topic.recommended_review && (
                          <Badge variant="danger" size="sm" className="shrink-0">
                            Review recommended
                          </Badge>
                        )}
                      </div>

                      {/* Completion */}
                      <div className="space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-text-muted">Completion</span>
                          <span className="font-mono text-text-secondary tabular-nums">
                            {Math.round(topic.completion_percentage)}%
                          </span>
                        </div>
                        <Progress
                          value={topic.completion_percentage}
                          size="sm"
                          variant="primary"
                        />
                      </div>

                      {/* Details row */}
                      <div className="flex items-center justify-between text-xs text-text-muted">
                        <span>
                          Mastery:{' '}
                          <span className="font-mono text-secondary tabular-nums">
                            {Math.round(topic.mastery_percentage)}%
                          </span>
                        </span>
                        <span>Quiz attempts: {topic.quiz_attempts}</span>
                      </div>

                      {topic.last_studied && (
                        <p className="text-xs text-text-muted">
                          Last studied:{' '}
                          <span className="text-text-secondary">
                            {relativeTime(topic.last_studied)}
                          </span>
                        </p>
                      )}
                    </div>
                  </Card>
                ))
              ) : (
                <div className="col-span-2">
                  <div className="flex flex-col items-center py-12 text-center">
                    <BarChart3 className="h-10 w-10 text-text-muted mb-3" />
                    <h3 className="font-display text-base font-semibold text-text-primary">
                      No progress yet
                    </h3>
                    <p className="text-sm text-text-secondary mt-1">
                      Start learning to see your progress here.
                    </p>
                  </div>
                </div>
              )}
            </div>
          </motion.div>

          {/* Recent Activity */}
          <motion.div variants={fadeUp} initial="initial" animate="animate" transition={{ delay: 0.2 }}>
            <SectionHeader title="Recent Activity" />

            <Card className="mt-4" aria-label="Recent activity timeline">
              {activities.length > 0 ? (
                <ul className="space-y-0" role="list">
                  {activities.map((event, idx) => (
                    <li
                      key={`${event.timestamp}-${idx}`}
                      className={cn(
                        'flex items-start gap-4 py-4',
                        idx !== activities.length - 1 && 'border-b border-surface-border'
                      )}
                    >
                      {/* Dot indicator */}
                      <div className="relative flex items-center justify-center mt-0.5">
                        <div
                          className={cn(
                            'h-2 w-2 rounded-full',
                            event.event_type === 'lesson_completed' && 'bg-primary',
                            event.event_type === 'quiz_completed' && 'bg-secondary',
                            event.event_type === 'topic_mastered' && 'bg-secondary',
                            event.event_type === 'topic_started' && 'bg-primary',
                            !['lesson_completed', 'quiz_completed', 'topic_mastered', 'topic_started'].includes(
                              event.event_type
                            ) && 'bg-text-muted'
                          )}
                        />
                      </div>

                      {/* Content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-text-primary capitalize">
                            {event.event_type.replace(/_/g, ' ')}
                          </span>
                          <span className="text-xs text-text-muted">{relativeTime(event.timestamp)}</span>
                        </div>
                        {event.topic && (
                          <p className="text-sm text-text-secondary mt-0.5 truncate">
                            {event.topic}
                          </p>
                        )}
                      </div>

                      {/* Icon */}
                      <div className="shrink-0 mt-0.5">{eventIcon(event.event_type)}</div>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="flex flex-col items-center py-10 text-center">
                  <Clock className="h-8 w-8 text-text-muted mb-2" />
                  <h3 className="font-display text-sm font-semibold text-text-primary">
                    No recent activity
                  </h3>
                  <p className="text-xs text-text-secondary mt-1">
                    Your recent learning activity will appear here.
                  </p>
                </div>
              )}
            </Card>
          </motion.div>
        </div>

        {/* ── Right Column (1/3) ─────────────────────────── */}
        <div className="space-y-6">
          {/* Learning Statistics */}
          <motion.div variants={fadeUp} initial="initial" animate="animate" transition={{ delay: 0.15 }}>
            <Card aria-label="Learning statistics">
              <SectionHeader title="Learning Statistics" />
              <dl className="mt-5 space-y-5">
                <StatRow
                  label="Average Quiz Score"
                  value={`${Math.round(dashboard?.average_quiz_score ?? 0)}%`}
                  icon={<Target className="h-4 w-4 text-primary" />}
                />
                <StatRow
                  label="Weekly Study Time"
                  value={formatTime(dashboard?.weekly_study_time_minutes ?? 0)}
                  icon={<Clock className="h-4 w-4 text-primary" />}
                />
                <StatRow
                  label="Daily Study Time"
                  value={formatTime(dashboard?.daily_study_time_minutes ?? 0)}
                  icon={<TrendingUp className="h-4 w-4 text-primary" />}
                />
                <StatRow
                  label="Overall Completion"
                  value={`${Math.round(dashboard?.overall_completion ?? 0)}%`}
                  icon={<CheckCircle className="h-4 w-4 text-primary" />}
                />
                <StatRow
                  label="Overall Mastery"
                  value={`${Math.round(dashboard?.overall_mastery ?? 0)}%`}
                  icon={<BrainCircuit className="h-4 w-4 text-secondary" />}
                  valueClassName="text-secondary"
                />
              </dl>
            </Card>
          </motion.div>

          {/* Streak Card */}
          <motion.div variants={fadeUp} initial="initial" animate="animate" transition={{ delay: 0.2 }}>
            <Card
              className="border-secondary/20"
              aria-label="Learning streak"
            >
              <div className="text-center py-2">
                {/* Streak active indicator */}
                <div className="flex items-center justify-center gap-2 mb-4">
                  <span
                    className={cn(
                      'h-2 w-2 rounded-full',
                      streak?.streak_active ? 'bg-green-400 shadow-[0_0_8px_rgba(74,222,128,0.5)]' : 'bg-text-muted'
                    )}
                    aria-label={streak?.streak_active ? 'Streak active' : 'Streak inactive'}
                  />
                  <span className="text-xs font-medium text-text-secondary uppercase tracking-wider">
                    {streak?.streak_active ? 'Active' : 'Inactive'}
                  </span>
                </div>

                {/* Large streak number */}
                <span className="font-display text-5xl font-bold text-text-primary tabular-nums">
                  {currentStreak}
                </span>
                <p className="font-display text-base font-medium text-text-secondary mt-1">
                  Current Streak
                </p>

                {/* Longest streak */}
                <div className="mt-6 pt-4 border-t border-surface-border">
                  <div className="flex items-center justify-center gap-2 text-sm">
                    <Zap className="h-4 w-4 text-secondary" />
                    <span className="text-text-muted">
                      Longest:{' '}
                      <span className="font-semibold text-text-secondary tabular-nums">
                        {streak?.longest_streak_days ?? 0} days
                      </span>
                    </span>
                  </div>
                </div>
              </div>
            </Card>
          </motion.div>

          {/* Mastery Overview */}
          <motion.div variants={fadeUp} initial="initial" animate="animate" transition={{ delay: 0.25 }}>
            <Card aria-label="Mastery overview">
              <SectionHeader title="Mastery Overview" />

              {adaptive && adaptive.state_distribution && Object.keys(adaptive.state_distribution).length > 0 ? (
                <div className="mt-5 space-y-3">
                  {Object.entries(adaptive.state_distribution).map(([state, count]) => (
                    <div key={state} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-text-secondary capitalize">
                          {stateLabels[state] ?? state.replace(/_/g, ' ')}
                        </span>
                        <span className="font-mono text-text-primary tabular-nums">{count}</span>
                      </div>
                      <div className="h-2 bg-surface-border rounded-full overflow-hidden">
                        <div
                          className={cn(
                            'h-full rounded-full transition-all duration-500',
                            stateColors[state] ?? 'bg-text-muted'
                          )}
                          style={{
                            width: `${adaptive.total_topics > 0 ? (count / adaptive.total_topics) * 100 : 0}%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}

                  {/* Total summary */}
                  <div className="pt-3 mt-3 border-t border-surface-border flex items-center justify-between text-xs text-text-muted">
                    <span>Total Topics</span>
                    <span className="font-mono text-text-secondary tabular-nums">
                      {adaptive.total_topics}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center py-8 text-center">
                  <Shield className="h-8 w-8 text-text-muted mb-2" />
                  <h3 className="font-display text-sm font-semibold text-text-primary">
                    No mastery data
                  </h3>
                  <p className="text-xs text-text-secondary mt-1">
                    Complete lessons and quizzes to build your mastery profile.
                  </p>
                </div>
              )}
            </Card>
          </motion.div>
        </div>
      </div>

      {/* ── Achievements Section ────────────────────────────────── */}
      <motion.section
        variants={fadeUp}
        initial="initial"
        animate="animate"
        className="pt-4 border-t border-surface-border"
        aria-label="Achievements"
      >
        <AchievementsSection />
      </motion.section>

      {/* ── Improvement Summary ──────────────────────────────── */}
      <motion.div
        variants={fadeUp}
        initial="initial"
        animate="animate"
        transition={{ delay: 0.3 }}
      >
        <Card className="bg-gradient-to-br from-surface to-surface-hover border-primary/10">
          <div className="flex items-start gap-3">
            <Lightbulb className="h-5 w-5 text-primary shrink-0 mt-0.5" />
            <div>
              <h3 className="font-display font-semibold text-text-primary text-sm mb-1">
                Weekly Summary
              </h3>
              <p className="text-sm text-text-secondary leading-relaxed">
                {lessonsCompleted === 0
                  ? "You haven't started learning yet. Pick a topic to begin your journey!"
                  : `You've completed ${lessonsCompleted} lesson${lessonsCompleted === 1 ? '' : 's'} and mastered ${topicsMastered} topic${topicsMastered === 1 ? '' : 's'}. ` +
                    (currentStreak > 0
                      ? `Your ${currentStreak}-day streak is active — keep the momentum! `
                      : 'Start a new streak today! ') +
                    (dashboard?.average_quiz_score && dashboard.average_quiz_score > 70
                      ? 'Quiz performance is strong — great understanding of the material.'
                      : dashboard?.average_quiz_score && dashboard.average_quiz_score > 50
                        ? 'Quiz scores are improving — review weaker areas to boost comprehension.'
                        : 'Focus on understanding concepts before moving to quizzes.')}
              </p>
            </div>
          </div>
        </Card>
      </motion.div>

      {/* ── Recent Improvements ───────────────────────────────── */}
      <motion.div
        variants={fadeUp}
        initial="initial"
        animate="animate"
        transition={{ delay: 0.35 }}
      >
        <Card>
          <SectionHeader
            title="Recent Improvements"
            description="Your latest learning achievements"
          />

          <div className="mt-4 space-y-3">
            {activities.length > 0 ? (
              activities.slice(0, 5).map((event, i) => (
                <div key={`${event.timestamp}-${i}`} className="flex items-start gap-3 py-2 border-b border-surface-border last:border-0">
                  {eventIcon(event.event_type)}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text-primary capitalize">
                      {event.event_type.replace(/_/g, ' ')}
                    </p>
                    {event.topic && (
                      <p className="text-xs text-text-muted">{event.topic}</p>
                    )}
                  </div>
                  <time className="text-xs text-text-muted whitespace-nowrap">
                    {relativeTime(event.timestamp)}
                  </time>
                </div>
              ))
            ) : (
              <div className="flex flex-col items-center py-6 text-center">
                <Activity className="h-8 w-8 text-text-muted mb-2" />
                <p className="text-sm text-text-secondary">No recent improvements</p>
                <p className="text-xs text-text-muted mt-1">
                  Complete lessons and quizzes to see your progress.
                </p>
              </div>
            )}
          </div>
        </Card>
      </motion.div>
    </main>
  )
}

// ─── StatRow sub-component ──────────────────────────────────

interface StatRowProps {
  label: string
  value: string
  icon: React.ReactNode
  valueClassName?: string
}

function StatRow({ label, value, icon, valueClassName }: StatRowProps) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-sm text-text-secondary">{label}</span>
      </div>
      <span
        className={cn(
          'font-display font-semibold text-text-primary tabular-nums text-sm',
          valueClassName
        )}
      >
        {value}
      </span>
    </div>
  )
}
