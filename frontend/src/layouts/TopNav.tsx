import { Search, Moon } from 'lucide-react'
import { useAuth } from '@/contexts/AuthContext'
import { Avatar } from '@/components/ui'
import { useLocation } from 'react-router-dom'

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/learning': 'Learning',
  '/roadmap': 'Roadmap',
  '/analytics': 'Analytics',
  '/resources': 'Resources',
  '/settings': 'Settings',
  '/goal': 'Learning Goal',
}

export function TopNav() {
  const { user } = useAuth()
  const location = useLocation()

  const title = pageTitles[location.pathname] || 'AAA'

  if (!user) return null

  return (
    <header
      className="h-14 border-b border-surface-border flex items-center justify-between px-6 bg-surface/50 backdrop-blur-sm"
      role="banner"
    >
      {/* Left: Page title */}
      <div>
        <h1 className="text-base font-display font-semibold text-text-primary">{title}</h1>
      </div>

      {/* Right: Search, Theme, Profile */}
      <div className="flex items-center gap-3">
        {/* Search */}
        <button
          className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm text-text-muted bg-surface border border-surface-border hover:border-text-muted transition-colors focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2"
          aria-label="Search"
        >
          <Search className="h-4 w-4" />
          <span className="hidden sm:inline">Search...</span>
          <kbd className="hidden md:inline-flex text-[10px] px-1 py-0.5 rounded bg-surface-border text-text-muted font-mono">
            Ctrl+K
          </kbd>
        </button>

        {/* Theme toggle placeholder */}
        <button
          className="p-2 rounded-md text-text-muted hover:text-text-secondary hover:bg-surface-hover transition-colors focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2"
          aria-label="Toggle theme"
        >
          <Moon className="h-4 w-4" />
        </button>

        {/* Profile */}
        <div className="flex items-center gap-2 pl-3 border-l border-surface-border">
          <Avatar name={user.username} size="sm" />
          <span className="text-sm text-text-primary hidden sm:inline">{user.username}</span>
        </div>
      </div>
    </header>
  )
}
