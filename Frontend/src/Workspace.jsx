import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, ArrowUpRight, Play, Pause, Heart, Download, Sparkles, Send, ChevronDown, ChevronUp, ThumbsUp, ThumbsDown, X, Music2, Pencil, Check, LoaderCircle, SlidersHorizontal, MessageCircle, ExternalLink } from 'lucide-react';
import { api, downloadPlaylist, normalizePlaylist, percent, titleCase, formatTime, safeUrl } from './api';
import { Artwork, ErrorBox, Loading, Meter, EmptyState } from './components';
import { usePlayer } from './Player';
import SongActions from './SongActions';

function TrackRow({ track, number, tracks, playlistId, mutate, pending, notify, isQueue }) {
  const [expanded, setExpanded] = useState(false); const [busy, setBusy] = useState(false);
  const player = usePlayer(); const active = player.current?.id === track.id;
  async function feedback(value) {
    setBusy(true);
    try { await mutate('/feedback', 'POST', { track_id: track.id, feedback: value }); notify(value === 'remove' ? 'Song removed.' : 'Hidden from this queue and its refinements.'); }
    catch (error) { notify(error.message, 'error'); } finally { setBusy(false); }
  }
  return <div className={`track-card ripple-object ${active ? 'track-active' : ''}`}><div className="track-row"><button className="track-play" aria-label={active && player.playing ? `Pause ${track.title}` : `Play ${track.title}`} onClick={() => active ? player.toggle() : player.start(tracks, number - 1, playlistId)}><span className="track-number">{String(number).padStart(2, '0')}</span><span className="track-play-icon">{active && player.playing ? <Pause size={16} /> : <Play size={16} />}</span></button><Artwork seed={track.id} imageUrl={track.image_url} className="track-art" /><div className="track-info"><strong className="ripple-text">{track.title}</strong><span>{track.artist}</span><div className="track-tags">{(track.genres || []).slice(0, 2).map(genre => <span key={genre}>{titleCase(genre)}</span>)}{track.source === 'local' && <span className="local-tag">LOCAL</span>}</div></div><span className="track-duration">{track.duration_seconds ? formatTime(track.duration_seconds) : '—'}</span>{isQueue && <div className="track-match"><strong>{track.score == null ? '—' : `${percent(track.score)}%`}</strong><span>match</span></div>}</div>
    <div className="song-action-bar"><button className="text-button" aria-expanded={expanded} aria-label={`Why this song: ${track.title}`} onClick={() => setExpanded(!expanded)}><Sparkles size={15} />Why this song?{expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}</button><SongActions track={track} sourceId={playlistId} notify={notify} disabled={pending || busy} />{isQueue && <button className="text-button" disabled={pending || busy} onClick={() => feedback('dislike')} aria-label={`Hide ${track.title}`}><ThumbsDown size={14} />Hide</button>}<button className="text-button" disabled={pending || busy} onClick={() => feedback('remove')} aria-label={`Remove ${track.title}`}><X size={14} />Remove</button></div>
    {expanded && <div className="explanation-panel ripple-object">
      <div className="explanation-header">
        <div className="explanation-heading"><Sparkles size={15} /><h4 className="ripple-text">Why this song?</h4></div>
        {track.score != null && (
          <div className="explanation-score-badge">
            <span className="score-pct">{percent(track.score)}%</span>
            <span className="score-label">overall match</span>
          </div>
        )}
      </div>
      {track.story && (
        <p className="explanation-story">{track.story}</p>
      )}
      {!track.story && track.explanation && (
        <p className="explanation-story">{track.explanation}</p>
      )}
      {track.story && track.explanation && track.explanation !== track.story && (
        <p className="explanation-summary">{track.explanation}</p>
      )}
      {track.score_breakdown && Object.keys(track.score_breakdown).length > 0 && (
        <div className="explanation-stats">
          <p className="explanation-stats-label">Score breakdown</p>
          <div className="score-grid">{Object.entries(track.score_breakdown).filter(([, value]) => value !== null && typeof value === 'number').map(([label, value]) => <Meter key={label} label={`${titleCase(label)} match`} value={value} detail={`${percent(value)}%`} />)}</div>
        </div>
      )}
      {track.metadata_notes && <p className="muted explanation-source-note">{track.metadata_notes}</p>}
      {safeUrl(track.external_url) && <a className="text-button" href={safeUrl(track.external_url)} target="_blank" rel="noopener noreferrer">View track <ExternalLink size={13} /></a>}
    </div>}</div>;
}

function MoodSummary({ profile, parser, previousProfile }) {
  if (!profile) return null;
  return <div className="mood-summary"><div className="mood-summary-title"><SlidersHorizontal size={14} /><span>THE FEELING WE HEARD</span><small>{parser === 'groq' ? 'AI interpreted' : 'Offline interpretation'}</small></div><div className="mood-summary-tags">{[profile.primary_mood, ...(profile.secondary_moods || []).slice(0, 2), profile.activity].filter(Boolean).map((tag, i) => <span className="chip" key={`${tag}-${i}`}>{titleCase(tag)}</span>)}</div><div className="mood-meters">{[['Energy', 'energy'], ['Positivity', 'valence']].map(([label, key]) => profile[key] != null && <div key={key}><Meter label={label} value={profile[key]} />{previousProfile && previousProfile[key] != null && previousProfile[key] !== profile[key] && <small className="change-note">{percent(previousProfile[key])}% → {percent(profile[key])}%</small>}</div>)}</div>{profile.preferred_genres?.length > 0 && <p className="mood-genre-list"><span>Leaning into</span> {profile.preferred_genres.map(titleCase).join(' · ')}</p>}{profile.excluded_genres?.length > 0 && <p className="mood-genre-list"><span>Leaving out</span> {profile.excluded_genres.map(titleCase).join(' · ')}</p>}</div>;
}

export default function Workspace({ id, navigate, notify }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ['playlist', id], queryFn: () => api(`/playlists/${encodeURIComponent(id)}`).then(normalizePlaylist), enabled: !!id });
  const playlist = query.data;
  const [message, setMessage] = useState(''); const [refining, setRefining] = useState(false); const [refineError, setRefineError] = useState(null); const [previousProfile, setPreviousProfile] = useState(null);
  const [renaming, setRenaming] = useState(false); const [name, setName] = useState(''); const [saving, setSaving] = useState(false); const [exportOpen, setExportOpen] = useState(false);
  const messagesEnd = useRef(null); const player = usePlayer();
  useEffect(() => { setMessage(''); setPreviousProfile(null); setRefineError(null); }, [id]);
  useEffect(() => { const panel = messagesEnd.current?.parentElement; if (panel) panel.scrollTo({ top: panel.scrollHeight, behavior: 'smooth' }); }, [playlist?.messages?.length]);
  const mutationLock = useRef(false); const [pending, setPending] = useState(false);
  function updatePlaylist(value) { client.setQueryData(['playlist', id], old => (old?.revision || 0) > (value.revision || 0) ? old : value); client.invalidateQueries({ queryKey: ['playlists'] }); if (value.kind === 'queue') client.setQueryData(['queue'], { queue: value }); player.syncPlaylist(id, value.tracks); }
  async function mutate(suffix, method, body) {
    if (mutationLock.current) throw new Error('Please wait for the current playlist update.');
    mutationLock.current = true; setPending(true);
    try {
      await client.cancelQueries({ queryKey: ['playlist', id] });
      const current = client.getQueryData(['playlist', id]);
      const result = normalizePlaylist(await api(`/playlists/${id}${suffix}`, { method, body: { ...body, revision: current?.revision } }));
      updatePlaylist(result); return result;
    } catch (error) {
      if (error.status === 409) { await client.invalidateQueries({ queryKey: ['playlist', id] }); client.invalidateQueries({ queryKey: ['playlists'] }); }
      throw error;
    } finally { mutationLock.current = false; setPending(false); }
  }
  async function patch(body) {
    setSaving(true);
    try { await mutate('', 'PATCH', body); setRenaming(false); notify(body.name ? 'Your playlist has a new name.' : body.saved ? 'Saved to your collection.' : 'Removed from saved playlists.'); }
    catch (error) { notify(error.message, 'error'); } finally { setSaving(false); }
  }
  async function refine(event) {
    event?.preventDefault(); if (message.trim().length < 3 || refining) return;
    setRefining(true); setRefineError(null);
    try { await mutate('/refine', 'POST', { message }); setPreviousProfile(playlist.profile); setMessage(''); notify('A new take on your moment. Your queue is updated.'); }
    catch (error) { setRefineError(error); } finally { setRefining(false); }
  }
  async function exportAs(format) { setExportOpen(false); try { await downloadPlaylist(id, format); notify(`Playlist exported as ${format.toUpperCase()}.`); } catch (error) { notify(error.message, 'error'); } }
  if (query.isLoading) return <Loading text="Bringing your soundtrack back…" />;
  if (query.error) return <div><button className="text-button" onClick={() => navigate('history')}><ArrowLeft size={16} />Your playlists</button><ErrorBox error={query.error} retry={query.refetch} /></div>;
  if (!playlist) return <EmptyState title="Let’s start with a feeling." description="Describe a moment and we’ll build your playlist here." action={() => navigate('create')} />;
  const isQueue = playlist.kind === 'queue';
  const duration = (playlist.tracks || []).reduce((sum, track) => sum + (track.duration_seconds || 0), 0);
  return <div className="workspace-page"><button className="text-button back-link" onClick={() => navigate('history')}><ArrowLeft size={15} />{isQueue ? 'My playlists' : 'All playlists'}</button><div className={`workspace-grid ${!isQueue ? 'collection-workspace' : ''}`}><div className="workspace-main"><div className="playlist-hero ripple-object"><Artwork seed={playlist.id || playlist.name} className="playlist-cover"><span className="cover-label">SOULTUNE<br />SESSIONS</span><span className="cover-mood">{titleCase(playlist.profile?.primary_mood || 'Your moment')}</span><span className="cover-vol">VOL. {String(playlist.version || 1).padStart(2, '0')}</span></Artwork><div className="playlist-hero-content"><p className="eyebrow">{isQueue ? 'YOUR ACTIVE MOOD QUEUE' : 'YOUR HANDPICKED COLLECTION'}</p>{renaming ? <form className="rename-form" onSubmit={event => { event.preventDefault(); patch({ name }); }}><label className="sr-only" htmlFor="playlist-name">Playlist name</label><input id="playlist-name" required maxLength={100} value={name} onChange={event => setName(event.target.value)} autoFocus /><button className="icon-button" disabled={saving || pending} aria-label="Save playlist name"><Check size={18} /></button><button type="button" className="icon-button" onClick={() => setRenaming(false)} aria-label="Cancel rename"><X size={18} /></button></form> : <div className="playlist-title"><h1 className="ripple-text">{playlist.name}</h1><button className="icon-button" aria-label="Rename playlist" onClick={() => { setName(playlist.name); setRenaming(true); }}><Pencil size={15} /></button></div>}<p className="playlist-original-prompt">{playlist.description ? `“${playlist.description}”` : "Handpicked by you. Add the songs you want to keep."}</p><p className="playlist-metadata">{playlist.tracks.length} tracks <span>·</span> {duration ? `about ${Math.round(duration / 60)} min` : 'Duration varies'} <span>·</span> Version {playlist.version || 1}</p><div className="playlist-actions"><button className="button primary ripple-object" disabled={!playlist.tracks.length} onClick={() => player.start(playlist.tracks, 0, id)}><Play size={16} fill="currentColor" />Play mix</button><button className="button secondary ripple-object" onClick={() => navigate(isQueue ? 'create' : 'library')}><Music2 size={16} />{isQueue ? 'Change mood' : 'Add songs'}</button><div className="export-wrap"><button className="icon-button export-button" aria-label="Export playlist" aria-expanded={exportOpen} onClick={() => setExportOpen(!exportOpen)}><Download size={18} /></button>{exportOpen && <div className="dropdown-menu"><button onClick={() => exportAs('json')}>Export JSON<span>Full playlist & mood</span></button><button onClick={() => exportAs('csv')}>Export CSV<span>Open in a spreadsheet</span></button></div>}</div></div></div></div>
      {playlist.warnings?.length > 0 && <div className="source-note"><Music2 size={15} /><div>{playlist.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</div></div>}
      <div className="track-list-heading"><span>#</span><span>THE SOUNDTRACK</span><span>{isQueue ? "MATCH" : ""}</span></div><div className="track-list">{playlist.tracks.map((track, index) => <TrackRow key={`${track.id}-${playlist.version}`} track={track} number={index + 1} tracks={playlist.tracks} playlistId={id} mutate={mutate} pending={pending} notify={notify} isQueue={isQueue} />)}</div>{!playlist.tracks.length && <EmptyState title={isQueue ? "No matching songs yet." : "Make this playlist yours."} description={isQueue ? "Try a broader mood or rescan your local library. Strict filters may leave fewer matches." : "Choose Add to playlist on any song in your mood queue, saved songs, or local library."} action={() => navigate('library')} actionLabel="Open local library" />}<p className="playlist-footnote"><Sparkles size={13} />Open “Why this song?” to see the recommendation and its scoring details.</p></div>
      {isQueue && <aside className="curator-panel ripple-object"><div className="curator-panel-header"><span className="curator-avatar"><Sparkles size={19} /></span><div><h2 className="ripple-text">Your personal curator</h2><p>Listening between the lines.</p></div><span className="tiny-dot" /></div><MoodSummary profile={playlist.profile} parser={playlist.parser} previousProfile={previousProfile} /><div className="chat-section-title"><MessageCircle size={14} /><span className="ripple-text">THE CONVERSATION</span></div><div className="chat-messages" aria-live="polite" aria-relevant="additions">{(playlist.messages || []).map((item, index) => <div className={`chat-message ${item.role === 'user' ? 'from-user' : 'from-curator'}`} key={`${index}-${item.created_at}`}><span className="message-label">{item.role === 'user' ? 'YOU' : 'SOULTUNE'}</span><p>{item.content}</p></div>)}{refining && <div className="chat-message from-curator"><span className="message-label">SOULTUNE</span><p className="refining-note"><LoaderCircle size={15} className="spin" />Finding a new take on your feeling…</p></div>}<div ref={messagesEnd} /></div><div className="chat-composer"><div className="refinement-chips">{['A little more upbeat', 'Less vocals', 'Something calmer'].map(suggestion => <button className="chip ripple-object" key={suggestion} disabled={pending} onClick={() => { setMessage(suggestion); document.getElementById('refine-message')?.focus(); }}>{suggestion}<span>+</span></button>)}</div><ErrorBox error={refineError} /><form onSubmit={refine}><label className="sr-only" htmlFor="refine-message">Refine your mood queue</label><textarea id="refine-message" value={message} onChange={event => setMessage(event.target.value)} maxLength={1500} placeholder="Same feeling, a little more…" rows={2} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); refine(); } }} /><button className="chat-send" disabled={pending || message.trim().length < 3} aria-label="Send queue refinement"><ArrowRight size={18} /></button></form><p>Your original mood stays. The details evolve.</p></div></aside>}</div></div>;
}
