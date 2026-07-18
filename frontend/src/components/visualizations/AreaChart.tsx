import { motion } from 'framer-motion'
import { cn } from '@/utils/cn'
import type { DataPoint } from './types'

interface AreaChartProps {
  data: DataPoint[]
  height?: number
  color?: string
  showAxis?: boolean
  animated?: boolean
  className?: string
}

export function AreaChart({
  data,
  height = 200,
  color = '#1FBF9E',
  showAxis = true,
  animated = true,
  className,
}: AreaChartProps) {
  if (!data || data.length === 0) return null

  const values = data.map((d) => d.value)
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const range = max - min || 1
  const padding = 20

  const points = data.map((d, i) => {
    const x = padding + (i / (data.length - 1 || 1)) * (100 - padding * 2)
    const y = padding + ((max - d.value) / range) * (height - padding * 2)
    return { x, y, label: d.label, value: d.value }
  })

  const areaPath = [
    points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' '),
    `L${points[points.length - 1]?.x ?? 100 - padding},${height - padding}`,
    `L${points[0]?.x ?? padding},${height - padding} Z`,
  ].join(' ')

  return (
    <div className={cn('w-full', className)} role="img" aria-label={`Area chart with ${data.length} data points`}>
      <svg
        viewBox={`0 0 ${100} ${height}`}
        className="w-full h-full overflow-visible"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {/* Gradient */}
        <defs>
          <linearGradient id={`areaGrad-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Area fill */}
        <motion.path
          d={areaPath}
          fill={`url(#areaGrad-${color.replace('#', '')})`}
          initial={animated ? { opacity: 0 } : undefined}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
        />

        {/* Line */}
        <motion.path
          d={points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={animated ? { pathLength: 0 } : undefined}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1, ease: 'easeOut' }}
        />

        {/* Axis */}
        {showAxis && (
          <line
            x1={padding}
            y1={height - padding}
            x2={100 - padding}
            y2={height - padding}
            stroke="#1E2430"
            strokeWidth="0.5"
          />
        )}
      </svg>

      {/* Labels */}
      <div className="flex justify-between px-1 mt-1">
        {data.filter((_, i) => i % Math.max(1, Math.floor(data.length / 5)) === 0 || i === data.length - 1).map((d, i) => (
          <span key={i} className="text-[10px] text-text-muted truncate">
            {d.label}
          </span>
        ))}
      </div>
    </div>
  )
}
