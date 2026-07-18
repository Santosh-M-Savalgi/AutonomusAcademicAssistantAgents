import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuth } from '@/contexts/AuthContext'
import { Button, Input } from '@/components/ui'
import { useAuthForm } from '@/hooks/useAuthForm'
import { ROUTES, APP } from '@/constants'
import { Eye, EyeOff, Sparkles, ArrowRight } from 'lucide-react'

export function LoginPage() {
  const [emailOrUsername, setEmailOrUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const { isLoading, error, execute } = useAuthForm()
  const { login } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    await execute(async () => {
      await login({ email_or_username: emailOrUsername, password })
      navigate(ROUTES.DASHBOARD)
    })
  }

  return (
    <div className="min-h-screen bg-background flex">
      {/* Left: Branding */}
      <div className="hidden lg:flex w-1/2 bg-surface border-r border-surface-border items-center justify-center p-12">
        <div className="max-w-md">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            <div className="h-12 w-12 rounded-xl bg-primary flex items-center justify-center mb-6">
              <Sparkles className="h-6 w-6 text-text-inverse" />
            </div>
            <h1 className="text-4xl font-display font-bold text-text-primary mb-3">
              {APP.FULL_NAME}
            </h1>
            <p className="text-lg text-text-secondary leading-relaxed">
              An intelligent AI-powered learning platform that adapts to your pace, 
              personalizes your curriculum, and helps you master any subject.
            </p>
            <div className="mt-8 space-y-4">
              {[
                { label: 'Adaptive Learning', desc: 'AI adjusts difficulty in real-time based on your performance' },
                { label: 'Smart Curriculum', desc: 'Automatically generated learning paths from any topic' },
                { label: 'Progress Tracking', desc: 'Detailed analytics and mastery tracking for every subject' },
              ].map((feature, i) => (
                <motion.div
                  key={feature.label}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.2 + i * 0.1 }}
                  className="flex gap-3"
                >
                  <div className="h-2 w-2 rounded-full bg-primary mt-2 shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-text-primary">{feature.label}</p>
                    <p className="text-xs text-text-muted">{feature.desc}</p>
                  </div>
                </motion.div>
              ))}
            </div>
          </motion.div>
        </div>
      </div>

      {/* Right: Form */}
      <div className="flex-1 flex items-center justify-center p-8">
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.5 }}
          className="w-full max-w-sm"
        >
          <div className="mb-8">
            <h2 className="text-2xl font-display font-bold text-text-primary mb-1">
              Welcome back
            </h2>
            <p className="text-sm text-text-secondary">
              Sign in to continue your learning journey
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400"
              >
                {error}
              </motion.div>
            )}

            <Input
              label="Email or Username"
              type="text"
              value={emailOrUsername}
              onChange={(e) => setEmailOrUsername(e.target.value)}
              placeholder="you@example.com"
              required
              autoComplete="username"
            />

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label htmlFor="password" className="text-sm font-medium text-text-primary">
                  Password
                </label>
                <Link
                  to={ROUTES.FORGOT_PASSWORD}
                  className="text-xs text-text-muted hover:text-primary transition-colors"
                >
                  Forgot password?
                </Link>
              </div>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Enter your password"
                  required
                  autoComplete="current-password"
                  className="h-10 w-full px-3 py-2 pr-10 text-sm rounded-md bg-surface border border-surface-border text-text-primary placeholder:text-text-muted transition-all duration-200 focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary hover:border-text-muted"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <Button type="submit" loading={isLoading} className="w-full">
              {isLoading ? 'Signing in...' : 'Sign in'}
              {!isLoading && <ArrowRight className="h-4 w-4" />}
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-text-muted">
            Don't have an account?{' '}
            <Link to={ROUTES.REGISTER} className="text-primary hover:text-primary-hover font-medium transition-colors">
              Create one
            </Link>
          </p>
        </motion.div>
      </div>
    </div>
  )
}
