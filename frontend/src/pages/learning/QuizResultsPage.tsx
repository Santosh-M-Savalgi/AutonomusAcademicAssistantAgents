import { useEffect } from 'react'
import { useLocation, useNavigate, useParams, Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Card, Button, Badge, SectionHeader } from '@/components/ui'
import { useEvaluateQuiz } from '@/services/learningApi'
import {
  CheckCircle,
  XCircle,
  Target,
  TrendingUp,
  BookOpen,
  ArrowLeft,
  ArrowRight,
  RotateCcw,
  AlertTriangle,
  Lightbulb,
  BrainCircuit,
  BarChart3,
} from 'lucide-react'
import { cn } from '@/utils/cn'
import type { AnswerSubmission, EvaluateResult } from '@/types/learning'

// ─── Helper ──────────────────────────────────────────────────────

function getScoreColor(score: number): string {
  if (score >= 70) return 'text-secondary'
  if (score >= 50) return 'text-primary'
  return 'text-danger'
}

function getScoreRingColor(score: number): string {
  if (score >= 70) return '#E8A93B'
  if (score >= 50) return '#1FBF9E'
  return '#EF4444'
}

function getScoreHeading(score: number): string {
  if (score >= 70) return 'Passed!'
  return 'Keep Going'
}

function getEncouragement(score: number): string {
  if (score >= 90) return 'Outstanding work! You have demonstrated a strong grasp of this topic.'
  if (score >= 70) return 'Great effort! You have a solid understanding of the material.'
  if (score >= 50) return 'Good start! Review the weak areas below to strengthen your understanding.'
  return 'Don\'t give up! Review the material and try again to improve your score.'
}

// ─── Donut Ring SVG Component ────────────────────────────────────

interface DonutRingProps {
  percentage: number
  color: string
  size?: number
  strokeWidth?: number
}

function DonutRing({ percentage, color, size = 180, strokeWidth = 12 }: DonutRingProps) {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (percentage / 100) * circumference

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="transform -rotate-90"
      aria-hidden="true"
    >
      {/* Background ring */}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="currentColor"
        className="text-surface-border"
        strokeWidth={strokeWidth}
      />
      {/* Score ring */}
      <motion.circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeDasharray={circumference}
        initial={{ strokeDashoffset: circumference }}
        animate={{ strokeDashoffset: offset }}
        transition={{ duration: 1.2, ease: 'easeOut', delay: 0.3 }}
      />
    </svg>
  )
}

// ─── Stat Card ───────────────────────────────────────────────────

interface StatCardItemProps {
  label: string
  value: number | string
  icon: React.ReactNode
  variant?: 'default' | 'success' | 'danger' | 'primary'
  delay?: number
}

const statIconColors: Record<string, string> = {
  default: 'text-text-secondary',
  success: 'text-success',
  danger: 'text-danger',
  primary: 'text-primary',
}

function StatCardItem({ label, value, icon, variant = 'default', delay = 0 }: StatCardItemProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay, ease: 'easeOut' }}
    >
      <Card aria-label={`${label}: ${value}`}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-text-secondary">{label}</span>
          <span className={statIconColors[variant]}>{icon}</span>
        </div>
        <span className="font-display text-2xl font-semibold text-text-primary tabular-nums">
          {value}
        </span>
      </Card>
    </motion.div>
  )
}

// ─── Module-level guard against StrictMode double-fire ─────────

const evaluateInFlight = new Set<string>()

// ─── Quiz Results Page ───────────────────────────────────────────

export function QuizResultsPage() {
  const { topicId } = useParams<{ topicId: string }>()
  const location = useLocation()
  const navigate = useNavigate()

  const locationState = location.state as
    | {
        answers: AnswerSubmission[]
        questions?: import('@/types/learning').QuizQuestion[]
        topicName?: string
        sessionId?: string
        totalQuestions?: number
      }
    | undefined

  const answers = locationState?.answers
  const questions = locationState?.questions
  const topicName = locationState?.topicName ?? 'Topic'
  const sessionId = locationState?.sessionId ?? ''

  const evaluateMutation = useEvaluateQuiz()

  // Submit for evaluation on mount — guarded against StrictMode double-fire.
  // Module-level Set survives remounts (unlike useMutation.isPending which
  // starts as false on every new mutation instance in StrictMode).
  useEffect(() => {
    const dedupKey = `${topicId}:${sessionId}`
    if (answers && topicId && !evaluateInFlight.has(dedupKey)) {
      evaluateInFlight.add(dedupKey)
      evaluateMutation.mutate({
        topic_id: topicId,
        topic_name: topicName,
        session_id: sessionId,
        answers,
      }, {
        onSettled: () => {
          evaluateInFlight.delete(dedupKey)
        },
      })
    }
    // Only run on mount when answers/topicId are available
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Auto-advance: navigate to next lesson when NEXT_TOPIC ─────────
  useEffect(() => {
    if (!evaluateMutation.isSuccess || !evaluateMutation.data) return
    const result = evaluateMutation.data
    if (result.routing_decision === 'NEXT_TOPIC' && result.next_lesson) {
      const nl = result.next_lesson
      // Navigate to lesson with the next topic's data
      navigate(`/lesson/${nl.topic_id}`, {
        state: {
          topicId: nl.topic_id,
          topicName: nl.topic_name,
          topicDescription: nl.topic_description,
          topicDifficulty: nl.topic_difficulty,
        },
        replace: true,
      })
    }
  }, [evaluateMutation.isSuccess, evaluateMutation.data, navigate])

  // ── Derived data ──────────────────────────────────────────────

  const evaluation: EvaluateResult | undefined = evaluateMutation.data

  const score = evaluation?.score ?? 0
  const totalQuestions = evaluation?.total_questions ?? locationState?.totalQuestions ?? 0
  const correctCount = evaluation?.correct_count ?? 0
  const incorrectCount = evaluation?.incorrect_count ?? 0
  const weakConcepts = evaluation?.weak_concept_tags ?? []
  const feedback = evaluation?.feedback
  const routingDecision = evaluation?.routing_decision
  const routingReason = evaluation?.routing_reason
  const nextTopicId = evaluation?.next_topic_id
  const nextLesson = evaluation?.next_lesson

  const scoreColor = getScoreColor(score)
  const ringColor = getScoreRingColor(score)
  const headingText = getScoreHeading(score)
  const encouragement = getEncouragement(score)

  // ── Animation variants ────────────────────────────────────────

  const heroVariants = {
    hidden: { opacity: 0, scale: 0.5 },
    visible: {
      opacity: 1,
      scale: 1,
      transition: { duration: 0.6, ease: 'easeOut' },
    },
  }

  // ── State: no data ────────────────────────────────────────────

  if (!answers) {
    return (
      <div className="min-h-screen bg-background p-6 flex items-center justify-center" aria-label="Quiz results error state">
        <Card className="max-w-md w-full text-center" padding="lg">
          <AlertTriangle className="h-12 w-12 text-danger mx-auto mb-4" aria-hidden="true" />
          <h2 className="text-xl font-display font-semibold text-text-primary mb-2">
            No quiz data found
          </h2>
          <p className="text-sm text-text-secondary mb-6">
            Quiz answers were not provided. Please retake the quiz to see your results.
          </p>
          <Button
            variant="secondary"
            icon={<ArrowLeft className="h-4 w-4" />}
            onClick={() => navigate('/roadmap')}
            aria-label="Back to roadmap"
          >
            Back to Roadmap
          </Button>
        </Card>
      </div>
    )
  }

  // ── State: loading evaluation ─────────────────────────────────

  if (evaluateMutation.isPending) {
    return (
      <div className="min-h-screen bg-background p-6 flex items-center justify-center" aria-label="Evaluating quiz results">
        <div className="flex flex-col items-center text-center">
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
            className="mb-6"
          >
            <BrainCircuit className="h-12 w-12 text-primary" aria-hidden="true" />
          </motion.div>
          <p className="text-lg font-display font-semibold text-text-primary mb-2">
            Evaluating your answers...
          </p>
          <p className="text-sm text-text-secondary max-w-xs">
            Please wait while we analyze your performance and generate personalized feedback.
          </p>
        </div>
      </div>
    )
  }

  // ── State: error ──────────────────────────────────────────────

  if (evaluateMutation.isError) {
    return (
      <div className="min-h-screen bg-background p-6 flex items-center justify-center" aria-label="Evaluation error state">
        <Card className="max-w-md w-full text-center" padding="lg">
          <AlertTriangle className="h-12 w-12 text-danger mx-auto mb-4" aria-hidden="true" />
          <h2 className="text-xl font-display font-semibold text-text-primary mb-2">
            Error evaluating quiz
          </h2>
          <p className="text-sm text-text-secondary mb-6">
            {(evaluateMutation.error as Error)?.message ??
              'An unexpected error occurred while evaluating your answers.'}
          </p>
          <Button
            variant="primary"
            icon={<RotateCcw className="h-4 w-4" />}
            onClick={() => evaluateMutation.mutate({
              topic_id: topicId!,
              topic_name: topicName,
              answers,
            })}
            aria-label="Retry evaluation"
          >
            Retry
          </Button>
        </Card>
      </div>
    )
  }

  // ─── Main Content ────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-background" aria-label="Quiz results page">
      <div className="max-w-4xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        {/* Back link */}
        <Link
          to="/roadmap"
          className="inline-flex items-center gap-1.5 text-sm text-text-muted hover:text-text-secondary transition-colors mb-6"
          aria-label="Back to roadmap"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Roadmap
        </Link>

        {/* ── 1. Score Hero Section ─────────────────────────────── */}
        <motion.div
          className="flex flex-col items-center text-center mb-8"
          variants={heroVariants}
          initial="hidden"
          animate="visible"
          aria-label="Score hero section"
        >
          {/* Score ring */}
          <div className="relative mb-6" aria-label={`Score: ${Math.round(score)}%`}>
            <DonutRing percentage={score} color={ringColor} size={180} strokeWidth={14} />
            <motion.div
              className="absolute inset-0 flex items-center justify-center"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4, delay: 0.8 }}
            >
              <span
                className={cn(
                  'font-display text-4xl font-bold tabular-nums',
                  scoreColor
                )}
              >
                {Math.round(score)}%
              </span>
            </motion.div>
          </div>

          {/* Heading */}
          <motion.h1
            className={cn(
              'text-3xl font-display font-bold mb-2',
              scoreColor
            )}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.5 }}
          >
            {headingText}
          </motion.h1>

          {/* Encouragement */}
          <motion.p
            className="text-text-secondary max-w-md text-sm leading-relaxed"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.7 }}
          >
            {encouragement}
          </motion.p>
        </motion.div>

        {/* ── 2. Results Summary Grid ───────────────────────────── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <StatCardItem
            label="Total Questions"
            value={totalQuestions}
            icon={<BookOpen className="h-5 w-5" />}
            variant="default"
            delay={0.1}
          />
          <StatCardItem
            label="Correct"
            value={correctCount}
            icon={<CheckCircle className="h-5 w-5" />}
            variant="success"
            delay={0.2}
          />
          <StatCardItem
            label="Incorrect"
            value={incorrectCount}
            icon={<XCircle className="h-5 w-5" />}
            variant="danger"
            delay={0.3}
          />
          <StatCardItem
            label="Score"
            value={`${Math.round(score)}%`}
            icon={<Target className="h-5 w-5" />}
            variant="primary"
            delay={0.4}
          />
        </div>

        {/* ── 2.5 Question-by-Question Breakdown ─────────────────── */}
        {questions && questions.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.45 }}
            className="mb-8"
          >
            <SectionHeader
              title="Your Answers"
              description="Review each question and your response"
              className="mb-3"
            />
            <div className="space-y-3">
              {questions.map((q, idx) => {
                const userAnswer = answers?.find(
                  (a) => a.questionId === q.id,
                )
                return (
                  <Card key={q.id} padding="md" aria-label={`Question ${idx + 1}`}>
                    <div className="flex items-start gap-3">
                      <Badge variant="default" size="sm" className="mt-0.5 shrink-0">
                        Q{idx + 1}
                      </Badge>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-text-primary mb-2">
                          {q.question}
                        </p>
                        <div className="space-y-1">
                          {q.options.map((opt, oi) => {
                            const isSelected = userAnswer?.selectedAnswer === opt
                            return (
                              <div
                                key={oi}
                                className={cn(
                                  'text-xs px-2 py-1 rounded border',
                                  isSelected
                                    ? 'border-primary bg-primary-muted text-text-primary font-medium'
                                    : 'border-surface-border text-text-muted',
                                )}
                              >
                                {opt}
                              </div>
                            )
                          })}
                        </div>
                        {userAnswer ? (
                          <p className="text-xs text-text-secondary mt-2">
                            Your answer: <span className="font-medium text-text-primary">{userAnswer.selectedAnswer}</span>
                          </p>
                        ) : (
                          <p className="text-xs text-text-muted mt-2 italic">Not answered</p>
                        )}
                      </div>
                    </div>
                  </Card>
                )
              })}
            </div>
          </motion.div>
        )}

        {/* ── 3. Feedback Section ───────────────────────────────── */}
        {feedback && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.5 }}
            className="mb-8"
          >
            <SectionHeader
              title="Feedback"
              description="Personalized insights on your performance"
              className="mb-3"
            />
            <Card padding="md" aria-label="Quiz feedback">
              <p className="italic text-text-secondary leading-relaxed mb-4">
                "{feedback}"
              </p>

              {/* Routing decision */}
              {routingDecision && (
                <div className="flex items-start gap-3 p-3 bg-surface border border-surface-border rounded-lg">
                  {routingDecision.toLowerCase().includes('advanc') ||
                  routingDecision.toLowerCase().includes('next') ? (
                    <TrendingUp
                      className="h-5 w-5 text-success mt-0.5 shrink-0"
                      aria-hidden="true"
                    />
                  ) : (
                    <Lightbulb
                      className="h-5 w-5 text-secondary mt-0.5 shrink-0"
                      aria-hidden="true"
                    />
                  )}
                  <div>
                    <p className="text-sm font-medium text-text-primary">
                      {routingDecision.toLowerCase().includes('advanc') ||
                      routingDecision.toLowerCase().includes('next')
                        ? 'Advancing to next topic'
                        : 'Review this topic'}
                    </p>
                    {routingReason && (
                      <p className="text-xs text-text-muted mt-0.5">{routingReason}</p>
                    )}
                  </div>
                </div>
              )}
            </Card>
          </motion.div>
        )}

        {/* ── 4. Weak Topics ─────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.6 }}
          className="mb-8"
        >
          <SectionHeader
            title="Areas for Improvement"
            description="Topics to focus on based on your quiz performance"
            className="mb-3"
          />

          <Card padding="md" aria-label="Weak topic areas">
            {weakConcepts.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {weakConcepts.map((concept) => (
                  <Badge key={concept} variant="danger" size="md">
                    {concept}
                  </Badge>
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <CheckCircle className="h-5 w-5 text-success shrink-0" aria-hidden="true" />
                <p className="text-sm text-text-secondary">
                  Great job! No weak areas detected.
                </p>
              </div>
            )}
          </Card>
        </motion.div>

        {/* ── 5. Action Buttons ──────────────────────────────────── */}
        <motion.div
          className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.7 }}
        >
          {/* Retry Quiz */}
          <Button
            variant="ghost"
            icon={<RotateCcw className="h-4 w-4" />}
            onClick={() => navigate(`/quiz/${topicId}`)}
            aria-label="Retry quiz"
            className="sm:order-1"
          >
            Retry Quiz
          </Button>

          {/* Continue Learning */}
          <Button
            variant="primary"
            icon={<ArrowRight className="h-4 w-4" />}
            onClick={() => {
              if (nextTopicId) {
                navigate(`/lesson/${nextTopicId}`)
              } else {
                navigate('/roadmap')
              }
            }}
            aria-label="Continue learning"
            className="sm:order-3"
          >
            Continue Learning
          </Button>

          {/* Back to Roadmap */}
          <Button
            variant="secondary"
            icon={<BarChart3 className="h-4 w-4" />}
            onClick={() => navigate('/roadmap')}
            aria-label="Back to roadmap"
            className="sm:order-2"
          >
            Back to Roadmap
          </Button>
        </motion.div>
      </div>
    </div>
  )
}
