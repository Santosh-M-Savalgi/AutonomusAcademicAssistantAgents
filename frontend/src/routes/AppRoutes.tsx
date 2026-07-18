import { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { AppLayout } from '@/layouts'
import { LoginPage, RegisterPage, ForgotPasswordPage, NotFoundPage } from '@/pages/auth'
import { UnauthorizedPage, ForbiddenPage } from '@/pages/auth'
import { RouteTransitionLoader } from '@/components/ui/RouteTransitionLoader'
import { ProtectedRoute } from './ProtectedRoute'
import { ROUTES } from '@/constants'

/* ─── Lazy-loaded pages ────────────────────────────────────── */

const DashboardPage = lazy(() =>
  import('@/pages/dashboard/DashboardPage').then((m) => ({ default: m.DashboardPage }))
)
const LearningPage = lazy(() =>
  import('@/pages/learning/LearningPage').then((m) => ({ default: m.LearningPage }))
)
const RoadmapPage = lazy(() =>
  import('@/pages/learning/RoadmapPage').then((m) => ({ default: m.RoadmapPage }))
)
const LessonPage = lazy(() =>
  import('@/pages/learning/LessonPage').then((m) => ({ default: m.LessonPage }))
)
const QuizPage = lazy(() =>
  import('@/pages/learning/QuizPage').then((m) => ({ default: m.QuizPage }))
)
const QuizResultsPage = lazy(() =>
  import('@/pages/learning/QuizResultsPage').then((m) => ({ default: m.QuizResultsPage }))
)
const ProfilePage = lazy(() =>
  import('@/pages/settings/ProfilePage').then((m) => ({ default: m.ProfilePage }))
)
const AnalyticsPage = lazy(() =>
  import('@/pages/analytics/AnalyticsPage').then((m) => ({ default: m.AnalyticsPage }))
)
const ResourcesPage = lazy(() =>
  import('@/pages/resources/ResourcesPage').then((m) => ({ default: m.ResourcesPage }))
)
const SettingsPage = lazy(() =>
  import('@/pages/settings/SettingsPage').then((m) => ({ default: m.SettingsPage }))
)
const LearningGoalPage = lazy(() =>
  import('@/pages/learning/LearningGoalPage').then((m) => ({ default: m.LearningGoalPage }))
)

/* ─── Suspense wrapper ─────────────────────────────────────── */

function PageSuspense({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<RouteTransitionLoader />}>
      {children}
    </Suspense>
  )
}

/* ─── Routes ───────────────────────────────────────────────── */

export function AppRoutes() {
  return (
    <Routes>
      {/* Public routes */}
      <Route
        path={ROUTES.LOGIN}
        element={
          <PageSuspense>
            <LoginPage />
          </PageSuspense>
        }
      />
      <Route
        path={ROUTES.REGISTER}
        element={
          <PageSuspense>
            <RegisterPage />
          </PageSuspense>
        }
      />
      <Route
        path={ROUTES.FORGOT_PASSWORD}
        element={
          <PageSuspense>
            <ForgotPasswordPage />
          </PageSuspense>
        }
      />

      {/* Protected routes */}
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route
          path={ROUTES.DASHBOARD}
          element={
            <PageSuspense>
              <DashboardPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.LEARNING}
          element={
            <PageSuspense>
              <LearningPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.ROADMAP}
          element={
            <PageSuspense>
              <RoadmapPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.LESSON}
          element={
            <PageSuspense>
              <LessonPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.QUIZ}
          element={
            <PageSuspense>
              <QuizPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.QUIZ_RESULTS}
          element={
            <PageSuspense>
              <QuizResultsPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.PROFILE}
          element={
            <PageSuspense>
              <ProfilePage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.ANALYTICS}
          element={
            <PageSuspense>
              <AnalyticsPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.RESOURCES}
          element={
            <PageSuspense>
              <ResourcesPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.SETTINGS}
          element={
            <PageSuspense>
              <SettingsPage />
            </PageSuspense>
          }
        />
        <Route
          path={ROUTES.GOAL}
          element={
            <PageSuspense>
              <LearningGoalPage />
            </PageSuspense>
          }
        />
      </Route>

      {/* Error pages */}
      <Route path="/401" element={<UnauthorizedPage />} />
      <Route path="/403" element={<ForbiddenPage />} />
      <Route path="/404" element={<NotFoundPage />} />
      <Route path="*" element={<Navigate to="/404" replace />} />
    </Routes>
  )
}
