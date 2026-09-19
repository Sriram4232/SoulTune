export const API = '/api/v1';
let csrfToken = '';
export function setCsrf(token) { csrfToken = token || ''; }

export async function api(path, options = {}) {
  const method = options.method || 'GET';
  const headers = { ...options.headers };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (!['GET', 'HEAD'].includes(method) && csrfToken) headers['X-CSRF-Token'] = csrfToken;
  let response;
  try {
    response = await fetch(`${API}${path}`, { ...options, method, headers, credentials: 'include', body: options.body === undefined ? undefined : JSON.stringify(options.body) });
  } catch { throw new Error('Cannot reach SoulTune. Check your connection and make sure the server is running.'); }
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
  const response = await fetch(`${API}/playlists/${encodeURIComponent(id)}/export?format=${format}`, { credentials: 'include' });
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
  if (value.startsWith('/api/') && !value.startsWith('//')) return value;
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
