import { EmptyState } from '@/components/ui'
import { FolderOpen } from 'lucide-react'

export function ResourcesPage() {
  return (
    <div className="p-6">
      <EmptyState
        title="Resources"
        description="Your saved resources and learning materials will appear here."
        icon={<FolderOpen className="h-12 w-12" />}
      />
    </div>
  )
}
