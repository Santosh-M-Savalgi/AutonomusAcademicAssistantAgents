import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Button } from '@/components/ui'
import { ROUTES } from '@/constants'

export function UnauthorizedPage() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-8">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center max-w-sm"
      >
        <div className="text-6xl font-display font-bold text-danger mb-4">401</div>
        <h2 className="text-xl font-display font-semibold text-text-primary mb-2">
          Unauthorized
        </h2>
        <p className="text-sm text-text-secondary mb-6">
          Please sign in to access this page. You may need valid credentials
          or a session that has not expired.
        </p>
        <Link to={ROUTES.LOGIN}>
          <Button>Sign in</Button>
        </Link>
      </motion.div>
    </div>
  )
}
