import React, { useState, useEffect } from 'react';
import { BookOpen, HelpCircle, ArrowLeft, Layers, Bookmark } from 'lucide-react';
import { api } from '../api';

// Native lightweight React Markdown Renderer for optimal rendering of AI-generated content
function Markdown({ text }) {
  if (!text) return null;

  // Normalize line breaks
  const normalizedText = text.replace(/\r\n/g, '\n');
  const blocks = normalizedText.split(/\n\n+/);

  const parseInline = (inlineText) => {
    if (!inlineText) return '';
    let parts = [inlineText];

    // Bold: **text**
    parts = parts.flatMap(part => {
      if (typeof part !== 'string') return part;
      const regex = /\*\*(.*?)\*\*/g;
      const split = part.split(regex);
      return split.map((sub, i) => (i % 2 === 1 ? <strong key={`bold-${i}`}>{sub}</strong> : sub));
    });

    // Inline code: `code`
    parts = parts.flatMap(part => {
      if (typeof part !== 'string') return part;
      const regex = /`(.*?)`/g;
      const split = part.split(regex);
      return split.map((sub, i) => (i % 2 === 1 ? <code key={`code-${i}`}>{sub}</code> : sub));
    });

    // Links: [text](url)
    parts = parts.flatMap(part => {
      if (typeof part !== 'string') return part;
      const regex = /\[(.*?)\]\((.*?)\)/g;
      if (!part.match(regex)) return part;

      const elements = [];
      let remaining = part;
      let keyIdx = 0;

      while (remaining) {
        const match = remaining.match(/\[(.*?)\]\((.*?)\)/);
        if (!match) {
          elements.push(remaining);
          break;
        }

        const index = match.index;
        const textStr = match[1];
        const urlStr = match[2];

        if (index > 0) {
          elements.push(remaining.substring(0, index));
        }

        elements.push(
          <a key={`link-${keyIdx}`} href={urlStr} target="_blank" rel="noopener noreferrer" className="lesson-link">
            {textStr}
          </a>
        );

        remaining = remaining.substring(index + match[0].length);
        keyIdx++;
      }
      return elements;
    });

    return parts;
  };

  return (
    <div className="lesson-content">
      {blocks.map((block, idx) => {
        const trimmed = block.trim();
        if (!trimmed) return null;

        // Code block
        if (trimmed.startsWith('```')) {
          const lines = trimmed.split('\n');
          const codeLang = lines[0].replace('```', '').trim();
          const codeBody = lines.slice(1, -1).join('\n');
          return (
            <pre key={`pre-${idx}`}>
              <code className={codeLang}>{codeBody}</code>
            </pre>
          );
        }

        // Headers
        if (trimmed.startsWith('### ')) {
          return <h3 key={`h3-${idx}`}>{parseInline(trimmed.replace('### ', ''))}</h3>;
        }
        if (trimmed.startsWith('## ')) {
          return <h2 key={`h2-${idx}`}>{parseInline(trimmed.replace('## ', ''))}</h2>;
        }
        if (trimmed.startsWith('# ')) {
          return <h1 key={`h1-${idx}`}>{parseInline(trimmed.replace('# ', ''))}</h1>;
        }

        // Blockquotes
        if (trimmed.startsWith('> ')) {
          const quoteText = trimmed.replace(/^>\s+/gm, '');
          return <blockquote key={`quote-${idx}`}>{parseInline(quoteText) }</blockquote>;
        }

        // Bullet lists
        if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
          const lines = trimmed.split('\n');
          return (
            <ul key={`ul-${idx}`}>
              {lines.map((line, lIdx) => {
                const cleanLine = line.replace(/^[-*]\s+/, '');
                return <li key={`li-${lIdx}`}>{parseInline(cleanLine)}</li>;
              })}
            </ul>
          );
        }

        // Numbered lists
        if (/^\d+\.\s+/.test(trimmed)) {
          const lines = trimmed.split('\n');
          return (
            <ol key={`ol-${idx}`}>
              {lines.map((line, lIdx) => {
                const cleanLine = line.replace(/^\d+\.\s+/, '');
                return <li key={`li-${lIdx}`}>{parseInline(cleanLine)}</li>;
              })}
            </ol>
          );
        }

        // Standard paragraph
        return <p key={`p-${idx}`}>{parseInline(trimmed)}</p>;
      })}
    </div>
  );
}

export default function LessonView({ studentId, onStartQuiz, onBackToSyllabus }) {
  const [lesson, setLesson] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showSources, setShowSources] = useState(true);

  useEffect(() => {
    const fetchLesson = async () => {
      try {
        setLoading(true);
        const data = await api.getLesson(studentId);
        setLesson(data);
      } catch (err) {
        console.error(err);
        setError(err.message || 'Failed to retrieve the lesson content.');
      } finally {
        setLoading(false);
      }
    };

    fetchLesson();
  }, [studentId]);

  if (loading) {
    return (
      <div className="loading-box" style={{ minHeight: '60vh' }}>
        <div className="academic-spinner"></div>
        <h2 className="loading-text">Opening Textbook Chapter...</h2>
        <p className="loading-subtext">Structuring reading layout and source index...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bookplate-card" style={{ textAlign: 'center' }}>
        <h2 className="results-verdict-title fail">Lesson Not Found</h2>
        <p style={{ color: 'var(--color-text-muted)', marginBottom: '1.5rem' }}>
          {error}
        </p>
        <button className="btn btn-primary" onClick={onBackToSyllabus}>
          Return to Syllabus
        </button>
      </div>
    );
  }

  return (
    <div className="lesson-layout">
      {/* Left Pane: Main Reading Area */}
      <div className="lesson-reading-pane">
        <div className="lesson-topic-indicator">Active Learning Unit</div>
        <h1 className="lesson-title">{lesson?.topic_name}</h1>
        
        <Markdown text={lesson?.lesson_content} />

        <div className="lesson-toolbar">
          <button className="btn btn-secondary" onClick={onBackToSyllabus}>
            <ArrowLeft size={16} />
            Return to Syllabus
          </button>
          
          <button className="btn btn-primary" onClick={onStartQuiz}>
            Begin Comprehension Check
            <HelpCircle size={16} />
          </button>
        </div>
      </div>

      {/* Right Pane: Sources used to compile lesson */}
      <div className="sources-sidebar">
        <div className="sidebar-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <Layers size={14} />
            Sources Cited ({lesson?.sources?.length || 0})
          </span>
          <button 
            className="btn-text" 
            style={{ fontSize: '0.75rem', textTransform: 'none', letterSpacing: 0 }}
            onClick={() => setShowSources(!showSources)}
          >
            {showSources ? 'Hide' : 'Show'}
          </button>
        </div>

        {showSources && (
          <div className="sources-list">
            {lesson?.sources && lesson.sources.length > 0 ? (
              lesson.sources.map((src, index) => (
                <div key={index} className="source-card">
                  <a
                    href={src.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="source-link"
                    title={src.source_url}
                  >
                    {src.source_url.replace(/https?:\/\/(www\.)?/, '').substring(0, 32)}...
                  </a>
                  <p className="source-summary">{src.summary}</p>
                </div>
              ))
            ) : (
              <div className="source-card" style={{ color: 'var(--color-text-muted)', textAlign: 'center', padding: '1.5rem' }}>
                <Bookmark size={20} style={{ margin: '0 auto 0.5rem auto', opacity: 0.5 }} />
                No web sources were cited for this foundational concept.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
