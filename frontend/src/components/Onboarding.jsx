import React, { useState } from 'react';
import { Upload, BookOpen, AlertCircle } from 'lucide-react';
import { api } from '../api';

export default function Onboarding({ onStudentCreated }) {
  const [name, setName] = useState('');
  const [activeTab, setActiveTab] = useState('text'); // 'text' or 'pdf'
  const [rawInput, setRawInput] = useState('');
  const [file, setFile] = useState(null);
  
  const [loading, setLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState('');
  const [error, setError] = useState(null);
  const [validationErrors, setValidationErrors] = useState({});

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      if (selectedFile.type !== 'application/pdf' && !selectedFile.name.toLowerCase().endsWith('.pdf')) {
        setError('Please select a valid PDF file.');
        setFile(null);
      } else {
        setError(null);
        setFile(selectedFile);
      }
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      if (droppedFile.type !== 'application/pdf' && !droppedFile.name.toLowerCase().endsWith('.pdf')) {
        setError('Only PDF files are supported.');
      } else {
        setError(null);
        setFile(droppedFile);
      }
    }
  };

  const validateForm = () => {
    const errors = {};
    if (!name.trim()) {
      errors.name = 'Name is required.';
    }
    if (activeTab === 'text' && !rawInput.trim()) {
      errors.rawInput = 'Please describe what you want to learn.';
    }
    if (activeTab === 'pdf' && !file) {
      errors.file = 'Please upload a syllabus PDF.';
    }
    setValidationErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setValidationErrors({});

    if (!validateForm()) return;

    setLoading(true);
    setLoadingStep('Initializing student record...');

    try {
      let result;
      if (activeTab === 'text') {
        setLoadingStep('Analyzing goals and structuring curriculum nodes...');
        result = await api.createStudent(name, rawInput);
      } else {
        setLoadingStep('Uploading syllabus PDF and parsing content structures...');
        result = await api.uploadSyllabus(name, file);
      }

      setLoadingStep('Finalizing your personal classroom...');
      
      // Save student_id for session resume
      localStorage.setItem('aaa_student_id', result.student_id);
      
      // Notify parent component
      onStudentCreated(result.student_id, result.syllabus);
    } catch (err) {
      console.error(err);
      if (err.code === 'validation_error' && err.details) {
        // Map FastAPI Pydantic errors to fields
        const fieldErrors = {};
        err.details.forEach(detail => {
          const loc = detail.loc;
          const msg = detail.msg;
          if (loc.includes('name')) fieldErrors.name = msg;
          if (loc.includes('raw_input')) fieldErrors.rawInput = msg;
          if (loc.includes('file')) fieldErrors.file = msg;
        });
        setValidationErrors(fieldErrors);
        setError('Please check the highlighted fields below.');
      } else {
        setError(err.message || 'An error occurred while generating your syllabus. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-box" style={{ minHeight: '60vh' }}>
        <div className="academic-spinner"></div>
        <h2 className="loading-text">{loadingStep}</h2>
        <p className="loading-subtext">Gemini is designing your custom learning path. This can take up to 20 seconds.</p>
      </div>
    );
  }

  return (
    <div className="bookplate-card">
      <div className="logo-section" style={{ justifyContent: 'center', marginBottom: '1.5rem' }}>
        <span className="logo-icon">🏛️</span>
        <span className="logo-text">Autonomous Academic Agent</span>
      </div>
      <h1 className="bookplate-title">Begin Your Study Session</h1>
      <p className="bookplate-subtitle">Establish your custom learning goals and structured curriculum.</p>

      {error && (
        <div className="error-banner">
          <AlertCircle size={18} style={{ flexShrink: 0, marginTop: '2px' }} />
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label className="form-label" htmlFor="student-name">Your Name</label>
          <input
            id="student-name"
            type="text"
            className="form-input"
            placeholder="Enter your name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={loading}
            aria-required="true"
          />
          {validationErrors.name && (
            <div className="error-inline">{validationErrors.name}</div>
          )}
        </div>

        <div className="tabs">
          <button
            type="button"
            className={`tab-btn ${activeTab === 'text' ? 'active' : ''}`}
            onClick={() => { setActiveTab('text'); setError(null); }}
            disabled={loading}
          >
            Describe Learning Goal
          </button>
          <button
            type="button"
            className={`tab-btn ${activeTab === 'pdf' ? 'active' : ''}`}
            onClick={() => { setActiveTab('pdf'); setError(null); }}
            disabled={loading}
          >
            Upload Syllabus PDF
          </button>
        </div>

        {activeTab === 'text' ? (
          <div className="form-group">
            <label className="form-label" htmlFor="learning-goal">What do you want to learn?</label>
            <textarea
              id="learning-goal"
              className="form-textarea"
              placeholder="Describe your learning goals, background, or topics you want to cover. Example: 'I want to understand the fundamentals of Quantum Mechanics starting from wave-particle duality up to Schrodinger's Equation. I have a basic high school physics background.'"
              value={rawInput}
              onChange={(e) => setRawInput(e.target.value)}
              disabled={loading}
              aria-required="true"
            />
            {validationErrors.rawInput && (
              <div className="error-inline">{validationErrors.rawInput}</div>
            )}
          </div>
        ) : (
          <div className="form-group">
            <label className="form-label">Syllabus File (PDF)</label>
            <div
              className="dropzone"
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onClick={() => document.getElementById('syllabus-file-input').click()}
            >
              <Upload className="dropzone-icon" style={{ margin: '0 auto 0.75rem auto' }} />
              <p className="dropzone-text">Click to choose or drag & drop syllabus PDF</p>
              <p className="dropzone-subtext">PDF files only (Max 10MB)</p>
              <input
                id="syllabus-file-input"
                type="file"
                accept=".pdf"
                style={{ display: 'none' }}
                onChange={handleFileChange}
                disabled={loading}
              />
            </div>
            {file && (
              <div className="file-selected-indicator">
                <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <BookOpen size={16} />
                  <strong>{file.name}</strong> ({Math.round(file.size / 1024)} KB)
                </span>
                <button
                  type="button"
                  className="btn-text"
                  onClick={(e) => { e.stopPropagation(); setFile(null); }}
                  style={{ textDecoration: 'none', borderBottom: 'none', fontSize: '0.8rem' }}
                >
                  Remove
                </button>
              </div>
            )}
            {validationErrors.file && (
              <div className="error-inline" style={{ marginTop: '0.5rem' }}>{validationErrors.file}</div>
            )}
          </div>
        )}

        <button
          type="submit"
          className="btn btn-primary"
          style={{ width: '100%', marginTop: '1.5rem', padding: '0.8rem' }}
          disabled={loading}
        >
          Initialize Academy
        </button>
      </form>
    </div>
  );
}
