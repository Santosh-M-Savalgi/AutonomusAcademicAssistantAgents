import React, { useState, useEffect } from 'react';
import { HelpCircle, AlertCircle, CheckCircle, RefreshCw, Milestone, Award, ArrowRight } from 'lucide-react';
import { api } from '../api';
import { NEXT_ACTION_MAP } from '../utils';

export default function QuizView({ studentId, onBackToSyllabus, onActionTriggered }) {
  const [quiz, setQuiz] = useState(null);
  const [answers, setAnswers] = useState({}); // { question_id: answer_text }
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  
  // Results states
  const [results, setResults] = useState(null); // { score, verdict, feedback, next_action }

  useEffect(() => {
    const fetchQuiz = async () => {
      try {
        setLoading(true);
        const data = await api.getQuiz(studentId);
        setQuiz(data);
        
        // Initialize empty answers
        const initialAnswers = {};
        data.questions.forEach((q) => {
          initialAnswers[q.question_id] = '';
        });
        setAnswers(initialAnswers);
      } catch (err) {
        console.error(err);
        setError(err.message || 'Failed to retrieve quiz questions.');
      } finally {
        setLoading(false);
      }
    };

    fetchQuiz();
  }, [studentId]);

  const handleAnswerChange = (questionId, value) => {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: value
    }));
  };

  const isFormValid = () => {
    // Make sure all questions have some text
    return quiz?.questions.every((q) => answers[q.question_id]?.trim().length > 0);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isFormValid()) return;

    setError(null);
    setSubmitting(true);

    try {
      const payload = Object.entries(answers).map(([qId, text]) => ({
        question_id: qId,
        answer_text: text
      }));

      const response = await api.submitAnswers(studentId, payload);
      setResults(response);
    } catch (err) {
      console.error(err);
      setError(err.message || 'Failed to submit answers for evaluation.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-box" style={{ minHeight: '60vh' }}>
        <div className="academic-spinner"></div>
        <h2 className="loading-text">Generating Comprehension Check...</h2>
        <p className="loading-subtext">The agent is formulating customized conceptual questions from the lesson content.</p>
      </div>
    );
  }

  if (submitting) {
    return (
      <div className="loading-box" style={{ minHeight: '60vh' }}>
        <div className="academic-spinner"></div>
        <h2 className="loading-text">Evaluating Comprehension...</h2>
        <p className="loading-subtext">The agent is reviewing your responses, evaluating conceptual precision, and preparing feedback.</p>
      </div>
    );
  }

  if (results) {
    const isPass = results.verdict === 'pass';
    const actionConfig = NEXT_ACTION_MAP[results.next_action] || {
      title: 'Session Updated',
      description: 'The agent has adjusted your curriculum. Let\'s continue.',
      buttonText: 'Continue'
    };

    return (
      <div className="quiz-layout">
        <div className="quiz-results-card">
          <h1 className={`results-verdict-title ${isPass ? 'pass' : 'fail'}`}>
            {isPass ? 'Comprehension Mastered' : 'Concepts Requiring Review'}
          </h1>
          <p style={{ textAlign: 'center', color: 'var(--color-text-muted)', fontSize: '0.95rem' }}>
            {isPass ? 'Excellent work! You have shown a strong grasp of the material.' : 'Don\'t worry. Reviewing materials is an important part of deep study.'}
          </p>

          <div className="score-display">
            <div className={`score-circle ${isPass ? 'pass' : 'fail'}`}>
              {Math.round(results.score)}%
            </div>
            <span className="score-label">Accuracy Score</span>
          </div>

          <div className="feedback-section">
            <h2 className="feedback-section-title">Academic Feedback</h2>
            <div className="feedback-list">
              {quiz.questions.map((q, idx) => {
                const studentAnswer = answers[q.question_id];
                const feedbackText = results.feedback[idx] || 'Response analyzed successfully.';
                // If feedback starts with correct/incorrect indicators, style them
                const isItemPass = feedbackText.toLowerCase().includes('correct') && !feedbackText.toLowerCase().includes('incorrect');
                
                return (
                  <div key={q.question_id} className={`feedback-item ${isPass ? 'pass' : 'fail'}`}>
                    <div className="question-num">Question {idx + 1}</div>
                    <p style={{ fontWeight: 600, fontFamily: 'var(--font-serif)', marginBottom: '0.5rem' }}>
                      {q.question}
                    </p>
                    <div style={{ fontStyle: 'italic', color: 'var(--color-text-muted)', marginBottom: '0.75rem', fontSize: '0.9rem' }}>
                      <strong>Your Answer:</strong> "{studentAnswer}"
                    </div>
                    <div style={{ fontSize: '0.95rem', borderTop: '1px solid var(--color-border)', paddingTop: '0.5rem' }}>
                      <strong>Feedback:</strong> {feedbackText}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Adaptive Next Action Box */}
          <div className={`action-card ${results.next_action}`}>
            <h3 className="action-card-title">{actionConfig.title}</h3>
            <p className="action-card-desc">{actionConfig.description}</p>
            
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                className="btn btn-primary"
                onClick={() => onActionTriggered(results.next_action)}
              >
                {actionConfig.buttonText}
                <ArrowRight size={16} />
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="quiz-layout">
      <div className="quiz-header">
        <h1 style={{ fontSize: '2rem', fontFamily: 'var(--font-serif)' }}>Comprehension Check</h1>
        <p className="quiz-subtitle">Topic: {quiz?.topic_name}</p>
      </div>

      {error && (
        <div className="error-banner">
          <AlertCircle size={18} />
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="quiz-sheet">
          {quiz?.questions.map((q, index) => (
            <div key={q.question_id} className="quiz-question-card">
              <div className="question-num">Question {index + 1} of {quiz.questions.length}</div>
              <h3 className="question-text">{q.question}</h3>
              
              <div className="form-group" style={{ margin: 0 }}>
                <label className="form-label" htmlFor={`ans-${q.question_id}`}>Your Response</label>
                <textarea
                  id={`ans-${q.question_id}`}
                  className="form-textarea"
                  style={{ minHeight: '100px', backgroundColor: 'var(--color-paper-bg)' }}
                  placeholder="Formulate your explanation here. Use your own words to describe the concepts..."
                  value={answers[q.question_id]}
                  onChange={(e) => handleAnswerChange(q.question_id, e.target.value)}
                  disabled={submitting}
                  aria-required="true"
                />
              </div>
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onBackToSyllabus}
            disabled={submitting}
          >
            Cancel and Return
          </button>
          
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!isFormValid() || submitting}
          >
            Submit Answers for Evaluation
          </button>
        </div>
      </form>
    </div>
  );
}
