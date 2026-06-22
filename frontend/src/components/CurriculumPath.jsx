import React from 'react';
import { BookOpen, CheckCircle, HelpCircle, AlertCircle, RefreshCw, Milestone } from 'lucide-react';
import { STATUS_MAP } from '../utils';

export default function CurriculumPath({ topics, currentTopicName, onSelectTopic }) {
  // Helper to find if a topic is a prerequisite for another topic in the list
  const getPrerequisiteRelations = () => {
    const relations = {};
    topics.forEach((topic) => {
      if (topic.inferred_gap) {
        // Find the topic that matches this inferred gap
        const prereq = topics.find(t => t.topic_name === topic.inferred_gap);
        if (prereq) {
          relations[prereq.topic_id] = topic.topic_id; // prereq -> target
        }
      }
    });
    return relations;
  };

  const prereqRelations = getPrerequisiteRelations();

  // Custom node renderer
  const renderNodeIcon = (topic, isActive) => {
    const status = topic.status;
    
    if (isActive) {
      return <BookOpen size={18} className="node-icon active-icon" />;
    }

    switch (status) {
      case 'taught':
      case 'strong':
        return <CheckCircle size={18} className="node-icon mastery-icon" />;
      case 'weak':
        return <RefreshCw size={16} className="node-icon review-icon" />;
      case 'critical':
        return <AlertCircle size={18} className="node-icon critical-icon" />;
      default:
        return <Milestone size={16} className="node-icon pending-icon" />;
    }
  };

  return (
    <div className="curriculum-path-container">
      <style>{`
        .curriculum-path-list {
          position: relative;
          padding-left: 2.5rem;
          list-style: none;
          margin-top: 1.5rem;
        }

        .curriculum-path-list::before {
          content: '';
          position: absolute;
          left: 11px;
          top: 8px;
          bottom: 8px;
          width: 2px;
          background-color: var(--color-border);
          z-index: 1;
        }

        .curriculum-path-item {
          position: relative;
          margin-bottom: 2rem;
          transition: all var(--transition-smooth);
        }

        .curriculum-path-item:last-child {
          margin-bottom: 0;
        }

        /* Connecting bullet/node */
        .curriculum-path-bullet {
          position: absolute;
          left: -2.5rem;
          top: 2px;
          width: 24px;
          height: 24px;
          border-radius: 50%;
          background-color: var(--color-paper-white);
          border: 2px solid var(--color-border);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 2;
          transition: all var(--transition-smooth);
        }

        /* Detour styling for prerequisites */
        .curriculum-path-item.is-prereq {
          padding-left: 1.5rem;
        }

        .curriculum-path-item.is-prereq .curriculum-path-bullet {
          left: -1rem;
          border-style: dashed;
        }

        /* Detour dashed connector visual */
        .curriculum-path-item.is-prereq::before {
          content: '';
          position: absolute;
          left: -11px;
          top: -20px;
          width: 15px;
          height: 35px;
          border-left: 2px dashed var(--color-accent-rust);
          border-bottom: 2px dashed var(--color-accent-rust);
          border-bottom-left-radius: 6px;
          z-index: 1;
        }

        /* Node States */
        .curriculum-path-item.active .curriculum-path-bullet {
          border-color: #B37D22;
          background-color: #FEF3C7;
          box-shadow: 0 0 0 4px rgba(179, 125, 34, 0.15);
          animation: pulse-border 2s infinite ease-in-out;
        }

        .curriculum-path-item.taught .curriculum-path-bullet,
        .curriculum-path-item.strong .curriculum-path-bullet {
          border-color: var(--color-accent-mastery);
          background-color: var(--color-accent-mastery-light);
        }

        .curriculum-path-item.weak .curriculum-path-bullet,
        .curriculum-path-item.critical .curriculum-path-bullet {
          border-color: var(--color-accent-rust);
          background-color: var(--color-accent-rust-light);
        }

        .node-icon {
          color: var(--color-text-muted);
        }
        .active-icon { color: #B37D22; }
        .mastery-icon { color: var(--color-accent-mastery); }
        .review-icon { color: var(--color-accent-rust); }
        .critical-icon { color: var(--color-accent-rust); }
        .pending-icon { color: var(--color-text-muted); }

        /* Card-like info on the side */
        .path-node-content {
          background-color: var(--color-paper-white);
          border: 1px solid var(--color-border);
          border-radius: var(--radius-sm);
          padding: 1rem 1.25rem;
          cursor: pointer;
          transition: all var(--transition-smooth);
        }

        .path-node-content:hover {
          border-color: var(--color-text-muted);
          transform: translateX(3px);
          box-shadow: 2px 2px 10px var(--color-shadow);
        }

        .curriculum-path-item.active .path-node-content {
          border-color: #B37D22;
          background-color: #FFFDF8;
        }

        .path-node-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 0.25rem;
        }

        .path-node-title {
          font-family: var(--font-serif);
          font-size: 1.1rem;
          font-weight: 600;
          color: var(--color-text-ink);
        }

        .curriculum-path-item.active .path-node-title {
          color: var(--color-text-ink);
        }

        .path-node-desc {
          font-size: 0.8rem;
          color: var(--color-text-muted);
        }

        .detour-indicator {
          margin-top: 0.5rem;
          padding: 0.4rem 0.6rem;
          background-color: var(--color-accent-rust-light);
          border: 1px solid var(--color-accent-rust);
          border-radius: var(--radius-sm);
          font-size: 0.75rem;
          color: var(--color-accent-rust);
          display: flex;
          align-items: center;
          gap: 0.4rem;
        }

        @keyframes pulse-border {
          0% { box-shadow: 0 0 0 0 rgba(179, 125, 34, 0.3); }
          70% { box-shadow: 0 0 0 6px rgba(179, 125, 34, 0); }
          100% { box-shadow: 0 0 0 0 rgba(179, 125, 34, 0); }
        }
      `}</style>

      <ul className="curriculum-path-list">
        {topics.map((topic, index) => {
          const isPrereq = !!prereqRelations[topic.topic_id];
          const isActive = topic.topic_name === currentTopicName;
          const statusConfig = STATUS_MAP[topic.status] || { label: 'Pending' };

          // If this is a critical topic, we want to know what prerequisite was inserted
          const hasInsertedPrereq = topic.status === 'critical' && topic.inferred_gap;

          return (
            <li
              key={topic.topic_id}
              className={`curriculum-path-item ${topic.status} ${isActive ? 'active' : ''} ${isPrereq ? 'is-prereq' : ''}`}
            >
              <div className="curriculum-path-bullet">
                {renderNodeIcon(topic, isActive)}
              </div>

              <div
                className="path-node-content"
                onClick={() => onSelectTopic && onSelectTopic(topic)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    onSelectTopic && onSelectTopic(topic);
                  }
                }}
              >
                <div className="path-node-header">
                  <span className="path-node-title">
                    {topic.topic_name}
                  </span>
                  <span
                    className="topic-status-pill"
                    style={{
                      backgroundColor: statusConfig.bg,
                      color: statusConfig.color,
                      fontSize: '0.7rem',
                      padding: '0.1rem 0.4rem'
                    }}
                  >
                    {isActive ? 'Current' : statusConfig.label}
                  </span>
                </div>

                <div className="path-node-desc">
                  {topic.subtopics && topic.subtopics.length > 0
                    ? `${topic.subtopics.length} concepts covered`
                    : 'Introductory concept'}
                  {topic.attempts > 0 && ` • Attempt ${topic.attempts}`}
                  {topic.quiz_score > 0 && ` • Best Quiz: ${Math.round(topic.quiz_score)}%`}
                </div>

                {hasInsertedPrereq && (
                  <div className="detour-indicator">
                    <Milestone size={12} style={{ flexShrink: 0 }} />
                    <span>
                      Inserted Prerequisite detour: <strong>{topic.inferred_gap}</strong>
                    </span>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
