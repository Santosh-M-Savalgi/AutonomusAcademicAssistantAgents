export const ROUTES = {
  LOGIN: '/login',
  REGISTER: '/register',
  FORGOT_PASSWORD: '/forgot-password',
  DASHBOARD: '/',
  LEARNING: '/learning',
  ROADMAP: '/roadmap',
  ANALYTICS: '/analytics',
  RESOURCES: '/resources',
  SETTINGS: '/settings',
} as const;

export const API_ENDPOINTS = {
  AUTH: {
    REGISTER: '/api/v2/auth/register',
    LOGIN: '/api/v2/auth/login',
    REFRESH: '/api/v2/auth/refresh',
    LOGOUT: '/api/v2/auth/logout',
    ME: '/api/v2/auth/me',
    CHANGE_PASSWORD: '/api/v2/auth/change-password',
  },
} as const;

export const APP = {
  NAME: 'AAA',
  FULL_NAME: 'Autonomous Academic Agent',
  VERSION: '2.0.0',
} as const;
