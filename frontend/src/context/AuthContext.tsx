/**
 * @fileoverview 전역 사용자 인증 상태(AuthContext) 및 세션 라이프사이클 관리 프로바이더
 */
import React, { createContext, useContext, useState, useEffect } from 'react';
import { type User, getCurrentUser, login as apiLogin, register as apiRegister, logout as apiLogout } from '../api/authClient';

interface AuthContextType {
  /** 현재 로그인된 사용자 프로필 (비로그인 시 null) */
  user: User | null;
  /** 초기 세션 확인 로딩 여부 */
  loading: boolean;
  /** 로그인 함수 */
  login: typeof apiLogin;
  /** 회원가입 함수 */
  register: typeof apiRegister;
  /** 로그아웃 함수 */
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * 애플리케이션 전역 인증 상태를 제공하는 Context Provider 컴포넌트
 */
export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // 초기 마운트 시 서버 세션 쿠키 유효성 확인
    const initAuth = async () => {
      const currentUser = await getCurrentUser();
      setUser(currentUser);
      setLoading(false);
    };

    initAuth();

    // 전역 401(Unauthorized) 이벤트 수신 시 세션 상태 초기화
    const handleUnauthorized = () => {
      setUser(null);
    };
    window.addEventListener('auth:unauthorized', handleUnauthorized);

    return () => {
      window.removeEventListener('auth:unauthorized', handleUnauthorized);
    };
  }, []);

  const login = async (...args: Parameters<typeof apiLogin>) => {
    const userData = await apiLogin(...args);
    setUser(userData);
    return userData;
  };

  const register = async (email: string, password: string, name: string) => {
    const registeredUser = await apiRegister(email, password, name);
    // 회원가입 직후 자동 로그인하여 HttpOnly 세션 쿠키를 발급받는다.
    try {
      const loggedInUser = await apiLogin(email, password);
      setUser(loggedInUser);
      return loggedInUser;
    } catch {
      setUser(registeredUser);
      return registeredUser;
    }
  };

  const logout = async () => {
    await apiLogout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

/**
 * 인증 컨텍스트를 조회하는 커스텀 Hook
 */
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};


