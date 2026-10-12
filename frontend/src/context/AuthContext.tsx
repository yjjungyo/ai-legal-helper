import React, { createContext, useContext, useState, useEffect } from 'react';
import { type User, getCurrentUser, login as apiLogin, register as apiRegister, logout as apiLogout } from '../api/authClient';

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: typeof apiLogin;
  register: typeof apiRegister;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if user is logged in
    const initAuth = async () => {
      const currentUser = await getCurrentUser();
      setUser(currentUser);
      setLoading(false);
    };

    initAuth();

    // Listen to global 401 events
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

  const register = async (...args: Parameters<typeof apiRegister>) => {
    const userData = await apiRegister(...args);
    setUser(userData);
    return userData;
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

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

