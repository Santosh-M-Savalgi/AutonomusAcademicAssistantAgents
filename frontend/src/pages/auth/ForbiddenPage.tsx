import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Button } from '@/components/ui'
import { ROUTES } from '@/constants'
import { ShieldAlert } from 'lucide-react'

export function ForbiddenPage() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-8">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center max-w-sm"
      >
        <ShieldAlert className="h-16 w-16 text-danger mx-auto mb-4" />
        <div className="text-6xl font-display font-bold text-danger mb-4">403</div>
        <h2 className="text-xl font-display font-semibold text-text-primary mb-2">
          Access Denied
        </h2>
        <p className="text-sm text-text-secondary mb-6">
          You do not have permission to access this page. Contact your
          administrator if you believe this is a mistake.
        </p>
        <Link to={ROUTES.DASHBOARD}>
          <Button>Go to Dashboard</Button>
        </Link>
      </motion.div>
    </div>
  )
}
