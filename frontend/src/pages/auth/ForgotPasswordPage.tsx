import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Button, Input } from '@/components/ui'
import { useAuthForm } from '@/hooks/useAuthForm'
import { ROUTES } from '@/constants'
import { ArrowLeft, Check, Mail } from 'lucide-react'

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const { isLoading, error, execute } = useAuthForm()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    // Simulate — backend endpoint may not exist yet
    await execute(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      setSent(true)
      return
    })
  }

  if (sent) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-8">
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="text-center max-w-sm"
        >
          <div className="h-16 w-16 rounded-full bg-primary-muted flex items-center justify-center mx-auto mb-6">
            <Mail className="h-8 w-8 text-primary" />
          </div>
          <h2 className="text-2xl font-display font-bold text-text-primary mb-2">
            Check your email
          </h2>
          <p className="text-sm text-text-secondary mb-6">
            If an account exists with {email}, we've sent password reset instructions.
          </p>
          <Link to={ROUTES.LOGIN}>
            <Button variant="secondary">Back to sign in</Button>
          </Link>
        </motion.div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-8">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-sm"
      >
        <Link
          to={ROUTES.LOGIN}
          className="inline-flex items-center gap-1 text-sm text-text-muted hover:text-primary transition-colors mb-8"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to sign in
        </Link>

        <div className="mb-8">
          <h2 className="text-2xl font-display font-bold text-text-primary mb-1">
            Reset password
          </h2>
          <p className="text-sm text-text-secondary">
            Enter your email and we'll send you reset instructions
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400">
              {error}
            </div>
          )}

          <Input
            label="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            required
            autoComplete="email"
          />

          <Button type="submit" loading={isLoading} className="w-full">
            {isLoading ? 'Sending...' : 'Send reset instructions'}
          </Button>
        </form>
      </motion.div>
    </div>
  )
}
