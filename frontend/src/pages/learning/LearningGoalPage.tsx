import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Button, Card } from '@/components/ui'
import { ROUTES } from '@/constants'
import { getErrorMessage } from '@/api/client'
import { useCreateLearningGoal } from '@/services/learningApi'
import { useLearningJourney } from '@/contexts/LearningContext'
import { BookOpen, Sparkles, ArrowRight, BrainCircuit, Target, Lightbulb } from 'lucide-react'

const SUGGESTED_GOALS = [
  'I want to learn Python',
  'Teach me Java',
  'Learn Data Structures & Algorithms',
  'Master Machine Learning',
  'Become a React developer',
  'Learn SQL and databases',
  'System Design for interviews',
]

export function LearningGoalPage() {
  const navigate = useNavigate()
  const [goal, setGoal] = useState('')
  const createGoal = useCreateLearningGoal()

  const { setLearningJourney } = useLearningJourney()
  const isSubmitting = createGoal.isPending

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!goal.trim() || isSubmitting) return

    try {
        const result = await createGoal.mutateAsync({ goal: goal.trim() })
        // Persist learning journey to localStorage so it survives navigation
        setLearningJourney(result.syllabus_id, result.session_id, result.title)
        navigate(ROUTES.ROADMAP, {
          state: {
            syllabusId: result.syllabus_id,
            sessionId: result.session_id,
            title: result.title,
            topics: result.topics,
            roadmap: result.roadmap,
            roadmapMode: result.roadmap_mode,
          },
        })
    } catch {
      // Error handled by the mutation's onError or the form
    }
  }

  const handleSuggestion = (suggestion: string) => {
    setGoal(suggestion)
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
        {/* ── Header ─────────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="mb-8"
        >
          <div className="flex items-center gap-3 mb-2">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary/10 text-primary">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-2xl font-display font-bold text-text-primary">
                What do you want to learn?
              </h1>
              <p className="text-sm text-text-secondary">
                I'll create a personalized curriculum and guide you through it step by step
              </p>
            </div>
          </div>
        </motion.div>

        {/* ── Input Form ─────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.1 }}
        >
          <Card padding="lg" className="mb-8">
            <form onSubmit={handleSubmit} className="space-y-4">
              {createGoal.isError && (
                <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400">
                  {getErrorMessage(createGoal.error)}
                </div>
              )}

              <div>
                <label htmlFor="goal-input" className="block text-sm font-medium text-text-primary mb-2">
                  Describe what you want to learn
                </label>
                <textarea
                  id="goal-input"
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  placeholder="e.g. I want to learn Python from scratch, or Teach me machine learning..."
                  className="w-full h-28 px-4 py-3 text-sm rounded-lg bg-surface border border-surface-border text-text-primary placeholder:text-text-muted transition-all duration-200 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary hover:border-text-muted resize-none"
                  maxLength={500}
                  disabled={isSubmitting}
                  autoFocus
                />
                <div className="flex justify-between mt-1.5">
                  <p className="text-xs text-text-muted">
                    Be as specific as you like — I'll figure out the best learning path
                  </p>
                  <span className="text-xs text-text-muted tabular-nums">
                    {goal.length}/500
                  </span>
                </div>
              </div>

              <Button
                type="submit"
                size="lg"
                loading={isSubmitting}
                disabled={!goal.trim()}
                className="w-full sm:w-auto"
              >
                {isSubmitting ? (
                  'Creating your learning plan...'
                ) : (
                  <>
                    Create Learning Plan
                    <ArrowRight className="h-4 w-4 ml-1" />
                  </>
                )}
              </Button>
            </form>
          </Card>
        </motion.div>

        {/* ── Suggestions ────────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.2 }}
        >
          <h2 className="text-sm font-medium text-text-secondary mb-3 flex items-center gap-2">
            <Lightbulb className="h-4 w-4" />
            Try one of these
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {SUGGESTED_GOALS.map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => handleSuggestion(suggestion)}
                disabled={isSubmitting}
                className="flex items-center gap-3 px-4 py-3 rounded-lg bg-surface border border-surface-border text-left text-sm text-text-secondary hover:text-text-primary hover:border-primary/30 hover:bg-surface-hover transition-all duration-200 disabled:opacity-50"
              >
                <BookOpen className="h-4 w-4 shrink-0 text-primary" />
                <span>{suggestion}</span>
              </button>
            ))}
          </div>
        </motion.div>

        {/* ── How it works ───────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.3 }}
          className="mt-10 grid grid-cols-1 sm:grid-cols-3 gap-4"
        >
          {[
            { icon: BrainCircuit, title: '1. AI Analysis', desc: 'I analyze your goal and break it into structured topics' },
            { icon: Target, title: '2. Learning Roadmap', desc: 'A personalized curriculum is created with clear milestones' },
            { icon: Sparkles, title: '3. Adaptive Learning', desc: 'Lessons, quizzes, and progress tracking adapt to your pace' },
          ].map((step) => (
            <div key={step.title} className="flex flex-col items-center text-center p-4">
              <step.icon className="h-8 w-8 text-primary mb-2" aria-hidden="true" />
              <h3 className="text-sm font-semibold text-text-primary mb-1">{step.title}</h3>
              <p className="text-xs text-text-muted leading-relaxed">{step.desc}</p>
            </div>
          ))}
        </motion.div>
      </div>
    </div>
  )
}
