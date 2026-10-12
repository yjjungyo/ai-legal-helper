export const API_BASE_URL = 'http://localhost:8000/api/v1';

export async function apiFetch(endpoint: string, options: RequestInit = {}): Promise<Response> {
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
  
  const headers: HeadersInit = {
    ...options.headers,
  };

  // Only set application/json if body is not FormData and Content-Type isn't already set
  if (!(options.body instanceof FormData) && !headers.hasOwnProperty('Content-Type') && !headers.hasOwnProperty('content-type')) {
    (headers as any)['Content-Type'] = 'application/json';
  }

  const response = await fetch(url, {
    ...options,
    credentials: 'include', // Important for HttpOnly cookies
    headers,
  });

  if (response.status === 401) {
    // Optionally trigger a global logout event here
    const event = new CustomEvent('auth:unauthorized');
    window.dispatchEvent(event);
  }

  return response;
}

