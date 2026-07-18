import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

/** Keys for persisting learning journey identity across navigations. */
const STORAGE_KEYS = {
  syllabusId: 'aaa_syllabus_id',
  sessionId: 'aaa_session_id',
  learningGoal: 'aaa_learning_goal',
} as const

interface LearningContextType {
  syllabusId: string
  sessionId: string
  learningGoal: string
  setLearningJourney: (syllabusId: string, sessionId: string, learningGoal: string) => void
  clearLearningJourney: () => void
}

const LearningContext = createContext<LearningContextType | null>(null)

function getStored(key: string): string {
  try {
    return localStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

export function LearningProvider({ children }: { children: ReactNode }) {
  const [syllabusId, setSyllabusId] = useState(() => getStored(STORAGE_KEYS.syllabusId))
  const [sessionId, setSessionId] = useState(() => getStored(STORAGE_KEYS.sessionId))
  const [learningGoal, setLearningGoal] = useState(() => getStored(STORAGE_KEYS.learningGoal))

  const setLearningJourney = useCallback(
    (sid: string, ssnId: string, goal: string) => {
      setSyllabusId(sid)
      setSessionId(ssnId)
      setLearningGoal(goal)
      try {
        localStorage.setItem(STORAGE_KEYS.syllabusId, sid)
        localStorage.setItem(STORAGE_KEYS.sessionId, ssnId)
        localStorage.setItem(STORAGE_KEYS.learningGoal, goal)
      } catch {
        // localStorage may be unavailable
      }
    },
    []
  )

  const clearLearningJourney = useCallback(() => {
    setSyllabusId('')
    setSessionId('')
    setLearningGoal('')
    try {
      localStorage.removeItem(STORAGE_KEYS.syllabusId)
      localStorage.removeItem(STORAGE_KEYS.sessionId)
      localStorage.removeItem(STORAGE_KEYS.learningGoal)
    } catch {
      // noop
    }
  }, [])

  return (
    <LearningContext.Provider
      value={{ syllabusId, sessionId, learningGoal, setLearningJourney, clearLearningJourney }}
    >
      {children}
    </LearningContext.Provider>
  )
}

export function useLearningJourney() {
  const ctx = useContext(LearningContext)
  if (!ctx) {
    throw new Error('useLearningJourney must be used within a LearningProvider')
  }
  return ctx
}
