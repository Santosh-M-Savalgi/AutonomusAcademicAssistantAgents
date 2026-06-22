import React, { useState, useEffect } from 'react';
import Onboarding from './components/Onboarding';
import SyllabusOverview from './components/SyllabusOverview';
import LessonView from './components/LessonView';
import QuizView from './components/QuizView';
import ProfileView from './components/ProfileView';
import ProgressBar from './components/ProgressBar';
import { api } from './api';

export default function App() {
  const [studentId, setStudentId] = useState(null);
  const [currentScreen, setCurrentScreen] = useState('onboarding'); // onboarding, syllabus, lesson, quiz, profile
  const [studentName, setStudentName] = useState('');
  
  // Progress stats for ProgressBar
  const [progressStats, setProgressStats] = useState({ completed: 0, total: 0 });
  const [loading, setLoading] = useState(true);

  // Attempt to auto-resume student session on mount
  useEffect(() => {
    const resumeSession = async () => {
      const savedStudentId = localStorage.getItem('aaa_student_id');
      if (savedStudentId) {
        try {
          // Verify with backend
          const studentProfile = await api.getStudent(savedStudentId);
          const topics = await api.getTopics(savedStudentId);
          
          setStudentId(savedStudentId);
          setStudentName(studentProfile.name);
          
          // Calculate progress stats
          const completed = topics.filter(t => t.status === 'taught').length;
          setProgressStats({ completed, total: topics.length });
          
          setCurrentScreen('syllabus');
        } catch (err) {
          console.warn('Could not auto-resume session:', err);
          // Clear stale ID
          localStorage.removeItem('aaa_student_id');
          setCurrentScreen('onboarding');
        }
      } else {
        setCurrentScreen('onboarding');
      }
      setLoading(false);
    };

    resumeSession();
  }, []);

  // Sync completion stats periodically or on view transitions
  const syncProgress = async (id) => {
    if (!id) return;
    try {
      const topics = await api.getTopics(id);
      const completed = topics.filter(t => t.status === 'taught').length;
      setProgressStats({ completed, total: topics.length });
    } catch (e) {
      console.warn('Could not sync completion stats:', e);
    }
  };

  const handleStudentCreated = (newId, syllabus) => {
    setStudentId(newId);
    
    // We can extract name from the syllabus response or profile
    api.getStudent(newId).then(profile => {
      setStudentName(profile.name);
    });

    const completed = syllabus.filter(t => t.status === 'taught').length;
    setProgressStats({ completed, total: syllabus.length });
    setCurrentScreen('syllabus');
  };

  const handleLogout = () => {
    localStorage.removeItem('aaa_student_id');
    setStudentId(null);
    setStudentName('');
    setProgressStats({ completed: 0, total: 0 });
    setCurrentScreen('onboarding');
  };

  const handleActionTriggered = (nextAction) => {
    syncProgress(studentId);
    // Based on action returned by evaluate answer, drive the next UI screen
    if (nextAction === 'advance' || nextAction === 'complete') {
      setCurrentScreen('syllabus');
    } else if (nextAction === 'reteach') {
      // Goes back to syllabus, student clicks "Review Lesson" to regenerate from backend
      setCurrentScreen('syllabus');
    } else if (nextAction === 'insert_prerequisite') {
      // Goes back to syllabus to see prerequisite detour in timeline
      setCurrentScreen('syllabus');
    } else {
      setCurrentScreen('syllabus');
    }
  };

  if (loading) {
    return (
      <div className="loading-box" style={{ minHeight: '100vh' }}>
        <div className="academic-spinner"></div>
        <h2 className="loading-text">Resuming academic session...</h2>
      </div>
    );
  }

  return (
    <div className="app-container">
      {/* Top minimal progress bar */}
      {studentId && (
        <ProgressBar
          completedCount={progressStats.completed}
          totalCount={progressStats.total}
        />
      )}

      {/* Header section */}
      <header className="app-header">
        <div className="logo-section" onClick={() => studentId && setCurrentScreen('syllabus')}>
          <span className="logo-icon">🏛️</span>
          <span className="logo-text">Autonomous Academic Agent</span>
        </div>
        
        {studentId && (
          <nav className="nav-section">
            <span
              className={`nav-link ${currentScreen === 'syllabus' ? 'active' : ''}`}
              onClick={() => { syncProgress(studentId); setCurrentScreen('syllabus'); }}
            >
              Syllabus Roadmap
            </span>
            <span
              className={`nav-link ${currentScreen === 'profile' ? 'active' : ''}`}
              onClick={() => setCurrentScreen('profile')}
            >
              Progress Log
            </span>
            <button
              onClick={handleLogout}
              className="btn btn-secondary"
              style={{ fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}
            >
              Change Student
            </button>
          </nav>
        )}
      </header>

      {/* Main page router */}
      <main style={{ flex: 1 }}>
        {currentScreen === 'onboarding' && (
          <Onboarding onStudentCreated={handleStudentCreated} />
        )}

        {currentScreen === 'syllabus' && studentId && (
          <SyllabusOverview
            studentId={studentId}
            onStartLesson={() => setCurrentScreen('lesson')}
            onSelectProfile={() => setCurrentScreen('profile')}
          />
        )}

        {currentScreen === 'lesson' && studentId && (
          <LessonView
            studentId={studentId}
            onStartQuiz={() => setCurrentScreen('quiz')}
            onBackToSyllabus={() => { syncProgress(studentId); setCurrentScreen('syllabus'); }}
          />
        )}

        {currentScreen === 'quiz' && studentId && (
          <QuizView
            studentId={studentId}
            onBackToSyllabus={() => { syncProgress(studentId); setCurrentScreen('syllabus'); }}
            onActionTriggered={handleActionTriggered}
          />
        )}

        {currentScreen === 'profile' && studentId && (
          <ProfileView
            studentId={studentId}
            onBack={() => setCurrentScreen('syllabus')}
          />
        )}
      </main>
    </div>
  );
}
