import { useState, useEffect } from 'react'
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Card, Button, Badge, Skeleton, Progress } from '@/components/ui'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui'
import { useGenerateLesson } from '@/services/learningApi'
import {
  BookOpen,
  ArrowLeft,
  ArrowRight,
  Clock,
  Target,
  ChevronRight,
  CheckCircle,
  Sparkles,
  Code,
  Lightbulb,
  FileText,
  GraduationCap,
  BrainCircuit,
  Video,
} from 'lucide-react'
import { cn } from '@/utils/cn'
import { formatTime } from '@/utils/cn'
import type { Lesson, TeachingCard } from '@/types/learning'

// ─── Default learning objectives (placeholder) ─────────────────

const DEFAULT_OBJECTIVES = [
  'Understand the core concepts and foundational principles',
  'Apply knowledge through practical examples and exercises',
  'Recognize common patterns and best practices',
  'Build confidence through hands-on application',
  'Connect new knowledge to existing understanding',
]

// ─── Card type configuration ───────────────────────────────────

type CardTypeConfig = {
  icon: React.ReactNode
  borderClass: string
  accentClass: string
}

const CARD_TYPE_CONFIG: Record<string, CardTypeConfig> = {
  concept: {
    icon: <Lightbulb className="h-5 w-5 text-primary" />,
    borderClass: 'border-l-primary/60',
    accentClass: 'text-primary',
  },
  example: {
    icon: <Code className="h-5 w-5 text-text-secondary" />,
    borderClass: 'border-l-surface-border',
    accentClass: 'text-text-secondary',
  },
  analogy: {
    icon: <BrainCircuit className="h-5 w-5 text-secondary" />,
    borderClass: 'border-l-secondary/60',
    accentClass: 'text-secondary',
  },
  summary: {
    icon: <FileText className="h-5 w-5 text-text-muted" />,
    borderClass: 'border-l-text-muted/40',
    accentClass: 'text-text-muted',
  },
}

const DEFAULT_CARD_CONFIG: CardTypeConfig = {
  icon: <FileText className="h-5 w-5 text-text-muted" />,
  borderClass: 'border-l-text-muted/40',
  accentClass: 'text-text-muted',
}

// ─── Helpers ───────────────────────────────────────────────────

function getCardConfig(cardType: string): CardTypeConfig {
  return CARD_TYPE_CONFIG[cardType] ?? DEFAULT_CARD_CONFIG
}

function extractObjectives(cards: TeachingCard[]): string[] {
  const objectives: string[] = []
  for (const card of cards) {
    // Try to extract bullet points or numbered items from the body
    const lines = card.body.split('\n')
    for (const line of lines) {
      const trimmed = line.trim()
      // Match bullet points, numbered items, or "Objectives:" / "You will learn:" sections
      if (
        /^[-*•]\s/.test(trimmed) ||
        /^\d+[.)]\s/.test(trimmed) ||
        /^(objective|learn|understand|master|be able to)/i.test(trimmed)
      ) {
        const clean = trimmed.replace(/^[-*•]\s*/, '').replace(/^\d+[.)]\s*/, '')
        if (clean.length > 10 && !objectives.includes(clean)) {
          objectives.push(clean)
        }
      }
    }
    if (objectives.length >= 5) break
  }
  return objectives.length > 0 ? objectives.slice(0, 5) : DEFAULT_OBJECTIVES
}

// ─── Stagger animation variants ────────────────────────────────

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1,
      delayChildren: 0.1,
    },
  },
}

const itemVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] },
  },
}

const sectionVariants = {
  hidden: { opacity: 0, y: 12 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] },
  },
}

// ─── Sub-components ────────────────────────────────────────────

function LessonSkeleton() {
  return (
    <div className="min-h-screen" aria-label="Loading lesson content" role="status">
      <div className="px-4 sm:px-6 lg:px-8 py-6 max-w-4xl mx-auto space-y-6">
        {/* Back button skeleton */}
        <Skeleton className="h-9 w-36 rounded-md" />

        {/* Title skeleton */}
        <div className="space-y-3">
          <Skeleton className="h-10 w-3/4" />
          <div className="flex gap-3">
            <Skeleton className="h-6 w-20 rounded-full" />
            <Skeleton className="h-6 w-28 rounded-full" />
            <Skeleton className="h-6 w-24 rounded-full" />
          </div>
        </div>

        {/* Objectives card skeleton */}
        <Skeleton className="h-44 w-full rounded-lg" variant="rectangular" />

        {/* Card skeletons */}
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-40 w-full rounded-lg" variant="rectangular" />
        ))}
      </div>
    </div>
  )
}

function LessonHeader({
  lesson,
}: {
  lesson: Lesson
}) {
  return (
    <motion.section
      variants={sectionVariants}
      initial="hidden"
      animate="visible"
      className="space-y-6"
    >
      {/* Back button */}
      <Link
        to="/roadmap"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-text-secondary hover:text-text-primary transition-colors group"
        aria-label="Back to Roadmap"
      >
        <ArrowLeft className="h-4 w-4 transition-transform group-hover:-translate-x-0.5" />
        Back to Roadmap
      </Link>

      {/* Title */}
      <div className="space-y-3">
        <h1 className="text-3xl sm:text-4xl font-display font-bold text-text-primary leading-tight">
          {lesson.title}
        </h1>

        {/* Metadata row */}
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Badge variant="primary" size="sm">
            {lesson.learning_mode}
          </Badge>

          <div className="flex items-center gap-1.5 text-text-secondary">
            <Clock className="h-4 w-4" />
            <span>{formatTime(lesson.estimated_minutes)}</span>
          </div>

          <div className="flex items-center gap-1.5 text-text-secondary">
            <Target className="h-4 w-4" />
            <span>{lesson.cards.length} cards</span>
          </div>
        </div>
      </div>
    </motion.section>
  )
}

function LearningObjectivesCard({
  objectives,
}: {
  objectives: string[]
}) {
  return (
    <motion.div variants={itemVariants}>
      <Card
        className="border-l-4 border-l-secondary/60 relative overflow-hidden"
        padding="lg"
      >
        {/* Subtle glow */}
        <div
          className="absolute -top-20 -right-20 h-40 w-40 rounded-full bg-secondary/5 blur-3xl pointer-events-none"
          aria-hidden="true"
        />

        <div className="flex items-start gap-4 relative z-10">
          <div className="shrink-0 mt-1">
            <div className="h-10 w-10 rounded-lg bg-secondary-muted flex items-center justify-center">
              <GraduationCap className="h-5 w-5 text-secondary" />
            </div>
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-lg font-display font-semibold text-text-primary mb-3">
              Learning Objectives
            </h2>
            <ul className="space-y-2.5">
              {objectives.map((obj, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2.5 text-sm text-text-secondary leading-relaxed"
                >
                  <CheckCircle className="h-4 w-4 text-secondary shrink-0 mt-0.5" />
                  <span>{obj}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Card>
    </motion.div>
  )
}

function TeachingCardView({
  card,
  index,
}: {
  card: TeachingCard
  index: number
}) {
  const config = getCardConfig(card.card_type)

  return (
    <motion.div variants={itemVariants}>
      <Card
        className={cn(
          'border-l-4 relative overflow-hidden',
          config.borderClass
        )}
        padding="lg"
      >
        {/* Type badge */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <div
              className={cn(
                'h-8 w-8 rounded-lg flex items-center justify-center',
                card.card_type === 'concept' && 'bg-primary-muted',
                card.card_type === 'example' && 'bg-surface-border',
                card.card_type === 'analogy' && 'bg-secondary-muted',
                card.card_type !== 'concept' &&
                  card.card_type !== 'example' &&
                  card.card_type !== 'analogy' &&
                  'bg-surface-border'
              )}
            >
              {config.icon}
            </div>
            <h3 className="text-base font-display font-semibold text-text-primary">
              {card.title}
            </h3>
          </div>
          <Badge
            variant={
              card.card_type === 'concept'
                ? 'primary'
                : card.card_type === 'analogy'
                ? 'secondary'
                : 'default'
            }
            size="sm"
            className="capitalize"
          >
            {card.card_type}
          </Badge>
        </div>

        {/* Body text with code block treatment */}
        <div className="text-sm text-text-secondary leading-relaxed space-y-3">
          {card.body.split('\n\n').map((paragraph, pi) => {
            const trimmed = paragraph.trim()
            if (!trimmed) return null

            // Detect code blocks (wrapped in backticks or indented)
            if (trimmed.startsWith('```') && trimmed.endsWith('```')) {
              const code = trimmed.replace(/^```\w*\n?/, '').replace(/\n?```$/, '')
              return (
                <pre
                  key={pi}
                  className="bg-surface-hover border border-surface-border rounded-md p-4 overflow-x-auto text-sm font-mono text-text-primary leading-relaxed"
                >
                  <code>{code}</code>
                </pre>
              )
            }

            // Inline code spans
            const parts = trimmed.split(/(`[^`]+`)/g)
            if (parts.length > 1) {
              return (
                <p key={pi}>
                  {parts.map((part, pi2) =>
                    part.startsWith('`') && part.endsWith('`') ? (
                      <code
                        key={pi2}
                        className="bg-surface-hover border border-surface-border rounded px-1.5 py-0.5 text-sm font-mono text-text-primary"
                      >
                        {part.slice(1, -1)}
                      </code>
                    ) : (
                      <span key={pi2}>{part}</span>
                    )
                  )}
                </p>
              )
            }

            return <p key={pi}>{trimmed}</p>
          })}
        </div>
      </Card>
    </motion.div>
  )
}

function YouTubeSuggestions({
  suggestions,
}: {
  suggestions: { title: string; url: string; video_id: string }[] | null | undefined
}) {
  if (!suggestions || suggestions.length === 0) return null

  return (
    <motion.div variants={itemVariants}>
      <Card className="border-l-4 border-l-danger/40 relative overflow-hidden" padding="lg">
        <div className="flex items-start gap-4 relative z-10">
          <div className="shrink-0 mt-1">
            <div className="h-10 w-10 rounded-lg bg-danger-muted flex items-center justify-center">
              <Video className="h-5 w-5 text-red-500" />
            </div>
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-lg font-display font-semibold text-text-primary mb-3">
              Related Videos
            </h2>
            <ul className="space-y-3">
              {suggestions.map((yt) => (
                <li key={yt.video_id || yt.url}>
                  <a
                    href={yt.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group flex items-start gap-3 text-sm text-text-secondary hover:text-text-primary transition-colors"
                  >
                    <Video className="h-4 w-4 text-red-500 shrink-0 mt-0.5 group-hover:scale-110 transition-transform" />
                    <span className="group-hover:underline underline-offset-2">
                      {yt.title}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Card>
    </motion.div>
  )
}

function NavigationFooter({
  hasPrevious,
  hasNext,
  onPrevious,
  onNext,
  onComplete,
}: {
  hasPrevious: boolean
  hasNext: boolean
  onPrevious: () => void
  onNext: () => void
  onComplete: () => void
}) {
  return (
    <motion.nav
      variants={sectionVariants}
      initial="hidden"
      animate="visible"
      className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 pt-6 pb-8 border-t border-surface-border"
      aria-label="Lesson navigation"
    >
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          icon={<ArrowLeft className="h-4 w-4" />}
          onClick={onPrevious}
          disabled={!hasPrevious}
          aria-label="Previous lesson"
        >
          Previous
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <Link to="/roadmap">
          <Button variant="secondary" size="sm" aria-label="Back to Roadmap">
            Back to Roadmap
          </Button>
        </Link>
        <Button
          variant="primary"
          size="sm"
          icon={<CheckCircle className="h-4 w-4" />}
          onClick={onComplete}
          aria-label="Complete lesson and continue"
        >
          Complete &amp; Continue
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={onNext}
          disabled={!hasNext}
          aria-label="Next lesson"
        >
          Next
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </motion.nav>
  )
}

function FloatingProgress({
  viewed,
  total,
}: {
  viewed: number
  total: number
}) {
  if (total === 0) return null

  return (
    <div
      className="sticky top-0 z-30 -mx-4 sm:-mx-6 lg:-mx-8 px-4 sm:px-6 lg:px-8 py-2.5 bg-background/80 backdrop-blur-md border-b border-surface-border"
      role="progressbar"
      aria-valuenow={viewed}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-label={`${viewed} of ${total} cards viewed`}
    >
      <div className="max-w-4xl mx-auto flex items-center gap-3">
        <span className="text-xs font-medium text-text-secondary whitespace-nowrap tabular-nums">
          {viewed} of {total} cards viewed
        </span>
        <Progress
          value={viewed}
          max={total}
          size="sm"
          variant="primary"
          className="flex-1"
        />
      </div>
    </div>
  )
}

// ─── Main Component ────────────────────────────────────────────

export function LessonPage() {
  const { topicId } = useParams<{ topicId: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const generateLesson = useGenerateLesson()

  // Read topic data from navigation state (populated by auto-advance)
  const navState = location.state as {
    topicId?: string
    topicName?: string
    topicDescription?: string
    topicDifficulty?: string
    sessionId?: string
  } | null

  const [viewedCards, setViewedCards] = useState<number>(0)
  const [hasScrolledPast, setHasScrolledPast] = useState<Set<number>>(new Set())

  const lesson = generateLesson.data ?? null
  const isLoading = generateLesson.isPending
  const isError = generateLesson.isError
  const error = generateLesson.error

  // Trigger lesson generation on mount
  useEffect(() => {
    if (topicId) {
      generateLesson.mutate({
        topic_id: topicId,
        topic_name: navState?.topicName ?? topicId,
        topic_description: navState?.topicDescription ?? '',
        topic_difficulty: navState?.topicDifficulty ?? 'beginner',
        session_id: navState?.sessionId ?? '',
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topicId])

  // Track which cards the user has scrolled past (counts as "viewed")
  useEffect(() => {
    if (!lesson?.cards.length) return

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const idx = Number(entry.target.getAttribute('data-card-index'))
            if (!isNaN(idx)) {
              setHasScrolledPast((prev) => {
                const next = new Set(prev)
                next.add(idx)
                return next
              })
            }
          }
        }
      },
      { threshold: 0.3 }
    )

    const elements = document.querySelectorAll('[data-card-index]')
    elements.forEach((el) => observer.observe(el))

    return () => observer.disconnect()
  }, [lesson])

  // Update viewed count whenever scroll tracking changes
  useEffect(() => {
    setViewedCards(hasScrolledPast.size)
  }, [hasScrolledPast])

  // Extract objectives
  const objectives = lesson ? extractObjectives(lesson.cards) : DEFAULT_OBJECTIVES

  // Navigation handlers
  const handlePrevious = () => {
    navigate(-1)
  }

  const handleNext = () => {
    // Could navigate to next lesson; currently placeholder
  }

  const handleComplete = () => {
    // Mark lesson as complete; navigate back to roadmap
    navigate('/roadmap')
  }

  const handleRetry = () => {
    if (topicId) {
      generateLesson.mutate({
        topic_id: topicId,
        topic_name: topicId,
      })
    }
  }

  // ── Loading state ──────────────────────────────────────────
  if (isLoading) {
    return <LessonSkeleton />
  }

  // ── Error state ────────────────────────────────────────────
  if (isError) {
    return (
      <div className="px-4 sm:px-6 lg:px-8 py-6 max-w-4xl mx-auto">
        <ErrorState
          title="Failed to load lesson"
          message={
            error instanceof Error
              ? error.message
              : 'Unable to generate the lesson content. Please check your connection and try again.'
          }
          onRetry={handleRetry}
        />
      </div>
    )
  }

  // ── Empty state ────────────────────────────────────────────
  if (!lesson) {
    return (
      <div className="px-4 sm:px-6 lg:px-8 py-6 max-w-4xl mx-auto">
        <EmptyState
          title="No lesson data"
          description="We couldn't find a lesson for this topic. Please try selecting a different topic."
          icon={<BookOpen className="h-12 w-12" />}
          action={
            <Link to="/roadmap">
              <Button variant="secondary" size="sm">
                Back to Roadmap
              </Button>
            </Link>
          }
        />
      </div>
    )
  }

  // ── Main lesson content ────────────────────────────────────
  return (
    <div className="min-h-screen">
      {/* Floating progress bar */}
      <FloatingProgress viewed={viewedCards} total={lesson.cards.length} />

      <div className="px-4 sm:px-6 lg:px-8 py-6 max-w-4xl mx-auto space-y-8">
        <AnimatePresence mode="wait">
          <motion.div
            key={lesson.topic_id}
            variants={containerVariants}
            initial="hidden"
            animate="visible"
            exit="hidden"
            className="space-y-8"
          >
            {/* Header */}
            <LessonHeader lesson={lesson} />

            {/* Learning Objectives */}
            <LearningObjectivesCard objectives={objectives} />

            {/* Teaching cards */}
            <motion.div
              variants={containerVariants}
              initial="hidden"
              animate="visible"
              className="space-y-6"
              aria-label="Lesson content sections"
            >
              {lesson.cards.map((card, index) => (
                <div key={`${card.card_type}-${index}`} data-card-index={index}>
                  <TeachingCardView card={card} index={index} />
                </div>
              ))}
            </motion.div>

            {/* YouTube Suggestions */}
            <YouTubeSuggestions suggestions={lesson.youtube_suggestions} />

            {/* Navigation Footer */}
            <NavigationFooter
              hasPrevious={false}
              hasNext={false}
              onPrevious={handlePrevious}
              onNext={handleNext}
              onComplete={handleComplete}
            />
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}

export default LessonPage
