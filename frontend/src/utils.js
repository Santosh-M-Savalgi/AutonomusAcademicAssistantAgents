// Common helper utilities for AAA frontend

/**
 * Format ISO datetime string to friendly readable text
 */
export function formatDateTime(isoString) {
  if (!isoString) return 'Never';
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    return date.toLocaleDateString(undefined, {
      month: 'long',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch (e) {
    return isoString;
  }
}

/**
 * Maps API topic status to human-readable labels
 */
export const STATUS_MAP = {
  pending: { label: 'Pending', color: 'var(--color-text-muted)', bg: '#FAF9F6' },
  in_progress: { label: 'In Progress', color: '#B37D22', bg: '#FDF7E7' },
  taught: { label: 'Taught', color: 'var(--color-accent-mastery)', bg: 'var(--color-accent-mastery-light)' },
  weak: { label: 'Needs Review', color: 'var(--color-accent-rust)', bg: 'var(--color-accent-rust-light)' },
  strong: { label: 'Mastered', color: 'var(--color-accent-mastery)', bg: 'var(--color-accent-mastery-light)' },
  critical: { label: 'Gaps Found', color: 'var(--color-accent-rust)', bg: 'var(--color-accent-rust-light)' }
};

/**
 * Mapping topic difficulty levels
 */
export const DIFFICULTY_MAP = {
  beginner: { label: 'Beginner', class: 'diff-beginner' },
  intermediate: { label: 'Intermediate', class: 'diff-intermediate' },
  advanced: { label: 'Advanced', class: 'diff-advanced' }
};

/**
 * Mapping API next_action values to helpful student descriptions
 */
export const NEXT_ACTION_MAP = {
  advance: {
    title: 'Topic Mastered',
    description: 'You have shown excellent comprehension. Let\'s move forward to the next topic in the curriculum.',
    buttonText: 'Advance to Next Lesson'
  },
  complete: {
    title: 'Curriculum Completed',
    description: 'Congratulations! You have completed all the topics in this syllabus and mastered the core concepts.',
    buttonText: 'View Final Syllabus'
  },
  reteach: {
    title: 'Let\'s Review',
    description: 'We\'ve identified some concepts that need reinforcing. Let\'s go over this topic again from a different perspective to solidify your understanding.',
    buttonText: 'Review Lesson'
  },
  insert_prerequisite: {
    title: 'Prerequisite Detour',
    description: 'To help you master this concept, we have identified and inserted a necessary prerequisite topic into your path. Let\'s build this foundation first.',
    buttonText: 'Begin Prerequisite Lesson'
  }
};
