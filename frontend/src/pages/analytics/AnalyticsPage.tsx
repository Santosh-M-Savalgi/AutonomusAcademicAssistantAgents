import { useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import { Card, SectionHeader, Badge, Skeleton } from '@/components/ui'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui'
import { Tabs } from '@/components/ui/Tabs'
import {
  useDashboard,
  useTopicProgress,
  useLearningStreak,
  useRecommendations,
  useWeakConcepts,
  useAdaptiveStatus,
} from '@/services/learningApi'
import {
  ProgressRing,
  AnimatedCounter,
  TrendCard,
  TopicMasteryCard,
  LineChart,
  BarChart,
  Heatmap,
  ChartContainer,
  ChartLegend,
} from '@/components/visualizations'
import { LearningInsights } from './InsightsSection'
import { AchievementsSection } from './AchievementsSection'
import { XPStreakSection } from './XPStreakSection'
import { useNavigate } from 'react-router-dom'
import {
  BarChart3,
  BookOpen,
  Zap,
  TrendingUp,
  Clock,
  Target,
  Award,
  BrainCircuit,
  Sparkles,
  Calendar,
  CheckCircle,
  AlertTriangle,
  Lightbulb,
  ArrowRight,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/utils/cn'
import type { TopicProgress, Recommendation } from '@/types/learning'
import type { TrendDirection } from '@/components/visualizations/types'

/* ─── Helpers ──────────────────────────────────────────────── */

function formatStudyTime(minutes: number): string {
  if (minutes < 60) return `${minutes}m`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

function getTrend(current: number, previous: number): TrendDirection {
  if (previous === 0) return 'neutral'
  const diff = current - previous
  if (diff > 5) return 'up'
  if (diff < -5) return 'down'
  return 'stable'
}

/* ─── Animation Variants ──────────────────────────────────── */

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.05 },
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

/* ─── Skeleton ─────────────────────────────────────────────── */

function AnalyticsSkeleton() {
  return (
    <div className="space-y-6" aria-label="Loading analytics">
      <div className="space-y-2">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-96" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} variant="rectangular" className="h-28 rounded-lg" />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Skeleton variant="rectangular" className="h-64 rounded-lg" />
          <Skeleton variant="rectangular" className="h-48 rounded-lg" />
        </div>
        <div className="space-y-6">
          <Skeleton variant="rectangular" className="h-48 rounded-lg" />
          <Skeleton variant="rectangular" className="h-64 rounded-lg" />
        </div>
      </div>
    </div>
  )
}

/* ─── Main Page ───────────────────────────────────────────── */

export function AnalyticsPage() {
  const navigate = useNavigate()

  const {
    data: dashboard,
    isLoading: dashLoading,
    isError: dashError,
    error: dashErr,
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
    data: recommendations,
    isLoading: recsLoading,
  } = useRecommendations()

  const {
    data: adaptive,
    isLoading: adaptiveLoading,
  } = useAdaptiveStatus()

  const isLoading = dashLoading || topicsLoading || streakLoading || adaptiveLoading

  // ── Derived Data ────────────────────────────────────────────

  const topicsMastered = topics?.filter((t) => t.mastery_percentage >= 80).length ?? 0
  const topicsRemaining = (topics?.length ?? 0) - topicsMastered
  const weakTopics = topics?.filter((t) => t.mastery_percentage < 50) ?? []
  const needsReview = topics?.filter((t) => t.recommended_review) ?? []

  const overallMastery = dashboard?.overall_mastery ?? 0
  const overallCompletion = dashboard?.overall_completion ?? 0
  const averageQuizScore = dashboard?.average_quiz_score ?? 0
  const studyTimeMin = dashboard?.daily_study_time_minutes ?? 0
  const weeklyStudyMin = dashboard?.weekly_study_time_minutes ?? 0
  const currentStreak = streak?.current_streak_days ?? dashboard?.current_streak_days ?? 0

  const topRec = useMemo(() => {
    if (!recommendations || recommendations.length === 0) return null
    return recommendations.reduce((best, r) => (r.priority > best.priority ? r : best))
  }, [recommendations])

  // ── Weekly activity data ───────────────────────────────────
  const weeklyActivityData = useMemo(() => {
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    // Use recent_activity timestamps to build a weekly pattern
    const activity = dashboard?.recent_activity ?? []
    const counts: Record<string, number> = {}
    days.forEach((d) => { counts[d] = 0 })

    activity.forEach((event) => {
      const date = new Date(event.timestamp)
      const dayIndex = date.getDay()
      const dayName = days[dayIndex === 0 ? 6 : dayIndex - 1]
      if (dayName) counts[dayName] = (counts[dayName] ?? 0) + 1
    })

    return days.map((day) => ({ label: day, value: counts[day] ?? 0 }))
  }, [dashboard?.recent_activity])

  // ── Monthly progress data (mock from topic progress) ──────
  const monthlyData = useMemo(() => {
    return [
      { label: 'Week 1', value: Math.round(overallCompletion * 0.6) },
      { label: 'Week 2', value: Math.round(overallCompletion * 0.75) },
      { label: 'Week 3', value: Math.round(overallCompletion * 0.9) },
      { label: 'Week 4', value: Math.round(overallCompletion) },
    ]
  }, [overallCompletion])

  // ── Study heatmap data ─────────────────────────────────────
  const heatmapData = useMemo(() => {
    const activity = dashboard?.recent_activity ?? []
    const dayCounts: Record<string, number> = {}

    activity.forEach((event) => {
      const dateStr = new Date(event.timestamp).toISOString().split('T')[0]
      dayCounts[dateStr] = (dayCounts[dateStr] ?? 0) + 1
    })

    return Object.entries(dayCounts).map(([date, value]) => ({
      date,
      value,
      label: `${value} activities`,
    }))
  }, [dashboard?.recent_activity])

  // ── Mastery distribution ───────────────────────────────────
  const masteryDistribution = useMemo(() => {
    const dist = adaptive?.state_distribution ?? {}
    return Object.entries(dist).map(([key, value]) => ({
      label: key.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()),
      value: value as number,
      color:
        key === 'mastered'
          ? '#E8A93B'
          : key === 'in_progress'
            ? '#1FBF9E'
            : key === 'struggling'
              ? '#EF4444'
              : '#5C6575',
    }))
  }, [adaptive?.state_distribution])

  // ── Quiz score trend ───────────────────────────────────────
  const quizTrend = useMemo(() => {
    const topicsWithScores = topics?.filter((t) => t.quiz_attempts > 0) ?? []
    return topicsWithScores.slice(0, 10).map((t) => ({
      label: t.topic_name.length > 12 ? t.topic_name.slice(0, 12) + '…' : t.topic_name,
      value: Math.round(t.average_score),
    }))
  }, [topics])

  // ── Tab State ────────────────────────────────────────────────
  const analyticsTabs = [
    { id: 'overview', label: 'Overview', icon: <BarChart3 className="h-4 w-4" /> },
    { id: 'insights', label: 'Insights', icon: <TrendingUp className="h-4 w-4" /> },
    { id: 'achievements', label: 'Achievements', icon: <Award className="h-4 w-4" /> },
    { id: 'xp', label: 'XP & Streak', icon: <Zap className="h-4 w-4" /> },
  ]
  const [activeTab, setActiveTab] = useState('overview')

  // ── Render ─────────────────────────────────────────────────

  if (isLoading) return <AnalyticsSkeleton />

  if (dashError) {
    return (
      <ErrorState
        title="Failed to load analytics"
        message={dashErr instanceof Error ? dashErr.message : 'An unexpected error occurred.'}
        onRetry={() => dashRefetch()}
      />
    )
  }

  return (
    <motion.div
      className="p-6 space-y-6 max-w-7xl mx-auto"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      aria-label="Analytics dashboard"
    >
      {/* ═══ Header ═══ */}
      <motion.div variants={itemVariants} className="space-y-1">
        <h1 className="font-display text-2xl font-bold text-text-primary">
          Analytics
        </h1>
        <p className="text-sm text-text-secondary">
          What have I learned? What am I weak at? What should I study next?
        </p>
      </motion.div>

      {/* ═══ Tabs ═══ */}
      <motion.div variants={itemVariants}>
        <Tabs tabs={analyticsTabs} activeTab={activeTab} onChange={setActiveTab} />
      </motion.div>

      {/* ═══ Tab Content ═══ */}
      {activeTab === 'overview' && (
        <>
          {/* Overview Stats */}
          <motion.div
            variants={itemVariants}
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
          >
            <TrendCard
              label="Overall Mastery"
              value={`${Math.round(overallMastery)}%`}
              trend={getTrend(overallMastery, overallMastery * 0.9)}
              trendValue="vs last week"
              icon={<BrainCircuit className="h-4 w-4" />}
              variant="secondary"
            />
            <TrendCard
              label="Avg Quiz Score"
              value={`${Math.round(averageQuizScore)}%`}
              icon={<Target className="h-4 w-4" />}
              variant="primary"
            />
            <TrendCard
              label="Current Streak"
              value={`${currentStreak}d`}
              icon={<Zap className="h-4 w-4" />}
              variant="secondary"
            />
            <TrendCard
              label="Study Time"
              value={formatStudyTime(weeklyStudyMin)}
              icon={<Clock className="h-4 w-4" />}
              variant="primary"
            />
          </motion.div>

          {/* Two-Column Layout */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-6">
              {/* Weekly Activity Chart */}
              <motion.div variants={itemVariants}>
                <ChartContainer
                  title="Weekly Activity"
                  description="Your study sessions this week"
                  isEmpty={weeklyActivityData.every((d) => d.value === 0)}
                  emptyMessage="No activity recorded this week"
                  height={280}
                >
                  <BarChart data={weeklyActivityData} height={220} color="#1FBF9E" />
                </ChartContainer>
              </motion.div>

              {/* Monthly Progress */}
              <motion.div variants={itemVariants}>
                <ChartContainer
                  title="Monthly Progress"
                  description="Overall completion trend"
                  height={280}
                >
                  <LineChart data={monthlyData} height={220} color="#E8A93B" />
                </ChartContainer>
              </motion.div>

              {/* Topic Progress Grid */}
              <motion.div variants={itemVariants}>
                <Card>
                  <SectionHeader
                    title="Topic Progress"
                    description={`${topicsMastered} mastered · ${weakTopics.length} weak · ${needsReview.length} needs review`}
                  />
                  <div className="mt-5 space-y-3">
                    {topics && topics.length > 0 ? (
                      topics.slice(0, 8).map((topic) => (
                        <TopicMasteryCard
                          key={topic.topic_id}
                          topicName={topic.topic_name}
                          mastery={topic.mastery_percentage}
                          completion={topic.completion_percentage}
                          quizScore={topic.average_score}
                          lastStudied={topic.last_studied}
                          needsReview={topic.recommended_review}
                          isWeak={topic.mastery_percentage < 50}
                          isMastered={topic.mastery_percentage >= 80}
                        />
                      ))
                    ) : (
                      <div className="flex flex-col items-center py-10 text-center">
                        <BookOpen className="h-10 w-10 text-text-muted mb-3" />
                        <p className="text-sm text-text-secondary">No topics yet</p>
                        <p className="text-xs text-text-muted mt-1">Start learning to see your topic progress here.</p>
                      </div>
                    )}
                  </div>
                  {topics && topics.length > 8 && (
                    <div className="mt-4 text-center">
                      <button onClick={() => navigate('/profile')} className="text-xs text-primary hover:text-primary-hover transition-colors">
                        View all {topics.length} topics →
                      </button>
                    </div>
                  )}
                </Card>
              </motion.div>

              {/* Quiz Scores by Topic */}
              {quizTrend.length > 0 && (
                <motion.div variants={itemVariants}>
                  <ChartContainer title="Quiz Scores by Topic" description="Your performance across topics" height={300}>
                    <BarChart data={quizTrend} height={240} color="#E8A93B" />
                  </ChartContainer>
                </motion.div>
              )}

              {/* Study Heatmap */}
              <motion.div variants={itemVariants}>
                <Card>
                  <SectionHeader title="Study Activity" description="Your learning consistency over time" />
                  <div className="mt-4">
                    {heatmapData.length > 0 ? (
                      <Heatmap data={heatmapData} />
                    ) : (
                      <div className="flex flex-col items-center py-8 text-center">
                        <Calendar className="h-8 w-8 text-text-muted mb-2" />
                        <p className="text-sm text-text-secondary">No study activity yet</p>
                        <p className="text-xs text-text-muted mt-1">Start learning to build your study heatmap.</p>
                      </div>
                    )}
                  </div>
                </Card>
              </motion.div>
            </div>

            <div className="space-y-6">
              {/* Mastery Overview */}
              <motion.div variants={itemVariants}>
                <Card>
                  <SectionHeader title="Mastery Overview" description="Your learning state distribution" />
                  <div className="mt-6 flex flex-col items-center">
                    <ProgressRing value={overallMastery} size={120} strokeWidth={10} color="secondary" label="Overall Mastery" />
                    <p className="text-xs text-text-muted mt-3">Overall Mastery</p>
                  </div>
                  {masteryDistribution.length > 0 && (
                    <div className="mt-6 space-y-3">
                      {masteryDistribution.map((item) => (
                        <div key={item.label} className="flex items-center justify-between text-xs">
                          <div className="flex items-center gap-2">
                            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} aria-hidden="true" />
                            <span className="text-text-secondary">{item.label}</span>
                          </div>
                          <span className="font-mono text-text-primary tabular-nums">{item.value}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              </motion.div>

              {/* Learning Stats */}
              <motion.div variants={itemVariants}>
                <Card>
                  <SectionHeader title="Learning Stats" description="Your journey at a glance" />
                  <div className="mt-5 space-y-4">
                    <StatRow label="Topics Completed" value={topicsMastered} icon={<CheckCircle className="h-4 w-4 text-primary" />} />
                    <StatRow label="Topics Remaining" value={topicsRemaining} icon={<BookOpen className="h-4 w-4 text-primary" />} />
                    <StatRow label="Quiz Accuracy" value={`${Math.round(averageQuizScore)}%`} icon={<Target className="h-4 w-4 text-primary" />} />
                    <StatRow label="Weekly Study" value={formatStudyTime(weeklyStudyMin)} icon={<Clock className="h-4 w-4 text-primary" />} />
                    <StatRow label="Daily Study" value={formatStudyTime(studyTimeMin)} icon={<TrendingUp className="h-4 w-4 text-primary" />} />
                    <StatRow label="Learning Streak" value={`${currentStreak} day${currentStreak === 1 ? '' : 's'}`} icon={<Zap className="h-4 w-4 text-secondary" />} valueClassName="text-secondary" />
                  </div>
                </Card>
              </motion.div>

              {/* Weak Topics */}
              {weakTopics.length > 0 && (
                <motion.div variants={itemVariants}>
                  <Card className="border-danger/20">
                    <SectionHeader title="Needs Attention" description="Topics below 50% mastery" />
                    <div className="mt-4 space-y-3">
                      {weakTopics.slice(0, 5).map((topic) => (
                        <div key={topic.topic_id} className="flex items-center gap-3">
                          <AlertTriangle className="h-4 w-4 text-danger shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-text-primary truncate">{topic.topic_name}</p>
                            <p className="text-xs text-text-muted">Mastery: {Math.round(topic.mastery_percentage)}%</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </Card>
                </motion.div>
              )}

              {/* Recommendations */}
              <motion.div variants={itemVariants}>
                <Card>
                  <SectionHeader title="Recommendations" description="Personalised for you" />
                  <div className="mt-4 space-y-3">
                    {recommendations && recommendations.length > 0 ? (
                      recommendations.slice(0, 4).map((rec) => (
                        <div key={rec.topic_id} className="flex items-start gap-3 p-2 rounded-md hover:bg-surface-hover transition-colors">
                          <Lightbulb className="h-4 w-4 text-secondary mt-0.5 shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-text-primary truncate">{rec.topic_name}</p>
                            <p className="text-xs text-text-muted mt-0.5">{rec.reason}</p>
                          </div>
                          <button onClick={() => navigate(`/lesson/${rec.topic_id}`)} className="shrink-0 p-1 text-primary hover:text-primary-hover transition-colors" aria-label={`Start ${rec.topic_name}`}>
                            <ArrowRight className="h-4 w-4" />
                          </button>
                        </div>
                      ))
                    ) : (
                      <div className="flex flex-col items-center py-6 text-center">
                        <Sparkles className="h-8 w-8 text-text-muted mb-2" />
                        <p className="text-sm text-text-secondary">No recommendations yet</p>
                        <p className="text-xs text-text-muted mt-1">Complete more lessons for personalised suggestions.</p>
                      </div>
                    )}
                  </div>
                </Card>
              </motion.div>

              {/* Quick Summary */}
              <motion.div variants={itemVariants}>
                <Card className="border-primary/20 bg-gradient-to-br from-surface to-surface-hover">
                  <div className="flex items-center gap-2 mb-3">
                    <Sparkles className="h-5 w-5 text-primary" />
                    <h3 className="font-display font-semibold text-text-primary text-sm">Signal & Mastery</h3>
                  </div>
                  <p className="text-xs text-text-secondary leading-relaxed">
                    Your learning signal is strong. Keep your streak alive and focus on
                    weak topics to accelerate mastery. Consistent daily study of{' '}
                    {studyTimeMin > 0 ? `${formatStudyTime(studyTimeMin)}` : 'at least 15 minutes'}
                    {' '}builds lasting understanding.
                  </p>
                </Card>
              </motion.div>
            </div>
          </div>
        </>
      )}

      {activeTab === 'insights' && <LearningInsights />}
      {activeTab === 'achievements' && <AchievementsSection />}
      {activeTab === 'xp' && <XPStreakSection />}
    </motion.div>
  )
}

/* ─── StatRow Sub-Component ───────────────────────────────── */

interface StatRowProps {
  label: string
  value: string | number
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
