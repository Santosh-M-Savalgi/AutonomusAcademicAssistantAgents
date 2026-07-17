export const colors = {
  background: '#0A0D12',
  surface: '#12161D',
  surfaceHover: '#181D27',
  surfaceBorder: '#1E2430',
  primary: '#1FBF9E',
  primaryHover: '#2AD4B2',
  primaryMuted: 'rgba(31, 191, 158, 0.1)',
  secondary: '#E8A93B',
  secondaryHover: '#F0BC4E',
  secondaryMuted: 'rgba(232, 169, 59, 0.1)',
  text: {
    primary: '#E7EAF0',
    secondary: '#8A94A6',
    muted: '#5C6575',
    inverse: '#0A0D12',
  },
  danger: '#EF4444',
  dangerHover: '#DC2626',
  success: '#22C55E',
  warning: '#E8A93B',
  overlay: 'rgba(0, 0, 0, 0.6)',
} as const

export const spacing = {
  0: '0px',
  1: '4px',
  2: '8px',
  3: '12px',
  4: '16px',
  5: '24px',
  6: '32px',
  7: '40px',
  8: '48px',
  9: '64px',
} as const

export const radius = {
  sm: '8px',
  md: '12px',
  lg: '16px',
  xl: '20px',
  full: '9999px',
} as const

export const shadows = {
  card: '0 1px 3px rgba(0, 0, 0, 0.3), 0 1px 2px rgba(0, 0, 0, 0.2)',
  elevated: '0 4px 6px rgba(0, 0, 0, 0.3), 0 2px 4px rgba(0, 0, 0, 0.2)',
  modal: '0 10px 25px rgba(0, 0, 0, 0.5), 0 4px 10px rgba(0, 0, 0, 0.3)',
  glow: '0 0 20px rgba(31, 191, 158, 0.15)',
  'glow-secondary': '0 0 20px rgba(232, 169, 59, 0.15)',
} as const

export const typography = {
  fontFamily: {
    display: "'Cabinet Grotesk', 'Geist', 'Inter', sans-serif",
    body: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    mono: "'JetBrains Mono', 'Fira Code', monospace",
  },
  fontSize: {
    xs: '0.75rem',
    sm: '0.875rem',
    base: '1rem',
    lg: '1.125rem',
    xl: '1.25rem',
    '2xl': '1.5rem',
    '3xl': '1.875rem',
    '4xl': '2.25rem',
    '5xl': '3rem',
  },
  fontWeight: {
    normal: '400',
    medium: '500',
    semibold: '600',
    bold: '700',
  },
} as const

export const transitions = {
  fast: '150ms cubic-bezier(0.16, 1, 0.3, 1)',
  normal: '200ms cubic-bezier(0.16, 1, 0.3, 1)',
  slow: '300ms cubic-bezier(0.16, 1, 0.3, 1)',
} as const

export const theme = {
  colors,
  spacing,
  radius,
  shadows,
  typography,
  transitions,
}

export type Theme = typeof theme
