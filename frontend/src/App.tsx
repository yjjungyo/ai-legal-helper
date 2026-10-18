/**
 * @fileoverview 애플리케이션 진입점 및 전역 라우팅 구성
 * 상단 글로벌 네비게이션 헤더(Navbar)와 메인 뷰 라우터를 제공합니다.
 */

import { BrowserRouter as Router, Routes, Route, Link, useNavigate } from 'react-router-dom';
import { CaseList } from './pages/CaseList';
import { CaseWorkspace } from './pages/CaseWorkspace';
import { Login } from './pages/Login';
import { Register } from './pages/Register';
import { AuthProvider, useAuth } from './context/AuthContext';
import './App.css';

/**
 * 전역 상단 네비게이션 바 컴포넌트
 * 로고, 사건 목록 바로가기 링크 및 사용자 프로필/인증 상태를 표시합니다.
 */
function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <header className="app-header">
      <Link to="/" className="app-brand">
        <div className="app-brand-logo">⚖️</div>
        <span>AI Legal Helper</span>
      </Link>

      <div className="app-user-section">
        {user ? (
          <>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.9em' }}>
              👤 <strong>{user.name || (user as any).display_name || '사용자'}</strong> 님
            </span>
            <button onClick={handleLogout} className="btn btn-secondary btn-sm">
              로그아웃
            </button>
          </>
        ) : (
          <>
            <span className="badge badge-green" style={{ display: 'inline-flex', gap: '4px' }}>
              ⚡ 1인 로컬 테스트 모드 (인증 생략)
            </span>
            <Link to="/" className="btn btn-outline btn-sm">
              사건 목록
            </Link>
          </>
        )}
      </div>
    </header>
  );
}

/**
 * 라우트별 메인 콘텐츠 영역 래퍼
 */
function AppContent() {
  return (
    <div className="app-layout">
      <Navbar />
      <main className="app-main">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/" element={<CaseList />} />
          <Route path="/:caseId/workspace/*" element={<CaseWorkspace />} />
        </Routes>
      </main>
    </div>
  );
}

/**
 * 최상위 루트 컴포넌트
 */
function App() {
  return (
    <AuthProvider>
      <Router>
        <AppContent />
      </Router>
    </AuthProvider>
  );
}

export default App;
