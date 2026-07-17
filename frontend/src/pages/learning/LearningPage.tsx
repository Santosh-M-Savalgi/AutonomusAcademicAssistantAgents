import { EmptyState } from '@/components/ui'
import { BookOpen } from 'lucide-react'

export function LearningPage() {
  return (
    <div className="p-6">
      <EmptyState
        title="Learning"
        description="Your active and completed lessons will appear here."
        icon={<BookOpen className="h-12 w-12" />}
      />
    </div>
  )
}
