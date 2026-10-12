import { BrowserRouter as Router, Routes, Route, Link, useNavigate } from 'react-router-dom';
import { CaseList } from './pages/CaseList';
import { CaseWorkspace } from './pages/CaseWorkspace';
import { Login } from './pages/Login';
import { Register } from './pages/Register';
import { AuthProvider, useAuth } from './context/AuthContext';
import './App.css';

function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', paddingBottom: '10px', borderBottom: '1px solid #eee' }}>
      <h1><Link to="/" style={{ textDecoration: 'none', color: 'inherit' }}>AI Legal Helper</Link></h1>
      {user ? (
        <div>
          <span style={{ marginRight: '15px' }}>👤 {user.name || (user as any).display_name || '로컬 테스터'} 님</span>
          <button onClick={handleLogout} style={{ padding: '5px 10px' }}>로그아웃</button>
        </div>
      ) : (
        <div>
          <span style={{ marginRight: '15px', color: '#2e7d32', fontWeight: 'bold' }}>⚡ 1인 로컬 테스트 모드 (인증 생략)</span>
          <Link to="/" style={{ textDecoration: 'none', color: '#1976d2' }}>사건 목록</Link>
        </div>
      )}
    </div>
  );
}

function AppContent() {
  return (
    <div className="container">
      <Navbar />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/" element={<CaseList />} />
        <Route path="/:caseId/workspace/*" element={<CaseWorkspace />} />
      </Routes>
    </div>
  );
}

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
