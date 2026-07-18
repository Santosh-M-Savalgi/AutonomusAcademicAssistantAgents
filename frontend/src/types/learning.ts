// ─── Learning Types ────────────────────────────────────────────

export interface TopicNode {
  id: string
  name: string
  slug: string
  difficulty: string
  learning_depth: number
  mastery_threshold: number
}

export interface TopicEdge {
  id: string
  parent_topic_id: string
  child_topic_id: string
  relationship_type: string
  weight: number
}

export interface SyllabusGraph {
  syllabus_id: string
  topics: TopicNode[]
  edges: TopicEdge[]
}

export interface LearningPathStep {
  topic_id: string
  topic_name: string
  topic_slug: string
  difficulty: string
  depth: number
  mastery_score: number
  is_completed: boolean
  is_blocked: boolean
  unmet_prerequisites: string[]
}

export interface LearningPath {
  mode: string
  total_topics: number
  completed_topics: number
  remaining_topics: number
  next_topic_id: string | null
  is_complete: boolean
  steps: LearningPathStep[]
}

// ─── Dashboard Types ──────────────────────────────────────────

export interface DashboardSummary {
  current_topic: string | null
  current_course: string | null
  overall_completion: number
  overall_mastery: number
  average_quiz_score: number
  weekly_study_time_minutes: number
  daily_study_time_minutes: number
  recent_sessions: number
  current_streak_days: number
  weakest_topic: string | null
  strongest_topic: string | null
  recommended_next_topic: string | null
  recent_activity?: ActivityEvent[]
}

export interface ActivityEvent {
  timestamp: string
  student_id: string
  session_id: string
  topic: string
  event_type: string
  metadata?: Record<string, unknown>
}

export interface TopicProgress {
  topic_id: string
  topic_name: string
  topic_slug: string
  completion_percentage: number
  mastery_percentage: number
  quiz_attempts: number
  average_score: number
  last_studied: string | null
  confidence_score: number
  recommended_review: boolean
  time_spent_minutes: number
}

export interface Recommendation {
  topic_id: string
  topic_name: string
  topic_slug: string
  reason: string
  priority: number
  recommendation_type: string
}

export interface LearningStreak {
  current_streak_days: number
  longest_streak_days: number
  last_activity_date: string
  streak_active: boolean
}

// ─── Lesson Types ─────────────────────────────────────────────

export interface TeachingCard {
  title: string
  body: string
  card_type: string
}

export interface YouTubeSuggestion {
  title: string
  url: string
  video_id: string
}

export interface Lesson {
  topic_id: string
  topic_name: string
  title: string
  cards: TeachingCard[]
  estimated_minutes: number
  learning_mode: string
  youtube_suggestions: YouTubeSuggestion[] | null
}

export interface LessonRequest {
  topic_id: string
  topic_name: string
  topic_description?: string
  topic_difficulty?: string
  learning_mode?: string
  mastery_score?: number
  prerequisite_context?: string
  student_preferences?: Record<string, unknown> | null
  user_id?: string
}

// ─── Quiz Types ───────────────────────────────────────────────

export interface QuizQuestion {
  id: string
  question: string
  options: string[]
  difficulty: string
  concept_tag: string
  bloom_level: string
  estimated_time_seconds: number
}

export interface Quiz {
  topic_id: string
  topic_name: string
  questions: QuizQuestion[]
  total_questions: number
  difficulty_breakdown: Record<string, number>
}

export interface QuizGenerateRequest {
  topic_id: string
  topic_name: string
  topic_description?: string
  topic_difficulty?: string
  mastery_score?: number
  num_questions?: number
  prerequisite_topics?: Array<{ id: string; name: string; mastery: number }> | null
}

export interface AnswerSubmission {
  question_id: string
  question: string
  selected_answer: string
  correct_answer: string
  is_correct: boolean
  concept_tag: string
  time_taken_seconds: number
}

export interface EvaluateRequest {
  topic_id: string
  topic_name: string
  topic_difficulty?: string
  attempts_on_current?: number
  mastery_score?: number
  prerequisite_topics?: Array<{ id: string; name: string; mastery: number }> | null
  answers: AnswerSubmission[]
}

export interface NextLessonInfo {
  topic_id: string
  topic_name: string
  topic_description: string
  topic_difficulty: string
}

export interface EvaluateResult {
  score: number
  total_questions: number
  correct_count: number
  incorrect_count: number
  weak_concept_tags: string[]
  strong_concept_tags: string[]
  feedback: string
  routing_decision: string
  routing_reason: string
  next_topic_id: string | null
  next_lesson: NextLessonInfo | null
}

// ─── Adaptive Types ───────────────────────────────────────────

export interface AdaptiveStatus {
  total_topics: number
  mastered_count: number
  current_topic_id: string | null
  current_topic_name: string | null
  current_state: string
  state_distribution: Record<string, number>
  overall_progress: number
}

export interface MasteryEntry {
  topic_id: string
  topic_name: string
  score: number
  confidence: number
  attempts_count: number
  threshold: number
  is_mastered: boolean
  is_weak: boolean
}

export interface WeakConcepts {
  weak_concepts: MasteryEntry[]
  prerequisite_deficiencies: MasteryEntry[]
  strongest_concepts: MasteryEntry[]
  has_deficiencies: boolean
  root_cause_topic_id: string | null
  root_cause_topic_name: string | null
}

// ─── Session Types ────────────────────────────────────────────

export interface SessionData {
  session_id: string
  student_id: string
  syllabus_id: string
  current_topic: string
  current_topic_id: string
  lesson_state: Record<string, unknown>
  quiz_state: Record<string, unknown>
  workflow_state: Record<string, unknown>
  mastery_snapshot: Record<string, unknown>
  retrieval_context: Record<string, unknown>
  last_activity: string
  created_at: string
  updated_at: string
  status: string
  metadata: Record<string, unknown>
}

// ─── User Profile ─────────────────────────────────────────────

export interface UserProfile {
  id: string
  email: string
  username: string
  role: string
  isActive: boolean
  current_level?: number
  current_course?: string
  total_lessons_completed?: number
  total_topics_mastered?: number
  total_study_time_minutes?: number
}

// ─── API Response wrapper ─────────────────────────────────────

export interface ApiResponse<T> {
  data: T | null
  error: string | null
  isLoading: boolean
}
