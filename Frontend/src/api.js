export const DEPLOYED_BACKEND_URL = 'https://soultune-zctz.onrender.com';
export const LOCAL_BACKEND_URL = 'http://127.0.0.1:8000';
export const DEPLOYED_FRONTEND_URL = 'https://soul-tune-kappa.vercel.app';

function resolveInitialBackend() {
  const envUrl = (import.meta.env?.VITE_API_URL || import.meta.env?.VITE_BACKEND_URL || '').trim();
  if (envUrl) return envUrl.replace(/\/$/, '');

  if (typeof window !== 'undefined') {
    const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);
    if (!isLocal) {
      return DEPLOYED_BACKEND_URL;
    }
  }
  // On localhost, default to deployed backend if available, with auto-fallback to local
  return DEPLOYED_BACKEND_URL;
}

let activeBackend = resolveInitialBackend();

export function getBackendUrl() {
  return activeBackend;
}

export function setBackendUrl(url) {
  activeBackend = url ? url.replace(/\/$/, '') : '';
}

export const getApiBase = () => (activeBackend ? `${activeBackend}/api/v1` : '/api/v1');
export const API = '/api/v1';
let csrfToken = '';
export function setCsrf(token) { csrfToken = token || ''; }

function getCandidateFallbacks() {
  const isLocal = typeof window !== 'undefined' && ['localhost', '127.0.0.1'].includes(window.location.hostname);
  if (isLocal) {
    return activeBackend === DEPLOYED_BACKEND_URL
      ? [LOCAL_BACKEND_URL, '']
      : [DEPLOYED_BACKEND_URL];
  }
  // On deployed domains: try relative rewrite proxy as fallback if direct fails, or direct if relative fails
  return activeBackend === DEPLOYED_BACKEND_URL ? [''] : [DEPLOYED_BACKEND_URL];
}

export async function api(path, options = {}) {
  const method = options.method || 'GET';
  const headers = { ...options.headers };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (!['GET', 'HEAD'].includes(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken;

  const fetchOptions = {
    ...options,
    method,
    headers,
    credentials: 'include',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  };

  const executeFetch = async (backend) => {
    const base = backend ? `${backend}/api/v1` : '/api/v1';
    return fetch(`${base}${path}`, fetchOptions);
  };

  let response;
  try {
    response = await executeFetch(activeBackend);
    // If local Vite proxy returns 503 indicating unreachable backend, trigger fallback
    if (response.status === 503) {
      const clone = response.clone();
      try {
        const body = await clone.json();
        if (body?.detail?.includes?.('Backend server is unreachable')) {
          throw new Error('Backend unreachable');
        }
      } catch (err) {
        if (err.message === 'Backend unreachable') throw err;
      }
    }
  } catch (err) {
    let fallbackSuccess = false;
    const fallbacks = getCandidateFallbacks();
    for (const candidate of fallbacks) {
      if (candidate === activeBackend) continue;
      try {
        response = await executeFetch(candidate);
        if (response.status !== 503) {
          activeBackend = candidate;
          fallbackSuccess = true;
          break;
        }
      } catch {
        // Continue trying next fallback candidate
      }
    }
    if (!fallbackSuccess) {
      throw new Error('Cannot reach SoulTune. Check your connection and make sure the server is running.');
    }
  }

  let result;
  try { result = await response.json(); } catch { result = {}; }
  if (!response.ok) {
    const detail = result.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg).join('. ') : 'Something went wrong. Please try again.';
    const error = new Error(message);
    error.status = response.status;
    error.retryAfter = Number(response.headers.get('Retry-After')) || 0;
    if (response.status === 401 && !path.startsWith('/auth/') && message !== 'Credentials are incorrect.') window.dispatchEvent(new Event('soultune-session-expired'));
    throw error;
  }
  if (result.csrf_token) setCsrf(result.csrf_token);
  return result;
}

export async function downloadPlaylist(id, format) {
  const base = activeBackend ? `${activeBackend}/api/v1` : '/api/v1';
  const response = await fetch(`${base}/playlists/${encodeURIComponent(id)}/export?format=${format}`, { credentials: 'include' });
  if (!response.ok) throw new Error('Could not export this playlist. Please try again.');
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `soultune-playlist.${format}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function safeUrl(value) {
  if (!value || typeof value !== 'string') return '';
  if (value.startsWith('/api/') && !value.startsWith('//')) {
    return activeBackend ? `${activeBackend}${value}` : value;
  }
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : ''; } catch { return ''; }
}

export const defaults = { genres: [], languages: [], activities: [], excluded_artists: [], excluded_genres: [], playlist_size: 10, allow_explicit: false, theme: 'dark', personalization: true, diversity: true };
export const genres = ['Indie', 'Electronic', 'Lo-fi', 'Pop', 'Rock', 'Hip-hop', 'Jazz', 'Classical', 'Ambient', 'R&B'];
export const languages = ['English', 'Hindi', 'Telugu', 'Tamil', 'Spanish', 'Instrumental'];
export const activities = ['Coding', 'Studying', 'Workout', 'Driving', 'Relaxing', 'Party'];
export const normalizePlaylist = data => data.playlist || data;
export const formatTime = (seconds) => { const s = Math.max(0, Math.floor(Number(seconds) || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
export const percent = value => Math.round(Math.min(1, Math.max(0, Number(value) || 0)) * 100);
export const titleCase = value => String(value || '').replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
