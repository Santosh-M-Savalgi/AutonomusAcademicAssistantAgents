import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { Card, SectionHeader, Badge, Skeleton } from '@/components/ui'
import { ProgressRing, AnimatedCounter, TrendCard } from '@/components/visualizations'
import { useDashboard, useTopicProgress, useLearningStreak } from '@/services/learningApi'
import {
  Award,
  Zap,
  BookOpen,
  BrainCircuit,
  Target,
  Star,
  Trophy,
  Flame,
  CheckCircle,
  Clock,
  Medal,
  Sparkles,
  Shield,
} from 'lucide-react'
import { cn } from '@/utils/cn'

/* ─── Types ────────────────────────────────────────────────── */

interface Achievement {
  id: string
  title: string
  description: string
  icon: React.ReactNode
  unlocked: boolean
  progress?: number
  target?: number
  category: 'milestone' | 'streak' | 'mastery' | 'quiz' | 'course'
  rarity: 'common' | 'rare' | 'epic' | 'legendary'
}

/* ─── Variants ─────────────────────────────────────────────── */

const stagger = {
  animate: { transition: { staggerChildren: 0.04 } },
}

const fadeUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
}

/* ─── Rarity Styles ────────────────────────────────────────── */

const rarityColors: Record<string, string> = {
  common: 'border-surface-border bg-surface',
  rare: 'border-secondary/30 bg-secondary-muted/5',
  epic: 'border-primary/30 bg-primary-muted/10',
  legendary: 'border-warning/30 bg-warning/10',
}

const rarityGlow: Record<string, string> = {
  common: '',
  rare: 'shadow-[0_0_12px_rgba(232,169,59,0.1)]',
  epic: 'shadow-[0_0_12px_rgba(31,191,158,0.15)]',
  legendary: 'shadow-[0_0_16px_rgba(232,169,59,0.2)]',
}

/* ─── Achievement Card ─────────────────────────────────────── */

function AchievementCard({ achievement, index: _i }: { achievement: Achievement; index: number }) {
  return (
    <motion.div
      variants={fadeUp}
      className={cn(
        'rounded-lg border p-4 transition-all duration-300',
        achievement.unlocked
          ? cn(rarityColors[achievement.rarity], rarityGlow[achievement.rarity])
          : 'border-surface-border bg-surface opacity-50'
      )}
    >
      <div className="flex items-start gap-3">
        <div
          className={cn(
            'h-10 w-10 rounded-lg flex items-center justify-center shrink-0',
            achievement.unlocked
              ? achievement.rarity === 'legendary'
                ? 'bg-warning/20 text-warning'
                : achievement.rarity === 'epic'
                  ? 'bg-primary-muted text-primary'
                  : achievement.rarity === 'rare'
                    ? 'bg-secondary-muted text-secondary'
                    : 'bg-surface-border text-text-muted'
              : 'bg-surface-border text-text-muted'
          )}
        >
          {achievement.icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4
              className={cn(
                'text-sm font-semibold truncate',
                achievement.unlocked ? 'text-text-primary' : 'text-text-muted'
              )}
            >
              {achievement.title}
            </h4>
            <Badge size="sm" variant={achievement.unlocked ? 'primary' : 'default'}>
              {achievement.rarity}
            </Badge>
          </div>
          <p className="text-xs text-text-secondary mt-0.5">{achievement.description}</p>
          {!achievement.unlocked && achievement.progress !== undefined && achievement.target !== undefined && (
            <div className="mt-2 flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-surface-border rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full transition-all duration-500"
                  style={{ width: `${Math.min((achievement.progress / achievement.target) * 100, 100)}%` }}
                />
              </div>
              <span className="text-[10px] text-text-muted tabular-nums">
                {achievement.progress}/{achievement.target}
              </span>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  )
}

/* ─── Achievements Container ───────────────────────────────── */

export function AchievementsSection() {
  const { data: dashboard, isLoading: dashLoading } = useDashboard()
  const { data: topics, isLoading: topicsLoading } = useTopicProgress()
  const { data: streak, isLoading: streakLoading } = useLearningStreak()

  const isLoading = dashLoading || topicsLoading || streakLoading

  const topicsMastered = topics?.filter((t) => t.mastery_percentage >= 80).length ?? 0
  const totalTopics = topics?.length ?? 0
  const currentStreak = streak?.current_streak_days ?? dashboard?.current_streak_days ?? 0
  const longestStreak = streak?.longest_streak_days ?? 0
  const lessonCount = dashboard?.recent_sessions ?? 0
  const avgQuizScore = dashboard?.average_quiz_score ?? 0
  const studyTimeMinutes = dashboard?.daily_study_time_minutes ?? 0

  const achievements: Achievement[] = useMemo(() => [
    {
      id: 'first_topic',
      title: 'First Steps',
      description: 'Complete your first topic',
      icon: <BookOpen className="h-5 w-5" />,
      unlocked: totalTopics > 0,
      progress: totalTopics,
      target: 1,
      category: 'milestone',
      rarity: 'common',
    },
    {
      id: 'five_topics',
      title: 'Topic Explorer',
      description: 'Complete 5 topics',
      icon: <BookOpen className="h-5 w-5" />,
      unlocked: topicsMastered >= 5,
      progress: topicsMastered,
      target: 5,
      category: 'milestone',
      rarity: 'common',
    },
    {
      id: 'master_three',
      title: 'Master of Three',
      description: 'Master 3 topics with 80%+ proficiency',
      icon: <Target className="h-5 w-5" />,
      unlocked: topicsMastered >= 3,
      progress: topicsMastered,
      target: 3,
      category: 'mastery',
      rarity: 'rare',
    },
    {
      id: 'master_ten',
      title: 'Master Scholar',
      description: 'Master 10 topics',
      icon: <Award className="h-5 w-5" />,
      unlocked: topicsMastered >= 10,
      progress: topicsMastered,
      target: 10,
      category: 'mastery',
      rarity: 'epic',
    },
    {
      id: 'streak_3',
      title: 'Consistent Learner',
      description: 'Maintain a 3-day learning streak',
      icon: <Zap className="h-5 w-5" />,
      unlocked: currentStreak >= 3,
      progress: currentStreak,
      target: 3,
      category: 'streak',
      rarity: 'common',
    },
    {
      id: 'streak_7',
      title: 'Weekly Warrior',
      description: 'Maintain a 7-day learning streak',
      icon: <Flame className="h-5 w-5" />,
      unlocked: currentStreak >= 7,
      progress: currentStreak,
      target: 7,
      category: 'streak',
      rarity: 'rare',
    },
    {
      id: 'streak_30',
      title: 'Monthly Master',
      description: 'Maintain a 30-day learning streak',
      icon: <Flame className="h-5 w-5" />,
      unlocked: currentStreak >= 30,
      progress: currentStreak,
      target: 30,
      category: 'streak',
      rarity: 'legendary',
    },
    {
      id: 'perfect_quiz',
      title: 'Perfect Score',
      description: 'Score 100% on any quiz',
      icon: <Star className="h-5 w-5" />,
      unlocked: avgQuizScore === 100,
      progress: Math.round(avgQuizScore),
      target: 100,
      category: 'quiz',
      rarity: 'epic',
    },
    {
      id: 'quiz_champion',
      title: 'Quiz Champion',
      description: 'Average quiz score over 90%',
      icon: <BrainCircuit className="h-5 w-5" />,
      unlocked: avgQuizScore >= 90,
      progress: Math.round(avgQuizScore),
      target: 90,
      category: 'quiz',
      rarity: 'rare',
    },
    {
      id: 'ten_lessons',
      title: 'Dedicated Student',
      description: 'Complete 10 lessons',
      icon: <BookOpen className="h-5 w-5" />,
      unlocked: lessonCount >= 10,
      progress: lessonCount,
      target: 10,
      category: 'milestone',
      rarity: 'rare',
    },
    {
      id: 'fifty_lessons',
      title: 'Learning Marathon',
      description: 'Complete 50 lessons',
      icon: <Trophy className="h-5 w-5" />,
      unlocked: lessonCount >= 50,
      progress: lessonCount,
      target: 50,
      category: 'milestone',
      rarity: 'epic',
    },
    {
      id: 'longest_streak',
      title: 'Endurance',
      description: 'Achieve a 14-day longest streak',
      icon: <Flame className="h-5 w-5" />,
      unlocked: longestStreak >= 14,
      progress: longestStreak,
      target: 14,
      category: 'streak',
      rarity: 'epic',
    },
    {
      id: 'course_complete',
      title: 'Course Complete',
      description: 'Finish an entire course',
      icon: <CheckCircle className="h-5 w-5" />,
      unlocked: dashboard?.overall_completion === 100,
      progress: Math.round(dashboard?.overall_completion ?? 0),
      target: 100,
      category: 'course',
      rarity: 'legendary',
    },
    {
      id: 'study_hours',
      title: 'Time Investment',
      description: 'Study for 10+ hours total',
      icon: <Clock className="h-5 w-5" />,
      unlocked: studyTimeMinutes >= 600,
      progress: Math.round(studyTimeMinutes),
      target: 600,
      category: 'milestone',
      rarity: 'rare',
    },
  ], [topicsMastered, totalTopics, currentStreak, longestStreak, lessonCount, avgQuizScore, studyTimeMinutes, dashboard?.overall_completion])

  const unlockedCount = achievements.filter((a) => a.unlocked).length
  const totalCount = achievements.length

  if (isLoading) {
    return (
      <div className="space-y-4" aria-label="Loading achievements">
        <Skeleton className="h-6 w-48" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} variant="rectangular" className="h-24 rounded-lg" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <motion.div
      className="space-y-6"
      variants={stagger}
      initial="initial"
      animate="animate"
      aria-label="Achievements"
    >
      {/* Progress Summary */}
      <motion.div variants={fadeUp} className="flex items-center gap-6">
        <ProgressRing
          value={(unlockedCount / totalCount) * 100}
          size={80}
          strokeWidth={6}
          color="secondary"
          label="Achievement Progress"
        />
        <div>
          <h3 className="font-display text-lg font-semibold text-text-primary">
            {unlockedCount} / {totalCount} Achievements
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            {unlockedCount === 0
              ? 'Start learning to unlock your first achievement!'
              : unlockedCount === totalCount
                ? 'All achievements unlocked! You are a true mastery scholar.'
                : `${totalCount - unlockedCount} more to collect`}
          </p>
        </div>
      </motion.div>

      {/* Achievement Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {achievements.map((achievement, i) => (
          <AchievementCard key={achievement.id} achievement={achievement} index={i} />
        ))}
      </div>

      {/* Certificate Placeholder */}
      <motion.div variants={fadeUp}>
        <Card className="border-2 border-dashed border-surface-border text-center">
          <div className="py-8">
            <Medal className="h-12 w-12 text-text-muted mx-auto mb-3" />
            <h3 className="font-display text-base font-semibold text-text-primary mb-1">
              Certificates
            </h3>
            <p className="text-sm text-text-secondary max-w-md mx-auto">
              Complete a course to earn a certificate of completion. Certificates will appear here once available.
            </p>
          </div>
        </Card>
      </motion.div>
    </motion.div>
  )
}
