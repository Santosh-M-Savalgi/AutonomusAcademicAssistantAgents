import { motion } from 'framer-motion'
import { Card, StatCard, SectionHeader, EmptyState } from '@/components/ui'
import { BookOpen, Zap, TrendingUp, Clock } from 'lucide-react'

export function DashboardPage() {
  return (
    <div className="p-6 space-y-6">
      <SectionHeader
        title="Dashboard"
        description="Overview of your learning progress"
      />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Current Streak" value="0 days" icon={<Zap className="h-4 w-4" />} variant="secondary" />
        <StatCard label="Topics Learned" value="0" icon={<BookOpen className="h-4 w-4" />} />
        <StatCard label="Mastery Rate" value="0%" icon={<TrendingUp className="h-4 w-4" />} />
        <StatCard label="Time Spent" value="0h" icon={<Clock className="h-4 w-4" />} />
      </div>

      <EmptyState
        title="Start your learning journey"
        description="Pick a topic or upload a syllabus to begin. Your progress will appear here."
        icon={<BookOpen className="h-12 w-12" />}
      />
    </div>
  )
}
