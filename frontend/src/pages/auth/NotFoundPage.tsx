import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Button } from '@/components/ui'
import { ROUTES } from '@/constants'

export function NotFoundPage() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-8">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center max-w-sm"
      >
        <div className="text-6xl font-display font-bold text-primary mb-4">404</div>
        <h2 className="text-xl font-display font-semibold text-text-primary mb-2">
          Page not found
        </h2>
        <p className="text-sm text-text-secondary mb-6">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <Link to={ROUTES.DASHBOARD}>
          <Button>Go to Dashboard</Button>
        </Link>
      </motion.div>
    </div>
  )
}
