// API Client for AAA (Autonomous Academic Agent)
const DEFAULT_BASE_URL = 'http://127.0.0.1:8000/api/v1';

// Load base URL from environment variable or default
const BASE_URL = import.meta.env.VITE_API_BASE_URL || DEFAULT_BASE_URL;

export class APIError extends Error {
  constructor(status, code, message, details = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/**
 * Handle API responses and standardize errors
 */
async function handleResponse(response) {
  if (response.ok) {
    return response.json();
  }

  let errorData;
  let code = 'unknown_error';
  let message = 'An unexpected error occurred';
  let details = null;

  try {
    errorData = await response.json();
    if (errorData?.error) {
      // standard AAA custom error structure: {error: {code, message}}
      code = errorData.error.code || code;
      message = errorData.error.message || message;
    } else if (errorData?.detail) {
      // FastAPI standard validation error or other detail
      code = 'validation_error';
      if (Array.isArray(errorData.detail)) {
        details = errorData.detail;
        message = errorData.detail.map(d => `${d.loc.join('.')}: ${d.msg}`).join(', ');
      } else {
        message = String(errorData.detail);
      }
    }
  } catch (e) {
    // Response was not JSON
    message = `Server responded with status ${response.status}`;
  }

  throw new APIError(response.status, code, message, details);
}

export const api = {
  /**
   * Create student from raw learning goal
   */
  async createStudent(name, rawInput) {
    const response = await fetch(`${BASE_URL}/students`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ name, raw_input: rawInput }),
    });
    return handleResponse(response);
  },

  /**
   * Create student from PDF syllabus file upload
   */
  async uploadSyllabus(name, file) {
    const formData = new FormData();
    formData.append('name', name);
    formData.append('file', file);

    const response = await fetch(`${BASE_URL}/students/upload-syllabus`, {
      method: 'POST',
      body: formData,
    });
    return handleResponse(response);
  },

  /**
   * Resume session / Get student profile
   */
  async getStudent(studentId) {
    const response = await fetch(`${BASE_URL}/students/${studentId}`);
    return handleResponse(response);
  },

  /**
   * Start pipeline for current/next topic
   */
  async startTopicPipeline(studentId) {
    const response = await fetch(`${BASE_URL}/students/${studentId}/start`, {
      method: 'POST',
    });
    return handleResponse(response);
  },

  /**
   * Fetch lesson content and sources
   */
  async getLesson(studentId) {
    const response = await fetch(`${BASE_URL}/students/${studentId}/lesson`);
    return handleResponse(response);
  },

  /**
   * Fetch quiz questions
   */
  async getQuiz(studentId) {
    const response = await fetch(`${BASE_URL}/students/${studentId}/quiz`);
    return handleResponse(response);
  },

  /**
   * Submit quiz answers
   * answers: [{question_id, answer_text}]
   */
  async submitAnswers(studentId, answers) {
    const response = await fetch(`${BASE_URL}/students/${studentId}/answer`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ answers }),
    });
    return handleResponse(response);
  },

  /**
   * Fetch full dashboard data
   */
  async getProfile(studentId) {
    const response = await fetch(`${BASE_URL}/students/${studentId}/profile`);
    return handleResponse(response);
  },

  /**
   * Fetch topic list with statuses
   */
  async getTopics(studentId) {
    const response = await fetch(`${BASE_URL}/students/${studentId}/topics`);
    return handleResponse(response);
  },

  /**
   * Health check
   */
  async checkHealth() {
    const response = await fetch(`${BASE_URL}/health`);
    return handleResponse(response);
  }
};
export default api;
