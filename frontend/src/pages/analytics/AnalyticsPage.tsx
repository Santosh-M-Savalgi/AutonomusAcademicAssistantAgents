import { EmptyState } from '@/components/ui'
import { BarChart3 } from 'lucide-react'

export function AnalyticsPage() {
  return (
    <div className="p-6">
      <EmptyState
        title="Analytics"
        description="Your learning analytics and progress charts will appear here."
        icon={<BarChart3 className="h-12 w-12" />}
      />
    </div>
  )
}
