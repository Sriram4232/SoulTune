import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { House, Sparkles, Library, History, ChartNoAxesCombined, Settings2, Heart, Plus, ArrowUpRight, Search, CheckCircle2, Info, AlertCircle, X, LogOut, Menu, ChevronRight } from 'lucide-react';
import { api, setCsrf, normalizePlaylist } from './api';
import { Brand, StatusPill, Loading } from './components';
import { Landing, AuthPage, Onboarding } from './PublicPages';
import { Dashboard, CreatePage } from './Dashboard';
import Workspace from './Workspace';
import { HistoryPage, LibraryPage, AnalyticsPage } from './CollectionPages';
import Settings from './Settings';
import { PlayerProvider, usePlayer } from './Player';
import LiquidCursor from './LiquidCursor';
import CosmicBackground from './CosmicBackground';

const navItems = [{ id: 'home', label: 'For you', icon: House }, { id: 'create', label: 'Mood queue', icon: Sparkles }, { id: 'library', label: 'Local library', icon: Library }, { id: 'history', label: 'My playlists', icon: History }, { id: 'analytics', label: 'Music insights', icon: ChartNoAxesCombined }];
const pages = new Set(['landing', 'login', 'signup', 'home', 'create', 'library', 'history', 'analytics', 'settings', 'saved']);
function readRoute() { const parts = window.location.hash.slice(1).split('/').filter(Boolean); if (parts[0] === 'playlist' && parts[1]) return { page: 'playlist', id: decodeURIComponent(parts[1]) }; return { page: pages.has(parts[0]) ? parts[0] : 'landing' }; }

function AppShell({ user, route, navigate, health, children, onLogout }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const saved = useQuery({ queryKey: ['saved-songs'], queryFn: () => api('/saved-songs') });
  const savedCount = saved.data?.tracks?.length || 0;
  useEffect(() => { setMenuOpen(false); }, [route.page, route.id]);
  return <div className="app-shell"><a href="#main-content" className="skip-link" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus(); }}>Skip to content</a><aside className={`sidebar ${menuOpen ? 'mobile-open' : ''}`}><Brand onClick={() => navigate('home')} /><div className="sidebar-label">YOUR SPACE</div><nav className="main-nav" aria-label="Main navigation">{navItems.map(({ id, label, icon: Icon }) => <button key={id} className={route.page === id ? 'active' : ''} aria-current={route.page === id ? 'page' : undefined} onClick={() => navigate(id)}><Icon size={19} /><span>{label}</span>{id === 'create' && <span className="nav-plus">+</span>}</button>)}</nav><div className="sidebar-divider" /><div className="sidebar-label">YOUR COLLECTION</div><button className={`saved-nav ${route.page === 'saved' ? 'active' : ''}`} onClick={() => navigate('saved')}><Heart size={18} /><span>Saved songs</span><small>{savedCount}</small></button><div className="sidebar-bottom"><div className="sidebar-note"><span className="sidebar-note-icon"><Sparkles size={19} /></span><strong>A mood is all it takes.</strong><p>Your next favorite song starts with a feeling.</p><button onClick={() => navigate('create')}>Find your sound <ArrowUpRight size={14} /></button></div><button className={`settings-nav-button ${route.page === 'settings' ? 'active' : ''}`} onClick={() => navigate('settings')}><Settings2 size={18} /><span>Settings & profile</span></button><button className="sidebar-account" onClick={() => navigate('settings')}><span className="avatar">{user.name?.slice(0, 1).toUpperCase() || 'V'}</span><span><strong>{user.name || 'Music lover'}</strong><small>{user.is_guest ? 'YOUR DEMO SPACE' : 'YOUR PERSONAL SPACE'}</small></span><ChevronRight size={16} /></button></div></aside>{menuOpen && <button className="mobile-overlay" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
    <div className="app-main"><header className="topbar"><div className="topbar-location"><span className="topbar-mobile"><Brand compact onClick={() => navigate('home')} /></span><span className="desktop-breadcrumb">Your space <ChevronRight size={12} /> <strong>{route.page === 'playlist' ? 'Your soundtrack' : route.page === 'saved' ? 'Saved songs' : route.page === 'settings' ? 'Settings & profile' : navItems.find(item => item.id === route.page)?.label || 'For you'}</strong></span></div><div className="topbar-right"><StatusPill health={health} /><span className="topbar-divider" /><button className="icon-button topbar-search" aria-label="Search your playlists" onClick={() => navigate('history')}><Search size={18} /></button><button className="avatar" aria-label="Open your profile" onClick={() => navigate('settings')}>{user.name?.slice(0, 1).toUpperCase() || 'V'}</button><button className="icon-button mobile-menu-toggle" aria-label="Open menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={20} /> : <Menu size={20} />}</button></div></header><main className="main-content" id="main-content" tabIndex={-1}>{children}<footer className="app-footer"><span>A LITTLE MORE MUSIC. A LITTLE MORE YOU.</span><span>Made for your moment <span>✦</span></span></footer></main></div>
    <nav className="mobile-bottom-nav" aria-label="Mobile navigation">{[{ id: 'home', label: 'For you', icon: House }, { id: 'create', label: 'Queue', icon: Sparkles }, { id: 'history', label: 'Playlists', icon: History }, { id: 'settings', label: 'You', icon: Settings2 }].map(({ id, label, icon: Icon }) => <button className={route.page === id ? 'active' : ''} key={id} onClick={() => navigate(id)}><Icon size={19} /><span>{label}</span></button>)}</nav></div>;
}

function SignedInApp({ user, route, navigate, draft, setDraft, onUpdate, onLogout, onDelete, notify }) {
  const client = useQueryClient(); const player = usePlayer();
  const query = useQuery({ queryKey: ['playlists'], queryFn: () => api('/playlists') });
  const queueQuery = useQuery({ queryKey: ['queue'], queryFn: () => api('/queue') });
  const healthQuery = useQuery({ queryKey: ['health'], queryFn: () => api('/health'), staleTime: 60000 });
  const [generating, setGenerating] = useState(false); const [generateError, setGenerateError] = useState(null);
  const actionLock = useRef(false); const pendingCreation = useRef(null); const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const playlists = query.data?.playlists || [];
  async function generate(description, playlist_size) {
    if (actionLock.current) return; actionLock.current = true; setGenerating(true); setGenerateError(null); setDraft(description);
    const signature = JSON.stringify([description.trim(), playlist_size]);
    if (pendingCreation.current?.signature !== signature) pendingCreation.current = { signature, id: crypto.randomUUID() };
    try { const data = normalizePlaylist(await api('/queue/generate', { method: 'POST', body: { request_id: pendingCreation.current.id, description, playlist_size: Math.max(1, Math.min(10, playlist_size || 10)) } })); if (!alive.current) return; pendingCreation.current = null; setDraft(''); client.setQueryData(['queue'], { queue: data }); player.syncPlaylist(data.id, data.tracks); client.setQueryData(['playlist', data.id], data); await client.invalidateQueries({ queryKey: ['playlists'] }); if (alive.current) navigate('playlist', data.id); }
    catch (e) { if (alive.current) { setGenerateError(e); notify(e.message, 'error'); } } finally { actionLock.current = false; setGenerating(false); }
  }
  const shared = { playlists, loading: query.isLoading, error: query.error, retry: query.refetch, navigate, onOpen: id => navigate('playlist', id), notify };
  const composer = { queue: queueQuery.data?.queue, draft, setDraft, onGenerate: generate, generating, error: generateError, preferenceSize: user.preferences?.playlist_size };
  let content;
  if (route.page === 'playlist') content = <Workspace key={route.id} id={route.id} navigate={navigate} notify={notify} />;
  else if (route.page === 'create') content = <CreatePage {...composer} queue={queueQuery.data?.queue} onOpen={id => navigate('playlist', id)} />;
  else if (route.page === 'saved') content = <LibraryPage key="saved-songs" notify={notify} savedOnly />;
  else if (route.page === 'history') content = <HistoryPage key={route.page} {...shared} />;
  else if (route.page === 'library') content = <LibraryPage key="local-library" notify={notify} />;
  else if (route.page === 'analytics') content = <AnalyticsPage {...shared} />;
  else if (route.page === 'settings') content = <Settings user={user} onUpdate={onUpdate} onLogout={() => { player.clear(); onLogout(); }} onDelete={() => { player.clear(); onDelete(); }} notify={notify} playlists={playlists} />;
  else content = <Dashboard {...shared} {...composer} error={query.error} generateError={generateError} user={user} health={healthQuery.data} />;
  return <AppShell user={user} route={route} navigate={navigate} health={healthQuery.data} onLogout={onLogout}>{content}</AppShell>;
}

export default function App() {
  const client = useQueryClient();
  const [route, setRoute] = useState(readRoute); const [user, setUser] = useState(null); const [checking, setChecking] = useState(true); const [authError, setAuthError] = useState(null); const [demoBusy, setDemoBusy] = useState(false);
  const [draft, setDraft] = useState('');
  const [toasts, setToasts] = useState([]);
  const notify = useCallback((message, kind = 'success') => { const id = Date.now() + Math.random(); setToasts(items => [...items.slice(-2), { id, message, kind }]); setTimeout(() => setToasts(items => items.filter(item => item.id !== id)), kind === 'error' ? 10000 : 6500); }, []);
  const navigate = useCallback((page, id) => { if (page === 'create') setDraft(''); const next = page === 'playlist' ? `#/playlist/${encodeURIComponent(id)}` : `#/${page}`; if (window.location.hash !== next) window.location.hash = next; else setRoute(readRoute()); window.scrollTo({ top: 0, behavior: 'instant' }); }, []);
  useEffect(() => { const update = () => setRoute(readRoute()); window.addEventListener('hashchange', update); return () => window.removeEventListener('hashchange', update); }, []);
  useEffect(() => { try { sessionStorage.removeItem('soultune-draft'); } catch { /* Storage can be disabled. */ } }, []);
  useEffect(() => { let alive = true; api('/auth/me').then(data => { if (alive) setUser(data.user); }).catch(error => { if (alive && error.status !== 401) setAuthError(error); }).finally(() => { if (alive) setChecking(false); }); return () => { alive = false; }; }, []);
  useEffect(() => { const expired = () => { setDraft(''); setUser(null); setCsrf(''); client.clear(); navigate('login'); notify('Your session ended. Sign in to return to your playlists.', 'info'); }; window.addEventListener('soultune-session-expired', expired); return () => window.removeEventListener('soultune-session-expired', expired); }, [client, navigate, notify]);
  useEffect(() => {
    const preference = user?.preferences?.theme || 'dark';
    const media = window.matchMedia('(prefers-color-scheme: light)');
    const update = () => { document.documentElement.dataset.theme = preference === 'system' ? media.matches ? 'light' : 'dark' : preference; };
    update(); media.addEventListener('change', update); return () => media.removeEventListener('change', update);
  }, [user?.preferences?.theme]);
  function onAuth(data) { setDraft(''); client.clear(); setUser(data.user); setAuthError(null); if (data.csrf_token) setCsrf(data.csrf_token); navigate('home'); }
  async function demo() { setDemoBusy(true); setAuthError(null); try { onAuth(await api('/auth/guest', { method: 'POST', body: {} })); } catch (e) { setAuthError(e); } finally { setDemoBusy(false); } }
  async function logout() { try { await api('/auth/logout', { method: 'POST', body: {} }); } catch (e) { if (e.status !== 401) { notify(e.message, 'error'); return; } } setDraft(''); setUser(null); setCsrf(''); client.clear(); navigate('landing'); }
  function deleted() { setUser(null); setCsrf(''); client.clear(); setDraft(''); navigate('landing'); notify('Your account and stored data have been deleted.'); }
  let content;
  if (checking) content = <div className="initial-loading"><Brand /><Loading text="Finding your place in the music…" /></div>;
  else if (!user) content = route.page === 'login' || route.page === 'signup' ? <AuthPage key={route.page} mode={route.page} navigate={navigate} onAuth={onAuth} /> : <Landing navigate={navigate} draft={draft} setDraft={setDraft} onDemo={demo} busy={demoBusy} error={authError} />;
  else if (!user.onboarding_completed && !user.is_guest) content = <Onboarding user={user} onComplete={setUser} navigate={navigate} />;
  else content = <PlayerProvider notify={notify}><SignedInApp user={user} route={route} navigate={navigate} draft={draft} setDraft={setDraft} onUpdate={setUser} onLogout={logout} onDelete={deleted} notify={notify} /></PlayerProvider>;
  return <><CosmicBackground /><LiquidCursor />{content}<div className="toast-region" aria-live="polite" aria-atomic="false">{toasts.map(toast => <div key={toast.id} className={`toast toast-${toast.kind}`} role={toast.kind === 'error' ? 'alert' : 'status'}>{toast.kind === 'error' ? <AlertCircle size={19} /> : toast.kind === 'info' ? <Info size={19} /> : <CheckCircle2 size={19} />}<span>{toast.message}</span><button className="icon-button" aria-label="Dismiss notification" onClick={() => setToasts(items => items.filter(item => item.id !== toast.id))}><X size={16} /></button></div>)}</div></>;
}
