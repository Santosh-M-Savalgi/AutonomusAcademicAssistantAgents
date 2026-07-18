import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { Card, SectionHeader, Badge, Skeleton } from '@/components/ui'
import { ProgressRing, TrendCard, AreaChart, LineChart, ChartContainer, AnimatedCounter } from '@/components/visualizations'
import { useDashboard, useTopicProgress, useWeakConcepts } from '@/services/learningApi'
import { BrainCircuit, TrendingUp, Target, AlertTriangle, Lightbulb, BookOpen, Sparkles, Zap, Star, ArrowRight } from 'lucide-react'
import { cn } from '@/utils/cn'
import { useNavigate } from 'react-router-dom'
import type { TrendDirection } from '@/components/visualizations/types'

/* ─── Helpers ──────────────────────────────────────────────── */

function getInsightTrend(current: number, threshold = 50): TrendDirection {
  if (current > threshold + 10) return 'up'
  if (current < threshold - 10) return 'down'
  return 'stable'
}

/* ─── Variants ─────────────────────────────────────────────── */

const stagger = {
  animate: {
    transition: { staggerChildren: 0.06 },
  },
}

const fadeUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
}

/* ─── Main Component ──────────────────────────────────────── */

export function LearningInsights() {
  const navigate = useNavigate()

  const { data: dashboard, isLoading: dashLoading } = useDashboard()
  const { data: topics, isLoading: topicsLoading } = useTopicProgress()

  const masteryScores = useMemo(() => {
    if (!topics) return {}
    return topics.reduce<Record<string, number>>((acc, t) => {
      acc[t.topic_id] = t.mastery_percentage
      return acc
    }, {})
  }, [topics])

  const currentTopicId = dashboard?.current_topic ?? undefined

  const {
    data: weakConcepts,
    isLoading: weakLoading,
  } = useWeakConcepts(masteryScores, currentTopicId ?? undefined)

  const isLoading = dashLoading || topicsLoading || weakLoading

  // ── Derived Insights ─────────────────────────────────────────

  const strongestTopics = useMemo(() => {
    if (!topics) return []
    return [...topics]
      .sort((a, b) => b.mastery_percentage - a.mastery_percentage)
      .slice(0, 3)
  }, [topics])

  const weakestTopics = useMemo(() => {
    if (!topics) return []
    return [...topics]
      .sort((a, b) => a.mastery_percentage - b.mastery_percentage)
      .filter((t) => t.quiz_attempts > 0)
      .slice(0, 3)
  }, [topics])

  const frequentlyFailed = useMemo(() => {
    if (!topics) return []
    return topics
      .filter((t) => t.average_score < 50 && t.quiz_attempts > 0)
      .slice(0, 3)
  }, [topics])

  const needsRevision = useMemo(() => {
    if (!topics) return []
    return topics.filter((t) => t.recommended_review).slice(0, 3)
  }, [topics])

  const overallMastery = dashboard?.overall_mastery ?? 0
  const avgQuizScore = dashboard?.average_quiz_score ?? 0
  const studyTime = dashboard?.daily_study_time_minutes ?? 0

  // Mock trend data from completion
  const progressTrend = useMemo(() => {
    const base = overallMastery
    return [
      { label: 'W1', value: Math.round(base * 0.55) },
      { label: 'W2', value: Math.round(base * 0.7) },
      { label: 'W3', value: Math.round(base * 0.85) },
      { label: 'W4', value: Math.round(base) },
    ]
  }, [overallMastery])

  if (isLoading) {
    return (
      <div className="space-y-4" aria-label="Loading insights">
        <Skeleton className="h-6 w-48" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} variant="rectangular" className="h-32 rounded-lg" />
          ))}
        </div>
        <Skeleton variant="rectangular" className="h-48 rounded-lg" />
      </div>
    )
  }

  return (
    <motion.div
      className="space-y-6"
      variants={stagger}
      initial="initial"
      animate="animate"
      aria-label="Learning insights"
    >
      {/* ═══ Overview Cards ═══ */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <motion.div variants={fadeUp}>
          <TrendCard
            label="Strongest Subject"
            value={strongestTopics[0]?.topic_name ?? 'N/A'}
            trend={getInsightTrend(strongestTopics[0]?.mastery_percentage ?? 0)}
            trendValue={`${Math.round(strongestTopics[0]?.mastery_percentage ?? 0)}%`}
            icon={<Star className="h-4 w-4" />}
            variant="secondary"
          />
        </motion.div>
        <motion.div variants={fadeUp}>
          <TrendCard
            label="Weakest Subject"
            value={weakestTopics[0]?.topic_name ?? 'N/A'}
            trend={weakestTopics.length > 0 ? 'down' : 'neutral'}
            trendValue={weakestTopics[0] ? `${Math.round(weakestTopics[0].mastery_percentage)}%` : undefined}
            icon={<AlertTriangle className="h-4 w-4" />}
          />
        </motion.div>
        <motion.div variants={fadeUp}>
          <TrendCard
            label="Learning Trend"
            value={overallMastery > 60 ? 'Improving' : 'Building Foundation'}
            trend={getInsightTrend(overallMastery, 50)}
            trendValue={`${Math.round(overallMastery)}%`}
            icon={<TrendingUp className="h-4 w-4" />}
            variant="primary"
          />
        </motion.div>
      </div>

      {/* ═══ Progress Trend Chart ═══ */}
      <motion.div variants={fadeUp}>
        <ChartContainer
          title="Learning Progression"
          description="Your mastery improvement over time"
          height={240}
        >
          <AreaChart
            data={progressTrend}
            height={180}
            color="#E8A93B"
          />
        </ChartContainer>
      </motion.div>

      {/* ═══ Two-Column Layout ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Strongest Subjects */}
        <motion.div variants={fadeUp}>
          <Card>
            <SectionHeader
              title="Strongest Subjects"
              description="Topics you've mastered"
            />
            <div className="mt-4 space-y-3">
              {strongestTopics.length > 0 ? (
                strongestTopics.map((topic, i) => (
                  <div key={topic.topic_id} className="flex items-center gap-3 p-2 rounded-md hover:bg-surface-hover transition-colors">
                    <div className="h-8 w-8 rounded-full bg-secondary-muted flex items-center justify-center text-secondary text-xs font-bold">
                      {i + 1}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-text-primary truncate">{topic.topic_name}</p>
                      <p className="text-xs text-text-muted">
                        Mastery: <span className="text-secondary font-medium">{Math.round(topic.mastery_percentage)}%</span>
                        {' · '}Quiz: {Math.round(topic.average_score)}%
                      </p>
                    </div>
                    <ProgressRing
                      value={topic.mastery_percentage}
                      size={44}
                      strokeWidth={4}
                      color="secondary"
                    />
                  </div>
                ))
              ) : (
                <div className="flex flex-col items-center py-8 text-center">
                  <Star className="h-8 w-8 text-text-muted mb-2" />
                  <p className="text-sm text-text-secondary">No mastered topics yet</p>
                </div>
              )}
            </div>
          </Card>
        </motion.div>

        {/* Weakest Subjects */}
        <motion.div variants={fadeUp}>
          <Card className="border-danger/20">
            <SectionHeader
              title="Weakest Subjects"
              description="Topics needing more practice"
            />
            <div className="mt-4 space-y-3">
              {weakestTopics.length > 0 ? (
                weakestTopics.map((topic) => (
                  <div key={topic.topic_id} className="flex items-center gap-3 p-2 rounded-md hover:bg-surface-hover transition-colors">
                    <AlertTriangle className="h-4 w-4 text-danger shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-text-primary truncate">{topic.topic_name}</p>
                      <p className="text-xs text-text-muted">
                        Mastery: <span className="text-danger font-medium">{Math.round(topic.mastery_percentage)}%</span>
                        {' · '}Attempts: {topic.quiz_attempts}
                      </p>
                    </div>
                    <button
                      onClick={() => navigate(`/lesson/${topic.topic_id}`)}
                      className="shrink-0 p-1 text-primary hover:text-primary-hover transition-colors"
                      aria-label={`Review ${topic.topic_name}`}
                    >
                      <ArrowRight className="h-4 w-4" />
                    </button>
                  </div>
                ))
              ) : (
                <div className="flex flex-col items-center py-8 text-center">
                  <Target className="h-8 w-8 text-text-muted mb-2" />
                  <p className="text-sm text-text-secondary">No weak topics detected</p>
                  <p className="text-xs text-text-muted mt-1">Great work staying on track!</p>
                </div>
              )}
            </div>
          </Card>
        </motion.div>

        {/* Frequently Failed */}
        {frequentlyFailed.length > 0 && (
          <motion.div variants={fadeUp}>
            <Card className="border-warning/20">
              <SectionHeader
                title="Frequently Failed"
                description="Topics with low quiz scores"
              />
              <div className="mt-4 space-y-3">
                {frequentlyFailed.map((topic) => (
                  <div key={topic.topic_id} className="flex items-center gap-3">
                    <div className="h-2 w-2 rounded-full bg-warning shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-text-primary truncate">{topic.topic_name}</p>
                      <p className="text-xs text-text-muted">
                        Avg score: <span className="text-warning">{Math.round(topic.average_score)}%</span>
                        {' · '}{topic.quiz_attempts} attempt{topic.quiz_attempts === 1 ? '' : 's'}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </motion.div>
        )}

        {/* Needs Revision */}
        {needsRevision.length > 0 && (
          <motion.div variants={fadeUp}>
            <Card>
              <SectionHeader
                title="Needs Revision"
                description="Topics recommended for review"
              />
              <div className="mt-4 space-y-3">
                {needsRevision.map((topic) => (
                  <div key={topic.topic_id} className="flex items-center gap-3 p-2 rounded-md hover:bg-surface-hover transition-colors cursor-pointer"
                    onClick={() => navigate(`/lesson/${topic.topic_id}`)}
                  >
                    <BookOpen className="h-4 w-4 text-primary shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-text-primary truncate">{topic.topic_name}</p>
                      <p className="text-xs text-text-muted">
                        Last studied: {topic.last_studied ? new Date(topic.last_studied).toLocaleDateString() : 'Unknown'}
                      </p>
                    </div>
                    <ArrowRight className="h-3.5 w-3.5 text-text-muted shrink-0" />
                  </div>
                ))}
              </div>
            </Card>
          </motion.div>
        )}
      </div>

      {/* ═══ Weak Concepts from Backend ═══ */}
      {weakConcepts && weakConcepts.weak_concepts.length > 0 && (
        <motion.div variants={fadeUp}>
          <Card className="border-primary/20">
            <SectionHeader
              title="AI-Detected Knowledge Gaps"
              description="Concepts the system identified as needing attention"
              icon={<BrainCircuit className="h-5 w-5 text-primary" />}
            />
            <div className="mt-4 space-y-3">
              {weakConcepts.weak_concepts.slice(0, 5).map((concept) => (
                <div key={concept.topic_id} className="flex items-center justify-between py-2 border-b border-surface-border last:border-0">
                  <div>
                    <p className="text-sm text-text-primary">{concept.topic_name}</p>
                    <p className="text-xs text-text-muted">
                      Confidence: {Math.round(concept.confidence * 100)}% · Attempts: {concept.attempts_count}
                    </p>
                  </div>
                  <Badge variant={concept.is_weak ? 'danger' : 'default'} size="sm">
                    {Math.round(concept.score)}%
                  </Badge>
                </div>
              ))}
            </div>
          </Card>
        </motion.div>
      )}

      {/* ═══ Improvement Summary ═══ */}
      <motion.div variants={fadeUp}>
        <Card className="bg-gradient-to-br from-surface to-surface-hover border-primary/10">
          <div className="flex items-start gap-3">
            <Lightbulb className="h-5 w-5 text-primary shrink-0 mt-0.5" />
            <div>
              <h3 className="font-display font-semibold text-text-primary text-sm mb-1">
                Insight Summary
              </h3>
              <p className="text-sm text-text-secondary leading-relaxed">
                {overallMastery > 60
                  ? `You're making solid progress with ${Math.round(overallMastery)}% overall mastery. `
                  : `You're building a foundation with ${Math.round(overallMastery)}% overall mastery. `}
                {avgQuizScore > 70
                  ? 'Your quiz performance is strong — keep it up! '
                  : avgQuizScore > 50
                    ? 'Your quiz scores are decent — focus on weaker areas to improve. '
                    : 'Focus on reviewing concepts before attempting quizzes. '}
                {strongestTopics[0] && `Your strongest area is "${strongestTopics[0].topic_name}". `}
                {weakestTopics[0] && `Spend extra time on "${weakestTopics[0].topic_name}".`}
              </p>
            </div>
          </div>
        </Card>
      </motion.div>
    </motion.div>
  )
}
