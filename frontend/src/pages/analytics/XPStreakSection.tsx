import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { Card, SectionHeader, Badge, Skeleton } from '@/components/ui'
import { ProgressRing, AnimatedCounter } from '@/components/visualizations'
import { useLearningStreak, useDashboard } from '@/services/learningApi'
import { Zap, Flame, Trophy, Target, Sparkles, Clock } from 'lucide-react'
import { cn } from '@/utils/cn'

interface XPStreakProps {
  className?: string
}

export function XPStreakSection({ className }: XPStreakProps) {
  const { data: streak, isLoading: streakLoading } = useLearningStreak()
  const { data: dashboard, isLoading: dashLoading } = useDashboard()

  const isLoading = streakLoading || dashLoading

  const currentStreak = streak?.current_streak_days ?? dashboard?.current_streak_days ?? 0
  const longestStreak = streak?.longest_streak_days ?? 0
  const streakActive = streak?.streak_active ?? false

  // Mock XP and level (presentation only, using backend data where available)
  const currentXP = useMemo(() => {
    // Calculate rough XP from activity
    const sessions = dashboard?.recent_sessions ?? 0
    const mastery = dashboard?.overall_mastery ?? 0
    return sessions * 50 + Math.round(mastery * 2)
  }, [dashboard?.recent_sessions, dashboard?.overall_mastery])

  const currentLevel = useMemo(() => {
    if (currentXP < 500) return 1
    if (currentXP < 1500) return 2
    if (currentXP < 3000) return 3
    if (currentXP < 5000) return 4
    if (currentXP < 7500) return 5
    if (currentXP < 10000) return 6
    if (currentXP < 15000) return 7
    if (currentXP < 20000) return 8
    return Math.floor(currentXP / 2500) + 1
  }, [currentXP])

  const xpForNextLevel = useMemo(() => {
    if (currentLevel === 1) return 500
    if (currentLevel === 2) return 1500
    if (currentLevel === 3) return 3000
    if (currentLevel === 4) return 5000
    if (currentLevel === 5) return 7500
    if (currentLevel === 6) return 10000
    if (currentLevel === 7) return 15000
    if (currentLevel === 8) return 20000
    return currentLevel * 2500
  }, [currentLevel])

  const xpProgress = useMemo(() => {
    // For display purposes — show progress towards next level milestone
    const prevMilestone = currentLevel === 1 ? 0 : [0, 500, 1500, 3000, 5000, 7500, 10000, 15000][currentLevel - 1] ?? (currentLevel - 1) * 2500
    const nextMilestone = xpForNextLevel
    const progressInLevel = currentXP - prevMilestone
    const range = nextMilestone - prevMilestone
    return range > 0 ? Math.min(Math.round((progressInLevel / range) * 100), 100) : 0
  }, [currentXP, currentLevel, xpForNextLevel])

  if (isLoading) {
    return (
      <div className={cn('space-y-4', className)} aria-label="Loading XP and streak">
        <div className="flex items-center gap-4">
          <Skeleton variant="circular" className="h-24 w-24" />
          <div className="space-y-2">
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-4 w-24" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Skeleton variant="rectangular" className="h-20 rounded-lg" />
          <Skeleton variant="rectangular" className="h-20 rounded-lg" />
        </div>
      </div>
    )
  }

  return (
    <motion.div
      className={cn('space-y-6', className)}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      aria-label="XP and streak overview"
    >
      {/* Level & XP */}
      <div className="flex items-center gap-6">
        <div className="relative">
          <ProgressRing
            value={xpProgress}
            size={96}
            strokeWidth={8}
            color="primary"
            label={`Level ${currentLevel} progress`}
          />
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="font-display text-xl font-bold text-text-primary">
              {currentLevel}
            </span>
          </div>
        </div>
        <div className="flex-1 space-y-2">
          <h3 className="font-display text-lg font-semibold text-text-primary">
            Level {currentLevel}
          </h3>
          <p className="text-sm text-text-secondary">
            <AnimatedCounter value={currentXP} suffix=" XP" />
          </p>
          <div className="space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-text-muted">Next level</span>
              <span className="text-text-secondary tabular-nums">
                {currentXP} / {xpForNextLevel.toLocaleString()} XP
              </span>
            </div>
            <div className="h-2 bg-surface-border rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-primary rounded-full"
                initial={{ width: 0 }}
                animate={{ width: `${xpProgress}%` }}
                transition={{ duration: 0.8, ease: 'easeOut' }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Streak Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Current Streak */}
        <Card className="border-secondary/20">
          <div className="flex items-center gap-4">
            <div className={cn(
              'h-14 w-14 rounded-xl flex items-center justify-center',
              streakActive
                ? 'bg-secondary-muted text-secondary'
                : 'bg-surface-border text-text-muted'
            )}>
              <Flame className={cn('h-7 w-7', streakActive && 'animate-pulse')} />
            </div>
            <div>
              <p className="text-xs text-text-muted uppercase tracking-wider font-medium">
                Current Streak
              </p>
              <p className="font-display text-3xl font-bold text-text-primary tabular-nums mt-0.5">
                {currentStreak}
              </p>
              <p className="text-xs text-text-secondary">
                {currentStreak === 0
                  ? 'Start today to begin your streak'
                  : streakActive
                    ? 'Active — keep going!'
                    : `${currentStreak} day${currentStreak === 1 ? '' : 's'} total`}
              </p>
            </div>
          </div>
        </Card>

        {/* Longest Streak */}
        <Card>
          <div className="flex items-center gap-4">
            <div className="h-14 w-14 rounded-xl bg-primary-muted text-primary flex items-center justify-center">
              <Trophy className="h-7 w-7" />
            </div>
            <div>
              <p className="text-xs text-text-muted uppercase tracking-wider font-medium">
                Longest Streak
              </p>
              <p className="font-display text-3xl font-bold text-text-primary tabular-nums mt-0.5">
                {longestStreak}
              </p>
              <p className="text-xs text-text-secondary">
                {longestStreak === 0
                  ? 'No streak data yet'
                  : `${longestStreak} day${longestStreak === 1 ? '' : 's'} record`}
              </p>
            </div>
          </div>
        </Card>

        {/* Weekly Goal */}
        <Card>
          <div className="flex items-center gap-4">
            <div className="h-14 w-14 rounded-xl bg-primary-muted text-primary flex items-center justify-center">
              <Target className="h-7 w-7" />
            </div>
            <div>
              <p className="text-xs text-text-muted uppercase tracking-wider font-medium">
                Weekly Goal
              </p>
              <p className="font-display text-2xl font-bold text-text-primary tabular-nums mt-0.5">
                {Math.round((dashboard?.weekly_study_time_minutes ?? 0) / 60 * 10) / 10}h
              </p>
              <p className="text-xs text-text-secondary">
                {dashboard?.weekly_study_time_minutes ?? 0 > 0
                  ? `${Math.round((dashboard?.weekly_study_time_minutes ?? 0) / 60 * 10) / 10}h this week`
                  : 'No study time this week'}
              </p>
            </div>
          </div>
        </Card>

        {/* Daily Activity */}
        <Card>
          <div className="flex items-center gap-4">
            <div className="h-14 w-14 rounded-xl bg-primary-muted text-primary flex items-center justify-center">
              <Sparkles className="h-7 w-7" />
            </div>
            <div>
              <p className="text-xs text-text-muted uppercase tracking-wider font-medium">
                Daily Study
              </p>
              <p className="font-display text-2xl font-bold text-text-primary tabular-nums mt-0.5">
                {dashboard?.daily_study_time_minutes ?? 0 > 0
                  ? `${dashboard?.daily_study_time_minutes ?? 0}m`
                  : '—'}
              </p>
              <p className="text-xs text-text-secondary">
                {dashboard?.daily_study_time_minutes ?? 0 > 0
                  ? 'Today\'s activity'
                  : 'No activity today'}
              </p>
            </div>
          </div>
        </Card>
      </div>
    </motion.div>
  )
}
