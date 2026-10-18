/**
 * @fileoverview 사용자 인증(로그인, 회원가입, 로그아웃, 세션 확인) API 클라이언트 모듈
 */
import { apiFetch } from './apiFetch';

/**
 * 인증된 사용자 프로필 인터페이스
 */
export interface User {
  id: string;
  email: string;
  name: string;
  display_name?: string;
  status?: string;
  role?: string;
}

/**
 * 백엔드 응답 객체를 프런트엔드 User 인터페이스로 정규화한다.
 * @param raw 백엔드 응답 JSON 객체
 * @returns 정규화된 User 객체
 */
function normalizeUser(raw: Record<string, unknown>): User {
  const displayName = (raw.display_name as string) || (raw.name as string) || '';
  return {
    id: String(raw.id || ''),
    email: String(raw.email || ''),
    name: displayName,
    display_name: displayName,
    status: (raw.status as string) || 'ACTIVE',
    role: (raw.role as string) || 'USER',
  };
}

/**
 * 이메일과 비밀번호로 로그인하고 세션 쿠키를 발급받는다.
 * @param email 사용자 이메일
 * @param password 비밀번호
 * @returns 로그인된 사용자 프로필
 */
export async function login(email: string, password: string): Promise<User> {
  const res = await apiFetch('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail || '로그인에 실패했습니다.');
  }
  const data = await res.json();
  // 로그인 응답에 id가 포함되어 있으면 즉시 정규화하고, 없으면 /auth/me를 호출해 프로필을 보강한다.
  if (data && data.id) {
    return normalizeUser(data);
  }
  const me = await getCurrentUser();
  if (!me) {
    throw new Error('로그인 후 사용자 정보를 불러오지 못했습니다.');
  }
  return me;
}

/**
 * 신규 사용자를 회원가입 등록한다.
 * @param email 사용자 이메일
 * @param password 비밀번호
 * @param name 사용자 표시 이름 (백엔드 display_name과 동시 전송)
 * @returns 생성된 사용자 프로필
 */
export async function register(email: string, password: string, name: string): Promise<User> {
  const res = await apiFetch('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password, name, display_name: name }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.detail || '회원가입에 실패했습니다.');
  }
  const data = await res.json();
  return normalizeUser(data);
}

/**
 * 현재 세션을 종료하고 쿠키를 제거한다.
 */
export async function logout(): Promise<void> {
  await apiFetch('/auth/logout', { method: 'POST' });
}

/**
 * 현재 세션 쿠키를 기반으로 로그인된 사용자 프로필을 조회한다.
 * @returns 로그인 상태인 경우 User 객체, 비로그인 시 null
 */
export async function getCurrentUser(): Promise<User | null> {
  try {
    const res = await apiFetch('/auth/me');
    if (res.ok) {
      const data = await res.json();
      return normalizeUser(data);
    }
    return null;
  } catch {
    return null;
  }
}


