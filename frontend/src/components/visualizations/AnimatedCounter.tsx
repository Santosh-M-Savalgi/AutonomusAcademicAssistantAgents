import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { cn } from '@/utils/cn'

interface AnimatedCounterProps {
  value: number
  suffix?: string
  prefix?: string
  duration?: number
  decimals?: number
  className?: string
  formatted?: boolean
}

export function AnimatedCounter({
  value,
  suffix = '',
  prefix = '',
  duration = 0.8,
  decimals = 0,
  className,
  formatted = true,
}: AnimatedCounterProps) {
  const [displayValue, setDisplayValue] = useState(0)

  useEffect(() => {
    let startTime: number | null = null
    const startValue = displayValue
    const endValue = value
    const delta = endValue - startValue

    if (delta === 0) return

    function animate(timestamp: number) {
      if (!startTime) startTime = timestamp
      const elapsed = timestamp - startTime
      const progress = Math.min(elapsed / (duration * 1000), 1)
      const eased = 1 - Math.pow(1 - progress, 3) // ease-out cubic
      setDisplayValue(startValue + delta * eased)
      if (progress < 1) {
        requestAnimationFrame(animate)
      }
    }

    requestAnimationFrame(animate)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, duration])

  const formatNumber = (n: number): string => {
    if (!formatted) return n.toFixed(decimals)
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
    return n.toFixed(decimals)
  }

  return (
    <motion.span
      className={cn('tabular-nums', className)}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
    >
      {prefix}{formatNumber(displayValue)}{suffix}
    </motion.span>
  )
}
