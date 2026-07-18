import { motion } from 'framer-motion'
import { cn } from '@/utils/cn'
import type { DataPoint } from './types'

interface BarChartProps {
  data: DataPoint[]
  height?: number
  color?: string
  showValues?: boolean
  animated?: boolean
  maxBars?: number
  className?: string
}

export function BarChart({
  data,
  height = 200,
  color = '#1FBF9E',
  showValues = false,
  animated = true,
  maxBars = 20,
  className,
}: BarChartProps) {
  if (!data || data.length === 0) return null

  const displayData = data.slice(0, maxBars)
  const values = displayData.map((d) => d.value)
  const max = Math.max(...values, 1)
  const padding = 24
  const innerWidth = 100 - padding * 2
  const barWidth = innerWidth / displayData.length * 0.7
  const gap = innerWidth / displayData.length * 0.3

  return (
    <div className={cn('w-full', className)} role="img" aria-label={`Bar chart with ${displayData.length} bars`}>
      <svg
        viewBox={`0 0 ${100} ${height}`}
        className="w-full h-full overflow-visible"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {/* Baseline */}
        <line
          x1={padding}
          y1={height - padding}
          x2={100 - padding}
          y2={height - padding}
          stroke="#1E2430"
          strokeWidth="0.5"
        />

        {/* Bars */}
        {displayData.map((d, i) => {
          const barH = (d.value / max) * (height - padding * 2)
          const x = padding + i * ((barWidth + gap) / (innerWidth / displayData.length)) * (innerWidth / displayData.length) + gap / 2
          const w = barWidth

          return (
            <g key={i}>
              <motion.rect
                x={x}
                y={height - padding - barH}
                width={w}
                height={barH}
                fill={color}
                rx="1"
                initial={animated ? { height: 0, y: height - padding } : undefined}
                animate={{ height: barH, y: height - padding - barH }}
                transition={{ duration: 0.6, delay: i * 0.03, ease: 'easeOut' }}
              />
              {showValues && barH > 10 && (
                <text
                  x={x + w / 2}
                  y={height - padding - barH - 2}
                  fill="#8A94A6"
                  fontSize="3"
                  textAnchor="middle"
                >
                  {d.value}
                </text>
              )}
            </g>
          )
        })}
      </svg>

      {/* X-axis labels */}
      <div className="flex justify-between px-1 mt-1">
        {displayData.filter((_, i) => i % Math.max(1, Math.floor(displayData.length / 6)) === 0 || i === displayData.length - 1).map((d, i) => (
          <span key={i} className="text-[10px] text-text-muted truncate">
            {d.label}
          </span>
        ))}
      </div>
    </div>
  )
}
