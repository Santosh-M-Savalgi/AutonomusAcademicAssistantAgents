import { useState, useMemo } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/utils/cn'
import {
  Sparkles,
  X,
  Loader2,
  ArrowUp,
  Lightbulb,
  BrainCircuit,
  BookOpen,
  Target,
  TrendingUp,
  Award,
  Zap,
  AlertTriangle,
} from 'lucide-react'
import { useDashboard, useTopicProgress, useLearningStreak, useRecommendations } from '@/services/learningApi'

type MentorState = 'idle' | 'expanded' | 'collapsed' | 'loading'

interface Suggestion {
  icon: React.ReactNode
  text: string
  action?: string
}

/* ─── Analytics Insights Hook ─────────────────────────────── */

function useAnalyticsInsights() {
  const { data: dashboard } = useDashboard()
  const { data: topics } = useTopicProgress()
  const { data: streak } = useLearningStreak()
  const { data: recommendations } = useRecommendations()

  return useMemo(() => {
    const insights: Suggestion[] = []

    if (!dashboard) return insights

    const overallMastery = dashboard.overall_mastery ?? 0
    const avgQuizScore = dashboard.average_quiz_score ?? 0
    const currentStreak = streak?.current_streak_days ?? dashboard.current_streak_days ?? 0
    const studyTime = dashboard.daily_study_time_minutes ?? 0
    const weakestTopic = dashboard.weakest_topic
    const strongestTopic = dashboard.strongest_topic
    const recommendedTopic = dashboard.recommended_next_topic

    // Mastery insight
    if (overallMastery > 70) {
      insights.push({
        icon: <Award className="h-3.5 w-3.5 text-secondary" />,
        text: `Your overall mastery is ${Math.round(overallMastery)}% — strong progress!`,
      })
    } else if (overallMastery > 40) {
      insights.push({
        icon: <TrendingUp className="h-3.5 w-3.5 text-primary" />,
        text: `Your mastery is at ${Math.round(overallMastery)}% — consistent study will improve this.`,
      })
    }

    // Quiz insight
    if (avgQuizScore > 80) {
      insights.push({
        icon: <BrainCircuit className="h-3.5 w-3.5 text-secondary" />,
        text: `Quiz accuracy at ${Math.round(avgQuizScore)}% — you're understanding the material well.`,
      })
    } else if (avgQuizScore > 50) {
      insights.push({
        icon: <Target className="h-3.5 w-3.5 text-primary" />,
        text: `Quiz accuracy is ${Math.round(avgQuizScore)}% — review weak areas to improve.`,
      })
    }

    // Streak insight
    if (currentStreak > 0) {
      insights.push({
        icon: <Zap className="h-3.5 w-3.5 text-secondary" />,
        text: currentStreak >= 7
          ? `Your ${currentStreak}-day streak is impressive — keep the momentum!`
          : `You're on a ${currentStreak}-day streak — stay consistent!`,
      })
    }

    // Weakest topic
    if (weakestTopic) {
      insights.push({
        icon: <AlertTriangle className="h-3.5 w-3.5 text-warning" />,
        text: `"${weakestTopic}" needs attention — consider reviewing this topic.`,
      })
    }

    // Strongest topic
    if (strongestTopic) {
      insights.push({
        icon: <Award className="h-3.5 w-3.5 text-secondary" />,
        text: `Your strongest topic is "${strongestTopic}". Great work!`,
      })
    }

    // Recommended topic
    if (recommendedTopic) {
      insights.push({
        icon: <Lightbulb className="h-3.5 w-3.5 text-primary" />,
        text: `Next up: "${recommendedTopic}" — ready to start?`,
        action: 'Start topic',
      })
    }

    // Weak concepts from topic data
    const weakTopics = topics?.filter((t) => t.mastery_percentage < 50 && t.quiz_attempts > 0)
    if (weakTopics && weakTopics.length > 0) {
      insights.push({
        icon: <AlertTriangle className="h-3.5 w-3.5 text-danger" />,
        text: `You have ${weakTopics.length} topic${weakTopics.length === 1 ? '' : 's'} below 50% mastery.`,
      })
    }

    // Study time insight
    if (studyTime > 0 && studyTime < 15) {
      insights.push({
        icon: <TrendingUp className="h-3.5 w-3.5 text-primary" />,
        text: 'Try to study at least 15 minutes daily for best results.',
      })
    } else if (studyTime >= 30) {
      insights.push({
        icon: <Sparkles className="h-3.5 w-3.5 text-primary" />,
        text: `Great study session today (${studyTime}m) — consistency builds mastery!`,
      })
    }

    // Limit to 4 insights
    return insights.slice(0, 4)
  }, [dashboard, topics, streak, recommendations])
}

/* ─── Page Suggestions ────────────────────────────────────── */

const pageSuggestions: Record<string, Suggestion[]> = {
  '/': [
    { icon: <Target className="h-3.5 w-3.5" />, text: 'Continue where you stopped', action: 'Resume learning' },
    { icon: <Lightbulb className="h-3.5 w-3.5" />, text: 'Try setting a daily study goal' },
  ],
  '/learning': [
    { icon: <BookOpen className="h-3.5 w-3.5" />, text: 'Pick a topic to start learning' },
    { icon: <BrainCircuit className="h-3.5 w-3.5" />, text: 'Review your roadmap for context' },
  ],
  '/roadmap': [
    { icon: <Target className="h-3.5 w-3.5" />, text: 'Your roadmap shows the big picture' },
    { icon: <Lightbulb className="h-3.5 w-3.5" />, text: 'Click any topic to begin learning' },
  ],
  '/analytics': [
    { icon: <TrendingUp className="h-3.5 w-3.5" />, text: 'Track your mastery growth over time' },
    { icon: <Target className="h-3.5 w-3.5" />, text: 'Focus on weak topics to improve scores' },
  ],
  '/profile': [
    { icon: <Award className="h-3.5 w-3.5" />, text: 'Check your achievements and milestones' },
    { icon: <Zap className="h-3.5 w-3.5" />, text: 'Your streak is a key success indicator' },
  ],
}

const mentorQuickActions: Suggestion[] = [
  { icon: <Lightbulb className="h-3.5 w-3.5" />, text: 'Explain this topic' },
  { icon: <BrainCircuit className="h-3.5 w-3.5" />, text: 'Give an example' },
  { icon: <BookOpen className="h-3.5 w-3.5" />, text: 'Simplify' },
]

export function AiMentor() {
  const [mentorState, setMentorState] = useState<MentorState>('collapsed')
  const [inputValue, setInputValue] = useState('')
  const location = useLocation()
  const navigate = useNavigate()
  const analyticsInsights = useAnalyticsInsights()

  const suggestions = useMemo(() => {
    // Analytics page gets AI-driven insights
    if (location.pathname === '/analytics') {
      return analyticsInsights.length > 0
        ? analyticsInsights
        : [
            { icon: <TrendingUp className="h-3.5 w-3.5" />, text: 'Complete lessons to see analytics insights' },
            { icon: <Target className="h-3.5 w-3.5" />, text: 'Take a quiz to measure your progress' },
          ]
    }

    // Profile page gets insights
    if (location.pathname.startsWith('/profile')) {
      return analyticsInsights.length > 0
        ? analyticsInsights
        : [
            { icon: <Target className="h-3.5 w-3.5" />, text: 'Track your progress and celebrate wins', action: 'View stats' },
            { icon: <Award className="h-3.5 w-3.5" />, text: 'Complete topics to unlock achievements' },
          ]
    }

    // Specific page suggestions
    for (const [path, s] of Object.entries(pageSuggestions)) {
      if (location.pathname === path) return s
    }

    // Lesson page
    if (location.pathname.startsWith('/lesson/')) {
      return [
        { icon: <Lightbulb className="h-3.5 w-3.5" />, text: 'Need help understanding this concept?', action: 'Ask' },
        { icon: <BrainCircuit className="h-3.5 w-3.5" />, text: 'Give me a real-world analogy' },
      ]
    }

    // Quiz page
    if (location.pathname.startsWith('/quiz/')) {
      return [
        { icon: <Lightbulb className="h-3.5 w-3.5" />, text: 'Review pointers before retrying', action: 'Review' },
        { icon: <Target className="h-3.5 w-3.5" />, text: 'Take your time and read each option carefully' },
      ]
    }

    // Quiz results
    if (location.pathname.startsWith('/quiz-results/')) {
      return [
        { icon: <Lightbulb className="h-3.5 w-3.5" />, text: 'Focus on weak areas for better results', action: 'Review' },
        { icon: <Target className="h-3.5 w-3.5" />, text: 'Review the lesson content before retrying' },
      ]
    }

    return mentorQuickActions
  }, [location.pathname, analyticsInsights])

  const toggle = () => {
    setMentorState((prev) => (prev === 'collapsed' ? 'expanded' : 'collapsed'))
  }

  const isOpen = mentorState === 'expanded' || mentorState === 'loading'

  const handleSend = () => {
    if (!inputValue.trim()) return
    setInputValue('')
    setMentorState('loading')
    setTimeout(() => {
      setMentorState('expanded')
    }, 1500)
  }

  return (
    <div className="fixed bottom-6 right-6 z-40 flex flex-col items-end gap-3">
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.9 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="w-80 bg-surface border border-surface-border rounded-xl shadow-elevated overflow-hidden"
            role="dialog"
            aria-label="AI Mentor chat"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
              <div className="flex items-center gap-2">
                <div className="h-6 w-6 rounded-full bg-primary-muted flex items-center justify-center">
                  <Sparkles className="h-3.5 w-3.5 text-primary" />
                </div>
                <span className="text-sm font-medium text-text-primary">AI Mentor</span>
              </div>
              <button
                onClick={toggle}
                className="p-1 rounded-md text-text-muted hover:text-text-primary transition-colors"
                aria-label="Close mentor"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Content */}
            <div className="p-4">
              {mentorState === 'loading' ? (
                <div className="flex flex-col items-center py-8 gap-3">
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
                  >
                    <Sparkles className="h-8 w-8 text-primary" />
                  </motion.div>
                  <p className="text-sm text-text-muted">Thinking...</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {/* Greeting */}
                  <p className="text-sm text-text-secondary leading-relaxed">
                    {location.pathname === '/analytics' || location.pathname.startsWith('/profile')
                      ? "Here are your learning insights based on your recent activity."
                      : "I'm your AI learning assistant. Ask me anything about your current topic, or get help understanding a concept."}
                  </p>

                  {/* Contextual suggestions / insights */}
                  <div className="space-y-1.5">
                    <p className="text-xs font-medium text-text-muted uppercase tracking-wider">
                      {location.pathname === '/analytics' || location.pathname.startsWith('/profile')
                        ? 'Insights'
                        : 'Suggestions'}
                    </p>
                    <div className="space-y-1">
                      {suggestions.map((suggestion, i) => (
                        <motion.button
                          key={i}
                          initial={{ opacity: 0, x: -5 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: i * 0.05 }}
                          onClick={() => {
                            if (suggestion.action === 'Start topic' && suggestion.text.includes('"')) {
                              navigate('/roadmap')
                            }
                            setInputValue(suggestion.text)
                          }}
                          className={cn(
                            'flex items-center gap-2 w-full text-left p-2 rounded-md text-xs',
                            'text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors'
                          )}
                        >
                          <span className="text-primary shrink-0">{suggestion.icon}</span>
                          <span>{suggestion.text}</span>
                        </motion.button>
                      ))}
                    </div>
                  </div>

                  {/* Quick actions */}
                  <div className="flex flex-wrap gap-2 pt-1">
                    {mentorQuickActions.slice(0, 3).map((action) => (
                      <button
                        key={action.text}
                        onClick={() => setInputValue(action.text)}
                        className="px-3 py-1.5 text-xs font-medium text-primary bg-primary-muted rounded-md hover:bg-primary/20 transition-colors"
                      >
                        {action.text}
                      </button>
                    ))}
                  </div>

                  {/* Input */}
                  <div className="flex items-center gap-2 p-2 bg-background rounded-lg border border-surface-border">
                    <input
                      type="text"
                      value={inputValue}
                      onChange={(e) => setInputValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault()
                          handleSend()
                        }
                      }}
                      placeholder="Ask a question..."
                      className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted outline-none"
                      aria-label="Ask AI Mentor a question"
                    />
                    <button
                      onClick={handleSend}
                      disabled={!inputValue.trim()}
                      className={cn(
                        'p-1.5 rounded-md transition-colors',
                        inputValue.trim()
                          ? 'bg-primary text-text-inverse hover:bg-primary-hover'
                          : 'bg-surface-border text-text-muted cursor-not-allowed'
                      )}
                      aria-label="Send message"
                    >
                      <ArrowUp className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Floating pill button */}
      <motion.button
        onClick={toggle}
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        className={cn(
          'flex items-center gap-2 px-4 py-2.5 rounded-full shadow-elevated transition-colors',
          isOpen
            ? 'bg-surface border border-surface-border text-text-secondary'
            : 'bg-primary text-text-inverse hover:bg-primary-hover'
        )}
        aria-label={isOpen ? 'Close AI Mentor' : 'Open AI Mentor'}
      >
        <Sparkles className={cn('h-4 w-4', isOpen ? 'text-primary' : 'text-text-inverse')} />
        <AnimatePresence>
          {!isOpen && (
            <motion.span
              initial={{ opacity: 0, width: 0 }}
              animate={{ opacity: 1, width: 'auto' }}
              exit={{ opacity: 0, width: 0 }}
              className="text-sm font-medium whitespace-nowrap overflow-hidden"
            >
              AI Mentor
            </motion.span>
          )}
        </AnimatePresence>
      </motion.button>
    </div>
  )
}
