import { Routes, Route, Navigate } from 'react-router-dom'
import { AppLayout } from '@/layouts'
import { LoginPage, RegisterPage, ForgotPasswordPage, NotFoundPage } from '@/pages/auth'
import { DashboardPage } from '@/pages/dashboard/DashboardPage'
import { LearningPage } from '@/pages/learning/LearningPage'
import { RoadmapPage } from '@/pages/learning/RoadmapPage'
import { LessonPage } from '@/pages/learning/LessonPage'
import { QuizPage } from '@/pages/learning/QuizPage'
import { QuizResultsPage } from '@/pages/learning/QuizResultsPage'
import { ProfilePage } from '@/pages/settings/ProfilePage'
import { AnalyticsPage } from '@/pages/analytics/AnalyticsPage'
import { ResourcesPage } from '@/pages/resources/ResourcesPage'
import { SettingsPage } from '@/pages/settings/SettingsPage'
import { ProtectedRoute } from './ProtectedRoute'
import { ROUTES } from '@/constants'

export function AppRoutes() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path={ROUTES.LOGIN} element={<LoginPage />} />
      <Route path={ROUTES.REGISTER} element={<RegisterPage />} />
      <Route path={ROUTES.FORGOT_PASSWORD} element={<ForgotPasswordPage />} />

      {/* Protected routes */}
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path={ROUTES.DASHBOARD} element={<DashboardPage />} />
        <Route path={ROUTES.LEARNING} element={<LearningPage />} />
        <Route path={ROUTES.ROADMAP} element={<RoadmapPage />} />
        <Route path={ROUTES.LESSON} element={<LessonPage />} />
        <Route path={ROUTES.QUIZ} element={<QuizPage />} />
        <Route path={ROUTES.QUIZ_RESULTS} element={<QuizResultsPage />} />
        <Route path={ROUTES.PROFILE} element={<ProfilePage />} />
        <Route path={ROUTES.ANALYTICS} element={<AnalyticsPage />} />
        <Route path={ROUTES.RESOURCES} element={<ResourcesPage />} />
        <Route path={ROUTES.SETTINGS} element={<SettingsPage />} />
      </Route>

      {/* 404 */}
      <Route path="/404" element={<NotFoundPage />} />
      <Route path="*" element={<Navigate to="/404" replace />} />
    </Routes>
  )
}
