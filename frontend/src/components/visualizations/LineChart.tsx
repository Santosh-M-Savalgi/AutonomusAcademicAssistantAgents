import { motion } from 'framer-motion'
import { cn } from '@/utils/cn'
import type { DataPoint } from './types'

interface LineChartProps {
  data: DataPoint[]
  height?: number
  color?: string
  showGrid?: boolean
  showDots?: boolean
  animated?: boolean
  className?: string
}

export function LineChart({
  data,
  height = 200,
  color = '#1FBF9E',
  showGrid = true,
  showDots = true,
  animated = true,
  className,
}: LineChartProps) {
  if (!data || data.length === 0) return null

  const values = data.map((d) => d.value)
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const range = max - min || 1
  const width = 100
  const padding = 20

  const points = data.map((d, i) => {
    const x = padding + (i / (data.length - 1 || 1)) * (width - padding * 2)
    const y = padding + ((max - d.value) / range) * (height - padding * 2)
    return { x, y, label: d.label, value: d.value }
  })

  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')

  const gridLines = showGrid
    ? Array.from({ length: 4 }).map((_, i) => {
        const y = padding + (i / 3) * (height - padding * 2)
        const label = Math.round(max - (i / 3) * range)
        return { y, label }
      })
    : []

  return (
    <div className={cn('w-full', className)} role="img" aria-label={`Line chart with ${data.length} data points`}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-full overflow-visible"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {/* Grid lines */}
        {gridLines.map((gl, i) => (
          <g key={i}>
            <line
              x1={padding}
              y1={gl.y}
              x2={width - padding}
              y2={gl.y}
              stroke="#1E2430"
              strokeWidth="0.5"
            />
            <text
              x={padding - 4}
              y={gl.y + 1}
              fill="#5C6575"
              fontSize="3"
              textAnchor="end"
              dominantBaseline="middle"
            >
              {gl.label}
            </text>
          </g>
        ))}

        {/* Line path */}
        <motion.path
          d={pathD}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={animated ? { pathLength: 0 } : undefined}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1, ease: 'easeOut' }}
        />

        {/* Area fill */}
        <motion.path
          d={`${pathD} L${points[points.length - 1]?.x ?? width - padding},${height - padding} L${points[0]?.x ?? padding},${height - padding} Z`}
          fill={`url(#lineGradient-${color.replace('#', '')})`}
          opacity={0.1}
          initial={animated ? { opacity: 0 } : undefined}
          animate={{ opacity: 0.1 }}
          transition={{ duration: 0.8, delay: 0.3 }}
        />

        <defs>
          <linearGradient id={`lineGradient-${color.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.4" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Data dots */}
        {showDots &&
          points.map((p, i) => (
            <motion.circle
              key={i}
              cx={p.x}
              cy={p.y}
              r="1.5"
              fill={color}
              stroke="#12161D"
              strokeWidth="0.5"
              initial={animated ? { scale: 0 } : undefined}
              animate={{ scale: 1 }}
              transition={{ duration: 0.3, delay: 0.8 + i * 0.05 }}
            />
          ))}
      </svg>

      {/* X-axis labels */}
      <div className="flex justify-between px-1 mt-1">
        {data.filter((_, i) => i % Math.max(1, Math.floor(data.length / 6)) === 0 || i === data.length - 1).map((d, i) => (
          <span key={i} className="text-[10px] text-text-muted truncate">
            {d.label}
          </span>
        ))}
      </div>
    </div>
  )
}
