import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/utils/cn'
import { Sparkles, X, Loader2, ArrowUp } from 'lucide-react'

type MentorState = 'idle' | 'expanded' | 'collapsed' | 'loading'

export function AiMentor() {
  const [mentorState, setMentorState] = useState<MentorState>('collapsed')

  const toggle = () => {
    if (mentorState === 'collapsed') {
      setMentorState('expanded')
    } else {
      setMentorState('collapsed')
    }
  }

  const isOpen = mentorState === 'expanded' || mentorState === 'loading'

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
                  <Loader2 className="h-6 w-6 text-primary animate-spin" />
                  <p className="text-sm text-text-muted">Thinking...</p>
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-sm text-text-secondary leading-relaxed">
                    I'm your AI learning assistant. Ask me anything about your current topic, 
                    or get help understanding a concept.
                  </p>
                  {/* Quick actions */}
                  <div className="flex flex-wrap gap-2">
                    {['Explain this topic', 'Give an example', 'Simplify'].map((action) => (
                      <button
                        key={action}
                        className="px-3 py-1.5 text-xs font-medium text-primary bg-primary-muted rounded-md hover:bg-primary/20 transition-colors"
                      >
                        {action}
                      </button>
                    ))}
                  </div>
                  {/* Input */}
                  <div className="flex items-center gap-2 p-2 bg-background rounded-lg border border-surface-border">
                    <input
                      type="text"
                      placeholder="Ask a question..."
                      className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted outline-none"
                    />
                    <button className="p-1.5 rounded-md bg-primary text-text-inverse hover:bg-primary-hover transition-colors">
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
        {!isOpen && <span className="text-sm font-medium">AI Mentor</span>}
      </motion.button>
    </div>
  )
}
