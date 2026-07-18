export interface DataPoint {
  label: string
  value: number
  secondary?: number
  date?: string
}

export interface ChartSeries {
  name: string
  data: DataPoint[]
  color?: string
}

export interface HeatmapData {
  date: string
  value: number
  label?: string
}

export type TrendDirection = 'up' | 'down' | 'stable' | 'neutral'
