import { apiFetch } from './apiFetch';

export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
}

export async function login(email: string, password: string): Promise<User> {
  const res = await apiFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password })
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || '로그인에 실패했습니다.');
  }
  return res.json();
}

export async function register(email: string, password: string, name: string): Promise<User> {
  const res = await apiFetch('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password, name })
  });
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || '회원가입에 실패했습니다.');
  }
  return res.json();
}

export async function logout(): Promise<void> {
  await apiFetch('/auth/logout', { method: 'POST' });
}

export async function getCurrentUser(): Promise<User | null> {
  try {
    const res = await apiFetch('/auth/me');
    if (res.ok) {
      return res.json();
    }
    return null;
  } catch (err) {
    return null;
  }
}

