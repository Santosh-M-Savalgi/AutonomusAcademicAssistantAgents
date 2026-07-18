import { useState, type ReactNode } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/utils/cn'

interface Tab {
  id: string
  label: string
  icon?: ReactNode
}

interface TabsProps {
  tabs: Tab[]
  activeTab?: string
  onChange?: (tabId: string) => void
  className?: string
}

export function Tabs({ tabs, activeTab: externalActive, onChange, className }: TabsProps) {
  const [internalActive, setInternalActive] = useState(tabs[0]?.id ?? '')
  const activeId = externalActive ?? internalActive

  const handleChange = (id: string) => {
    if (!externalActive) setInternalActive(id)
    onChange?.(id)
  }

  return (
    <div className={cn('flex gap-1 p-1 bg-surface border border-surface-border rounded-lg', className)} role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={activeId === tab.id}
          onClick={() => handleChange(tab.id)}
          className={cn(
            'relative flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md transition-colors duration-200',
            activeId === tab.id
              ? 'text-text-primary'
              : 'text-text-muted hover:text-text-secondary'
          )}
        >
          {activeId === tab.id && (
            <motion.div
              layoutId="tab-indicator"
              className="absolute inset-0 bg-surface-hover rounded-md"
              transition={{ type: 'spring', stiffness: 500, damping: 35 }}
            />
          )}
          <span className="relative z-10 flex items-center gap-2">
            {tab.icon}
            {tab.label}
          </span>
        </button>
      ))}
    </div>
  )
}

// -- Section Divider --
interface SectionHeaderProps {
  title: string
  description?: string
  action?: ReactNode
  className?: string
}

export function SectionHeader({ title, description, action, className }: SectionHeaderProps) {
  return (
    <div className={cn('flex items-center justify-between', className)}>
      <div>
        <h2 className="text-lg font-semibold text-text-primary">{title}</h2>
        {description && <p className="text-sm text-text-secondary mt-0.5">{description}</p>}
      </div>
      {action && <div>{action}</div>}
    </div>
  )
}
