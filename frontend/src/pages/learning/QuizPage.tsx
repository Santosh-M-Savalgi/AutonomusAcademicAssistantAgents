import { useState, useCallback, useEffect } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Card, Button, Badge, Progress, Skeleton } from '@/components/ui'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui'
import { useQuiz } from '@/services/learningApi'
import {
  BookOpen,
  Clock,
  ArrowLeft,
  ArrowRight,
  CheckCircle,
  XCircle,
  HelpCircle,
  List,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Flag,
  Send,
  Loader2,
} from 'lucide-react'
import { cn } from '@/utils/cn'
import type { QuizQuestion } from '@/types/learning'

// ─── Animation Variants ─────────────────────────────────────────────────────

const CARD_VARIANTS = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.35, ease: 'easeOut' } },
  exit: { opacity: 0, y: -20, transition: { duration: 0.2 } },
}

const OPTION_VARIANTS = {
  hidden: { opacity: 0, x: -12 },
  visible: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: { delay: 0.1 + i * 0.05, duration: 0.25, ease: 'easeOut' },
  }),
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function getDifficultyColor(difficulty: string): 'primary' | 'secondary' | 'default' {
  switch (difficulty.toLowerCase()) {
    case 'beginner':
      return 'success'
    case 'intermediate':
      return 'secondary'
    case 'advanced':
      return 'danger'
    default:
      return 'default'
  }
}

function getDifficultyLabel(difficulty: string): string {
  switch (difficulty.toLowerCase()) {
    case 'beginner':
      return 'Beginner'
    case 'intermediate':
      return 'Intermediate'
    case 'advanced':
      return 'Advanced'
    default:
      return difficulty
  }
}

// ─── Sub-components ─────────────────────────────────────────────────────────

function QuizHeaderSkeleton() {
  return (
    <div className="flex flex-col gap-4 mb-8">
      <div className="flex items-center justify-between">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-9 w-24" />
      </div>
      <div className="flex items-center gap-4">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-5 w-20" />
      </div>
      <Skeleton className="h-2 w-full" />
    </div>
  )
}

function QuestionSkeleton() {
  return (
    <Card className="max-w-2xl mx-auto">
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <Skeleton className="h-6 w-24 rounded-full" />
          <Skeleton className="h-6 w-28 rounded-full" />
          <Skeleton className="h-6 w-20 rounded-full" />
        </div>
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-4/5" />
        <div className="space-y-3 pt-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-14 w-full rounded-lg" />
          ))}
        </div>
      </div>
    </Card>
  )
}

// ─── Main Component ─────────────────────────────────────────────────────────

export function QuizPage() {
  const { topicId } = useParams<{ topicId: string }>()
  const location = useLocation()
  const navigate = useNavigate()

  // Read topic data from navigation state (populated by LessonPage)
  const navState = location.state as {
    topicId?: string
    topicName?: string
    sessionId?: string
    questions?: import('@/types/learning').QuizQuestion[] | null
  } | null

  const [answers, setAnswers] = useState<Map<string, string>>(new Map())
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // ── Quiz source: pre-generated from lesson, or fetch on demand ──────

  const preGenQuestions = navState?.questions ?? null

  const quizQuery = useQuiz(
    topicId,
    {
      topic_id: topicId ?? '',
      topic_name: navState?.topicName ?? '',
      session_id: navState?.sessionId ?? '',
      num_questions: 10,
    },
    { enabled: !!topicId && !preGenQuestions },  // skip API call if pre-generated
  )

  const quiz = preGenQuestions
    ? { topicName: navState?.topicName ?? '', questions: preGenQuestions }
    : quizQuery.data
      ? { topicName: quizQuery.data.topic_name, questions: quizQuery.data.questions }
      : null

  // Stable key that only changes when the actual question set changes,
  // not when the wrapper object is recreated on every render.
  const quizQuestionsKey = quiz?.questions.map((q) => q.id).join(',') ?? ''

  // Reset answers + question index when quiz source changes
  useEffect(() => {
    setAnswers(new Map())
    setCurrentQuestionIndex(0)
  }, [quizQuestionsKey])

  // ── Derived state ────────────────────────────────────────────────────────

  const questions = quiz?.questions ?? []
  const totalQuestions = questions.length
  const currentQuestion = questions[currentQuestionIndex] ?? null
  const answeredCount = answers.size
  const allAnswered = answeredCount === totalQuestions && totalQuestions > 0
  const answeredQuestions = new Set(answers.keys())

  // ── Answer handlers ──────────────────────────────────────────────────────

  const selectAnswer = useCallback(
    (questionId: string, option: string) => {
      setAnswers((prev) => {
        const next = new Map(prev)
        next.set(questionId, option)
        return next
      })
    },
    []
  )

  const goToQuestion = useCallback((index: number) => {
    if (index >= 0 && index < totalQuestions) {
      setCurrentQuestionIndex(index)
    }
  }, [totalQuestions])

  const goNext = useCallback(() => {
    if (currentQuestionIndex < totalQuestions - 1) {
      setCurrentQuestionIndex((prev) => prev + 1)
    }
  }, [currentQuestionIndex, totalQuestions])

  const goPrevious = useCallback(() => {
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex((prev) => prev - 1)
    }
  }, [currentQuestionIndex])

  // ── Keyboard navigation ──────────────────────────────────────────────────

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Number keys 1-4 for option selection
      if (currentQuestion && ['1', '2', '3', '4'].includes(e.key)) {
        const idx = parseInt(e.key, 10) - 1
        if (idx < currentQuestion.options.length) {
          selectAnswer(currentQuestion.id, currentQuestion.options[idx])
        }
      }
      // Arrow keys for navigation
      if (e.key === 'ArrowRight') goNext()
      if (e.key === 'ArrowLeft') goPrevious()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [currentQuestion, selectAnswer, goNext, goPrevious])

  // ── Submit handler ───────────────────────────────────────────────────────

  const handleSubmit = useCallback(() => {
    if (!quiz || !allAnswered || isSubmitting) return
    setIsSubmitting(true)

    const submissionData = {
      topicId: topicId!,
      topicName: quiz.topicName,
      sessionId: navState?.sessionId ?? '',
      questions: quiz.questions,
      answers: Array.from(answers.entries()).map(([questionId, selectedAnswer]) => ({
        questionId,
        selectedAnswer,
      })),
    }

    navigate(`/quiz-results/${topicId}`, { state: submissionData })
  }, [quiz, topicId, answers, allAnswered, isSubmitting, navigate])

  // ── Render: Loading ──────────────────────────────────────────────────────

  if (quizQuery.isLoading) {
    return (
      <div className="min-h-screen bg-background" role="status" aria-label="Loading quiz">
        <div className="max-w-6xl mx-auto px-4 py-8">
          <QuizHeaderSkeleton />
          <QuestionSkeleton />
        </div>
      </div>
    )
  }

  // ── Render: Error ────────────────────────────────────────────────────────

  if (quizQuery.isError) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <ErrorState
          title="Failed to load quiz"
          message={quizQuery.error?.message || 'Unable to generate quiz questions. Please try again.'}
          onRetry={() => quizQuery.refetch()}
        />
      </div>
    )
  }

  // ── Render: Empty ────────────────────────────────────────────────────────

  if (!quiz || questions.length === 0) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <EmptyState
          title="No quiz available"
          description="No questions could be generated for this topic. Please try again later."
          icon={<BookOpen className="h-12 w-12" />}
          action={
            <Button variant="secondary" onClick={() => quizQuery.refetch()} loading={quizQuery.isLoading}>
              Try Again
            </Button>
          }
        />
      </div>
    )
  }

  // ── Render: Quiz ─────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 py-6 lg:py-8">
        {/* ── Quiz Header ───────────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="mb-6 space-y-4"
        >
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => navigate(-1)}
                aria-label="Go back"
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>
              <h1 className="text-xl lg:text-2xl font-display font-bold text-text-primary">
                {quiz.topicName} Quiz
              </h1>
            </div>

            <div className="flex items-center gap-4 text-text-muted">
              <div className="flex items-center gap-1.5 text-sm" aria-label="Quiz timer">
                <Clock className="h-4 w-4" />
                <span className="font-mono tabular-nums">--:--</span>
              </div>
              <div className="hidden sm:flex items-center gap-1.5 text-sm text-text-secondary">
                <List className="h-4 w-4" />
                <span>{answeredCount}/{totalQuestions}</span>
              </div>
            </div>
          </div>

          {/* Progress bar */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-sm">
              <span className="text-text-secondary">
                Question <span className="text-text-primary font-medium">{currentQuestionIndex + 1}</span> of{' '}
                {totalQuestions}
              </span>
              <span className="text-text-muted text-xs">
                {Math.round(((currentQuestionIndex + 1) / totalQuestions) * 100)}%
              </span>
            </div>
            <Progress
              value={currentQuestionIndex + 1}
              max={totalQuestions}
              size="md"
              variant="primary"
            />
          </div>
        </motion.div>

        {/* ── Main layout: Question + Navigation side-by-side on desktop ── */}
        <div className="flex flex-col lg:flex-row gap-6">
          {/* ── Question Card ───────────────────────────────────────────── */}
          <div className="flex-1 min-w-0">
            <AnimatePresence mode="wait">
              <motion.div
                key={currentQuestion?.id ?? 'empty'}
                variants={CARD_VARIANTS}
                initial="hidden"
                animate="visible"
                exit="exit"
              >
                <Card className="max-w-2xl mx-auto" padding="lg">
                  {/* Badges row */}
                  <div className="flex flex-wrap items-center gap-2 mb-5">
                    <Badge variant="primary" size="sm">
                      Question {currentQuestionIndex + 1}
                    </Badge>
                    {currentQuestion && (
                      <>
                        <Badge
                          variant={getDifficultyColor(currentQuestion.difficulty)}
                          size="sm"
                        >
                          {getDifficultyLabel(currentQuestion.difficulty)}
                        </Badge>
                        <Badge variant="default" size="sm">
                          {currentQuestion.concept_tag}
                        </Badge>
                      </>
                    )}
                  </div>

                  {/* Question text */}
                  <h2 className="font-display text-lg lg:text-xl font-semibold text-text-primary mb-6 leading-relaxed">
                    {currentQuestion?.question}
                  </h2>

                  {/* Options */}
                  <div className="space-y-3" role="radiogroup" aria-label="Answer options">
                    {currentQuestion?.options.map((option, idx) => {
                      const isSelected = answers.get(currentQuestion.id) === option
                      return (
                        <motion.button
                          key={option}
                          custom={idx}
                          variants={OPTION_VARIANTS}
                          initial="hidden"
                          animate="visible"
                          onClick={() => selectAnswer(currentQuestion.id, option)}
                          className={cn(
                            'w-full flex items-center gap-3 px-4 py-3.5 rounded-lg border text-left transition-all duration-200',
                            'focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2',
                            isSelected
                              ? 'border-primary bg-primary-muted text-text-primary'
                              : 'border-surface-border bg-surface text-text-secondary hover:border-primary/30 hover:bg-surface-hover hover:text-text-primary'
                          )}
                          role="radio"
                          aria-checked={isSelected}
                          aria-label={`Option ${idx + 1}: ${option}`}
                        >
                          {/* Radio circle indicator */}
                          <span
                            className={cn(
                              'flex-shrink-0 flex items-center justify-center w-6 h-6 rounded-full border-2 transition-all duration-200 text-xs font-semibold',
                              isSelected
                                ? 'border-primary bg-primary text-text-inverse'
                                : 'border-surface-border text-text-muted'
                            )}
                          >
                            {idx + 1}
                          </span>
                          <span className="flex-1 text-sm leading-relaxed">{option}</span>
                          {isSelected && (
                            <CheckCircle className="h-4 w-4 text-primary flex-shrink-0" />
                          )}
                        </motion.button>
                      )
                    })}
                  </div>

                  {/* Next / Previous question prompt */}
                  <div className="flex items-center justify-between mt-6 pt-4 border-t border-surface-border">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={goPrevious}
                      disabled={currentQuestionIndex === 0}
                      aria-label="Previous question"
                    >
                      <ChevronLeft className="h-4 w-4" />
                      Previous
                    </Button>

                    {answers.has(currentQuestion?.id ?? '') && (
                      <motion.span
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="text-xs text-primary font-medium"
                      >
                        {currentQuestionIndex < totalQuestions - 1
                          ? 'Press Enter or → to continue'
                          : 'Last question'}
                      </motion.span>
                    )}

                    {currentQuestionIndex < totalQuestions - 1 ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={goNext}
                        disabled={!answers.has(currentQuestion?.id ?? '')}
                        aria-label="Next question"
                      >
                        Next
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    ) : (
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={handleSubmit}
                        disabled={!allAnswered || isSubmitting}
                        aria-label="Submit quiz"
                      >
                        {isSubmitting ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Send className="h-4 w-4" />
                        )}
                        Submit
                      </Button>
                    )}
                  </div>
                </Card>
              </motion.div>
            </AnimatePresence>
          </div>

          {/* ── Question Navigation Sidebar (desktop) ────────────────────── */}
          <motion.aside
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3, delay: 0.15 }}
            className="hidden lg:block w-64 flex-shrink-0"
            aria-label="Question navigation"
          >
            <Card padding="md" className="sticky top-8">
              <div className="flex items-center gap-2 mb-4">
                <BarChart3 className="h-4 w-4 text-text-secondary" />
                <h3 className="text-sm font-medium text-text-primary">Questions</h3>
              </div>

              <div className="grid grid-cols-5 gap-2 mb-4">
                {questions.map((q, idx) => {
                  const isCurrent = idx === currentQuestionIndex
                  const isAnswered = answeredQuestions.has(q.id)
                  return (
                    <button
                      key={q.id}
                      onClick={() => goToQuestion(idx)}
                      className={cn(
                        'w-10 h-10 rounded-lg text-sm font-medium transition-all duration-200',
                        'focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2',
                        isCurrent && 'bg-primary text-text-inverse shadow-glow',
                        !isCurrent && isAnswered && 'bg-secondary-muted text-secondary border border-secondary/30',
                        !isCurrent && !isAnswered && 'bg-surface-hover text-text-muted border border-surface-border hover:border-primary/40 hover:text-text-primary'
                      )}
                      aria-label={`Question ${idx + 1}${isCurrent ? ', current' : ''}${isAnswered ? ', answered' : ', unanswered'}`}
                      aria-current={isCurrent ? 'true' : undefined}
                    >
                      {idx + 1}
                    </button>
                  )
                })}
              </div>

              {/* Legend */}
              <div className="flex items-center gap-3 text-xs text-text-muted pt-3 border-t border-surface-border">
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-sm bg-primary" /> Current
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-sm bg-secondary/60" /> Answered
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded-sm bg-surface-border" /> Unanswered
                </span>
              </div>
            </Card>

            {/* Submit section */}
            <Card padding="md" className="mt-4">
              <p className="text-xs text-text-muted mb-3 leading-relaxed">
                Review your answers before submitting.
              </p>
              <Button
                variant="primary"
                size="md"
                className="w-full"
                onClick={handleSubmit}
                disabled={!allAnswered || isSubmitting}
                aria-label="Submit quiz"
              >
                {isSubmitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
                {allAnswered ? 'Submit Quiz' : `${totalQuestions - answeredCount} remaining`}
              </Button>
            </Card>
          </motion.aside>
        </div>

        {/* ── Mobile bottom navigation bar ───────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.2 }}
          className="lg:hidden fixed bottom-0 left-0 right-0 bg-surface border-t border-surface-border px-4 py-3 z-40"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-secondary">
                {answeredCount}/{totalQuestions} answered
              </span>
              {allAnswered && (
                <Badge variant="success" size="sm">
                  All answered
                </Badge>
              )}
            </div>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSubmit}
              disabled={!allAnswered || isSubmitting}
              aria-label="Submit quiz"
            >
              {isSubmitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              Submit
            </Button>
          </div>
          {/* Scrollable question dots */}
          <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-none" role="tablist" aria-label="Question navigation">
            {questions.map((q, idx) => {
              const isCurrent = idx === currentQuestionIndex
              const isAnswered = answeredQuestions.has(q.id)
              return (
                <button
                  key={q.id}
                  onClick={() => goToQuestion(idx)}
                  className={cn(
                    'flex-shrink-0 w-8 h-8 rounded-md text-xs font-medium transition-all duration-200',
                    'focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2',
                    isCurrent && 'bg-primary text-text-inverse',
                    !isCurrent && isAnswered && 'bg-secondary-muted text-secondary border border-secondary/30',
                    !isCurrent && !isAnswered && 'bg-surface-hover text-text-muted border border-surface-border'
                  )}
                  role="tab"
                  aria-selected={isCurrent}
                  aria-label={`Go to question ${idx + 1}${isAnswered ? ' (answered)' : ''}`}
                >
                  {idx + 1}
                </button>
              )
            })}
          </div>
        </motion.div>

        {/* Spacer for mobile bottom nav */}
        <div className="lg:hidden h-24" />
      </div>
    </div>
  )
}

export default QuizPage
