import React, { useState, useEffect } from 'react';
import { BookOpen, RefreshCw, AlertTriangle, Play, CheckCircle } from 'lucide-react';
import { api } from '../api';
import CurriculumPath from './CurriculumPath';
import { formatDateTime, STATUS_MAP } from '../utils';

export default function SyllabusOverview({ studentId, onStartLesson, onSelectProfile }) {
  const [profile, setProfile] = useState(null);
  const [topics, setTopics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [startLoading, setStartLoading] = useState(false);
  const [startLoadingStep, setStartLoadingStep] = useState('');
  const [error, setError] = useState(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [profileData, topicsData] = await Promise.all([
        api.getProfile(studentId),
        api.getTopics(studentId)
      ]);
      setProfile(profileData);
      setTopics(topicsData);
    } catch (err) {
      console.error(err);
      setError('Could not retrieve syllabus data. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [studentId]);

  const handleStartSession = async () => {
    setError(null);
    setStartLoading(true);
    setStartLoadingStep('Summoning lesson documents...');

    try {
      // Step 1: Start Pipeline (runs Search → Teach → Quiz nodes)
      setStartLoadingStep('Reading academic web sources...');
      const response = await api.startTopicPipeline(studentId);
      
      if (response.status === 'complete') {
        setStartLoadingStep('Course fully completed!');
        // Refresh profile data
        fetchData();
        return;
      }
      
      setStartLoadingStep('Compiling lesson textbook page...');
      // Allow visual buffer for student comfort
      setTimeout(() => {
        onStartLesson(response.current_topic);
        setStartLoading(false);
      }, 1000);

    } catch (err) {
      console.error(err);
      setError(err.message || 'Failed to start lesson. The search API or AI tutor may be busy.');
      setStartLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-box" style={{ minHeight: '60vh' }}>
        <div className="academic-spinner"></div>
        <h2 className="loading-text">Retrieving study notebook...</h2>
      </div>
    );
  }

  if (startLoading) {
    return (
      <div className="loading-box" style={{ minHeight: '60vh' }}>
        <div className="academic-spinner"></div>
        <h2 className="loading-text">{startLoadingStep}</h2>
        <p className="loading-subtext">The agent is reading research papers, synthesizing definitions, and writing quiz sheets. This may take 10-15 seconds.</p>
      </div>
    );
  }

  // Find the active topic
  const activeTopic = topics.find(topic => topic.topic_name === profile?.currently_on);
  const isCourseComplete = topics.length > 0 && topics.every(t => t.status === 'taught');

  return (
    <div className="syllabus-container">
      <div className="syllabus-header">
        <div className="student-greeting">
          Welcome back, {profile?.name} • Session #{profile?.session_count}
        </div>
        <div className="syllabus-title-block">
          <div>
            <h1 className="syllabus-title">Study Path</h1>
            <p className="profile-meta-text">Last active: {formatDateTime(profile?.last_active)}</p>
          </div>
          <div>
            <button className="btn btn-secondary" onClick={onSelectProfile}>
              View Progress Log
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="error-banner" style={{ marginBottom: '2rem' }}>
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* Signature Element - Curriculum Timeline Path */}
      <div className="curriculum-path-card" style={{ marginBottom: '3rem' }}>
        <h2 className="topic-list-title">Syllabus Roadmap</h2>
        <CurriculumPath
          topics={topics}
          currentTopicName={profile?.currently_on}
          onSelectTopic={(topic) => {
            // Optional: click to inspect subtopics
          }}
        />
      </div>

      {/* Dynamic Action Panel */}
      <div className="bookplate-card" style={{ maxWidth: '100%', margin: '0 0 3rem 0', padding: '2rem' }}>
        {isCourseComplete ? (
          <div style={{ textAlign: 'center' }}>
            <CheckCircle size={40} style={{ color: 'var(--color-accent-mastery)', marginBottom: '1rem' }} />
            <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.4rem', marginBottom: '0.5rem' }}>Course Completed</h3>
            <p style={{ fontSize: '0.9rem', color: 'var(--color-text-muted)', marginBottom: '1.5rem' }}>
              You have read and masterfully completed all topics in your curriculum!
            </p>
            <button className="btn btn-primary" onClick={fetchData}>
              Sync Progress
            </button>
          </div>
        ) : activeTopic ? (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1.5rem', flexWrap: 'wrap' }}>
            <div style={{ flex: 1 }}>
              <span className="topic-difficulty-pill diff-intermediate" style={{ marginBottom: '0.5rem' }}>
                Active Topic
              </span>
              <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.5rem', fontWeight: 700 }}>
                {activeTopic.topic_name}
              </h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', marginTop: '0.25rem' }}>
                Difficulty: <span style={{ textTransform: 'capitalize' }}>{activeTopic.difficulty}</span>
                {activeTopic.attempts > 0 && ` • Attempts: ${activeTopic.attempts}`}
              </p>
              
              {activeTopic.inferred_gap && (
                <div className="topic-inferred-gap" style={{ marginTop: '1rem' }}>
                  <strong>Prerequisite Required:</strong> We noticed gaps in <em>{activeTopic.inferred_gap}</em>. Let's study this foundations module first to strengthen your baseline.
                </div>
              )}
            </div>

            <div>
              <button
                className="btn btn-primary"
                onClick={handleStartSession}
                style={{ fontSize: '1rem', padding: '0.8rem 1.5rem' }}
              >
                <Play size={16} fill="currentColor" />
                {activeTopic.attempts > 0 ? 'Resume Lesson' : 'Begin Lesson'}
              </button>
            </div>
          </div>
        ) : (
          <div style={{ textAlign: 'center' }}>
            <BookOpen size={40} style={{ color: 'var(--color-text-muted)', marginBottom: '1rem' }} />
            <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.4rem', marginBottom: '0.5rem' }}>Ready to Begin</h3>
            <p style={{ fontSize: '0.9rem', color: 'var(--color-text-muted)', marginBottom: '1.5rem' }}>
              Initialize your first lesson study segment.
            </p>
            <button className="btn btn-primary" onClick={handleStartSession}>
              Start First Topic
            </button>
          </div>
        )}
      </div>

      {/* Topic Card Detail Checklist */}
      <div>
        <h2 className="topic-list-title">Topics Overview</h2>
        <div className="topic-cards-container">
          {topics.map((topic) => {
            const isActive = topic.topic_name === profile?.currently_on;
            const statusConfig = STATUS_MAP[topic.status] || { label: 'Pending', bg: '#fff' };

            return (
              <div key={topic.topic_id} className={`topic-card ${topic.status} ${isActive ? 'in_progress' : ''}`}>
                <div className="topic-meta-left">
                  <span className={`topic-difficulty-pill diff-${topic.difficulty}`}>
                    {topic.difficulty}
                  </span>
                  <h3 className="topic-card-name">{topic.topic_name}</h3>
                  <div className="topic-subtopics">
                    {topic.subtopics && topic.subtopics.length > 0 ? (
                      <span><strong>Key Concepts:</strong> {topic.subtopics.join(' • ')}</span>
                    ) : (
                      <span>Core curriculum introduction node</span>
                    )}
                  </div>
                  {topic.inferred_gap && (
                    <div className="topic-inferred-gap">
                      <strong>Identified Study Gap:</strong> Requires learning prerequisite module: <em>{topic.inferred_gap}</em>.
                    </div>
                  )}
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.5rem' }}>
                  <span
                    className="topic-status-pill"
                    style={{ backgroundColor: statusConfig.bg, color: statusConfig.color }}
                  >
                    {isActive ? 'Currently Studying' : statusConfig.label}
                  </span>
                  {topic.attempts > 0 && (
                    <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                      Attempts: {topic.attempts}
                    </span>
                  )}
                  {topic.quiz_score > 0 && (
                    <span style={{ fontSize: '0.75rem', color: 'var(--color-accent-mastery)', fontWeight: 600 }}>
                      Mastery Score: {Math.round(topic.quiz_score)}%
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
