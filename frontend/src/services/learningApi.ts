import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/api/client'
import type {
  DashboardSummary,
  TopicProgress,
  Recommendation,
  LearningStreak,
  LearningPath,
  Lesson,
  LessonRequest,
  Quiz,
  QuizGenerateRequest,
  EvaluateRequest,
  EvaluateResult,
  SyllabusGraph,
  AdaptiveStatus,
  WeakConcepts,
  SessionData,
} from '@/types/learning'

// ─── Dashboard Hooks ──────────────────────────────────────────

export function useDashboard() {
  return useQuery<DashboardSummary>({
    queryKey: ['dashboard'],
    queryFn: async () => {
      const { data } = await apiClient.get('/api/v2/dashboard')
      return data
    },
  })
}

export function useTopicProgress() {
  return useQuery<TopicProgress[]>({
    queryKey: ['dashboard', 'progress'],
    queryFn: async () => {
      const { data } = await apiClient.get('/api/v2/dashboard/progress')
      return data
    },
  })
}

export function useRecommendations() {
  return useQuery<Recommendation[]>({
    queryKey: ['dashboard', 'recommendations'],
    queryFn: async () => {
      const { data } = await apiClient.get('/api/v2/dashboard/recommendations')
      return data
    },
  })
}

export function useLearningStreak() {
  return useQuery<LearningStreak>({
    queryKey: ['dashboard', 'streak'],
    queryFn: async () => {
      const { data } = await apiClient.get('/api/v2/dashboard/streak')
      return data
    },
  })
}

// ─── Knowledge Graph / Roadmap Hooks ──────────────────────────

export function useSyllabusGraph(syllabusId: string) {
  return useQuery<SyllabusGraph>({
    queryKey: ['knowledge-graph', syllabusId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/api/v2/knowledge-graph/${syllabusId}`)
      return data
    },
    enabled: !!syllabusId,
  })
}

export function useLearningPath(
  syllabusTopicIds: string[],
  masteryScores: Record<string, number> = {},
  mode: string = 'standard'
) {
  return useQuery<LearningPath>({
    queryKey: ['learning-path', { syllabusTopicIds, masteryScores, mode }],
    queryFn: async () => {
      const { data } = await apiClient.post('/api/v2/knowledge-graph/learning-path', {
        syllabus_topic_ids: syllabusTopicIds,
        mastery_scores: masteryScores,
        mode,
      })
      return data
    },
    enabled: syllabusTopicIds.length > 0,
  })
}

// ─── Lesson Hooks ─────────────────────────────────────────────

export function useGenerateLesson() {
  return useMutation({
    mutationFn: async (request: LessonRequest) => {
      const { data } = await apiClient.post<Lesson>('/api/v2/lessons/lesson', request)
      return data
    },
  })
}

// ─── Quiz Hooks ───────────────────────────────────────────────

export function useGenerateQuiz() {
  return useMutation({
    mutationFn: async (request: QuizGenerateRequest) => {
      const { data } = await apiClient.post<Quiz>('/api/v2/quiz/generate', request)
      return data
    },
  })
}

export function useEvaluateQuiz() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (request: EvaluateRequest) => {
      const { data } = await apiClient.post<EvaluateResult>('/api/v2/quiz/evaluate', request)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}

// ─── Adaptive Hooks ───────────────────────────────────────────

export function useAdaptiveStatus() {
  return useQuery<AdaptiveStatus>({
    queryKey: ['adaptive', 'status'],
    queryFn: async () => {
      const { data } = await apiClient.get('/api/v2/adaptive/status')
      return data
    },
  })
}

export function useWeakConcepts(
  masteryScores: Record<string, number>,
  currentTopicId?: string
) {
  return useQuery<WeakConcepts>({
    queryKey: ['adaptive', 'weak-concepts', { masteryScores, currentTopicId }],
    queryFn: async () => {
      const { data } = await apiClient.post('/api/v2/knowledge-graph/weak-concepts', {
        mastery_scores: masteryScores,
        current_topic_id: currentTopicId,
      })
      return data
    },
    enabled: Object.keys(masteryScores).length > 0,
  })
}

// ─── Session Hooks ────────────────────────────────────────────

export function useCreateSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (params: { syllabus_id?: string; session_id?: string; metadata?: Record<string, unknown> }) => {
      const { data } = await apiClient.post<SessionData>('/api/v2/sessions', params)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })
}

export function useSession(sessionId: string) {
  return useQuery<SessionData>({
    queryKey: ['sessions', sessionId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/api/v2/sessions/${sessionId}`)
      return data
    },
    enabled: !!sessionId,
  })
}

export function useCompleteSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (sessionId: string) => {
      const { data } = await apiClient.post(`/api/v2/sessions/${sessionId}/complete`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}
