import React, { useState, useEffect } from 'react';
import { BookOpen, CheckCircle, RefreshCw, Milestone, Clock, Calendar, ChevronLeft } from 'lucide-react';
import { api } from '../api';
import { formatDateTime } from '../utils';

export default function ProfileView({ studentId, onBack }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchProfile = async () => {
      try {
        setLoading(true);
        const data = await api.getProfile(studentId);
        setProfile(data);
      } catch (err) {
        console.error(err);
        setError('Could not retrieve student portfolio. Please try again.');
      } finally {
        setLoading(false);
      }
    };

    fetchProfile();
  }, [studentId]);

  if (loading) {
    return (
      <div className="loading-box" style={{ minHeight: '60vh' }}>
        <div className="academic-spinner"></div>
        <h2 className="loading-text">Retrieving study portfolio...</h2>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bookplate-card" style={{ textAlign: 'center' }}>
        <h2 className="results-verdict-title fail">Portfolio Error</h2>
        <p style={{ color: 'var(--color-text-muted)', marginBottom: '1.5rem' }}>{error}</p>
        <button className="btn btn-primary" onClick={onBack}>
          Return to Syllabus
        </button>
      </div>
    );
  }

  // Calculate numbers
  const totalTopics = profile?.wants_to_read?.length || 0;
  const completedCount = profile?.was_taught?.length || 0;
  const pendingCount = profile?.pending?.length || 0;
  const weakCount = profile?.weak_topics?.length || 0;

  return (
    <div className="profile-container">
      <div style={{ marginBottom: '1.5rem' }}>
        <button className="btn btn-secondary btn-text" onClick={onBack} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
          <ChevronLeft size={16} />
          Back to Syllabus Roadmap
        </button>
      </div>

      <div className="profile-card">
        <h1 className="profile-name">{profile?.name}</h1>
        <p className="profile-meta-text" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <Clock size={14} />
          Student ID: {profile?.student_id}
        </p>
        <p className="profile-meta-text" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '0.25rem' }}>
          <Calendar size={14} />
          Last active study session: {formatDateTime(profile?.last_active)}
        </p>

        {/* Stats Grid */}
        <div className="stats-grid">
          <div className="stat-box">
            <div className="stat-value">{profile?.session_count}</div>
            <div className="stat-label">Study Sessions</div>
          </div>
          <div className="stat-box" style={{ borderLeft: '3px solid var(--color-accent-mastery)' }}>
            <div className="stat-value" style={{ color: 'var(--color-accent-mastery)' }}>
              {completedCount} / {totalTopics}
            </div>
            <div className="stat-label">Topics Mastered</div>
          </div>
          <div className="stat-box" style={{ borderLeft: weakCount > 0 ? '3px solid var(--color-accent-rust)' : '1px solid var(--color-border)' }}>
            <div className="stat-value" style={{ color: weakCount > 0 ? 'var(--color-accent-rust)' : 'var(--color-text-ink)' }}>
              {weakCount}
            </div>
            <div className="stat-label">Gaps Requiring Review</div>
          </div>
        </div>

        {/* Currently Studying */}
        {profile?.currently_on ? (
          <div style={{ padding: '1.25rem', backgroundColor: '#FFFDF6', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)' }}>
            <span className="topic-difficulty-pill diff-intermediate" style={{ marginBottom: '0.5rem' }}>
              Currently Studying
            </span>
            <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: '1.2rem', fontWeight: 600 }}>
              {profile.currently_on}
            </h3>
          </div>
        ) : (
          <div style={{ padding: '1.25rem', backgroundColor: 'var(--color-accent-mastery-light)', border: '1px solid var(--color-accent-mastery)', borderRadius: 'var(--radius-sm)', textAlign: 'center' }}>
            <span style={{ color: 'var(--color-accent-mastery)', fontWeight: 600, fontSize: '0.95rem' }}>
              🏆 All topics in this path have been mastered!
            </span>
          </div>
        )}
      </div>

      {/* Lists of Topics split */}
      <div className="topics-summary-grid">
        {/* Completed list */}
        <div className="summary-list-card" style={{ borderTop: '4px solid var(--color-accent-mastery)' }}>
          <h2 className="summary-list-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <CheckCircle size={16} style={{ color: 'var(--color-accent-mastery)' }} />
            Completed Modules ({completedCount})
          </h2>
          <ul className="summary-list">
            {profile?.was_taught && profile.was_taught.length > 0 ? (
              profile.was_taught.map((topicName, idx) => (
                <li key={idx} className="summary-list-item">
                  <span className="bullet-dot taught" />
                  <span>{topicName}</span>
                </li>
              ))
            ) : (
              <li className="summary-list-item" style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                No topics mastered yet. Complete comprehension checks to earn mastery.
              </li>
            )}
          </ul>
        </div>

        {/* Needs Review or Pending list */}
        <div className="summary-list-card" style={{ borderTop: weakCount > 0 ? '4px solid var(--color-accent-rust)' : '4px solid var(--color-border)' }}>
          <h2 className="summary-list-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {weakCount > 0 ? (
              <RefreshCw size={16} style={{ color: 'var(--color-accent-rust)' }} />
            ) : (
              <Milestone size={16} style={{ color: 'var(--color-text-muted)' }} />
            )}
            {weakCount > 0 ? `Review Gaps (${weakCount})` : `Remaining Modules (${pendingCount})`}
          </h2>
          <ul className="summary-list">
            {weakCount > 0 ? (
              profile.weak_topics.map((topicName, idx) => (
                <li key={idx} className="summary-list-item" style={{ color: 'var(--color-accent-rust)', fontWeight: 500 }}>
                  <span className="bullet-dot weak" />
                  <span>{topicName}</span>
                </li>
              ))
            ) : profile?.pending && profile.pending.length > 0 ? (
              profile.pending.map((topicName, idx) => (
                <li key={idx} className="summary-list-item">
                  <span className="bullet-dot" />
                  <span>{topicName}</span>
                </li>
              ))
            ) : (
              <li className="summary-list-item" style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                No remaining modules left in this syllabus.
              </li>
            )}
          </ul>
        </div>
      </div>
    </div>
  );
}
